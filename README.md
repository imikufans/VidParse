# VidParse — 多平台视频解析工具

<div align="center">

**VidParse** 是一个基于 Python 的多平台视频解析工具，支持 **Bilibili / 抖音 / YouTube** 以及 yt-dlp 覆盖的上千个平台。

输入一个视频链接，即可获取 **标题、作者、封面、时长** 以及 **可直接下载的媒体直链**，并提供 **音视频无损合成**、**扫码登录解锁高清** 等能力。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#)

</div>

> ⚠️ **免责声明**：本工具仅用于**个人学习、技术研究与有版权内容的合法备份**。请遵守各平台服务条款与相关法律法规，不得用于侵权、盗录、传播他人版权内容或任何商业用途。解析得到的链接具有时效性，且平台接口随时可能调整，作者不对任何使用后果负责。

---

## 📑 目录

- [新手从这里开始](#-新手从这里开始最简单的三种方式)
- [功能特性](#-功能特性)
- [方式一：桌面版（exe 安装包 / 便携包）](#方式一桌面版新手最省事)
- [方式二：一键启动脚本](#方式二一键启动batwindows)
- [方式三：命令行 / HTTP API / Python 调用](#方式三命令行--http-api--python-调用)
- [常见问题 FAQ](#-常见问题-faq新手必看)
- [接口调研结论](#-接口调研结论)
- [项目结构](#-项目结构)
- [从源码运行与开发](#-从源码运行与开发)
- [贡献指南](#-贡献指南)
- [已知限制](#-已知限制)
- [License](#-license)

---

## 🚀 新手从这里开始（最简单的三种方式）

你是第一次使用？按下面的顺序选一种即可：

| 你的情况 | 推荐方式 | 需要装 Python 吗 |
|---------|---------|----------------|
| 只想双击就用，不想装任何东西 | [方式一：桌面版](#方式一桌面版新手最省事) | ❌ 不需要 |
| 已经有 Python，想在本机跑网页界面 | [方式二：一键启动.bat](#方式二一键启动batwindows) | ✅ 需要 |
| 想集成到自己的程序 / 服务器 | [方式三：API / 命令行](#方式三命令行--http-api--python-调用) | ✅ 需要 |

**三步通用流程**（无论哪种方式）：

1. 启动 VidParse（桌面版双击 exe / 脚本双击 `一键启动.bat`）；
2. 浏览器里粘贴一个**视频链接**，点击「开始解析」；
3. 在结果里点「播放」「下载」或用「音视频合成」得到高清带声音的 MP4。

> 💡 **链接怎么来？** 在 B站/抖音 App 或网页里打开视频 → 点「分享」→「复制链接」，把复制到的整段文字粘进来即可（支持 `https://v.douyin.com/xxx/` 这种短链）。

---

## ✨ 功能特性

- 🌐 **图形化 Web 界面**：零依赖（Python 标准库实现），解析/播放/下载/合成全在浏览器完成；
- 🔐 **扫码登录自动获取 Cookie**：B站扫码、抖音浏览器登录，自动保存，新手无需手动复制 Cookie；
- 🎬 **音视频无损合成**：DASH 分离流一键合并为带声音的高清 MP4（内置 ffmpeg，`-c copy` 零损失）；
- 🔗 **防盗链自动处理**：内置代理注入 `Referer`，解决直链 403；支持拖动进度条（Range）；
- 🧩 **多平台**：专用接口优先（B站/抖音/YouTube），失败自动回退 yt-dlp，覆盖上千平台；
- 📦 **开箱即用**：内置 ffmpeg 与 yt-dlp，无需额外安装；
- 🖥️ **桌面封装**：提供 Windows NSIS 安装包与便携绿色包（Electron）。

---

## 方式一：桌面版（新手最省事）

桌面版把 Python 后端和运行时一起打进了 Electron 应用，**不需要安装 Python**。

### Windows

1. 到 [Releases](../../releases) 下载 `VidParse.exe`（安装版）或 `VidParsePortable.zip`（便携版）；
2. **安装版**：双击安装，按提示完成，桌面会出现「VidParse」图标，双击打开；
3. **便携版**：解压 zip 到任意文件夹，双击里面的 `VidParse.exe`；
4. 应用会自动启动本地服务并打开界面，之后按 [三步通用流程](#-新手从这里开始最简单的三种方式) 使用即可。

> 首次运行如被 Windows Defender / SmartScreen 拦截，选择「更多信息」→「仍要运行」（未签名应用的正常提示）。

### 数据存放位置

Cookie、下载文件等数据写在用户目录（避免 Program Files 的写权限问题）：

```
Windows: %APPDATA%/vidparse-desktop/data/
```

---

## 方式二：一键启动.bat（Windows）

适合已安装 Python 的用户，无需打包环境。

1. 安装 Python 3.9+，安装时**务必勾选「Add Python to PATH」**；
2. 下载/克隆本项目到本地；
3. **双击 `一键启动.bat`** —— 会自动启动服务并打开浏览器；
4. 在网页里粘贴视频链接 → 点「开始解析」。

也可以手动启动：

```bash
python webui.py --port 8080
# 浏览器打开 http://127.0.0.1:8080
```

关闭黑色命令行窗口即停止服务。

---

## 方式三：命令行 / HTTP API / Python 调用

### 命令行 CLI

```bash
# 基础解析（人类可读输出）
python cli.py "https://www.bilibili.com/video/BV1GJ411x7h7"

# 列出全部可用清晰度/格式
python cli.py "https://www.bilibili.com/video/BV1GJ411x7h7" -f

# JSON 输出（便于程序处理）
python cli.py "https://v.douyin.com/xxxx/" --json

# 下载最佳画质到指定目录
python cli.py "https://www.youtube.com/watch?v=xxxx" -d -o ./downloads

# 下载指定格式
python cli.py "<url>" --format-id "80" -d

# B站高清：设置 SESSDATA（也可设环境变量 BILIBILI_SESSDATA）
python cli.py "<url>" --sessdata "你的SESSDATA"

# 批量解析（urls.txt 每行一个链接）
python cli.py --batch urls.txt --json
```

参数说明：

| 参数 | 含义 |
|------|------|
| `-f, --formats` | 列出全部可下载格式（含清晰度、编码、大小） |
| `-d, --download` | 下载最佳视频流 |
| `-o, --output` | 下载目录 |
| `--format-id` | 指定下载的格式 ID |
| `--json` | 以 JSON 输出（含全部字段与直链） |
| `--sessdata` | B站 Cookie，用于高码率/1080P+ |
| `--no-fallback` | 禁用 yt-dlp 兜底 |
| `--quality` | B站清晰度 qn 值（默认 80=1080P） |

### HTTP API

```bash
python server.py --port 8080
# 可选：python server.py --port 8080 --sessdata "你的SESSDATA"
```

接口列表：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 接口说明 |
| GET | `/health` | 健康检查 |
| GET | `/platforms` | 支持的平台列表 |
| GET | `/parse?url=<链接>` | 解析视频（JSON） |
| POST | `/parse` | `{"url": "...", "sessdata": "..."}` |

示例：

```bash
curl "http://localhost:8080/parse?url=https%3A%2F%2Fwww.bilibili.com%2Fvideo%2FBV1GJ411x7h7"

curl -X POST http://localhost:8080/parse \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

返回结构（成功）：

```json
{
  "success": true,
  "platform": "bilibili",
  "data": {
    "platform": "bilibili",
    "video_id": "BV1GJ411x7h7",
    "title": "【官方 MV】Never Gonna Give You Up - Rick Astley",
    "author": "索尼音乐中国",
    "duration": 213,
    "cover": "http://i1.hdslb.com/...",
    "formats": [
      {"format_id": "mp4-1", "url": "https://....mp4", "quality": "720P 高清", "ext": "mp4", "media_type": "both"}
    ]
  }
}
```

失败时：`{"success": false, "platform": "...", "error": "..."}`（HTTP 502）。

**音视频合成 API**（由 `webui.py` 提供，需 ffmpeg）：

```bash
# 1. 检查 ffmpeg 是否就绪
curl http://localhost:8080/api/ffmpeg/status

# 2. 提交合成任务（视频流 + 音频流直链）
curl -X POST http://localhost:8080/api/merge/start \
  -H "Content-Type: application/json" \
  -d '{"video_url":"https://...视频流.m4s","audio_url":"https://...音频流.m4s","platform":"bilibili","title":"视频名","quality":"1080P"}'

# 3. 轮询进度
curl "http://localhost:8080/api/merge/status?id=任务ID"

# 4. 下载/播放合成结果（支持 Range）
curl "http://localhost:8080/api/merge/file?id=任务ID" -o 输出.mp4
```

### Python 代码调用

```python
from vidparse import VideoParser

parser = VideoParser(sessdata="", fallback_ytdlp=True)

# 方式 1：不抛异常，返回结果包装
result = parser.parse("https://www.bilibili.com/video/BV1GJ411x7h7")
if result.success:
    info = result.info
    print(info.title, info.author, info.duration)
    for f in info.formats:
        print(f.format_id, f.quality, f.url)
    best = info.best_video        # 最优视频格式
    audio = info.best_audio       # 最优音频格式
else:
    print("解析失败：", result.error)

# 方式 2：失败抛异常
info = parser.parse_or_raise("https://www.youtube.com/watch?v=xxxx")

# 方式 3：直接拿 JSON 字典
data = parser.parse_json(url)
```

---

## 🙋 常见问题 FAQ（新手必看）

### Q1：解析出的链接直接复制到浏览器打开是 403？

这是各平台 CDN 的**防盗链**机制（要求请求带 `Referer`），**不是接口失效**。VidParse 界面里的「播放」「下载」都走内置代理 `/api/proxy`，服务端会自动注入正确 `Referer`，可正常播放/下载并支持拖动进度条。

若仍报 403，多半是**直链过期**（有效期约 2~6 小时），重新解析一次即可。若想复制原始直链自己用，需要自行带上对应平台的 `Referer`。

### Q2：B站视频播放没有声音？

B站高清（1080P+）采用 **DASH** 技术：视频和音频是**两条独立的流**，单独播放视频流没声音。

- 界面已默认附带一个「✦ 有声」的合并流作为首个选项（720P 可直接播放）；
- 想要 **1080P+ 无损高画质 + 声音**，请使用「🎬 音视频合成」面板，选好视频流和音频流一键合成即可（内置 ffmpeg，零损失）。

### Q3：抖音链接解析失败？

- **只支持单个视频链接**（形如 `www.douyin.com/video/数字ID` 或 `v.douyin.com/xxx` 短链）。搜索页 `/search/`、精选 `/jingxuan/`、主页 `/user/` 等**列表页不含单视频数据，无法解析**——请点进具体视频后再复制链接。
- 抖音反爬严格，纯 HTTP 成功率不稳定。建议点界面顶部「打开浏览器登录」扫码登录后再解析；工具也会自动降级 yt-dlp 兜底。

### Q4：如何登录获取 Cookie？

界面顶部有两个登录入口：

| 平台 | 操作 | 说明 |
|------|------|------|
| **B站** | 点「扫码登录」→ 用 B站 App 扫码并在手机确认 | 自动获取 SESSDATA，解锁 1080P+/会员画质 |
| **抖音** | 点「打开浏览器登录」→ 在弹窗里用抖音 App 扫码登录 | 通过浏览器调试协议自动读取 Cookie，绕过风控 |

登录后 Cookie 仅保存在本机，不会上传。若自动方式不可用，也可点「手动粘贴」（B站填 SESSDATA，抖音填完整 Cookie）。

### Q5：ffmpeg 相关功能提示不可用？

本项目已内置 `bin/ffmpeg.exe`。若文件丢失，双击 `安装ffmpeg.bat` 可自动重新安装；Linux/macOS 用户可 `brew install ffmpeg` 或用系统包管理器安装。

### Q6：需要联网吗？

解析时需要联网访问平台接口；二维码生成库是本地内置的，无需联网。

---

## 🔬 接口调研结论

调研时间：2026-11。各平台方案与可用性如下：

| 平台 | 采用接口 | 鉴权要求 | 稳定性 | 说明 |
|------|----------|----------|--------|------|
| **Bilibili** | `api.bilibili.com/x/web-interface/view`（元信息）<br>`/x/player/playurl`（合并流）<br>`/x/player/wbi/playurl`（DASH/高码率，需 WBI 签名） | 免登录可解析 ≤720P；1080P+/会员画质需 `SESSDATA` | ⭐⭐⭐⭐ 高 | 已实测可用。WBI 签名算法公开稳定，playurl 直链有效期约 2~6 小时 |
| **抖音** | 分享短链 `v.douyin.com` 重定向 → 视频页 `window._ROUTER_DATA` → 无水印直链；失败降级移动端 detail API / yt-dlp | 免登录受限，高码率/稳定解析建议 Cookie | ⭐⭐ 中（反爬强） | 反爬策略频繁变动，纯 HTTP 常失败；**只支持单个视频链接** |
| **YouTube** | Piped API `/streams/{id}` 与 Invidious API `/api/v1/videos/{id}` 公开实例；失败降级 yt-dlp | 免 Key | ⭐⭐⭐ 中 | 公开实例可能被封 IP；yt-dlp 兜底最稳 |
| **其他 1000+ 平台** | `yt-dlp` 的 extractor（微博、小红书、快手、TikTok、Twitter、AcFun…） | 视平台而定 | ⭐⭐⭐⭐ 高 | 由 yt-dlp 社区维护，本项目仅做统一封装 |

**技术路线**：优先用各平台专用接口（更快、可拿无水印直链）；失败自动回退 yt-dlp（覆盖广、抗变动）；核心解析用 Python 标准库实现，零依赖即可运行。

**参考的开源实现**：
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)（上千平台，Unlicense）
- [douyinVd](https://github.com/pwh-pwh/douyinVd)（抖音解析参考）
- bilibili-api / downkyi 等社区的 B站 API 与 WBI 签名实现
- [Piped](https://piped.video) / [Invidious](https://invidious.io) 公开实例列表

---

## 📁 项目结构

```
VidParse/
├── README.md                # 本文档（新手指南）
├── LICENSE                  # MIT 许可证
├── CONTRIBUTING.md          # 贡献指南
├── CHANGELOG.md             # 更新日志
├── requirements.txt         # 可选依赖
├── 一键启动.bat             # Windows 双击启动（自动开浏览器）
├── 安装ffmpeg.bat           # ffmpeg 补装脚本
├── webui.py                 # 图形界面 Web 服务（标准库实现）
├── cli.py                   # 命令行入口
├── server.py                # 纯 HTTP API（无界面）
├── web/                     # 前端页面
│   ├── index.html
│   └── static/qrcode.min.js # 本地二维码库
├── bin/                     # 内置工具（不纳入 git，见 Releases）
│   ├── ffmpeg.exe
│   └── ytdlp/
├── electron/                # Electron 桌面封装
│   ├── main.js
│   ├── preload.js
│   └── assets/icon.ico
├── package.json             # Electron 构建配置
└── vidparse/                # 核心 Python 包
    ├── __init__.py
    ├── core.py              # 调度核心（识别→解析→兜底）
    ├── auth.py              # 扫码登录 + Cookie 管理 + CDP 浏览器自动化
    ├── merger.py            # 音视频合成引擎
    ├── models.py            # 数据模型
    ├── utils.py             # HTTP 客户端 / 平台识别
    ├── wbi.py               # B站 WBI 签名
    └── parsers/
        ├── base.py
        ├── bilibili.py
        ├── douyin.py
        ├── youtube.py
        └── ytdlp.py
```

---

## 🛠️ 从源码运行与开发

### 环境要求

- Python 3.9+（核心功能零第三方依赖）
- 可选：ffmpeg（音视频合成）、yt-dlp（兜底，已内置于 `bin/`）

### 本地运行

```bash
git clone https://github.com/imikufans/VidParse.git
cd VidParse

# 直接运行，核心功能零依赖
python webui.py --port 8080

# 或命令行
python cli.py "https://www.bilibili.com/video/BV1GJ411x7h7"
```

### 构建 Windows 桌面版（Electron）

```bash
npm install
npm run dist       # 生成 dist/VidParse.exe
# 便携包：将 dist/win-unpacked 目录打包为 zip 即可
```

> 内置运行时位于 `runtime/python`（打包时用 `extraResources` 带入），发布包中提供；开发源码仓库不包含该运行时与 `bin/` 二进制。

---

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

- 提交前请确保 `python -m py_compile` 通过；
- 新增平台解析器请放在 `vidparse/parsers/` 并继承 `BaseParser`；
- 遵循「免责声明」，不要提交任何 Cookie、个人信息或二进制大文件。

---

## ⚠️ 已知限制

1. **直链时效性**：解析出的直链（尤其 B站/YouTube）通常 2~6 小时过期，需重新解析。
2. **B站高清**：1080P+/杜比/会员画质必须提供 `SESSDATA`；DASH 分离流可在界面用「音视频合成」合并。
3. **抖音反爬**：风控严格，纯 HTTP 成功率不稳定；建议登录后再解析。抖音只支持**单个视频链接**，列表页无法解析。
4. **YouTube 公开实例**：Piped/Invidious 实例可能被封，最终由 yt-dlp 兜底。
5. **平台接口变更**：接口随时可能调整，失效时优先升级 yt-dlp 或更新对应解析器。
6. **macOS 桌面版**：仓库当前提供 Windows 桌面封装；macOS 可直接使用 Python 方式（`webui.py`），darwin 桌面包需在有签名环境的 macOS 上构建。

---

## 📄 License

本项目代码采用 [MIT License](LICENSE)。所依赖的 yt-dlp 为 Unlicense 公共领域许可，ffmpeg 遵循其自身许可证（LGPL/GPL，视构建而定）。

---

<div align="center">

Made with ❤️ by [imikufans](https://github.com/imikufans)

如果本项目对你有帮助，欢迎点一个 ⭐ Star！

</div>
