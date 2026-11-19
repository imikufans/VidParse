"""音视频合成引擎(DASH 分离流 -> 单个带声音的 mp4).

B站/YouTube 等高画质走 DASH: 视频流与音频流分开, 单独播放无声音。
本模块负责:
  1. 带正确 Referer/Cookie 分别下载视频流与音频流到本地
  2. 用 ffmpeg 无损合并(-c copy), 输出带声音的 mp4
  3. 全程进度可查询, 支持任务取消

ffmpeg 获取优先级:
  1. 项目内 bin/ffmpeg.exe (随工具分发, 免安装)
  2. 系统 PATH 中的 ffmpeg
  3. 常见安装路径

零第三方依赖(仅标准库) + 可选 ffmpeg 二进制。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from .utils import DEFAULT_UA

# 数据目录: 优先用环境变量(桌面版指向用户可写目录), 否则用项目根
_DATA_DIR = os.environ.get("VIDPARSE_DATA_DIR", "").strip()
APP_DIR = Path(_DATA_DIR) if _DATA_DIR else Path(__file__).resolve().parent.parent
BASE_DIR = Path(__file__).resolve().parent.parent  # ffmpeg 随程序, 始终用安装目录
BIN_DIR = BASE_DIR / "bin"
OUTPUT_DIR = APP_DIR / "downloads"

# 各平台 CDN 的 Referer(B站 DASH 流必须带, 否则 403)
PLATFORM_REFERER = {
    "bilibili": "https://www.bilibili.com/",
    "douyin": "https://www.douyin.com/",
    "youtube": "https://www.youtube.com/",
}

# ffmpeg 自动下载的地址(Windows 静态版, 用于一键启动脚本引导)
FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def find_ffmpeg() -> Optional[str]:
    """查找可用的 ffmpeg 可执行文件, 返回绝对路径或 None."""
    candidates = [
        BIN_DIR / "ffmpeg.exe",
        BIN_DIR / "ffmpeg",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    found = shutil.which("ffmpeg")
    if found:
        return found
    for p in (
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    ):
        if os.path.exists(p):
            return p
    return None


def ffmpeg_status() -> Dict[str, Any]:
    """返回 ffmpeg 可用状态与版本信息(供前端展示)."""
    exe = find_ffmpeg()
    if not exe:
        return {"available": False, "path": "", "version": "", "message": "未找到 ffmpeg"}
    try:
        out = subprocess.run(
            [exe, "-version"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        first = (out.stdout or out.stderr).splitlines()[0] if (out.stdout or out.stderr) else ""
        return {"available": True, "path": exe, "version": first[:160], "message": "就绪"}
    except Exception as e:
        return {"available": False, "path": exe, "version": "", "message": f"ffmpeg 无法执行: {e}"}


# ---------------- 任务模型 ----------------
class MergeTask:
    def __init__(self, video_url: str, audio_url: str, platform: str,
                 title: str, quality: str, cookie: str = "", referer: str = ""):
        self.id = uuid.uuid4().hex[:12]
        self.video_url = video_url
        self.audio_url = audio_url
        self.platform = platform
        self.title = title
        self.quality = quality
        self.cookie = cookie
        self.referer = referer
        self.status = "pending"        # pending / running / done / error / cancelled
        self.progress = 0              # 0-100
        self.stage = "准备中"
        self.message = ""
        self.output_name = ""
        self.created = time.time()
        self._cancel = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "message": self.message,
            "output_name": self.output_name,
            "title": self.title,
            "quality": self.quality,
        }


class MergeManager:
    """合成任务管理器(线程安全)."""

    def __init__(self) -> None:
        self._tasks: Dict[str, MergeTask] = {}
        self._lock = threading.Lock()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def submit(self, *, video_url: str, audio_url: str, platform: str,
               title: str = "video", quality: str = "", cookie: str = "",
               referer: str = "") -> MergeTask:
        task = MergeTask(video_url, audio_url, platform, title, quality, cookie, referer)
        with self._lock:
            self._tasks[task.id] = task
        task._thread = threading.Thread(target=self._run, args=(task,), daemon=True)
        task._thread.start()
        return task

    def get(self, task_id: str) -> Optional[MergeTask]:
        with self._lock:
            return self._tasks.get(task_id)

    def cancel(self, task_id: str) -> bool:
        task = self.get(task_id)
        if not task or task.status not in ("pending", "running"):
            return False
        task._cancel.set()
        task.status = "cancelled"
        task.message = "用户已取消"
        return True

    def list(self) -> list:
        with self._lock:
            return [t.to_dict() for t in self._tasks.values()]

    def output_path(self, task_id: str) -> Optional[Path]:
        task = self.get(task_id)
        if not task or task.status != "done" or not task.output_name:
            return None
        p = OUTPUT_DIR / task.output_name
        return p if p.exists() else None

    # ---------------- 内部实现 ----------------
    def _download(self, task: MergeTask, url: str, dest: Path,
                  start: int, end: int) -> None:
        """带 Referer/Cookie 流式下载, 进度映射到 [start, end] 区间."""
        if task.referer.startswith(("http://", "https://")):
            referer = task.referer
        elif task.platform in PLATFORM_REFERER:
            referer = PLATFORM_REFERER[task.platform]
        else:
            parsed = urllib.parse.urlparse(url)
            referer = f"{parsed.scheme}://{parsed.netloc}/" if parsed.netloc else ""
        headers = {
            "User-Agent": DEFAULT_UA,
            "Accept": "*/*",
        }
        if referer:
            headers["Referer"] = referer
        if task.cookie:
            headers["Cookie"] = task.cookie
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            got = 0
            last_report = 0.0
            while True:
                if task._cancel.is_set():
                    raise RuntimeError("已取消")
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                now = time.time()
                if now - last_report > 0.4:  # 限频, 避免频繁写状态
                    if total:
                        task.progress = start + int((got / total) * (end - start))
                    task.message = f"已下载 {got / 1024 / 1024:.1f} MB"
                    last_report = now
            if total:
                task.progress = end

    @staticmethod
    def _safe_name(name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip(" .") or "video"
        return cleaned[:80]

    def _run(self, task: MergeTask) -> None:
        tmp_v = tmp_a = None
        try:
            exe = find_ffmpeg()
            if not exe:
                raise RuntimeError(
                    "未找到 ffmpeg。请运行「安装ffmpeg.bat」或把 ffmpeg.exe 放到 bin/ 目录后重试。"
                )

            task.status = "running"
            task.stage = "下载视频流"
            task.progress = 2
            safe_title = self._safe_name(task.title)
            tmp_v = OUTPUT_DIR / f"_{task.id}_video.m4s"
            tmp_a = OUTPUT_DIR / f"_{task.id}_audio.m4s"
            self._download(task, task.video_url, tmp_v, 3, 45)

            task.stage = "下载音频流"
            task.message = ""
            self._download(task, task.audio_url, tmp_a, 46, 70)

            if task._cancel.is_set():
                raise RuntimeError("已取消")

            task.stage = "合成中"
            task.progress = 72
            task.message = "ffmpeg 正在合并音视频…"
            output_name = f"{safe_title}_{task.quality or '合并'}.mp4".replace("__", "_")
            output_path = OUTPUT_DIR / output_name

            # -c copy 无损合并(最快, 无画质损失); 失败则重编码兜底
            cmd = [
                exe, "-y",
                "-i", str(tmp_v),
                "-i", str(tmp_a),
                "-c", "copy",
                "-movflags", "+faststart",
                "-map", "0:v:0", "-map", "1:a:0",
                str(output_path),
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1024:
                # 降级: 重新编码(兼容性更好)
                task.message = "无损合并失败, 尝试重新编码…"
                cmd = [
                    exe, "-y",
                    "-i", str(tmp_v),
                    "-i", str(tmp_a),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart",
                    "-map", "0:v:0", "-map", "1:a:0",
                    str(output_path),
                ]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=900,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if proc.returncode != 0 or not output_path.exists():
                    raise RuntimeError(f"ffmpeg 合并失败: {(proc.stderr or '')[-300:]  }")

            if task._cancel.is_set():
                raise RuntimeError("已取消")

            task.output_name = output_name
            task.progress = 100
            task.stage = "完成"
            task.message = "合成完成, 可播放或下载"
            task.status = "done"
        except RuntimeError as e:
            if task._cancel.is_set():
                return
            task.status = "error"
            task.message = str(e)
            task.stage = "失败"
        except Exception as e:
            task.status = "error"
            task.message = f"合成失败: {e}"
            task.stage = "失败"
        finally:
            # 清理临时文件
            for p in (tmp_v, tmp_a):
                if p and p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass


# 全局单例
merge_manager = MergeManager()
