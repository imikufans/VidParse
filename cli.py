#!/usr/bin/env python3
"""VidParse 命令行工具.

示例:
    python cli.py "https://www.bilibili.com/video/BV1xx411c7mD"
    python cli.py "https://v.douyin.com/xxxx" -f
    python cli.py "https://www.youtube.com/watch?v=xxxx" -d -o ./downloads
    python cli.py --batch urls.txt --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

from vidparse import VideoParser, __version__
from vidparse.models import VideoInfo
from vidparse.utils import safe_filename

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


def print_human(info: VideoInfo, detailed: bool = False) -> None:
    print("=" * 64)
    print(f"平台:     {info.platform}")
    print(f"标题:     {info.title}")
    print(f"作者:     {info.author}  (ID: {info.author_id})")
    if info.duration:
        m, s = divmod(info.duration, 60)
        h, m = divmod(m, 60)
        print(f"时长:     {h:02d}:{m:02d}:{s:02d}" if h else f"时长:     {m:02d}:{s:02d}")
    if info.view_count:
        print(f"播放量:   {info.view_count}")
    print(f"视频ID:   {info.video_id}")
    if info.extra:
        extras = ", ".join(f"{k}={v}" for k, v in info.extra.items() if k != "engine")
        if extras:
            print(f"附加:     {extras}")
    print(f"\n可用格式 ({len(info.formats)}):")
    for i, f in enumerate(info.formats[:40]):
        size = f"{f.size / 1024 / 1024:.1f}MB" if f.size else "-"
        print(
            f"  [{i:>2}] {f.format_id:<14} {f.media_type:<5} "
            f"{f.quality or '-':<16} {f.ext or '?':<5} "
            f"{f.width}x{f.height} {f.note} (size={size})"
        )
    best = info.best_video
    if best:
        print(f"\n最佳视频格式: [{best.format_id}] {best.quality}")
        print(f"直链(前120字符): {best.url[:120]}{'...' if len(best.url) > 120 else ''}")
    print("=" * 64)


def download(url: str, filepath: str, referer: str = "", headers: dict | None = None) -> None:
    """流式下载, 显示进度."""
    h = {"User-Agent": UA}
    if referer:
        h["Referer"] = referer
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    tmp = filepath + ".part"
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 / total
                    sys.stdout.write(
                        f"\r  下载中 {done/1024/1024:.1f}/{total/1024/1024:.1f}MB ({pct:.0f}%)"
                    )
                    sys.stdout.flush()
        os.replace(tmp, filepath)
        print(f"\r  已保存: {filepath}                    ")
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise e


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="vidparse",
        description="多平台VidParse (Bilibili / 抖音 / YouTube / yt-dlp 支持的上千平台)",
    )
    ap.add_argument("urls", nargs="*", help="一个或多个视频链接")
    ap.add_argument("--batch", help="从文本文件读取链接(每行一个)")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出解析结果")
    ap.add_argument("-f", "--formats", action="store_true", help="列出所有可用格式")
    ap.add_argument("-d", "--download", action="store_true", help="下载最佳格式到本地")
    ap.add_argument("-o", "--output", default=".", help="下载目录(默认当前目录)")
    ap.add_argument("--format-id", help="下载指定格式 ID(默认选最佳)")
    ap.add_argument("--sessdata", default=os.environ.get("BILIBILI_SESSDATA", ""),
                    help="B站 SESSDATA Cookie(高清画质, 也可设环境变量)")
    ap.add_argument("--no-fallback", action="store_true", help="禁用 yt-dlp 兜底")
    ap.add_argument("--quality", type=int, default=80, help="B站清晰度 qn(默认 80=1080P)")
    ap.add_argument("--version", action="version", version=f"vidparse {__version__}")
    args = ap.parse_args()

    urls = list(args.urls)
    if args.batch:
        try:
            with open(args.batch, encoding="utf-8") as fh:
                urls += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
        except OSError as e:
            print(f"读取批量文件失败: {e}", file=sys.stderr)
            return 2

    if not urls:
        ap.print_help()
        return 1

    parser = VideoParser(
        sessdata=args.sessdata,
        fallback_ytdlp=not args.no_fallback,
        quality=args.quality,
    )

    json_results = []
    for url in urls:
        result = parser.parse(url)
        if args.json:
            json_results.append(result.to_dict())
            continue
        if not result.success:
            print(f"[失败] {url}\n  原因: {result.error}", file=sys.stderr)
            continue
        info = result.info
        assert info is not None
        print_human(info, detailed=args.formats)

        if args.download:
            fmt = None
            if args.format_id:
                fmt = next((f for f in info.formats if f.format_id == args.format_id), None)
                if fmt is None:
                    print(f"[警告] 未找到格式 {args.format_id}, 使用最佳格式", file=sys.stderr)
            fmt = fmt or info.best_video
            if not fmt:
                print("[跳过] 无可用视频流", file=sys.stderr)
                continue
            os.makedirs(args.output, exist_ok=True)
            ext = fmt.ext or "mp4"
            filename = safe_filename(info.title or info.video_id or "video") + f".{ext}"
            filepath = os.path.join(args.output, filename)
            print(f"下载: {fmt.quality} ({fmt.format_id}) -> {filepath}")
            try:
                download(
                    fmt.url,
                    filepath,
                    referer=info.source_url,
                    headers={"Referer": info.source_url, "User-Agent": UA},
                )
            except Exception as e:
                print(f"[下载失败] {e}", file=sys.stderr)

    if args.json:
        print(json.dumps(
            json_results[0] if len(json_results) == 1 else json_results,
            ensure_ascii=False, indent=2,
        ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
