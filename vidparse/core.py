"""解析调度核心: 平台识别 -> 选择解析器 -> 失败自动兜底."""

from __future__ import annotations

from typing import Any, Dict, List

from .auth import CookieStore
from .models import ParseError, ParseResult, VideoInfo
from .parsers import BilibiliParser, DouyinParser, YoutubeParser, YtDlpParser
from .parsers.base import BaseParser
from .utils import HttpClient, detect_platform


class VideoParser:
    """多平台视频解析统一入口.

    用法:
        parser = VideoParser()
        result = parser.parse("https://www.bilibili.com/video/BV1xx411c7mD")
        print(result.to_dict())

        # 抛出式接口
        info = parser.parse_or_raise(url)
    """

    def __init__(
        self,
        *,
        sessdata: str = "",
        douyin_cookie: str = "",
        fallback_ytdlp: bool = True,
        timeout: int = 20,
        retries: int = 5,
        auto_cookie: bool = True,
        **options: Any,
    ):
        """初始化.

        :param sessdata: B站 SESSDATA Cookie(可选, 用于高清/会员画质)
        :param douyin_cookie: 抖音 Cookie(可选, 用于绕过风控)
        :param fallback_ytdlp: 专用解析器失败时是否用 yt-dlp 兜底
        :param timeout: HTTP 超时(秒)
        :param auto_cookie: 是否自动加载本地已保存的登录 Cookie(扫码登录后免配置)
        :param options: 透传给解析器的额外参数(如 quality/dash/cookiefile)
        """
        self.options = options
        self.client = HttpClient(timeout=timeout)
        self.fallback_ytdlp = fallback_ytdlp

        # 自动加载本地扫码登录保存的 Cookie(显式传入的优先)
        store = CookieStore() if auto_cookie else None
        if not sessdata and store:
            sessdata = store.get_sessdata()
        if not douyin_cookie and store:
            douyin_cookie = store.get_douyin_cookie()

        common = dict(options)
        self.parsers: List[BaseParser] = [
            BilibiliParser(self.client, sessdata=sessdata, **common),
            DouyinParser(self.client, cookie=douyin_cookie, **common),
            YoutubeParser(self.client, **common),
        ]
        self.fallback = YtDlpParser(self.client, **common)

    def _select_parsers(self, url: str) -> List[BaseParser]:
        platform = detect_platform(url)
        matched = [p for p in self.parsers if p.can_handle(url)]
        if platform != "generic" and matched:
            return matched  # 专用解析器
        # 未识别平台: 只用通用兜底
        return [self.fallback]

    def parse(self, url: str) -> ParseResult:
        """解析链接, 返回 ParseResult(不抛异常)."""
        if not isinstance(url, str) or not url.strip():
            return ParseResult.fail("链接不能为空")
        url = url.strip()

        parsers = self._select_parsers(url)
        errors: List[str] = []
        skip_fallback = False
        for parser in parsers:
            try:
                info: VideoInfo = parser.parse(url)
                return ParseResult.ok(info)
            except ParseError as e:
                errors.append(f"[{parser.platform}] {e.message}")
                if getattr(e, "skip_fallback", False):
                    skip_fallback = True
            except Exception as e:  # 防止单个解析器的未知异常中断整体
                errors.append(f"[{parser.platform}] 未预期错误: {e}")

        # 专用解析器全失败 -> yt-dlp 兜底(确定性失败时跳过)
        if self.fallback_ytdlp and not skip_fallback and self.fallback not in parsers:
            try:
                info = self.fallback.parse(url)
                return ParseResult.ok(info)
            except ParseError as e:
                errors.append(f"[generic/yt-dlp] {e.message}")

        return ParseResult.fail("; ".join(errors) or "未知解析失败", detect_platform(url))

    def parse_or_raise(self, url: str) -> VideoInfo:
        """解析链接, 失败时抛 ParseError."""
        result = self.parse(url)
        if not result.success:
            raise ParseError(result.error or "解析失败", result.platform)
        assert result.info is not None
        return result.info

    def parse_json(self, url: str) -> Dict[str, Any]:
        """解析并返回可序列化的字典."""
        return self.parse(url).to_dict()
