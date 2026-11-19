"""YouTube 解析器.

两套方案(按优先级自动尝试):
  1. Piped / Invidious 公开 API 实例(无需官方 Key, 纯 HTTP):
     - Piped:     GET {instance}/streams/{videoId}
                  -> videoStreams[] / audioStreams[] / hls
     - Invidious: GET {instance}/api/v1/videos/{videoId}
                  -> formatStreams[] / adaptiveFormats[]
     公开实例来自 piped.video / invidious.io 官方列表, 会动态挑选可用节点。
  2. yt-dlp 兜底(由社区持续维护, 抗 YouTube 变动能力最强)。

视频 ID 支持: youtube.com/watch?v= / youtu.be/ / youtube.com/shorts/
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..models import ParseError, VideoFormat, VideoInfo
from ..utils import HttpClient, detect_platform
from .base import BaseParser

# 公开实例(来自 piped.video / invidious.io 官方实例列表)
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi.moomoo.me",
    "https://pipedapi.adminforge.de",
    "https://api.piped.privacydev.net",
]
INVIDIOUS_INSTANCES = [
    "https://yewtu.be",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
]

VIDEO_ID_PATTERNS = [
    re.compile(r"[?&]v=([\w-]{11})"),
    re.compile(r"youtu\.be/([\w-]{11})"),
    re.compile(r"youtube\.com/shorts/([\w-]{11})"),
    re.compile(r"youtube\.com/embed/([\w-]{11})"),
    re.compile(r"^[\w-]{11}$"),
]


class YoutubeParser(BaseParser):
    platform = "youtube"

    def __init__(self, client: HttpClient | None = None, **options):
        super().__init__(client, **options)
        self.piped_instances = options.get("piped_instances") or PIPED_INSTANCES
        self.invidious_instances = options.get("invidious_instances") or INVIDIOUS_INSTANCES

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == "youtube"

    @staticmethod
    def extract_video_id(url: str) -> str:
        for pattern in VIDEO_ID_PATTERNS:
            m = pattern.search(url)
            if m:
                return m.group(1)
        raise ParseError("无法从链接中提取 YouTube 视频 ID", "youtube")

    def _try_piped(self, video_id: str) -> VideoInfo | None:
        for base in self.piped_instances:
            try:
                data = self.client.get_json(f"{base}/streams/{video_id}", timeout=10)
                if not data.get("videoStreams") and not data.get("hls"):
                    continue
                formats: List[VideoFormat] = []
                for s in data.get("videoStreams") or []:
                    if not s.get("url"):
                        continue
                    formats.append(VideoFormat(
                        format_id=str(s.get("quality", "")),
                        url=s["url"],
                        quality=str(s.get("quality", "")),
                        ext=str(s.get("format", "")).split("/")[-1] if s.get("format") else "mp4",
                        width=int(s.get("width") or 0),
                        height=int(s.get("height") or 0),
                        fps=float(s.get("fps") or 0),
                        protocol="hls" if s.get("url", "").endswith(".m3u8") else "http",
                        media_type="both" if not s.get("videoOnly") is True else "video",
                        note="Piped",
                    ))
                for s in data.get("audioStreams") or []:
                    if not s.get("url"):
                        continue
                    formats.append(VideoFormat(
                        format_id=f"audio-{s.get('quality', '')}",
                        url=s["url"],
                        quality=f"音频 {s.get('quality', '')}",
                        ext="m4a",
                        protocol="http", media_type="audio",
                        bitrate=int(s.get("bitrate") or 0),
                        note="Piped",
                    ))
                if data.get("hls"):
                    formats.append(VideoFormat(
                        format_id="hls", url=data["hls"], quality="HLS 自适应",
                        protocol="hls", media_type="both", note="Piped",
                    ))
                if not formats:
                    continue
                return self._to_info(video_id, data, formats, f"Piped:{base}")
            except Exception:
                continue
        return None

    def _try_invidious(self, video_id: str) -> VideoInfo | None:
        for base in self.invidious_instances:
            try:
                data = self.client.get_json(
                    f"{base}/api/v1/videos/{video_id}", timeout=10
                )
                if not data.get("formatStreams") and not data.get("adaptiveFormats"):
                    continue
                formats: List[VideoFormat] = []
                for s in data.get("formatStreams") or []:
                    if not s.get("url"):
                        continue
                    formats.append(VideoFormat(
                        format_id=str(s.get("itag", "")),
                        url=s["url"],
                        quality=str(s.get("qualityLabel", "")),
                        ext=str(s.get("type", "")).split("/")[-1] if s.get("type") else "mp4",
                        protocol="http", media_type="both", note="Invidious",
                    ))
                for s in data.get("adaptiveFormats") or []:
                    if not s.get("url"):
                        continue
                    is_video = str(s.get("type", "")).startswith("video")
                    formats.append(VideoFormat(
                        format_id=str(s.get("itag", "")),
                        url=s["url"],
                        quality=str(s.get("qualityLabel", "") or s.get("bitrate", "")),
                        ext=str(s.get("type", "")).split("/")[-1] if s.get("type") else "",
                        width=int(s.get("width") or 0),
                        height=int(s.get("height") or 0),
                        protocol="http",
                        media_type="video" if is_video else "audio",
                        bitrate=int(s.get("bitrate") or 0),
                        note="Invidious adaptive",
                    ))
                if not formats:
                    continue
                return self._to_info(video_id, data, formats, f"Invidious:{base}")
            except Exception:
                continue
        return None

    @staticmethod
    def _to_info(video_id: str, d: Dict[str, Any], formats: List[VideoFormat], engine: str) -> VideoInfo:
        thumbnails = d.get("thumbnailUrl") or d.get("videoThumbnails") or []
        cover = ""
        if isinstance(thumbnails, str):
            cover = thumbnails
        elif isinstance(thumbnails, list) and thumbnails:
            cover = thumbnails[-1].get("url", "") if isinstance(thumbnails[-1], dict) else str(thumbnails[-1])

        # Piped: uploader / uploaded; Invidious: author / published
        author = d.get("uploader") or d.get("author") or ""
        published = d.get("uploaded") or d.get("published") or 0
        if isinstance(published, str):
            published = 0

        return VideoInfo(
            platform="youtube",
            video_id=video_id,
            title=d.get("title", ""),
            author=author,
            duration=int(d.get("duration") or d.get("lengthSeconds") or 0),
            cover=cover,
            description=d.get("description", "") or "",
            publish_time=int(published or 0),
            view_count=int(d.get("views") or 0),
            like_count=int(d.get("likes") or 0),
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            formats=formats,
            extra={"engine": engine},
        )

    def parse(self, url: str) -> VideoInfo:
        video_id = self.extract_video_id(url)

        # 优先 Piped / Invidious(纯 HTTP, 无需安装依赖)
        info = self._try_piped(video_id)
        if info:
            return info
        info = self._try_invidious(video_id)
        if info:
            return info

        # 兜底 yt-dlp
        try:
            from .ytdlp import YtDlpParser
            return YtDlpParser(client=self.client, **self.options).parse(url)
        except ParseError as e:
            raise ParseError(
                "YouTube 解析失败: Piped/Invidious 公开实例不可用, 且 yt-dlp 兜底失败"
                f"({e.message}). 建议 pip install -U yt-dlp 后重试。",
                self.platform,
                e,
            ) from e
