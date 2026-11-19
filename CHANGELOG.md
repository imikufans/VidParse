# 更新日志 · VidParse

本项目所有重要变更都会记录在此文件中。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [1.1.0] - 2026-11-20

### 新增
- Electron 桌面版：Windows NSIS 安装包与便携绿色包，内置 Python 运行时，无需安装 Python。
- 音视频无损合成面板：DASH 分离流一键合并为带声音的高清 MP4（内置 ffmpeg，`-c copy` 零损失）。
- B站扫码登录、抖音浏览器登录，自动获取并保存 Cookie。
- 抖音移动端 detail API 兜底，提升短链解析成功率。
- 内置 yt-dlp（覆盖上千平台兜底）与 ffmpeg。

### 修复
- 抖音短链 302 重定向、搜索页/主页误解析、SSL EOF / WinError 10054 等网络问题。
- B站 CDN 403（代理注入 Referer）、登录后 DASH 无声等问题。
- 一键启动脚本换行与编码问题。

### 变更
- 项目正式开源，品牌名统一为 **VidParse**，Python 包 `videoparse` 更名为 `vidparse`。

## [1.0.0] - 2026-11-18

### 新增
- 首个版本：Bilibili / 抖音 / YouTube 解析，Web 界面、CLI、HTTP API 三种用法。
- 基于 Python 标准库实现核心解析，零依赖即可运行。

[1.1.0]: https://github.com/imikufans/VidParse/releases/tag/v1.1.0
[1.0.0]: https://github.com/imikufans/VidParse/releases/tag/v1.0.0
