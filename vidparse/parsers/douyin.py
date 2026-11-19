"""抖音解析器.

接口链路(基于抖音 Web 端公开数据, 社区广泛使用):
  1. 从分享文本/口令提取链接, v.douyin.com 短链跟随重定向拿到 video/xxxx 页面
  2. 请求视频页 HTML, 从中提取 window._ROUTER_DATA (新版) 中的 aweme 详情
     - 兼容旧版 window._RENDER_DATA (URL 编码的 JSON)
  3. 拿到 play_addr / video_id 后, 通过内部 play 接口换取无水印直链:
     https://aweme.snssdk.com/aweme/v1/play/?video_id=<id>&ratio=1080p&line=0
     (该接口 302 到实际 CDN 地址, 跟随重定向即得到无水印 mp4)

说明: 抖音反爬策略更新频繁; 本解析器实现多种兜底提取方式, 若均失败,
上层工厂会自动回退到 yt-dlp(其抖音 extractor 由社区持续维护)。
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Dict, List

from ..models import ParseError, VideoFormat, VideoInfo
from ..utils import (
    MOBILE_UA,
    HttpClient,
    detect_platform,
    extract_first_url,
    resolve_redirect,
)
from .base import BaseParser

PLAY_API = "https://aweme.snssdk.com/aweme/v1/play/"


class DouyinParser(BaseParser):
    platform = "douyin"

    def __init__(self, client: HttpClient | None = None, cookie: str = "", **options):
        super().__init__(client, **options)
        self.cookie = cookie

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == "douyin"

    def _headers(self, referer: str = "https://www.douyin.com/") -> Dict[str, str]:
        headers = {
            "User-Agent": MOBILE_UA,
            "Referer": referer,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        return headers

    @staticmethod
    def _get_by_path(obj: Any, path: str) -> Any:
        """按 'a.b.c' 路径安全取值."""
        cur = obj
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def _find_aweme(self, data: Any) -> Dict[str, Any] | None:
        """在嵌套数据中递归寻找第一个包含 video/aweme_id 的 aweme 对象."""
        if isinstance(data, dict):
            if "aweme_id" in data and ("video" in data or "desc" in data):
                return data
            for v in data.values():
                found = self._find_aweme(v)
                if found:
                    return found
        elif isinstance(data, list):
            for item in data:
                found = self._find_aweme(item)
                if found:
                    return found
        return None

    def _extract_from_html(self, html: str) -> Dict[str, Any] | None:
        # 方式一: window._ROUTER_DATA = {...}
        m = re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\});?", html, re.S)
        if m:
            try:
                obj = json.loads(m.group(1))
                aweme = self._find_aweme(obj)
                if aweme:
                    return aweme
            except json.JSONDecodeError:
                pass

        # 方式二: window._RENDER_DATA = <urlencoded json>
        m = re.search(r"window\._RENDER_DATA\s*=\s*(\d+|'[^']+'|\"[^\"]+\")", html)
        if m:
            raw = m.group(1).strip("'\"")
            try:
                decoded = urllib.parse.unquote(raw)
                obj = json.loads(decoded)
                aweme = self._find_aweme(obj)
                if aweme:
                    return aweme
            except (json.JSONDecodeError, ValueError):
                pass

        # 方式三: 页面内嵌 JSON-LD / RENDER_DATA 直接的 aweme_detail
        m = re.search(r'"aweme_detail"\s*:\s*(\{.*?\})(?:,\s*"|})', html, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return None

    def _no_watermark_url(self, video_id: str, ratio: str = "1080p") -> str:
        return f"{PLAY_API}?video_id={video_id}&ratio={ratio}&line=0"

    # 这些是抖音的「列表/搜索/主页」类路径, 页面里不含单个视频数据, 无法解析
    _NON_VIDEO_PATHS = (
        "/search", "/jingxuan", "/discover", "/user/", "/user?",
        "/follow", "/friend", "/hot", "/topic/", "/challenge/",
        "/collection/", "/favorites", "/like", "/watchlater",
    )

    @classmethod
    def _is_non_video_page(cls, link: str) -> bool:
        path = urllib.parse.urlparse(link).path.lower().rstrip("/") + "/"
        return any(p.rstrip("/") + "/" in path for p in cls._NON_VIDEO_PATHS)

    @staticmethod
    def _extract_video_id(link: str) -> str:
        """从链接里提取抖音视频 ID(兼容 /video/<id>、/share/video/<id>、modal_id 等)."""
        m = re.search(r"/(?:video|note)/(\d+)", link)
        if m:
            return m.group(1)
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        for key in ("modal_id", "video_id", "aweme_id", "item_id"):
            if qs.get(key):
                return qs[key][0]
        m = re.search(r"(?:aweme_id|item_id)=(\d+)", link)
        return m.group(1) if m else ""

    @staticmethod
    def _has_video_id(link: str) -> bool:
        return bool(DouyinParser._extract_video_id(link))

    def _fetch_aweme_via_mobile_api(self, aweme_id: str) -> Dict[str, Any] | None:
        """用移动端 detail API 获取视频数据.

        Web 端 /aweme/v1/web/aweme/detail/ 需要 a_bogus 签名(403), 而移动端
        aweme.snssdk.com/aweme/v1/aweme/detail/ 用登录 Cookie 即可返回完整数据。
        这是当前反爬环境下最稳的兜底路径。
        """
        url = (
            "https://aweme.snssdk.com/aweme/v1/aweme/detail/"
            f"?aweme_id={aweme_id}&aid=1128&version_code=112800&device_platform=iphone"
        )
        ua = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        )
        headers = {
            "User-Agent": ua,
            "Accept": "application/json",
            "Connection": "close",
            "Referer": f"https://www.douyin.com/video/{aweme_id}",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        try:
            data = self.client.get_json(url, headers=headers)
        except Exception:
            return None
        if data.get("status_code") != 0:
            return None
        return data.get("aweme_detail") or None

    def parse(self, url: str) -> VideoInfo:
        link = extract_first_url(url) or url

        # 短链 / 口令里的链接先跟随重定向
        if "v.douyin.com" in link or "iesdouyin.com/share" in link:
            try:
                link = resolve_redirect(self.client, link)
            except Exception as e:
                raise ParseError(f"抖音短链解析失败: {e}", self.platform, e) from e
            # 抖音会对风控 IP 把短链降级重定向到首页(不含视频 ID), 此时无法继续
            if not self._has_video_id(link):
                raise ParseError(
                    "抖音短链被重定向到了首页, 未能拿到视频 ID(当前网络环境被抖音风控, "
                    "常见于服务器/数据中心 IP)。请在浏览器打开该视频, 用浏览器地址栏的完整链接"
                    "(形如 www.douyin.com/video/数字ID)重新解析, 或复制分享口令重试。",
                    self.platform, skip_fallback=True,
                )

        # 搜索页 / 发现页 / 用户主页没有视频数据, 提前给出明确指引, 避免无谓等待与误导
        if self._is_non_video_page(link):
            raise ParseError(
                "这是一个抖音搜索/列表页, 不含可解析的单个视频。"
                "请打开具体视频后复制其链接(形如 www.douyin.com/video/数字ID)或分享口令再解析。",
                self.platform, skip_fallback=True,
            )

        # 从 URL 里提取视频 ID(短链解析后 link 可能已是分享页, 也可能仍是原视频链接)
        aweme_id_hint = self._extract_video_id(link)
        aweme: Dict[str, Any] | None = None

        # 路径一: 请求视频页 HTML, 从 SSR 数据提取
        try:
            html = self.client.get_text(link, headers=self._headers(link))
            aweme = self._extract_from_html(html)
        except Exception:
            aweme = None  # 网络/反爬失败时退到移动端 API

        # 路径二(关键兜底): 抖音 Web SSR 常不含视频数据, 改用不需 a_bogus 签名的移动端 detail API
        if not aweme and aweme_id_hint:
            aweme = self._fetch_aweme_via_mobile_api(aweme_id_hint)

        if not aweme:
            raise ParseError(
                "未能从抖音页面提取视频数据(可能被反爬拦截)。请确认已扫码登录抖音后重试,"
                "或在浏览器打开视频用地址栏完整链接解析。",
                self.platform,
            )

        video = aweme.get("video") or {}
        aweme_id = str(aweme.get("aweme_id", ""))
        video_id = str(
            self._get_by_path(video, "play_addr.video_id")
            or self._get_by_path(video, "bitrate_info.0.play_addr.video_id")
            or self._get_by_path(video, "download_addr.video_id")
            or ""
        )

        formats: List[VideoFormat] = []
        # 优先用 play_addr.url_list 里的直链
        url_list = (
            self._get_by_path(video, "play_addr.url_list")
            or self._get_by_path(video, "bitrate_info.0.play_addr.url_list")
            or []
        )
        for i, u in enumerate(url_list):
            if u:
                formats.append(VideoFormat(
                    format_id=f"douyin-{i}",
                    url=u,
                    quality="无水印" if i == 0 else f"线路{i}",
                    ext="mp4",
                    width=int(video.get("width", 0) or 0),
                    height=int(video.get("height", 0) or 0),
                    protocol="http", media_type="both",
                ))

        # 拿到 video_id 后生成无水印直链(更稳定)
        if video_id:
            formats.insert(0, VideoFormat(
                format_id="no-watermark",
                url=self._no_watermark_url(video_id),
                quality="1080P 无水印",
                ext="mp4",
                width=int(video.get("width", 0) or 0),
                height=int(video.get("height", 0) or 0),
                protocol="http", media_type="both",
                note="play 接口 302 到 CDN 直链",
            ))

        if not formats:
            raise ParseError("抖音视频无可用播放地址", self.platform)

        author = aweme.get("author") or {}
        stats = aweme.get("statistics") or {}
        cover = (
            self._get_by_path(video, "cover.url_list.0")
            or self._get_by_path(video, "origin_cover.url_list.0")
            or ""
        )
        return VideoInfo(
            platform=self.platform,
            video_id=aweme_id,
            title=aweme.get("desc", ""),
            author=author.get("nickname", ""),
            author_id=str(author.get("uid", "")),
            duration=int((video.get("duration") or 0) // 1000),
            cover=cover,
            description=aweme.get("desc", ""),
            publish_time=int(aweme.get("create_time") or 0),
            like_count=int(stats.get("digg_count") or 0),
            source_url=link,
            formats=formats,
            extra={"video_id": video_id, "aweme_id": aweme_id},
        )
