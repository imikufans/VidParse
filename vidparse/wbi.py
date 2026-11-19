"""Bilibili WBI 签名算法.

B站自 2023 年起对 /x/.../wbi/... 系列接口(如 wbi/playurl)要求额外签名参数
w_rid 与 wts。算法公开且稳定:

1. 请求 /x/web-interface/nav 拿到 wbi_img.img_url 与 sub_url, 取文件名(去扩展名)
   得到 img_key / sub_key。
2. raw_key = img_key + sub_key, 按固定的 64 位重排表取字符, 取前 32 位得 mixin_key。
3. 参数按 key 排序, 过滤 value 中的 !'()* 字符, urlencode。
4. wts = 当前秒级时间戳(允许一定偏差), w_rid = md5(encoded_params + mixin_key)。
5. 把 w_rid / wts 附加到请求参数。

参考: 社区开源的 bilibili-api / downkyi 等对 WBI 的公开实现。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict
from urllib.parse import urlencode

from .utils import HttpClient

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"


def _extract_key(url: str) -> str:
    return url.rsplit("/", 1)[-1].split(".")[0]


def get_mixin_key(raw_key: str) -> str:
    return "".join(raw_key[i] for i in MIXIN_KEY_ENC_TAB)[:32]


class WbiSigner:
    """缓存 img_key/sub_key 的 WBI 签名器."""

    def __init__(self, client: HttpClient):
        self.client = client
        self._img_key = ""
        self._sub_key = ""
        self._fetched_at = 0.0

    def refresh(self) -> bool:
        """从 nav 接口刷新密钥. 成功返回 True."""
        try:
            data = self.client.get_json(
                NAV_URL,
                headers={"Referer": "https://www.bilibili.com/"},
            )
            wbi_img = (data.get("data") or {}).get("wbi_img") or {}
            img_url = wbi_img.get("img_url", "")
            sub_url = wbi_img.get("sub_url", "")
            if not img_url or not sub_url:
                return False
            self._img_key = _extract_key(img_url)
            self._sub_key = _extract_key(sub_url)
            self._fetched_at = time.time()
            return True
        except Exception:
            return False

    def _ensure_keys(self) -> bool:
        # 密钥有效期很长(通常随版本更新才变), 缓存 1 小时
        if not self._img_key or time.time() - self._fetched_at > 3600:
            return self.refresh()
        return True

    @staticmethod
    def _sanitize(value: Any) -> str:
        # 过滤掉 !'()* 这几个特殊字符
        return "".join(ch for ch in str(value) if ch not in "!'()*")

    def sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """给参数字典加上 w_rid 与 wts."""
        if not self._ensure_keys():
            raise RuntimeError("无法获取 WBI 签名密钥")

        mixin_key = get_mixin_key(self._img_key + self._sub_key)
        params = dict(params)
        params["wts"] = int(time.time())
        # 按 key 排序并清洗 value
        items = sorted((k, self._sanitize(v)) for k, v in params.items())
        query = urlencode(items)
        w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
        params["w_rid"] = w_rid
        return params
