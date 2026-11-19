"""VidParse - 多平台视频解析工具.

支持平台:
    - Bilibili (b23.tv / bilibili.com)
    - 抖音 (v.douyin.com / douyin.com)
    - YouTube (Piped / Invidious / yt-dlp)
    - 以及其他 yt-dlp 支持的上千个平台

纯 Python 标准库即可运行核心解析; yt-dlp 作为可选增强(YouTube 兜底与通用平台)。
"""

from .models import VideoInfo, VideoFormat, ParseError, ParseResult
from .core import VideoParser

__version__ = "1.1.0"
__all__ = [
    "VideoInfo",
    "VideoFormat",
    "ParseError",
    "ParseResult",
    "VideoParser",
    "__version__",
]
