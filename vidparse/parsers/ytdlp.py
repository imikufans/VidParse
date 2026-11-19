"""yt-dlp 通用解析器(兜底).

yt-dlp 支持上千个站点(YouTube/B站/抖音/TikTok/微博/小红书/推特/...),
作为其他专用解析器的统一兜底。作为 Python 库调用:

    import yt_dlp
    with yt_dlp.YoutubeDL({'skip_download': True, 'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)

依赖: pip install yt-dlp (可选)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

from ..models import ParseError, VideoFormat, VideoInfo
from .base import BaseParser

# 内置 yt-dlp 目录(bin/ytdlp), 让工具零依赖即可使用; 不污染系统 Python 环境
_VENDOR_DIR = Path(__file__).resolve().parents[2] / "bin" / "ytdlp"


def _ensure_vendor_path() -> None:
    vendor = str(_VENDOR_DIR)
    if _VENDOR_DIR.is_dir() and vendor not in sys.path:
        sys.path.insert(0, vendor)


def is_ytdlp_available() -> bool:
    _ensure_vendor_path()
    try:
        import yt_dlp  # noqa: F401
        return True
    except ImportError:
        return False


class YtDlpParser(BaseParser):
    platform = "generic"

    def can_handle(self, url: str) -> bool:
        # 兜底解析器可处理任意 http(s) 链接
        return url.lower().startswith(("http://", "https://")) or is_ytdlp_available()

    def parse(self, url: str) -> VideoInfo:
        if not is_ytdlp_available():
            raise ParseError(
                "未安装 yt-dlp, 请执行: pip install yt-dlp",
                self.platform,
            )

        _ensure_vendor_path()
        try:
            import yt_dlp
        except ImportError as e:  # pragma: no cover
            raise ParseError(
                "无法导入 yt-dlp, 请确认 bin/ytdlp 目录完整或执行 pip install yt-dlp",
                self.platform, e,
            ) from e

        ydl_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": False,
        }
        # 支持透传 cookies / headers 等 yt-dlp 选项
        for key in ("cookiefile", "http_headers", "proxy", "username", "password"):
            if key in self.options:
                ydl_opts[key] = self.options[key]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            raise ParseError(f"yt-dlp 解析失败: {e}", self.platform, e) from e

        if not info:
            raise ParseError("yt-dlp 未返回视频信息", self.platform)

        # 单条视频(非播放列表)的 formats
        formats: List[VideoFormat] = []
        for f in info.get("formats") or []:
            if not f.get("url"):
                continue
            vcodec = f.get("vcodec") or "none"
            acodec = f.get("acodec") or "none"
            if vcodec != "none" and acodec != "none":
                media_type = "both"
            elif vcodec != "none":
                media_type = "video"
            elif acodec != "none":
                media_type = "audio"
            else:
                media_type = "video"
            formats.append(VideoFormat(
                format_id=str(f.get("format_id", "")),
                url=f["url"],
                quality=str(f.get("format_note") or f.get("height") or ""),
                ext=f.get("ext", ""),
                width=int(f.get("width") or 0),
                height=int(f.get("height") or 0),
                fps=float(f.get("fps") or 0),
                codec=vcodec if vcodec != "none" else acodec,
                protocol=str(f.get("protocol", "http")).split("+")[0],
                media_type=media_type,
                bitrate=int(f.get("tbr") or 0) * 1000,
                size=int(f.get("filesize") or f.get("filesize_approx") or 0),
            ))

        # 有些站点只给一个合并好的 url
        if not formats and info.get("url"):
            formats.append(VideoFormat(
                format_id="default",
                url=info["url"],
                ext=info.get("ext", ""),
                media_type="both",
            ))

        uploader = info.get("uploader") or info.get("channel") or ""
        return VideoInfo(
            platform=self._detect_source(info, url),
            video_id=str(info.get("id", "")),
            title=info.get("title", ""),
            author=uploader,
            author_id=str(info.get("channel_id") or info.get("uploader_id") or ""),
            duration=int(info.get("duration") or 0),
            cover=info.get("thumbnail", "") or "",
            description=info.get("description", "") or "",
            publish_time=int(info.get("timestamp") or 0),
            view_count=int(info.get("view_count") or 0),
            like_count=int(info.get("like_count") or 0),
            source_url=info.get("webpage_url", url),
            formats=formats,
            extra={"engine": "yt-dlp", "extractor": info.get("extractor_key", "")},
        )

    @staticmethod
    def _detect_source(info: Dict[str, Any], url: str) -> str:
        extractor = (info.get("extractor_key") or "").lower()
        if "youtube" in extractor:
            return "youtube"
        if "bilibili" in extractor or "bilibili" in url:
            return "bilibili"
        if "douyin" in extractor or "douyin" in url or "tiktok" in extractor:
            return "douyin"
        return "generic"
