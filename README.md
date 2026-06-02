# Paper Reader

一个基于 Gradio 的论文精读助手：上传 PDF 后，自动解析论文正文，调用 Anthropic Claude 生成分段精读笔记，并支持导出 Markdown / PDF。

## Features

- PDF 文本层解析，低文本量 PDF 自动尝试 OCR
- 针对论文结构生成 8 段式中文精读笔记
- CrossRef 元数据校验和数值交叉检查
- Gradio 本地 Web UI，支持 PDF 预览和流式生成
- 支持断点续写和历史记录
- 导出 Markdown 和 PDF 笔记

## Requirements

- Python 3.10+
- Tesseract OCR，可选，用于扫描版 PDF
- Poppler，可选，用于 OCR 前的 PDF 转图
- Anthropic API key，或兼容 Anthropic SDK 的代理服务

## Installation

```powershell
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

编辑 `.env`：

```dotenv
ANTHROPIC_API_KEY=your_anthropic_api_key_here
MODEL_NAME=claude-sonnet-4-6
ANTHROPIC_BASE_URL=
```

`ANTHROPIC_BASE_URL` 可留空。只有在使用兼容 Anthropic SDK 的中转服务时才填写。

## Run

```powershell
python app.py
```

或在 Windows 上双击：

```text
run.bat
```

应用默认在本机启动，并自动打开浏览器。

## Notes

- `.env`、`data/`、`build/`、`dist/` 不会提交到 Git。
- 首次运行会创建本地 `data/` 目录保存历史记录和断点进度。
- 如果扫描版 PDF 无法 OCR，请确认 Tesseract 和 Poppler 已安装并加入 `PATH`。

## Packaging

项目包含 PyInstaller spec，可按需打包：

```powershell
pip install pyinstaller
pyinstaller "论文精读助手.spec"
```

## License

MIT
