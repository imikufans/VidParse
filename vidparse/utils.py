"""通用工具: HTTP 请求 / 平台识别 / 链接提取.

为避免强制安装第三方库, 这里用标准库 urllib 实现了一个够用的 HTTP 客户端,
支持: 自定义 Header、Cookie、重定向跟随、gzip/deflate 解压、超时与重试。
若环境安装了 requests, 也可由各解析器自行选择。
"""

from __future__ import annotations

import gzip
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Any, Dict, Optional, Tuple

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class HttpClient:
    """轻量 HTTP 客户端(标准库实现)."""

    def __init__(self, timeout: int = 15, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self._opener = self._build_opener()

    @staticmethod
    def _build_opener() -> urllib.request.OpenerDirector:
        # 默认 urllib 已自带重定向处理器, 这里仅保证 gzip 支持通过手动解压完成
        return urllib.request.build_opener()

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[bytes] = None,
        follow_redirect: bool = True,
    ) -> Tuple[bytes, Dict[str, str], str]:
        """返回 (body_bytes, response_headers, final_url)."""
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)

        final_headers: Dict[str, str] = {
            "User-Agent": DEFAULT_UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            # 抖音等平台会阻断被风控的 keep-alive 连接; 显式关闭连接每次新建, 显著提高成功率
            "Connection": "close",
        }
        if headers:
            final_headers.update(headers)

        req = urllib.request.Request(url, data=data, headers=final_headers, method=method)
        if not follow_redirect:
            # 用一个不跟随重定向的 opener
            opener = urllib.request.build_opener(NoRedirect)
        else:
            opener = self._opener

        last_err: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                with opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    resp_headers = {k.lower(): v for k, v in resp.headers.items()}
                    final_url = resp.geturl()
                    # 记录真实状态码: NoRedirect 下 3xx 被当作 200 返回, 需据此识别重定向
                    resp_headers["__status__"] = str(getattr(resp, "status", 200) or 200)
                break
            except urllib.error.HTTPError as e:
                # 4xx/5xx 也把 body 读出来, 便于上层判断具体错误
                raw = e.read()
                resp_headers = {k.lower(): v for k, v in e.headers.items()}
                resp_headers["__status__"] = str(e.code)
                final_url = e.geturl() or url
                if e.code >= 400:
                    raise HttpStatusError(e.code, url, raw, resp_headers) from e
                break
            except (socket.timeout, TimeoutError, ConnectionResetError,
                    ConnectionAbortedError, BrokenPipeError, ssl.SSLEOFError,
                    ssl.SSLWantReadError) as e:
                # 读取超时 / 连接被重置 / TLS 连接被中断: 重试, 最后一次才抛出统一的 NetworkError
                last_err = e
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise NetworkError(f"{type(e).__name__}(重试 {self.retries} 次后仍失败)", url) from e
            except urllib.error.URLError as e:
                reason = str(e.reason)
                # 部分环境下 socket.timeout / 连接重置被包在 URLError.reason 里
                if isinstance(e.reason, (socket.timeout, TimeoutError, ConnectionResetError,
                                         ConnectionAbortedError, BrokenPipeError,
                                         ssl.SSLEOFError, ssl.SSLWantReadError)):
                    last_err = e
                    if attempt < self.retries:
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise NetworkError(f"{type(e.reason).__name__}(重试 {self.retries} 次后仍失败)", url) from e
                raise NetworkError(reason, url) from e

        # 解压
        encoding = resp_headers.get("content-encoding", "").lower()
        if encoding == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        elif encoding == "deflate":
            try:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    pass
        return raw, resp_headers, final_url

    def get_json(self, url: str, **kwargs: Any) -> Dict[str, Any]:
        body, _, _ = self.request(url, **kwargs)
        return json.loads(body.decode("utf-8", errors="replace"))

    def get_text(self, url: str, encoding: str = "utf-8", **kwargs: Any) -> str:
        body, _, _ = self.request(url, **kwargs)
        return body.decode(encoding, errors="replace")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止跟随重定向的处理器."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class HttpStatusError(Exception):
    def __init__(self, code: int, url: str, body: bytes, headers: Dict[str, str]):
        self.code = code
        self.url = url
        self.body = body
        self.headers = headers
        super().__init__(f"HTTP {code} for {url}")


class NetworkError(Exception):
    def __init__(self, reason: str, url: str):
        self.reason = reason
        self.url = url
        super().__init__(f"网络错误 {reason} for {url}")


# ---------------------------------------------------------------------------
# 平台识别与链接提取
# ---------------------------------------------------------------------------

def detect_platform(url_or_text: str) -> str:
    """根据 URL / 分享文本判断平台.

    返回: bilibili / douyin / youtube / generic
    """
    def _match(text: str) -> str:
        if any(k in text for k in ("bilibili.com", "b23.tv")):
            return "bilibili"
        if any(k in text for k in ("douyin.com", "iesdouyin.com")):
            return "douyin"
        if any(k in text for k in ("youtube.com", "youtu.be", "youtube-nocookie.com")):
            return "youtube"
        return "generic"

    result = _match(url_or_text.lower())
    if result != "generic":
        return result
    # 兼容带中文文案的分享文本: 提取里面的链接再判断一次(仅一层, 避免递归)
    for u in extract_urls(url_or_text):
        result = _match(u.lower())
        if result != "generic":
            return result
    return "generic"


URL_RE = re.compile(r"https?://[^\s<>\"'\[\]（） 【】]+", re.UNICODE)


def extract_urls(text: str) -> list[str]:
    """从一段文本(抖音分享口令等)中提取所有 http(s) 链接."""
    return [u.rstrip(".,;，。；") for u in URL_RE.findall(text)]


def extract_first_url(text: str) -> Optional[str]:
    urls = extract_urls(text)
    return urls[0] if urls else None


def resolve_redirect(client: HttpClient, short_url: str, max_hops: int = 8) -> str:
    """手动跟随重定向, 拿到短链(如 b23.tv / v.douyin.com)的最终 URL.

    注意: urllib 的 NoRedirect handler 让 redirect_request 返回 None 时, 302 会被
    "吞掉"当作普通响应返回(状态码不再抛 HTTPError), location 只在 headers 里。
    因此这里必须主动检查响应状态/headers, 不能只依赖捕获 HttpStatusError。
    """
    current = short_url
    for _ in range(max_hops):
        try:
            _, headers, final = client.request(current, follow_redirect=False)
        except HttpStatusError as e:
            loc = e.headers.get("location")
            if 300 <= e.code < 400 and loc:
                current = urllib.parse.urljoin(current, loc)
                continue
            raise
        # 关键是这里: 即使没抛异常, 也要检查 headers 里是否有 location(302 被吞的情况)
        loc = headers.get("location")
        if loc and headers.get("__status__", "").startswith("3"):
            current = urllib.parse.urljoin(final or current, loc)
            continue
        if loc and (final == current or not final):
            # 兜底: 无状态码信息但有 location 且未前进, 视为重定向
            current = urllib.parse.urljoin(current, loc)
            continue
        return final or current
    return current


def safe_filename(name: str, max_len: int = 120) -> str:
    """把标题清理为安全的文件名."""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
    name = name.strip(" .")
    if not name:
        name = "video"
    return name[:max_len]
