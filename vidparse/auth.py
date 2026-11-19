"""登录与 Cookie 管理.

提供两种自动获取 Cookie 的方式(纯标准库实现, 无需第三方依赖):

1. Bilibili 扫码登录(官方接口):
   GET  /x/passport-login/web/qrcode/generate   -> url + qrcode_key
   GET  /x/passport-login/web/qrcode/poll       -> 扫码状态, 成功后 Set-Cookie 下发 SESSDATA
   状态码: 86101 未扫码 / 86090 已扫未确认 / 0 成功 / 86038 已过期

2. 抖音 CDP 浏览器登录:
   以 --remote-debugging-port 启动 Edge/Chrome 打开抖音登录页,
   用户扫码/登录后, 通过 Chrome DevTools Protocol 的 Network.getAllCookies
   读取 sessionid 等 Cookie, 绕过纯 HTTP 的风控(4031)。

Cookie 统一保存到本地 .cookies.json(仅存本机, 不上传), 解析器自动加载。
"""

from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import socket
import struct
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import DEFAULT_UA, MOBILE_UA

# Cookie 文件放在包的上级目录(项目根), 便于用户查找与管理
COOKIE_FILE = Path(__file__).resolve().parent.parent / ".cookies.json"

BILI_QR_GENERATE = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
BILI_QR_POLL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
BILI_NAV = "https://api.bilibili.com/x/web-interface/nav"

# 抖音的 /passport/login/ 已废弃, 直接访问会返回 {"非法应用", error_code:22},
# 无法展示登录二维码。改用首页, 由用户在右上角点「登录」后扫码。
DOUYIN_LOGIN_URL = "https://www.douyin.com/"
DOUYIN_HOME = "https://www.douyin.com/"


# ---------------------------------------------------------------------------
# Cookie 持久化
# ---------------------------------------------------------------------------

