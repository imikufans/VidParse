"""Bilibili 解析器.

接口链路(均来自 B站 Web 端公开接口, 社区广泛使用):
  1. b23.tv 短链 -> 重定向拿到真实 BV 号
  2. /x/web-interface/view?bvid=  -> 标题/UP主/封面/时长/分P cid
  3. /x/player/wbi/playurl   (WBI 签名, DASH, 需登录 Cookie 拿高码率)
     或 /x/player/playurl    (无需签名, 480P 及以下 mp4/flv 合并流)
     - fnval=0  -> data.durl[].url        : 音视频合并, 直接可播
     - fnval=16 -> data.dash.video/audio  : DASH 分离, 清晰度更高

登录态(可选): 传入 SESSDATA Cookie 可解析高码率/1080P+ 与会员画质。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from ..models import ParseError, VideoFormat, VideoInfo
from ..utils import HttpClient, detect_platform, resolve_redirect
from ..wbi import WbiSigner
from .base import BaseParser

VIEW_API = "https://api.bilibili.com/x/web-interface/view"
PLAYURL_API = "https://api.bilibili.com/x/player/playurl"
PLAYURL_WBI_API = "https://api.bilibili.com/x/player/wbi/playurl"

BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
AV_RE = re.compile(r"/av(\d+)")
BVID_PATTERNS = re.compile(r"^(BV[0-9A-Za-z]{10})$")


class BilibiliParser(BaseParser):
    platform = "bilibili"

    def __init__(self, client: HttpClient | None = None, sessdata: str = "", **options):
        super().__init__(client, **options)
        self.sessdata = sessdata
        self._signer = WbiSigner(self.client)

    def can_handle(self, url: str) -> bool:
        return detect_platform(url) == "bilibili"

    def _headers(self, referer: str = "https://www.bilibili.com/") -> Dict[str, str]:
        headers = {"Referer": referer}
        if self.sessdata:
            headers["Cookie"] = f"SESSDATA={self.sessdata}"
        return headers

    def _extract_bvid(self, url: str) -> str:
        # 短链先跟随重定向
        if "b23.tv" in url:
            url = resolve_redirect(self.client, url)
        m = BV_RE.search(url)
        if m:
            return m.group(1)
        # av 号: 通过 /x/web-interface/view 也可用 aid 查询, 这里转换为 bvid 由 view 接口处理
        m = AV_RE.search(url)
        if m:
            return ""
        raise ParseError("无法从链接中提取 B站 BV 号", self.platform)

    def _fetch_view(self, *, bvid: str = "", aid: str = "") -> Dict[str, Any]:
        params: Dict[str, Any] = {"bvid": bvid} if bvid else {"aid": aid}
        try:
            data = self.client.get_json(VIEW_API, params=params, headers=self._headers())
        except Exception as e:
            raise ParseError(f"获取 B站视频信息失败: {e}", self.platform, e) from e
        if data.get("code") != 0:
            raise ParseError(f"B站 view 接口返回错误: {data.get('message')}", self.platform)
        return data.get("data") or {}

    def _fetch_playurl(
        self,
        bvid: str,
        cid: int,
        quality: int,
        use_dash: bool,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "bvid": bvid,
            "cid": cid,
            "qn": quality,
            "fnval": 16 if use_dash else 0,
            "fnver": 0,
            "fourk": 1,
            "dbid": 0,
        }
        headers = self._headers(f"https://www.bilibili.com/video/{bvid}")

        # 优先尝试 WBI 签名接口(高清/DASH 必备), 失败回退到老接口
        if use_dash or self.sessdata:
            try:
                signed = self._signer.sign(params)
                data = self.client.get_json(PLAYURL_WBI_API, params=signed, headers=headers)
                if data.get("code") == 0:
                    return data.get("data") or {}
            except Exception:
                pass  # 回退老接口

        try:
            data = self.client.get_json(PLAYURL_API, params=params, headers=headers)
            if data.get("code") == 0:
                return data.get("data") or {}
        except Exception as e:
            raise ParseError(f"获取 B站播放地址失败: {e}", self.platform, e) from e
        raise ParseError("获取 B站播放地址失败: 接口未返回有效数据", self.platform)

    @staticmethod
    def _quality_name(quality: int) -> str:
        return {
            120: "4K 超高清", 116: "1080P60 高帧率", 112: "1080P+ 高码率",
            80: "1080P 高清", 74: "720P60 高帧率", 64: "720P 高清",
            32: "480P 清晰", 16: "360P 流畅",
        }.get(quality, f"qn={quality}")

    def _build_formats(self, play: Dict[str, Any], use_dash: bool) -> List[VideoFormat]:
        formats: List[VideoFormat] = []

        # DASH: 分离的音视频流
        dash = play.get("dash") or {}
        for v in dash.get("video") or []:
            url = v.get("baseUrl") or v.get("base_url") or ""
            if not url:
                continue
            w, h = v.get("width", 0), v.get("height", 0)
            formats.append(VideoFormat(
                format_id=str(v.get("id", "")),
                url=url,
                quality=f"{h}P {v.get('frame', '')}".strip(),
                ext="m4s",
                width=w, height=h,
                codec=str(v.get("codecs", "")).split("-")[0],
                protocol="dash", media_type="video",
                bitrate=int(v.get("bandwidth", 0) or 0) // 8,
                note=self._quality_name(int(v.get("id", 0) or 0)),
            ))
        for a in dash.get("audio") or []:
            url = a.get("baseUrl") or a.get("base_url") or ""
            if not url:
                continue
            formats.append(VideoFormat(
                format_id=f"audio-{a.get('id', '')}",
                url=url,
                quality=f"音频 {int(a.get('bandwidth', 0) or 0)//1000}kbps",
                ext="m4s",
                codec=str(a.get("codecs", "")).split("-")[0],
                protocol="dash", media_type="audio",
                bitrate=int(a.get("bandwidth", 0) or 0) // 8,
            ))

        # 合并流 durl
        for d in play.get("durl") or []:
            formats.append(VideoFormat(
                format_id=f"mp4-{d.get('order', 0)}",
                url=d.get("url", ""),
                quality=self._quality_name(int(play.get("quality", 0) or 0)),
                ext="mp4",
                protocol="http", media_type="both",
                size=int(d.get("size", 0) or 0),
            ))
        return formats

    def parse(self, url: str) -> VideoInfo:
        bvid = self._extract_bvid(url)

        # av 号链接: 用 aid 拉取 view 拿 bvid
        av_match = AV_RE.search(url)
        view = self._fetch_view(bvid=bvid, aid=(av_match.group(1) if av_match else ""))
        bvid = view.get("bvid", bvid)

        pages = view.get("pages") or []
        if not pages:
            raise ParseError("该 B站视频没有可用的分P", self.platform)

        # 支持通过 #page=2 或 ?p=2 选择分P, 默认第 1P
        page_index = 0
        m = re.search(r"[?&#]p(?:age)?=(\d+)", url, re.I)
        if m:
            page_index = max(0, min(int(m.group(1)) - 1, len(pages) - 1))
        page = pages[page_index]
        cid = int(page.get("cid", 0))

        use_dash = bool(self.options.get("dash", True)) and bool(self.sessdata)
        quality = int(self.options.get("quality", 80))
        play = self._fetch_playurl(bvid, cid, quality, use_dash)

        formats = self._build_formats(play, use_dash)

        # 登录态下 DASH 是音视频分离流(单独播放无声音)。额外请求一个 fnval=0 的
        # 合并流(mp4, 含声音), 作为"一键播放"选项放在最前, 兼顾画质与易用性。
        merged_added = False
        if use_dash and formats:
            try:
                merged_play = self._fetch_playurl(bvid, cid, quality, False)
                merged = self._build_formats(merged_play, False)
                if merged:
                    for mf in merged:
                        mf.note = "合并流·含声音"
                    formats = merged + formats
                    merged_added = True
            except Exception:
                pass  # 合并流获取失败不影响 DASH 结果

        # 无 DASH 时自动降级为合并流
        if not formats:
            play = self._fetch_playurl(bvid, cid, quality, False)
            formats = self._build_formats(play, False)
        if not formats:
            raise ParseError("未找到可用的 B站视频流", self.platform)

        owner = view.get("owner") or {}
        stat = view.get("stat") or {}
        return VideoInfo(
            platform=self.platform,
            video_id=bvid,
            title=view.get("title", ""),
            author=owner.get("name", ""),
            author_id=str(owner.get("mid", "")),
            duration=int(view.get("duration") or 0),
            cover=view.get("pic", ""),
            description=view.get("desc", ""),
            publish_time=int(view.get("pubdate") or 0),
            view_count=int(stat.get("view") or 0),
            like_count=int(stat.get("like") or 0),
            source_url=f"https://www.bilibili.com/video/{bvid}",
            formats=formats,
            extra={
                "cid": cid,
                "page": page_index + 1,
                "total_pages": len(pages),
                "dash": any(f.protocol == "dash" for f in formats),
                "has_merged": merged_added,
            },
        )
