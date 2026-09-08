# 剪贴板库 ClipboardLibrary — Windows 剪贴板历史与截图管理器

[![Latest release](https://img.shields.io/github/v/release/Han-business1/ClipboardLibrary?label=最新版本&color=2775f5)](https://github.com/Han-business1/ClipboardLibrary/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/Han-business1/ClipboardLibrary/total?label=下载量&color=27a66b)](https://github.com/Han-business1/ClipboardLibrary/releases)
[![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4?logo=windows11)](https://github.com/Han-business1/ClipboardLibrary/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.12-3776ab?logo=python&logoColor=white)](https://www.python.org/)

剪贴板库（ClipboardLibrary）是一款面向 Windows 10/11 的本地剪贴板管理器。它可以在后台自动记录复制、剪切和截图内容，并提供按日期归档、全文搜索、内容编辑、置顶收藏、标签备注和版本追溯功能。

ClipboardLibrary is a local-first Windows clipboard history manager for text and screenshots. It provides automatic capture, daily archives, full-text search, editing, pinning, notes, and version history in a bilingual desktop interface.

> 所有剪贴板数据默认仅保存在本机，不需要注册账号，也不会自动上传云端。

## 下载与安装 Download

### [下载最新 Windows 安装程序 / Download the latest Windows installer](https://github.com/Han-business1/ClipboardLibrary/releases/latest)

打开最新版发布页面，在 **Assets** 中下载 `ClipboardLibrary-Setup-*.exe`。安装后的软件是独立 EXE，不要求预先安装 Python。

升级前请先从系统托盘完全退出旧版本。升级不会删除已有的剪贴板历史数据库。

## 为什么使用剪贴板库

如果你经常需要找回刚才复制的文字、代码、链接或截图，ClipboardLibrary 可以把零散的 Windows 剪贴板内容整理成可搜索、可编辑、可追溯的本地资料库。

- 自动保存复制、剪切和截图内容
- 按日期查看每天的剪贴板历史记录
- 快速搜索文字、标签和备注
- 编辑历史内容并保留每个版本
- 将常用内容置顶，随时再次复制
- 后台运行并支持 Windows 开机自启
- 简体中文与 English 界面即时切换
- 数据保存在本机，适合重视隐私的用户

## 核心功能 Features

### 剪贴板历史与日期归档

- 使用 Windows 剪贴板序号捕获每一次复制或剪切，相同内容重复操作也会独立记录
- 历史记录按本地日期自动归类，默认显示今天
- 通过日期下拉框查看任意有记录日期，并按最新或最早排序
- 跨过午夜后自动进入新日期，旧记录不会被清空或覆盖

### 文本、图片与截图管理

- 自动捕获文本、系统截图以及复制的图片
- 图片以 PNG 原图保存在本机，卡片中显示缩略图
- 支持高清预览、再次复制和另存 PNG
- 每条内容以独立矩形卡片展示，包含类型、标签、备注和精确时间

### 搜索、编辑与版本追溯

- 全文搜索剪贴板内容、标签和备注
- 置顶常用文本、代码片段、链接和截图
- 直接编辑内容、标签与备注，并自动生成版本历史
- 查看捕获、编辑、恢复、复制和置顶等操作轨迹
- 恢复任意历史版本，或导出包含版本与轨迹的 JSON 备份

### Windows 桌面体验

- 系统托盘后台运行，关闭主窗口后继续自动记录
- 支持登录 Windows 后自动启动和开机后静默运行
- 窗口、导航栏和内容面板均可调整尺寸并自动保存
- 提供紧凑、标准和宽屏界面预设
- 支持 Windows Per-Monitor V2 高 DPI 渲染
- 支持简体中文和 English

## 使用方法

1. 安装并启动 ClipboardLibrary。
2. 正常使用 `Ctrl+C`、`Ctrl+X` 或 Windows 截图功能。
3. 在“历史记录”中选择日期并查看当天内容。
4. 使用“快速搜索”跨日期查找文字、链接、代码或备注。
5. 点击任意卡片即可编辑、置顶、再次复制或查看版本历史。

快捷键：

- `Ctrl+F`：进入快速搜索
- `Ctrl+S`：保存当前编辑

## 数据与隐私 Privacy

历史数据库保存在：

```text
%LOCALAPPDATA%\ClipboardLibrary\clipboard.db
```

截图原图保存在同一数据目录的 `images` 文件夹。软件不会自动把剪贴板内容发送到网络。

剪贴板可能包含密码、验证码或其他敏感信息，请及时删除不需要的记录，并妥善保护 Windows 账户。

## English overview

ClipboardLibrary is a Windows clipboard manager and searchable clipboard history app built with Python, Tkinter, and SQLite.

- Capture copied or cut text, images, and screenshots automatically
- Browse clipboard history by date without deleting older records
- Search across text, tags, and notes
- Edit saved clips while keeping version history and activity logs
- Pin frequently used snippets and copy them again with one click
- Run in the system tray and launch automatically with Windows
- Store clipboard data locally for privacy
- Switch between Simplified Chinese and English

Go to [Releases](https://github.com/Han-business1/ClipboardLibrary/releases/latest) to download the latest Windows EXE installer.

## 开发与构建 Development

开发环境要求 Python 3.12。安装依赖后可以直接运行：

```powershell
python -m pip install -r requirements.txt
python clipboard_library.py
```

生成独立 EXE 和 Windows 安装程序：

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

构建流程使用 PyInstaller 和 Inno Setup 6。

## 反馈、建议与贡献 Community

- [提交问题或功能建议 / Issues](https://github.com/Han-business1/ClipboardLibrary/issues)
- [参与讨论 / Discussions](https://github.com/Han-business1/ClipboardLibrary/discussions)
- [查看更新记录 / Releases](https://github.com/Han-business1/ClipboardLibrary/releases)

欢迎 Star、Fork、提交 Issue 或 Pull Request，帮助改进这个 Windows 剪贴板历史与截图管理工具。