class CookieStore:
    """本地 Cookie 存储(JSON). 线程安全的简单读写封装."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else COOKIE_FILE
        self._lock = __import__("threading").Lock()

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {}
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}

    def save(self, data: Dict[str, Any]) -> None:
        with self._lock:
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            # 尽量限制为当前用户可读(Windows 下 best-effort)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    def get_platform(self, platform: str) -> Dict[str, Any]:
        return (self.load().get(platform) or {})

    def set_platform(self, platform: str, info: Dict[str, Any]) -> None:
        data = self.load()
        data[platform] = {**info, "updated_at": int(time.time())}
        self.save(data)

    def delete(self, platform: str) -> None:
        data = self.load()
        data.pop(platform, None)
        self.save(data)

    def get_sessdata(self) -> str:
        return str(self.get_platform("bilibili").get("sessdata", ""))

    def get_douyin_cookie(self) -> str:
        return str(self.get_platform("douyin").get("cookie", ""))

    def status(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        bili = self.get_platform("bilibili")
        dy = self.get_platform("douyin")
        result["bilibili"] = {
            "logged_in": bool(bili.get("sessdata")),
            "username": bili.get("username", ""),
            "updated_at": bili.get("updated_at", 0),
        }
        result["douyin"] = {
            "logged_in": bool(dy.get("cookie")),
            "username": dy.get("username", ""),
            "updated_at": dy.get("updated_at", 0),
        }
        return result


# ---------------------------------------------------------------------------
# Bilibili 扫码登录
# ---------------------------------------------------------------------------

class BiliQrLogin:
    """B站扫码登录流程(由 Web 层驱动: start -> 前端展示二维码 -> poll 循环)."""

    def __init__(self, store: CookieStore | None = None):
        self.store = store or CookieStore()

    def start(self) -> Dict[str, str]:
        """申请二维码, 返回 {url, qrcode_key}."""
        req = urllib.request.Request(
            BILI_QR_GENERATE,
            headers={"User-Agent": DEFAULT_UA, "Referer": "https://passport.bilibili.com/"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"申请B站二维码失败: {e}") from e
        if data.get("code") != 0:
            raise RuntimeError(f"申请B站二维码失败: {data.get('message')}")
        d = data["data"]
        return {"url": d["url"], "qrcode_key": d["qrcode_key"]}

    def poll(self, qrcode_key: str) -> Dict[str, Any]:
        """轮询扫码状态.

        返回 {"status": "pending"|"scanned"|"expired"|"success"|"error",
              "message": ..., "username": ...}
        成功时自动保存 Cookie。
        """
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar)
        )
        url = BILI_QR_POLL + "?" + urllib.parse.urlencode({"qrcode_key": qrcode_key})
        req = urllib.request.Request(
            url,
            headers={"User-Agent": DEFAULT_UA, "Referer": "https://passport.bilibili.com/"},
        )
        try:
            with opener.open(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            return {"status": "error", "message": f"轮询失败: {e}"}

        code = ((data.get("data") or {}).get("code"))
        if code == 86101:
            return {"status": "pending", "message": "等待扫码"}
        if code == 86090:
            return {"status": "scanned", "message": "已扫码, 请在手机上确认"}
        if code == 86038:
            return {"status": "expired", "message": "二维码已过期, 请刷新"}
        if code == 0:
            cookies = {c.name: c.value for c in jar}
            sessdata = cookies.get("SESSDATA", "")
            if not sessdata:
                # 某些情况 Set-Cookie 不在 jar 而需从 header 取, 兜底解析
                return {"status": "error", "message": "登录成功但未获取到 SESSDATA"}
            info = {"sessdata": sessdata,
                    "bili_jct": cookies.get("bili_jct", ""),
                    "DedeUserID": cookies.get("DedeUserID", "")}
            # 尝试获取昵称
            try:
                nav_req = urllib.request.Request(
                    BILI_NAV,
                    headers={"User-Agent": DEFAULT_UA,
                             "Cookie": f"SESSDATA={sessdata}",
                             "Referer": "https://www.bilibili.com/"},
                )
                with urllib.request.urlopen(nav_req, timeout=10) as r:
                    nav = json.loads(r.read().decode("utf-8"))
                uname = ((nav.get("data") or {}).get("userInfo") or {}).get("uname", "")
                info["username"] = uname
            except Exception:
                pass
            self.store.set_platform("bilibili", info)
            return {"status": "success", "message": "登录成功",
                    "username": info.get("username", "")}
        return {"status": "error", "message": f"未知状态码: {code}"}


# ---------------------------------------------------------------------------
# CDP WebSocket 最小客户端(标准库实现)
# ---------------------------------------------------------------------------

class CDPClient:
    """Chrome DevTools Protocol 的极简 WebSocket 客户端."""

    def __init__(self, ws_url: str, timeout: int = 10):
        u = urllib.parse.urlparse(ws_url)
        self.host = u.hostname or "127.0.0.1"
        self.port = u.port or 80
        self.path = u.path + (("?" + u.query) if u.query else "")
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("ascii"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("CDP WebSocket 握手失败")
            buf += chunk
        head, self._buf = buf.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n")[0] + b" ":
            raise RuntimeError("CDP WebSocket 握手失败: " + head.decode(errors="replace"))
        self._id = 0

    def _recv_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("CDP 连接已关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def send(self, payload: Dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            header = bytes([0x81, 0x80 | n])
        elif n < 65536:
            header = bytes([0x81, 0x80 | 126]) + struct.pack(">H", n)
        else:
            header = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(header + mask + masked)

    def recv(self) -> Dict[str, Any]:
        while True:
            h = self._recv_exact(2)
            opcode = h[0] & 0x0F
            length = h[1] & 0x7F
            masked = h[1] & 0x80
            if length == 126:
                length = struct.unpack(">H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else None
            payload = self._recv_exact(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:  # ping -> 忽略
                continue
            if opcode in (0x1, 0x0):
                return json.loads(payload.decode("utf-8", errors="replace"))

    def call(self, method: str, params: Optional[Dict[str, Any]] = None,
             timeout: int = 15) -> Dict[str, Any]:
        self._id += 1
        mid = self._id
        self.send({"id": mid, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.recv()
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result", {})
        raise TimeoutError(f"CDP 调用超时: {method}")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 抖音 CDP 浏览器登录
# ---------------------------------------------------------------------------

class DouyinLogin:
    """用真实浏览器扫码登录抖音并读取 Cookie.

    流程:
      start()  -> 启动 Edge/Chrome(独立配置目录, 带调试端口) 打开登录页
      poll()   -> 通过 CDP 读取 cookie, 检测到 sessionid 即保存
      stop()   -> 关闭浏览器
    """

    def __init__(self, store: CookieStore | None = None, port: int = 9333):
        self.store = store or CookieStore()
        self.port = port
        self.proc: Optional[subprocess.Popen] = None
        self.profile = os.path.join(
            os.path.expanduser("~"), ".vidparse", "dy-browser-profile"
        )

    @staticmethod
    def find_browser() -> Optional[str]:
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _port_open(self) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version",
                                        timeout=2) as r:
                r.read()
            return True
        except Exception:
            return False

    def _focus_login_page(self) -> None:
        """调试端口已开时: 打开/定位到抖音登录页并把窗口置前.

        兼容"浏览器残留后台进程但窗口被关掉/藏到后台"的情况, 避免用户
        点了登录却感觉"浏览器没弹出来"。
        """
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/json/list", timeout=5
            ) as r:
                targets = json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            return
        pages = [t for t in targets if t.get("type") == "page"]
        dy_tab = next((t for t in pages if "douyin.com" in t.get("url", "")), None)
        activated = False
        if dy_tab:
            # 失效的 /passport/login/ 会显示"非法应用", 导航回首页
            if "/passport/login" in dy_tab.get("url", ""):
                try:
                    c = CDPClient(dy_tab.get("webSocketDebuggerUrl", ""))
                    try:
                        c.call("Page.enable")
                        c.call("Page.navigate", {"url": DOUYIN_LOGIN_URL})
                    finally:
                        c.close()
                except Exception:
                    pass
            # 置前该标签(并把窗口从后台拉起)
            try:
                c = CDPClient(dy_tab.get("webSocketDebuggerUrl", ""))
                try:
                    c.call("Page.bringToFront")
                    activated = True
                finally:
                    c.close()
            except Exception:
                pass
            if not activated:
                try:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/json/activate/{dy_tab.get('id')}",
                        timeout=5).read()
                    activated = True
                except Exception:
                    pass
        if not activated:
            # 没有可用抖音标签: 新开一个登录标签并激活
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}/json/new?"
                    + urllib.parse.quote(DOUYIN_LOGIN_URL, safe=""),
                    method="PUT",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    new_tab = json.loads(r.read().decode("utf-8", "replace"))
                tid = new_tab.get("id")
                if tid:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/json/activate/{tid}",
                        timeout=5).read()
            except Exception:
                pass

    def start(self) -> Dict[str, Any]:
        browser = self.find_browser()
        if not browser:
            raise RuntimeError("未找到 Edge 或 Chrome 浏览器, 请手动粘贴 Cookie")
        os.makedirs(self.profile, exist_ok=True)
        if not self._port_open():
            try:
                self.proc = subprocess.Popen(
                    [browser,
                     f"--remote-debugging-port={self.port}",
                     f"--user-data-dir={self.profile}",
                     "--no-first-run", "--no-default-browser-check",
                     "--disable-extensions", "--new-window",
                     DOUYIN_LOGIN_URL],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                raise RuntimeError(f"启动浏览器失败: {e}") from e
            # 等待调试端口就绪(最多约 10 秒), 避免前端过早轮询
            for _ in range(50):
                if self._port_open():
                    break
                time.sleep(0.2)
        else:
            # 端口已被残留实例占用: 复用它, 但要确保登录页被打开并置前
            self._focus_login_page()
        return {"message": "已打开抖音登录页, 请在浏览器右上角点『登录』并扫码",
                "login_url": DOUYIN_LOGIN_URL,
                "port": self.port}

    def _read_cookies_via_cdp(self) -> List[Dict[str, Any]]:
        if not self._port_open():
            return []
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/json/list", timeout=5
        ) as r:
            targets = json.loads(r.read().decode("utf-8"))
        ws_url = ""
        for t in targets:
            if t.get("type") == "page" and "douyin.com" in t.get("url", ""):
                ws_url = t.get("webSocketDebuggerUrl", "")
                break
        if not ws_url:
            for t in targets:
                if t.get("type") == "page":
                    ws_url = t.get("webSocketDebuggerUrl", "")
                    break
        if not ws_url:
            return []
        client = CDPClient(ws_url)
        try:
            client.call("Network.enable")
            result = client.call("Network.getAllCookies")
            return result.get("cookies", [])
        finally:
            client.close()

    def poll(self) -> Dict[str, Any]:
        """检查是否已登录成功, 成功则自动保存 Cookie."""
        try:
            cookies = self._read_cookies_via_cdp()
        except Exception as e:
            return {"status": "error", "message": f"读取浏览器 Cookie 失败: {e}"}
        if not cookies:
            return {"status": "pending", "message": "等待浏览器打开登录页（若窗口在后台，请从任务栏切回）"}

        domain_cookies = [c for c in cookies if "douyin.com" in c.get("domain", "")]
        # 登录态关键 Cookie: sessionid / sessionid_ss
        session = next(
            (c for c in domain_cookies
             if c.get("name") in ("sessionid", "sessionid_ss") and c.get("value")),
            None,
        )
        if not session:
            return {"status": "pending", "message": "等待扫码登录（未检测到登录态）"}

        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in domain_cookies)
        info: Dict[str, Any] = {"cookie": cookie_str, "sessionid": session["value"]}
        # 尝试读取昵称
        try:
            client = None
            for t in json.loads(
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list",
                                       timeout=5).read().decode("utf-8")
            ):
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    client = CDPClient(t["webSocketDebuggerUrl"])
                    break
            if client:
                res = client.call("Runtime.evaluate", {
                    "expression": "document.title", "returnByValue": True
                })
                title = ((res.get("result") or {}).get("value") or "")
                info["username"] = title[:40]
                client.close()
        except Exception:
            pass
        self.store.set_platform("douyin", info)
        return {"status": "success", "message": "登录成功, 已自动保存 Cookie",
                "username": info.get("username", "")}

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None


# 全局单例(Web 层共享)
_cookie_store = CookieStore()
