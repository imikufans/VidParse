"""统一数据模型.

所有平台解析器把各自平台的返回数据结构, 归一化为这里的 VideoInfo / VideoFormat,
从而让上层(CLI / HTTP API)以同一种方式消费。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class VideoFormat:
    """单个可下载的媒体格式/清晰度."""

    format_id: str                 # 平台内部格式标识(如 "80", "1080p", "137+140")
    url: str                       # 可直接请求的媒体 URL(可能是分片的 DASH/HLS)
    quality: str = ""              # 人类可读的清晰度, 如 "1080P 高码率"
    ext: str = ""                  # 容器/扩展名: mp4 / flv / m4a ...
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""                # 视频编码, 如 av01 / h264
    protocol: str = "http"         # http / https / dash / hls
    media_type: str = "video"      # video / audio / both
    bitrate: int = 0
    size: int = 0                  # 字节, 0 表示未知
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VideoInfo:
    """归一化后的视频信息."""

    platform: str                  # bilibili / douyin / youtube / generic
    video_id: str = ""             # 平台内唯一 ID (bvid / aweme_id / videoId)
    title: str = ""
    author: str = ""
    author_id: str = ""
    duration: int = 0              # 秒
    cover: str = ""                # 封面图 URL
    description: str = ""
    publish_time: int = 0          #  unix 秒
    view_count: int = 0
    like_count: int = 0
    source_url: str = ""
    formats: List[VideoFormat] = field(default_factory=list)
    # 解析链路里的附加信息(如是否用了 WBI 签名、走了哪个 YouTube 实例)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["formats"] = [f.to_dict() for f in self.formats]
        return data

    @property
    def best_video(self) -> Optional[VideoFormat]:
        """按分辨率挑选最优的视频格式(音频/混合流)."""
        candidates = [f for f in self.formats if f.media_type in ("video", "both")]
        if not candidates:
            return None
        return max(candidates, key=lambda f: (f.height or 0, f.bitrate or 0))

    @property
    def best_audio(self) -> Optional[VideoFormat]:
        candidates = [f for f in self.formats if f.media_type in ("audio", "both")]
        if not candidates:
            return None
        return max(candidates, key=lambda f: f.bitrate or 0)


class ParseError(Exception):
    """解析失败异常."""

    def __init__(self, message: str, platform: str = "", cause: Exception | None = None,
                 skip_fallback: bool = False):
        super().__init__(message)
        self.message = message
        self.platform = platform
        self.cause = cause
        # 确定性失败(如短链被降级、列表页): 兜底解析器也无能为力, 跳过以避免误导性错误信息
        self.skip_fallback = skip_fallback

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.message,
            "platform": self.platform,
            "cause": repr(self.cause) if self.cause else None,
        }


@dataclass
class ParseResult:
    """解析结果包装: 成功返回 info, 失败返回 error."""

    success: bool
    info: Optional[VideoInfo] = None
    error: Optional[str] = None
    platform: str = ""

    @classmethod
    def ok(cls, info: VideoInfo) -> "ParseResult":
        return cls(success=True, info=info, platform=info.platform)

    @classmethod
    def fail(cls, message: str, platform: str = "") -> "ParseResult":
        return cls(success=False, error=message, platform=platform)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "success": self.success,
            "platform": self.platform,
        }
        if self.success and self.info is not None:
            data["data"] = self.info.to_dict()
        else:
            data["error"] = self.error
        return data
