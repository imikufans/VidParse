# 贡献指南 · VidParse

感谢你愿意为 VidParse 做贡献！在提交之前，请花几分钟阅读以下约定。

## 行为准则

- 友善、尊重地交流；
- 不提交任何违反平台条款、侵犯版权或涉及个人隐私的内容；
- 本项目仅用于个人学习与合法备份。

## 如何贡献

### 报告 Bug

开一个 Issue，并尽量包含：

- 使用的平台与视频链接（可打码）；
- 复现步骤；
- 期望行为与实际行为；
- 运行环境（Windows / macOS / Linux、Python 版本）；
- 相关报错信息（可去掉 Cookie 等敏感字段）。

### 提交代码（Pull Request）

1. Fork 本仓库，创建分支：`git checkout -b feature/你的功能`；
2. 编写代码，遵循现有风格（Python 标准库优先，避免引入重依赖）；
3. 本地验证：
   ```bash
   python -m py_compile cli.py server.py webui.py vidparse/*.py vidparse/parsers/*.py
   python cli.py --help
   ```
4. 提交并推送：`git commit -m "简短说明" && git push origin feature/你的功能`；
5. 在 GitHub 上发起 Pull Request，说明改动动机与测试情况。

### 新增平台解析器

- 在 `vidparse/parsers/` 下新增文件，继承 `BaseParser`；
- 在 `vidparse/parsers/__init__.py` 注册；
- 在 `vidparse/utils.py` 的 `detect_platform` 中加入平台识别；
- 更新 README 的平台支持表格。

## 提交规范

- 提交信息用中文或英文均可，务必简明扼要；
- 一次提交只做一件事；
- **不要提交**：`.cookies.json`、`runtime/`、`bin/` 下的二进制大文件、`dist/`、个人 Cookie 或密钥。

## 许可

提交即表示你同意你的贡献以 MIT License 发布。
