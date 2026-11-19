#!/usr/bin/env python3
"""HTTP API 服务(仅用标准库, 零依赖即可运行).

接口:
    GET  /                      -> 简易说明页
    GET  /health                -> 健康检查
    GET  /parse?url=<链接>       -> 解析视频(返回 JSON)
    POST /parse                 -> Body: {"url": "...", "sessdata": "..."}
    GET  /platforms             -> 支持的平台列表

启动:
    python server.py --port 8080
    python server.py --port 8080 --sessdata <B站SESSDATA>   # 支持高清

示例:
    curl "http://localhost:8080/parse?url=https://www.bilibili.com/video/BV1xx411c7mD"
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from vidparse import VideoParser, __version__


class Handler(BaseHTTPRequestHandler):
    server_version = f"vidparse/{__version__}"

    def _send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json({"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path == "/":
            info = {
                "name": "VidParse API",
                "version": __version__,
                "endpoints": [
                    "GET /parse?url=<视频链接>",
                    "POST /parse  {\"url\": \"...\"}",
                    "GET /platforms",
                    "GET /health",
                ],
            }
            return self._send_json(info)

        if path == "/health":
            return self._send_json({"status": "ok"})

        if path == "/platforms":
            return self._send_json({
                "platforms": [
                    {"name": "bilibili", "urls": "bilibili.com, b23.tv"},
                    {"name": "douyin", "urls": "douyin.com, v.douyin.com"},
                    {"name": "youtube", "urls": "youtube.com, youtu.be"},
                    {"name": "generic", "urls": "yt-dlp 支持的上千平台"},
                ]
            })

        if path == "/parse":
            url = (query.get("url") or [""])[0]
            sessdata = (query.get("sessdata") or [self.server.sessdata])[0]
            if not url:
                return self._send_json({"success": False, "error": "缺少 url 参数"}, 400)
            vp = VideoParser(sessdata=sessdata)
            result = vp.parse(url)
            return self._send_json(result.to_dict(), 200 if result.success else 502)

        self._send_json({"error": "Not Found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/parse":
            return self._send_json({"error": "Not Found"}, 404)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return self._send_json({"error": "请求体不是合法 JSON"}, 400)
        url = payload.get("url", "")
        sessdata = payload.get("sessdata") or self.server.sessdata
        if not url:
            return self._send_json({"success": False, "error": "缺少 url 字段"}, 400)
        vp = VideoParser(sessdata=sessdata)
        result = vp.parse(url)
        self._send_json(result.to_dict(), 200 if result.success else 502)

    def log_message(self, fmt: str, *args) -> None:
        # 简化日志输出
        print(f"[{self.address_string()}] {fmt % args}")


def main() -> None:
    ap = argparse.ArgumentParser(description="VidParse HTTP API 服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--sessdata", default="", help="B站 SESSDATA Cookie(可选)")
    args = ap.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.sessdata = args.sessdata  # type: ignore[attr-defined]
    print(f"VidParse API 运行中: http://{args.host}:{args.port}")
    print("示例: /parse?url=https://www.bilibili.com/video/BV1xx411c7mD")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        httpd.server_close()


if __name__ == "__main__":
    main()
