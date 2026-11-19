#!/usr/bin/env python3
"""VidParse 图形化 Web 界面(零第三方依赖, 仅用标准库).

功能:
    - 视频解析(B站/抖音/YouTube 等), 展示元信息与所有可用格式, 支持播放/下载
    - B站扫码登录: 官方二维码登录, 自动获取并保存 SESSDATA(解锁高清)
    - 抖音登录: 自动打开浏览器扫码登录, 通过 CDP 自动读取 Cookie(绕过风控)
    - Cookie 状态管理: 查看登录状态、清空
    - 手动粘贴 Cookie(兜底)

启动:
    python webui.py --port 8080
    或双击「一键启动.bat」, 会自动打开浏览器
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

from vidparse import VideoParser, __version__
from vidparse.auth import (
    BiliQrLogin, CookieStore, DouyinLogin,
)
from vidparse.merger import ffmpeg_status, merge_manager
from vidparse.utils import DEFAULT_UA

# 各平台 CDN 需要的 Referer(B站直链防盗链: 必须带 bilibili.com 的 Referer,
# 否则 CDN 返回 403)。代理接口以此重建请求头。
PLATFORM_REFERER = {
    "bilibili": "https://www.bilibili.com/",
    "douyin": "https://www.douyin.com/",
    "youtube": "https://www.youtube.com/",
}

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"

store = CookieStore()
bili_login = BiliQrLogin(store)
douyin_login = DouyinLogin(store)

# 保存当前活跃的 B站二维码 key(供轮询使用)
_state = {"bili_key": "", "bili_url": ""}
_state_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = f"vidparse-web/{__version__}"

    # ---------------- 响应工具 ----------------
    def _send(self, body: bytes, content_type: str, status: int = 200,
              extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(body, "application/json; charset=utf-8", status)

    def _html(self, filename: str) -> None:
        path = WEB_DIR / filename
        if not path.exists():
            return self._send(b"Not Found", "text/plain; charset=utf-8", 404)
        body = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or "javascript" in ctype:
            ctype += "; charset=utf-8"
        self._send(body, ctype)

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # ---------------- 本地文件 serve(合成结果下载/播放, 支持 Range) ----------------
    def _serve_file(self, fpath: Path) -> None:
        size = fpath.stat().st_size
        ctype = mimetypes.guess_type(str(fpath))[0] or "video/mp4"
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header:
            m = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header(
            "Content-Disposition",
            f'attachment; filename*=UTF-8\'\'{urllib.parse.quote(fpath.name)}',
        )
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(fpath, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------------- 媒体代理(解决防盗链 403) ----------------
    def _proxy_media(self, target: str, platform: str, custom_referer: str = "") -> None:
        """带正确 Referer 代理转发媒体流, 支持 Range 断点/拖动播放.

        B站/抖音 CDN 有防盗链: 浏览器直接打开直链不带 Referer 会被 403。
        这里由服务端注入对应平台的 Referer 再转发, 浏览器即可正常播放/下载。
        对 yt-dlp 兜底的 generic 平台, 允许前端传入自定义 Referer(来源站)。
        """
        if not target.lower().startswith(("http://", "https://")):
            return self._json({"success": False, "error": "无效的媒体地址"}, 400)

        # 自定义 Referer 优先(仅允许 http(s), 防 SSRF 式头注入)
        if custom_referer.startswith(("http://", "https://")):
            referer = custom_referer
        elif platform in PLATFORM_REFERER:
            referer = PLATFORM_REFERER[platform]
        else:
            # generic 平台: 从直链本身推导来源站(如 https://xxx.com/path -> https://xxx.com/)
            parsed_target = urlparse(target)
            referer = f"{parsed_target.scheme}://{parsed_target.netloc}/" if parsed_target.netloc else ""
        req_headers = {
            "User-Agent": DEFAULT_UA,
            "Referer": referer,
            "Accept": "*/*",
        }
        # 透传 Range(视频拖动进度条必需)
        range_header = self.headers.get("Range")
        if range_header:
            req_headers["Range"] = range_header
        # 透传登录 Cookie(B站高码率/DASH 流需要)
        saved = store.get_platform(platform)
        if platform == "bilibili" and saved.get("sessdata"):
            req_headers["Cookie"] = f"SESSDATA={saved['sessdata']}"
        elif platform == "douyin" and saved.get("cookie"):
            req_headers["Cookie"] = saved["cookie"]

        req = urllib.request.Request(target, headers=req_headers, method="GET")
        try:
            upstream = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            # 上游 403/404 等, 转成 JSON 错误返回给前端
            return self._json({
                "success": False,
                "error": f"CDN 返回 HTTP {e.code}（直链可能已过期，请重新解析）",
            }, 502)
        except Exception as e:
            return self._json({"success": False, "error": f"代理请求失败: {e}"}, 502)

        try:
            status = upstream.status
            content_type = upstream.headers.get("Content-Type", "video/mp4")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Accept-Ranges", "bytes")
            for key in ("Content-Length", "Content-Range"):
                val = upstream.headers.get(key)
                if val:
                    self.send_header(key, val)
            self.end_headers()
            if self.command == "HEAD":
                return
            # 分块转发(64KB), 避免大文件占满内存
            while True:
                chunk = upstream.read(65536)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break  # 用户关闭播放器/取消下载
        finally:
            upstream.close()

    # ---------------- 路由 ----------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        try:
            if path == "/" or path == "/index.html":
                return self._html("index.html")
            # 静态资源(安全: 仅允许 web/static/ 下的文件, 防目录穿越)
            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                if rel and "/" not in rel and "\\" not in rel and ".." not in rel:
                    return self._html("static/" + rel)

            # 媒体代理: ?url=<直链>&platform=bilibili  (解决 CDN 防盗链 403)
            if path == "/api/proxy":
                target = unquote((query.get("url") or [""])[0])
                platform = (query.get("platform") or ["bilibili"])[0]
                custom_referer = unquote((query.get("referer") or [""])[0])
                if not target:
                    return self._json({"success": False, "error": "缺少 url 参数"}, 400)
                return self._proxy_media(target, platform, custom_referer)

            if path == "/api/health":
                return self._json({"status": "ok", "version": __version__})

            # ffmpeg 可用性(合成功能依赖)
            if path == "/api/ffmpeg/status":
                return self._json({"success": True, "data": ffmpeg_status()})

            # 合成任务状态查询
            if path == "/api/merge/status":
                task_id = (query.get("id") or [""])[0]
                task = merge_manager.get(task_id)
                if not task:
                    return self._json({"success": False, "error": "任务不存在"}, 404)
                return self._json({"success": True, "data": task.to_dict()})

            # 合成结果下载/播放(支持 Range)
            if path == "/api/merge/file":
                task_id = (query.get("id") or [""])[0]
                fpath = merge_manager.output_path(task_id)
                if not fpath:
                    return self._json({"success": False, "error": "文件尚未就绪"}, 404)
                return self._serve_file(fpath)

            if path == "/api/cookie/status":
                return self._json({"success": True, "data": store.status()})

            if path == "/api/cookie/delete":
                platform = (query.get("platform") or [""])[0]
                if platform in ("bilibili", "douyin"):
                    store.delete(platform)
                    return self._json({"success": True, "message": "已清除"})
                return self._json({"success": False, "error": "无效平台"}, 400)

            # B站扫码: 生成二维码
            if path == "/api/login/bili/qrcode":
                try:
                    qr = bili_login.start()
                    with _state_lock:
                        _state["bili_key"] = qr["qrcode_key"]
                        _state["bili_url"] = qr["url"]
                    return self._json({
                        "success": True,
                        "data": {"url": qr["url"], "qrcode_key": qr["qrcode_key"]},
                    })
                except Exception as e:
                    return self._json({"success": False, "error": str(e)}, 500)

            # B站扫码: 轮询状态
            if path == "/api/login/bili/poll":
                with _state_lock:
                    key = query.get("key", [_state["bili_key"]])[0]
                if not key:
                    return self._json({"success": False, "error": "请先获取二维码"}, 400)
                result = bili_login.poll(key)
                return self._json({"success": True, "data": result})

            # 抖音登录: 打开浏览器
            if path == "/api/login/douyin/start":
                try:
                    result = douyin_login.start()
                    return self._json({"success": True, "data": result})
                except Exception as e:
                    return self._json({"success": False, "error": str(e)}, 500)

            # 抖音登录: 轮询 Cookie
            if path == "/api/login/douyin/poll":
                result = douyin_login.poll()
                return self._json({"success": True, "data": result})

            # 视频解析
            if path == "/api/parse":
                url = (query.get("url") or [""])[0]
                if not url:
                    return self._json({"success": False, "error": "缺少 url 参数"}, 400)
                vp = VideoParser()
                result = vp.parse(url)
                return self._json(result.to_dict())

            self._json({"error": "Not Found"}, 404)
        except Exception as e:
            self._json({"success": False, "error": f"服务器错误: {e}"}, 500)

    def do_HEAD(self) -> None:  # noqa: N802
        """HEAD 复用 GET 的路由(响应体自动跳过), 便于播放器/工具探测媒体头."""
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        try:
            if path == "/api/cookie/set":
                payload = self._body_json()
                platform = payload.get("platform", "")
                cookie_str = str(payload.get("cookie", "")).strip()
                if platform not in ("bilibili", "douyin") or not cookie_str:
                    return self._json({"success": False, "error": "参数不完整"}, 400)
                if platform == "bilibili":
                    # 支持粘贴完整 Cookie 或仅 SESSDATA
                    sessdata = payload.get("sessdata", "") or cookie_str
                    if "SESSDATA=" in cookie_str:
                        for part in cookie_str.split(";"):
                            if "SESSDATA=" in part:
                                sessdata = part.split("SESSDATA=", 1)[1].strip()
                    store.set_platform("bilibili", {"sessdata": sessdata})
                else:
                    store.set_platform("douyin", {"cookie": cookie_str})
                return self._json({"success": True, "message": "Cookie 已保存"})

            if path == "/api/login/douyin/stop":
                douyin_login.stop()
                return self._json({"success": True, "message": "已关闭登录浏览器"})

            # 提交音视频合成任务
            if path == "/api/merge/start":
                payload = self._body_json()
                video_url = str(payload.get("video_url", "")).strip()
                audio_url = str(payload.get("audio_url", "")).strip()
                platform = str(payload.get("platform", "bilibili")).strip()
                if not video_url or not audio_url:
                    return self._json({"success": False, "error": "缺少视频流或音频流地址"}, 400)
                # 注入登录 Cookie, 避免高码率 DASH 流下载 403
                cookie = ""
                saved = store.get_platform(platform)
                if platform == "bilibili" and saved.get("sessdata"):
                    cookie = f"SESSDATA={saved['sessdata']}"
                elif platform == "douyin" and saved.get("cookie"):
                    cookie = saved["cookie"]
                task = merge_manager.submit(
                    video_url=video_url, audio_url=audio_url, platform=platform,
                    title=str(payload.get("title", "video")),
                    quality=str(payload.get("quality", "高画质")),
                    cookie=cookie,
                    referer=str(payload.get("referer", "")),
                )
                return self._json({"success": True, "data": task.to_dict()})

            # 取消合成任务
            if path == "/api/merge/cancel":
                payload = self._body_json()
                ok = merge_manager.cancel(str(payload.get("id", "")))
                return self._json({"success": ok, "message": "已取消" if ok else "任务不可取消"})

            self._json({"error": "Not Found"}, 404)
        except Exception as e:
            self._json({"success": False, "error": f"服务器错误: {e}"}, 500)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.address_string()}] {fmt % args}")


def main() -> None:
    ap = argparse.ArgumentParser(description="VidParse 图形化界面")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print("=" * 56)
    print(f"  VidParse 图形界面 v{__version__}")
    print(f"  打开浏览器访问: {url}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 56)

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        douyin_login.stop()
        httpd.server_close()


if __name__ == "__main__":
    main()
