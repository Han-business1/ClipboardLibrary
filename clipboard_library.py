from __future__ import annotations

import json
import io
import os
import queue
import shutil
import sqlite3
import sys
import tkinter as tk
import ctypes
import uuid
import winreg
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import pystray
    from PIL import Image, ImageDraw, ImageGrab, ImageTk
except ImportError:  # Source mode can still run without the optional tray package.
    pystray = None
    Image = ImageDraw = ImageGrab = ImageTk = None


APP_NAME = "剪贴板库"
DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ClipboardLibrary"
DB_PATH = DATA_DIR / "clipboard.db"
SETTINGS_PATH = DATA_DIR / "settings.json"
DEFAULT_SETTINGS = {
    "auto_capture": True,
    "start_on_boot": False,
    "start_minimized": True,
    "close_to_tray": True,
    "poll_interval": 650,
    "language": "zh_CN",
}

I18N = {
    "zh_CN": {
        "app": "剪贴板库", "tagline": "保存每一次复制，需要时轻松找回。",
        "history": "历史记录", "pinned": "置顶常用", "search": "快速搜索", "settings": "设置",
        "items": "条记录", "local_only": "你的内容仅保存在本机", "listening": "正在监听",
        "paused": "已暂停", "pause": "暂停监听", "resume": "继续监听", "export": "导出备份",
        "all_types": "全部类型", "newest": "最新在前", "oldest": "最早在前",
        "timeline": "每次复制、剪切和截图都会自动记录", "empty": "暂无匹配记录\n复制文字或截图后会自动出现在这里",
        "text": "文本", "image": "截图", "record": "记录", "pin_mark": "已置顶",
        "no_tag": "未添加标签", "has_note": "有备注", "click_edit": "点击查看与编辑 →",
        "content": "内容预览", "image_preview": "截图预览", "image_missing": "截图文件不可用",
        "copy_again": "再次复制", "save_image": "另存截图", "pin": "置顶 / 取消", "delete": "删除",
        "tags": "标签", "note": "备注", "save_changes": "保存修改", "choose": "选择一条记录开始",
        "versions": "版本历史", "activity": "操作轨迹", "restore": "恢复所选", "version": "版本",
        "time": "时间", "action": "动作", "detail": "说明", "created": "创建于",
        "settings_title": "设置", "settings_subtitle": "外观、语言、后台运行与自动记录",
        "language": "界面语言", "chinese": "简体中文", "english": "English",
        "auto_capture": "自动记录剪贴板", "auto_capture_desc": "复制文字或图片、系统截图时自动保存",
        "start_boot": "登录 Windows 后自动启动", "start_boot_desc": "为当前 Windows 用户添加启动项",
        "start_hidden": "开机启动时在后台运行", "start_hidden_desc": "不弹出主窗口，仅显示在系统托盘",
        "close_tray": "关闭窗口后继续运行", "close_tray_desc": "隐藏到系统托盘并继续监听",
        "frequency": "监听频率", "fast": "快速 · 350 毫秒", "standard": "标准 · 650 毫秒", "eco": "节能 · 1000 毫秒",
        "cancel": "取消", "save_settings": "保存设置", "saved": "设置已保存",
        "empty_content": "内容不能为空。", "delete_confirm": "删除这条记录及其所有版本和轨迹？",
        "restore_confirm": "恢复到这个版本？当前内容也会留在版本历史中。",
        "image_copy_error": "无法复制截图", "image_unavailable": "截图文件不可用。",
        "startup_error": "无法更新 Windows 启动项", "backup_done": "备份已导出",
    },
    "en_US": {
        "app": "ClipboardLibrary", "tagline": "Save what you copy. Find it when you need it.",
        "history": "History", "pinned": "Pinned", "search": "Search", "settings": "Settings",
        "items": "items", "local_only": "Your content stays on this device", "listening": "Listening",
        "paused": "Paused", "pause": "Pause", "resume": "Resume", "export": "Export backup",
        "all_types": "All types", "newest": "Newest first", "oldest": "Oldest first",
        "timeline": "Every copy, cut, and screenshot is saved automatically", "empty": "No matching items\nCopy text or take a screenshot to get started",
        "text": "Text", "image": "Image", "record": "Item", "pin_mark": "Pinned",
        "no_tag": "No tags", "has_note": "Has note", "click_edit": "View and edit →",
        "content": "Content preview", "image_preview": "Image preview", "image_missing": "Image file unavailable",
        "copy_again": "Copy again", "save_image": "Save image", "pin": "Pin / Unpin", "delete": "Delete",
        "tags": "Tags", "note": "Note", "save_changes": "Save changes", "choose": "Select an item to begin",
        "versions": "Version history", "activity": "Activity", "restore": "Restore selected", "version": "Version",
        "time": "Time", "action": "Action", "detail": "Details", "created": "Created",
        "settings_title": "Settings", "settings_subtitle": "Appearance, language, background mode, and capture",
        "language": "Display language", "chinese": "简体中文", "english": "English",
        "auto_capture": "Automatically save clipboard", "auto_capture_desc": "Save copied text, images, and screenshots",
        "start_boot": "Launch when I sign in", "start_boot_desc": "Add a startup entry for the current Windows user",
        "start_hidden": "Start in the background", "start_hidden_desc": "Show only the system tray icon on startup",
        "close_tray": "Keep running when closed", "close_tray_desc": "Hide to the system tray and continue listening",
        "frequency": "Capture frequency", "fast": "Fast · 350 ms", "standard": "Standard · 650 ms", "eco": "Eco · 1000 ms",
        "cancel": "Cancel", "save_settings": "Save settings", "saved": "Settings saved",
        "empty_content": "Content cannot be empty.", "delete_confirm": "Delete this item, all versions, and its activity history?",
        "restore_confirm": "Restore this version? The current content will remain in version history.",
        "image_copy_error": "Unable to copy image", "image_unavailable": "Image file unavailable.",
        "startup_error": "Unable to update Windows startup", "backup_done": "Backup exported",
    },
}


def load_settings() -> dict:
    settings = DEFAULT_SETTINGS.copy()
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            settings.update({key: saved[key] for key in settings if key in saved})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return settings


def save_settings(settings: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def configure_windows_startup(enabled: bool) -> None:
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            if getattr(sys, "frozen", False):
                command = f'"{sys.executable}" --autostart'
            else:
                command = f'"{sys.executable}" "{Path(__file__).resolve()}" --autostart'
            winreg.SetValueEx(key, "ClipboardLibrary", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "ClipboardLibrary")
            except FileNotFoundError:
                pass
            legacy_shortcut = Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/剪贴板库.lnk"
            try:
                legacy_shortcut.unlink()
            except (FileNotFoundError, OSError):
                pass


def copy_image_to_windows_clipboard(image_path: Path) -> None:
    """Place a PNG file on the Windows clipboard as CF_DIB."""
    if Image is None:
        raise RuntimeError("Pillow 图像组件不可用")
    with Image.open(image_path) as source:
        image = source.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, "BMP")
        dib = buffer.getvalue()[14:]

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel32.GlobalFree.argtypes = (ctypes.c_void_p,)
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    user32.SetClipboardData.restype = ctypes.c_void_p

    handle = kernel32.GlobalAlloc(0x0002, len(dib))
    if not handle:
        raise OSError("无法分配剪贴板图像内存")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        kernel32.GlobalFree(handle)
        raise OSError("无法锁定剪贴板图像内存")
    ctypes.memmove(pointer, dib, len(dib))
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        raise OSError("系统剪贴板正被其他程序占用")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(8, handle):  # CF_DIB
            kernel32.GlobalFree(handle)
            raise OSError("无法写入图像剪贴板")
        handle = None  # Windows owns the allocation after SetClipboardData succeeds.
    finally:
        user32.CloseClipboard()


def enable_high_dpi() -> None:
    """Ask Windows for per-monitor DPI rendering before Tk creates a window."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            pass


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def display_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime("%m-%d %H:%M:%S")
    except ValueError:
        return value


class Store:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.data_dir = path.parent
        self.images_dir = self.data_dir / "images"
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                clip_type TEXT NOT NULL DEFAULT 'text',
                image_path TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                pinned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS versions (
                id INTEGER PRIMARY KEY,
                clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_clips_updated ON clips(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_versions_clip ON versions(clip_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_events_clip ON events(clip_id, id DESC);
            """
        )
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(clips)").fetchall()}
        if "clip_type" not in columns:
            self.db.execute("ALTER TABLE clips ADD COLUMN clip_type TEXT NOT NULL DEFAULT 'text'")
        if "image_path" not in columns:
            self.db.execute("ALTER TABLE clips ADD COLUMN image_path TEXT NOT NULL DEFAULT ''")
        self.db.commit()

    def capture(self, content: str) -> int | None:
        content = content.strip("\x00")
        if not content.strip():
            return None
        stamp = now()
        cur = self.db.execute(
            "INSERT INTO clips(content, created_at, updated_at) VALUES (?, ?, ?)",
            (content, stamp, stamp),
        )
        clip_id = int(cur.lastrowid)
        self.db.execute(
            "INSERT INTO versions(clip_id, content, reason, created_at) VALUES (?, ?, ?, ?)",
            (clip_id, content, "捕获原文", stamp),
        )
        self.log(clip_id, "已捕获", "来自系统剪贴板", stamp, commit=False)
        self.db.commit()
        return clip_id

    def capture_image(self, image: "Image.Image") -> int:
        self.images_dir.mkdir(parents=True, exist_ok=True)
        stamp = now()
        filename = f"screenshot-{datetime.now():%Y%m%d-%H%M%S-%f}-{uuid.uuid4().hex[:6]}.png"
        image_path = self.images_dir / filename
        normalized = image.convert("RGBA") if image.mode not in ("RGB", "RGBA") else image.copy()
        normalized.save(image_path, format="PNG", optimize=True)
        width, height = normalized.size
        content = f"截图 {width}×{height}"
        cur = self.db.execute(
            """INSERT INTO clips(content, clip_type, image_path, created_at, updated_at)
               VALUES (?, 'image', ?, ?, ?)""",
            (content, str(image_path), stamp, stamp),
        )
        clip_id = int(cur.lastrowid)
        self.db.execute(
            "INSERT INTO versions(clip_id, content, reason, created_at) VALUES (?, ?, ?, ?)",
            (clip_id, content, "捕获截图", stamp),
        )
        self.log(clip_id, "已捕获截图", f"{width}×{height} PNG", stamp, commit=False)
        self.db.commit()
        return clip_id

    def list_clips(self, query: str = "", oldest_first: bool = False,
                   pinned_only: bool = False) -> list[sqlite3.Row]:
        direction = "ASC" if oldest_first else "DESC"
        conditions = []
        params: list[str | int] = []
        if query:
            like = f"%{query}%"
            conditions.append("(content LIKE ? OR note LIKE ? OR tags LIKE ?)")
            params.extend((like, like, like))
        if pinned_only:
            conditions.append("pinned = 1")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        return self.db.execute(
            f"SELECT * FROM clips{where} ORDER BY created_at {direction}, id {direction}", params
        ).fetchall()

    def stats(self) -> tuple[int, int]:
        today = datetime.now().astimezone().date().isoformat()
        total = self.db.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
        today_count = self.db.execute(
            "SELECT COUNT(*) FROM clips WHERE substr(created_at, 1, 10)=?", (today,)
        ).fetchone()[0]
        return int(total), int(today_count)

    def get(self, clip_id: int) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()

    def save(self, clip_id: int, content: str, note: str, tags: str) -> None:
        old = self.get(clip_id)
        if not old:
            return
        if (old["content"], old["note"], old["tags"]) == (content, note, tags):
            return
        stamp = now()
        self.db.execute(
            "UPDATE clips SET content=?, note=?, tags=?, updated_at=? WHERE id=?",
            (content, note, tags, stamp, clip_id),
        )
        self.db.execute(
            """INSERT INTO versions(clip_id, content, note, tags, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (clip_id, content, note, tags, "手动编辑", stamp),
        )
        self.log(clip_id, "已编辑", "保存了新版本", stamp, commit=False)
        self.db.commit()

    def toggle_pin(self, clip_id: int) -> bool:
        row = self.get(clip_id)
        value = not bool(row["pinned"]) if row else False
        self.db.execute("UPDATE clips SET pinned=? WHERE id=?", (int(value), clip_id))
        self.log(clip_id, "已置顶" if value else "取消置顶")
        return value

    def delete(self, clip_id: int) -> None:
        row = self.get(clip_id)
        if row and row["clip_type"] == "image" and row["image_path"]:
            try:
                image_path = Path(row["image_path"]).resolve()
                images_root = self.images_dir.resolve()
                if image_path.is_relative_to(images_root):
                    image_path.unlink(missing_ok=True)
            except OSError:
                pass
        self.db.execute("DELETE FROM clips WHERE id=?", (clip_id,))
        self.db.commit()

    def versions(self, clip_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM versions WHERE clip_id=? ORDER BY id DESC", (clip_id,)
        ).fetchall()

    def events(self, clip_id: int) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM events WHERE clip_id=? ORDER BY id DESC", (clip_id,)
        ).fetchall()

    def restore(self, clip_id: int, version_id: int) -> None:
        version = self.db.execute(
            "SELECT * FROM versions WHERE id=? AND clip_id=?", (version_id, clip_id)
        ).fetchone()
        if not version:
            return
        stamp = now()
        self.db.execute(
            "UPDATE clips SET content=?, note=?, tags=?, updated_at=? WHERE id=?",
            (version["content"], version["note"], version["tags"], stamp, clip_id),
        )
        self.db.execute(
            """INSERT INTO versions(clip_id, content, note, tags, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (clip_id, version["content"], version["note"], version["tags"], "恢复历史版本", stamp),
        )
        self.log(clip_id, "已恢复", f"恢复版本 #{version_id}", stamp, commit=False)
        self.db.commit()

    def log(self, clip_id: int, action: str, detail: str = "", stamp: str | None = None,
            commit: bool = True) -> None:
        self.db.execute(
            "INSERT INTO events(clip_id, action, detail, created_at) VALUES (?, ?, ?, ?)",
            (clip_id, action, detail, stamp or now()),
        )
        if commit:
            self.db.commit()

    def export(self, path: str) -> None:
        payload = []
        for row in self.list_clips():
            item = dict(row)
            item["versions"] = [dict(v) for v in self.versions(row["id"])]
            item["events"] = [dict(e) for e in self.events(row["id"])]
            payload.append(item)
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class ClipboardLibrary(tk.Tk):
    BG = "#edf3fa"
    PANEL = "#ffffff"
    SIDEBAR = "#f5f8fc"
    CARD = "#f9fbfe"
    CARD_HOVER = "#f0f5fb"
    CARD_SELECTED = "#e8f2ff"
    BORDER = "#dce5f0"
    TEXT = "#182236"
    MUTED = "#77849a"
    ACCENT = "#2775f5"
    ACCENT_SOFT = "#dbeaff"
    DANGER = "#d64b55"

    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
        self.language = str(self.settings.get("language", "zh_CN"))
        self.view_mode = "history"
        self.store = Store()
        self.current_id: int | None = None
        self.card_widgets: dict[int, tk.Frame] = {}
        self.thumbnail_refs: dict[int, "ImageTk.PhotoImage"] = {}
        self.preview_image_ref = None
        self.suppress_clipboard: str | None = None
        self.last_seen: str | None = None
        self.last_sequence = 0
        self.capture_enabled = bool(self.settings["auto_capture"])
        self.poll_interval = int(self.settings["poll_interval"])
        self.search_after: str | None = None
        self.tray_icon = None
        self.tray_commands: queue.SimpleQueue[str] = queue.SimpleQueue()
        self.really_quitting = False

        self.title(self.t("app"))
        self.geometry("1280x820")
        self.minsize(980, 660)
        self.configure(bg=self.BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style()
        self._build()
        self.bind("<Control-s>", lambda _event: self.save_current())
        self.bind("<Control-f>", lambda _event: self.set_view("search"))
        self.refresh()
        self.create_tray_icon()
        self.after(100, self.poll_tray_commands)
        self.after(350, self.poll_clipboard)
        self.after(80, self.apply_launch_mode)

    def t(self, key: str) -> str:
        return I18N.get(self.language, I18N["zh_CN"]).get(key, key)

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Muted.TLabel", foreground=self.MUTED)
        style.configure("Title.TLabel", foreground=self.TEXT, font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("TButton", background=self.CARD, foreground=self.TEXT, borderwidth=0,
                        padding=(12, 8), font=("Microsoft YaHei UI", 9))
        style.map("TButton", background=[("active", self.CARD_HOVER)])
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#175fd8")])
        style.configure("Danger.TButton", foreground=self.DANGER)
        style.configure("TEntry", fieldbackground=self.CARD, foreground=self.TEXT,
                        insertcolor=self.TEXT, borderwidth=0, padding=9)
        style.configure("Treeview", background=self.PANEL, fieldbackground=self.PANEL,
                        foreground=self.TEXT, rowheight=54, borderwidth=0,
                        font=("Microsoft YaHei UI", 10))
        style.map("Treeview", background=[("selected", self.ACCENT_SOFT)], foreground=[("selected", self.TEXT)])
        style.configure("Treeview.Heading", background=self.PANEL, foreground=self.MUTED,
                        borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.configure("TNotebook", background=self.PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.PANEL, foreground=self.MUTED,
                        padding=(14, 8), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", self.CARD)],
                  foreground=[("selected", self.TEXT)])

    def _build(self) -> None:
        shell = tk.Frame(self, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1)
        shell.pack(fill="both", expand=True, padx=18, pady=18)

        sidebar = tk.Frame(shell, bg=self.SIDEBAR, width=190)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=self.SIDEBAR)
        brand.pack(fill="x", padx=18, pady=(22, 28))
        tk.Label(brand, text="▣", bg=self.SIDEBAR, fg=self.ACCENT,
                 font=("Segoe UI Symbol", 24, "bold")).pack(side="left")
        tk.Label(brand, text="Clipboard\nLibrary", bg=self.SIDEBAR, fg=self.TEXT,
                 justify="left", font=("Segoe UI", 11, "bold")).pack(side="left", padx=8)

        self.nav_buttons: dict[str, tk.Button] = {}
        nav_items = (("history", "◷", "history"), ("pinned", "★", "pinned"),
                     ("search", "⌕", "search"), ("settings", "⚙", "settings"))
        for mode, icon, key in nav_items:
            button = tk.Button(sidebar, text=f"{icon}   {self.t(key)}", anchor="w",
                               bg=self.SIDEBAR, fg=self.MUTED, activebackground=self.ACCENT_SOFT,
                               activeforeground=self.ACCENT, relief="flat", borderwidth=0,
                               padx=18, pady=11, font=("Microsoft YaHei UI", 10), cursor="hand2",
                               command=lambda value=mode: self.set_view(value))
            button.pack(fill="x", padx=9, pady=2)
            self.nav_buttons[mode] = button

        side_bottom = tk.Frame(sidebar, bg=self.SIDEBAR)
        side_bottom.pack(side="bottom", fill="x", padx=18, pady=20)
        self.side_count_label = tk.Label(side_bottom, text=f"0 {self.t('items')}", bg=self.SIDEBAR,
                                         fg=self.MUTED, font=("Segoe UI", 9))
        self.side_count_label.pack(anchor="w")
        tk.Label(side_bottom, text=self.t("local_only"), bg=self.SIDEBAR, fg=self.MUTED,
                 wraplength=150, justify="left", font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(5, 0))

        workspace = tk.Frame(shell, bg=self.PANEL)
        workspace.pack(side="left", fill="both", expand=True)
        topbar = tk.Frame(workspace, bg=self.PANEL)
        topbar.pack(fill="x", padx=22, pady=(18, 12))
        titles = tk.Frame(topbar, bg=self.PANEL)
        titles.pack(side="left")
        self.section_title = tk.Label(titles, text=self.t("history"), bg=self.PANEL, fg=self.TEXT,
                                      font=("Microsoft YaHei UI", 18, "bold"))
        self.section_title.pack(anchor="w")
        tk.Label(titles, text=self.t("tagline"), bg=self.PANEL, fg=self.MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        self.status = ttk.Label(topbar, text=f"● {self.t('listening')}", foreground=self.ACCENT,
                                background=self.PANEL)
        self.status.pack(side="right", padx=(10, 0))
        ttk.Button(topbar, text=self.t("export"), command=self.export).pack(side="right")
        self.pause_button = ttk.Button(topbar, text=self.t("pause"), command=self.toggle_capture)
        self.pause_button.pack(side="right", padx=8)

        content_area = tk.Frame(workspace, bg=self.PANEL)
        content_area.pack(fill="both", expand=True, padx=22, pady=(0, 18))
        left = tk.Frame(content_area, bg=self.PANEL, width=455)
        left.pack(side="left", fill="both", expand=False)
        left.pack_propagate(False)
        divider = tk.Frame(content_area, bg=self.BORDER, width=1)
        divider.pack(side="left", fill="y", padx=16)
        right = tk.Frame(content_area, bg=self.PANEL)
        right.pack(side="left", fill="both", expand=True)

        search_wrap = tk.Frame(left, bg=self.PANEL)
        search_wrap.pack(fill="x", pady=(0, 8))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.on_search)
        self.search_entry = ttk.Entry(search_wrap, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.sort_var = tk.StringVar(value=self.t("newest"))
        sort_box = ttk.Combobox(search_wrap, textvariable=self.sort_var,
                                values=(self.t("newest"), self.t("oldest")), width=12, state="readonly")
        sort_box.pack(side="left", padx=(8, 0))
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        tk.Label(left, text=self.t("timeline"), bg=self.PANEL, fg=self.MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 6))

        timeline = tk.Frame(left, bg=self.PANEL)
        timeline.pack(fill="both", expand=True)
        self.card_canvas = tk.Canvas(timeline, bg=self.PANEL, highlightthickness=0, borderwidth=0)
        card_scroll = ttk.Scrollbar(timeline, orient="vertical", command=self.card_canvas.yview)
        self.card_canvas.configure(yscrollcommand=card_scroll.set)
        card_scroll.pack(side="right", fill="y")
        self.card_canvas.pack(side="left", fill="both", expand=True)
        self.card_host = tk.Frame(self.card_canvas, bg=self.PANEL)
        self.card_window = self.card_canvas.create_window((0, 0), window=self.card_host, anchor="nw")
        self.card_host.bind("<Configure>", lambda _event: self.card_canvas.configure(scrollregion=self.card_canvas.bbox("all")))
        self.card_canvas.bind("<Configure>", lambda event: self.card_canvas.itemconfigure(self.card_window, width=event.width))
        self.card_canvas.bind("<MouseWheel>", self.on_card_scroll)
        self.card_host.bind("<MouseWheel>", self.on_card_scroll)

        toolbar = tk.Frame(right, bg=self.PANEL)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text=self.t("copy_again"), style="Accent.TButton", command=self.copy_current).pack(side="left")
        self.save_image_button = ttk.Button(toolbar, text=self.t("save_image"), command=self.save_image_copy, state="disabled")
        self.save_image_button.pack(side="left", padx=7)
        ttk.Button(toolbar, text=self.t("pin"), command=self.pin_current).pack(side="left")
        ttk.Button(toolbar, text=self.t("delete"), style="Danger.TButton", command=self.delete_current).pack(side="right")

        fields = tk.Frame(right, bg=self.PANEL)
        fields.pack(fill="both", expand=True)
        self.content_label = tk.Label(fields, text=self.t("content"), bg=self.PANEL, fg=self.TEXT,
                                      font=("Microsoft YaHei UI", 10, "bold"))
        self.content_label.pack(anchor="w")
        self.image_panel = tk.Frame(fields, bg=self.CARD, highlightbackground=self.BORDER, highlightthickness=1)
        self.image_preview = tk.Label(self.image_panel, bg=self.CARD, fg=self.MUTED,
                                      text=self.t("image_missing"), font=("Microsoft YaHei UI", 10))
        self.image_preview.pack(fill="both", expand=True, padx=12, pady=12)
        self.content = tk.Text(fields, height=10, wrap="word", undo=True, bg=self.CARD, fg=self.TEXT,
                               insertbackground=self.TEXT, relief="flat", highlightbackground=self.BORDER,
                               highlightthickness=1, padx=14, pady=12, font=("Microsoft YaHei UI", 11),
                               selectbackground=self.ACCENT_SOFT)
        self.content.pack(fill="both", expand=True, pady=(6, 10))
        meta = tk.Frame(fields, bg=self.PANEL)
        self.meta_frame = meta
        meta.pack(fill="x")
        tk.Label(meta, text=self.t("tags"), bg=self.PANEL, fg=self.MUTED).grid(row=0, column=0, sticky="w")
        tk.Label(meta, text=self.t("note"), bg=self.PANEL, fg=self.MUTED).grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.tags = ttk.Entry(meta)
        self.note = ttk.Entry(meta)
        self.tags.grid(row=1, column=0, sticky="ew", pady=6)
        self.note.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=6)
        meta.columnconfigure(0, weight=1)
        meta.columnconfigure(1, weight=2)
        action = tk.Frame(fields, bg=self.PANEL)
        action.pack(fill="x", pady=(0, 8))
        self.detail_label = tk.Label(action, text=self.t("choose"), bg=self.PANEL, fg=self.MUTED,
                                     font=("Microsoft YaHei UI", 9))
        self.detail_label.pack(side="left")
        ttk.Button(action, text=self.t("save_changes"), style="Accent.TButton", command=self.save_current).pack(side="right")

        notebook = ttk.Notebook(fields)
        notebook.pack(fill="both", expand=True)
        version_frame = ttk.Frame(notebook, style="Panel.TFrame")
        event_frame = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(version_frame, text=self.t("versions"))
        notebook.add(event_frame, text=self.t("activity"))
        self.version_tree = ttk.Treeview(version_frame, columns=("reason", "time"), show="headings", height=5)
        self.version_tree.heading("reason", text=self.t("version")); self.version_tree.heading("time", text=self.t("time"))
        self.version_tree.column("reason", width=180); self.version_tree.column("time", width=140, anchor="e")
        self.version_tree.pack(side="left", fill="both", expand=True, pady=8)
        ttk.Button(version_frame, text=self.t("restore"), command=self.restore_version).pack(side="right", padx=(8, 0), pady=8)
        self.event_tree = ttk.Treeview(event_frame, columns=("action", "detail", "time"), show="headings", height=5)
        for key, label, width in (("action", self.t("action"), 90), ("detail", self.t("detail"), 220), ("time", self.t("time"), 140)):
            self.event_tree.heading(key, text=label); self.event_tree.column(key, width=width, anchor="e" if key == "time" else "w")
        self.event_tree.pack(fill="both", expand=True, pady=8)
        self.update_nav_state()

    def _build_legacy(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=22, pady=(18, 12))
        ttk.Label(header, text="剪贴板库", style="Title.TLabel").pack(side="left")
        self.status = ttk.Label(header, text="● 正在监听", foreground=self.ACCENT)
        self.status.pack(side="left", padx=16)
        ttk.Button(header, text="导出备份", command=self.export).pack(side="right")
        ttk.Button(header, text="设置", command=self.open_settings).pack(side="right", padx=(8, 0))
        self.pause_button = ttk.Button(header, text="暂停监听", command=self.toggle_capture)
        self.pause_button.pack(side="right", padx=8)

        summary = ttk.Frame(self)
        summary.pack(fill="x", padx=22, pady=(0, 12))
        self.total_label = ttk.Label(summary, text="全部 0 条")
        self.total_label.pack(side="left")
        self.today_label = ttk.Label(summary, text="今天 0 条", style="Muted.TLabel")
        self.today_label.pack(side="left", padx=18)
        ttk.Label(summary, text="所有内容仅保存在本机", style="Muted.TLabel").pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=22, pady=(0, 20))

        left = ttk.Frame(body, style="Panel.TFrame", width=390)
        right = ttk.Frame(body, style="Panel.TFrame")
        body.add(left, weight=2)
        body.add(right, weight=3)

        search_wrap = ttk.Frame(left, style="Panel.TFrame")
        search_wrap.pack(fill="x", padx=12, pady=(12, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self.on_search)
        self.search_entry = ttk.Entry(search_wrap, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.sort_var = tk.StringVar(value="最新在前")
        sort_box = ttk.Combobox(search_wrap, textvariable=self.sort_var,
                                values=("最新在前", "最早在前"), width=9, state="readonly")
        sort_box.pack(side="left", padx=(8, 0))
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        self.search_var.set("")

        ttk.Label(left, text="时间线 · 每次复制/剪切均独立记录", style="Muted.TLabel",
                  background=self.PANEL).pack(anchor="w", padx=14, pady=(0, 5))
        timeline = tk.Frame(left, bg=self.PANEL, highlightthickness=0)
        timeline.pack(fill="both", expand=True, padx=(12, 4), pady=(0, 12))
        self.card_canvas = tk.Canvas(timeline, bg=self.PANEL, highlightthickness=0,
                                     borderwidth=0, takefocus=True)
        card_scroll = ttk.Scrollbar(timeline, orient="vertical", command=self.card_canvas.yview)
        self.card_canvas.configure(yscrollcommand=card_scroll.set)
        card_scroll.pack(side="right", fill="y")
        self.card_canvas.pack(side="left", fill="both", expand=True)
        self.card_host = tk.Frame(self.card_canvas, bg=self.PANEL)
        self.card_window = self.card_canvas.create_window((0, 0), window=self.card_host, anchor="nw")
        self.card_host.bind(
            "<Configure>",
            lambda _event: self.card_canvas.configure(scrollregion=self.card_canvas.bbox("all")),
        )
        self.card_canvas.bind(
            "<Configure>",
            lambda event: self.card_canvas.itemconfigure(self.card_window, width=event.width),
        )
        self.card_canvas.bind("<MouseWheel>", self.on_card_scroll)
        self.card_host.bind("<MouseWheel>", self.on_card_scroll)

        toolbar = ttk.Frame(right, style="Panel.TFrame")
        toolbar.pack(fill="x", padx=16, pady=(14, 8))
        ttk.Button(toolbar, text="复制", style="Accent.TButton", command=self.copy_current).pack(side="left")
        self.save_image_button = ttk.Button(toolbar, text="另存截图", command=self.save_image_copy, state="disabled")
        self.save_image_button.pack(side="left", padx=7)
        ttk.Button(toolbar, text="置顶 / 取消", command=self.pin_current).pack(side="left", padx=7)
        ttk.Button(toolbar, text="删除", style="Danger.TButton", command=self.delete_current).pack(side="right")

        fields = ttk.Frame(right, style="Panel.TFrame")
        fields.pack(fill="both", expand=True, padx=16)
        self.content_label = ttk.Label(fields, text="内容", background=self.PANEL)
        self.content_label.pack(anchor="w")
        self.image_panel = tk.Frame(fields, bg=self.CARD, highlightbackground=self.BORDER,
                                    highlightthickness=1)
        self.image_preview = tk.Label(self.image_panel, bg=self.CARD, fg=self.MUTED,
                                      text="截图文件不可用", font=("Microsoft YaHei UI", 10))
        self.image_preview.pack(fill="both", expand=True, padx=12, pady=12)
        self.content = tk.Text(fields, height=10, wrap="word", undo=True, bg=self.CARD,
                               fg=self.TEXT, insertbackground=self.TEXT, relief="flat",
                               padx=12, pady=10, font=("Microsoft YaHei UI", 11),
                               selectbackground="#315e59")
        self.content.pack(fill="both", expand=True, pady=(6, 10))

        meta = ttk.Frame(fields, style="Panel.TFrame")
        self.meta_frame = meta
        meta.pack(fill="x")
        ttk.Label(meta, text="标签", background=self.PANEL).grid(row=0, column=0, sticky="w")
        ttk.Label(meta, text="备注", background=self.PANEL).grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.tags = ttk.Entry(meta)
        self.note = ttk.Entry(meta)
        self.tags.grid(row=1, column=0, sticky="ew", pady=6)
        self.note.grid(row=1, column=1, sticky="ew", padx=(12, 0), pady=6)
        meta.columnconfigure(0, weight=1)
        meta.columnconfigure(1, weight=2)

        action = ttk.Frame(fields, style="Panel.TFrame")
        action.pack(fill="x", pady=(0, 8))
        self.detail_label = ttk.Label(action, text="选择一条记录开始", style="Muted.TLabel", background=self.PANEL)
        self.detail_label.pack(side="left")
        ttk.Button(action, text="保存修改", style="Accent.TButton", command=self.save_current).pack(side="right")

        notebook = ttk.Notebook(fields)
        notebook.pack(fill="both", expand=True, pady=(0, 14))
        version_frame = ttk.Frame(notebook, style="Panel.TFrame")
        event_frame = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(version_frame, text="版本历史")
        notebook.add(event_frame, text="操作轨迹")

        self.version_tree = ttk.Treeview(version_frame, columns=("reason", "time"), show="headings", height=5)
        self.version_tree.heading("reason", text="版本")
        self.version_tree.heading("time", text="时间")
        self.version_tree.column("reason", width=180)
        self.version_tree.column("time", width=140, anchor="e")
        self.version_tree.pack(side="left", fill="both", expand=True, pady=8)
        ttk.Button(version_frame, text="恢复所选", command=self.restore_version).pack(side="right", padx=(8, 0), pady=8)

        self.event_tree = ttk.Treeview(event_frame, columns=("action", "detail", "time"), show="headings", height=5)
        for key, label, width in (("action", "动作", 90), ("detail", "说明", 220), ("time", "时间", 140)):
            self.event_tree.heading(key, text=label)
            self.event_tree.column(key, width=width, anchor="e" if key == "time" else "w")
        self.event_tree.pack(fill="both", expand=True, pady=8)

    def set_view(self, mode: str) -> None:
        if mode == "settings":
            self.open_settings()
            return
        self.view_mode = mode
        if mode == "search":
            self.search_entry.focus_set()
        self.update_nav_state()
        self.refresh()

    def update_nav_state(self) -> None:
        if not hasattr(self, "nav_buttons"):
            return
        title_key = "pinned" if self.view_mode == "pinned" else ("search" if self.view_mode == "search" else "history")
        self.section_title.configure(text=self.t(title_key))
        for mode, button in self.nav_buttons.items():
            active = mode == self.view_mode or (mode == "search" and self.view_mode == "search")
            button.configure(bg=self.ACCENT_SOFT if active else self.SIDEBAR,
                             fg=self.ACCENT if active else self.MUTED)

    def rebuild_interface(self) -> None:
        current = self.current_id
        self.title(self.t("app"))
        for child in self.winfo_children():
            child.destroy()
        self._style()
        self._build()
        self.current_id = current
        self.bind("<Control-s>", lambda _event: self.save_current())
        self.bind("<Control-f>", lambda _event: self.set_view("search"))
        self.refresh(select_id=current)
        self.set_capture_enabled(self.capture_enabled, persist=False)

    def poll_clipboard(self) -> None:
        if not self.capture_enabled:
            self.after(self.poll_interval, self.poll_clipboard)
            return
        try:
            sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
            if sequence != self.last_sequence:
                self.last_sequence = sequence
                try:
                    value = self.clipboard_get()
                except tk.TclError:
                    value = None
                if isinstance(value, str):
                    self.last_seen = value
                    if value == self.suppress_clipboard:
                        self.suppress_clipboard = None
                    else:
                        clip_id = self.store.capture(value)
                        if clip_id:
                            self.refresh(select_id=clip_id)
                elif ImageGrab is not None:
                    grabbed = ImageGrab.grabclipboard()
                    if Image is not None and isinstance(grabbed, Image.Image):
                        clip_id = self.store.capture_image(grabbed)
                        self.refresh(select_id=clip_id)
                        self.status.configure(text="✓ " + ("Screenshot saved" if self.language == "en_US" else "截图已保存"), foreground=self.ACCENT)
                        self.after(1800, lambda: self.set_capture_enabled(self.capture_enabled, persist=False))
        except (tk.TclError, OSError):
            pass
        self.after(self.poll_interval, self.poll_clipboard)

    def toggle_capture(self) -> None:
        self.set_capture_enabled(not self.capture_enabled)

    def set_capture_enabled(self, enabled: bool, persist: bool = True) -> None:
        self.capture_enabled = enabled
        if enabled:
            self.last_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
            self.pause_button.configure(text=self.t("pause"))
            self.status.configure(text=f"● {self.t('listening')}", foreground=self.ACCENT)
        else:
            self.pause_button.configure(text=self.t("resume"))
            self.status.configure(text=f"Ⅱ {self.t('paused')}", foreground=self.MUTED)
        if persist:
            self.settings["auto_capture"] = enabled
            save_settings(self.settings)
        if self.tray_icon:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass

    def apply_launch_mode(self) -> None:
        self.set_capture_enabled(bool(self.settings["auto_capture"]), persist=False)
        if "--autostart" in sys.argv and self.settings["start_minimized"]:
            self.withdraw()

    def create_tray_icon(self) -> None:
        if pystray is None or Image is None or ImageDraw is None:
            return
        icon_image = Image.new("RGBA", (64, 64), (18, 24, 33, 255))
        draw = ImageDraw.Draw(icon_image)
        draw.rounded_rectangle((13, 12, 51, 55), radius=8, fill=(98, 214, 194, 255))
        draw.rounded_rectangle((24, 7, 40, 19), radius=4, fill=(245, 247, 250, 255))
        for y in (27, 37, 47):
            draw.rounded_rectangle((21, y, 43, y + 4), radius=2, fill=(24, 61, 58, 255))

        def enqueue(command: str):
            return lambda _icon=None, _item=None: self.tray_commands.put(command)

        self.tray_icon = pystray.Icon(
            "ClipboardLibrary",
            icon_image,
            "剪贴板库 ClipboardLibrary",
            menu=pystray.Menu(
                pystray.MenuItem(lambda _item: "Open ClipboardLibrary" if self.language == "en_US" else "打开剪贴板库", enqueue("show"), default=True),
                pystray.MenuItem(
                    lambda _item: (("Resume capture" if not self.capture_enabled else "Pause capture")
                                   if self.language == "en_US" else
                                   ("继续自动记录" if not self.capture_enabled else "暂停自动记录")),
                    enqueue("toggle"),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(lambda _item: "Quit" if self.language == "en_US" else "退出", enqueue("quit")),
            ),
        )
        self.tray_icon.run_detached()

    def poll_tray_commands(self) -> None:
        try:
            while True:
                command = self.tray_commands.get_nowait()
                if command == "show":
                    self.deiconify()
                    self.state("normal")
                    self.lift()
                    self.focus_force()
                elif command == "toggle":
                    self.toggle_capture()
                elif command == "quit":
                    self.quit_app()
                    return
        except queue.Empty:
            pass
        if not self.really_quitting:
            self.after(100, self.poll_tray_commands)

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(f"{self.t('settings_title')} · ClipboardLibrary")
        dialog.geometry("570x610")
        dialog.minsize(530, 560)
        dialog.configure(bg=self.BG)
        dialog.transient(self)
        dialog.grab_set()

        wrap = tk.Frame(dialog, bg=self.BG)
        wrap.pack(fill="both", expand=True, padx=26, pady=22)
        tk.Label(wrap, text=self.t("settings_title"), bg=self.BG, fg=self.TEXT,
                 font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        tk.Label(wrap, text=self.t("settings_subtitle"), bg=self.BG, fg=self.MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(2, 16))

        language_row = tk.Frame(wrap, bg=self.BG)
        language_row.pack(fill="x", pady=(0, 10))
        tk.Label(language_row, text=self.t("language"), bg=self.BG, fg=self.TEXT,
                 font=("Microsoft YaHei UI", 10, "bold")).pack(side="left")
        language_var = tk.StringVar(value=self.t("chinese") if self.language == "zh_CN" else self.t("english"))
        language_box = ttk.Combobox(language_row, textvariable=language_var, state="readonly", width=16,
                                    values=(self.t("chinese"), self.t("english")))
        language_box.pack(side="right")

        variables = {
            "auto_capture": tk.BooleanVar(value=bool(self.settings["auto_capture"])),
            "start_on_boot": tk.BooleanVar(value=bool(self.settings["start_on_boot"])),
            "start_minimized": tk.BooleanVar(value=bool(self.settings["start_minimized"])),
            "close_to_tray": tk.BooleanVar(value=bool(self.settings["close_to_tray"])),
        }

        options = (
            ("auto_capture", self.t("auto_capture"), self.t("auto_capture_desc")),
            ("start_on_boot", self.t("start_boot"), self.t("start_boot_desc")),
            ("start_minimized", self.t("start_hidden"), self.t("start_hidden_desc")),
            ("close_to_tray", self.t("close_tray"), self.t("close_tray_desc")),
        )
        for key, title, description in options:
            card = tk.Frame(wrap, bg=self.CARD, highlightbackground=self.BORDER, highlightthickness=1)
            card.pack(fill="x", pady=5)
            check = tk.Checkbutton(card, text=title, variable=variables[key], bg=self.CARD,
                                   fg=self.TEXT, activebackground=self.CARD, activeforeground=self.TEXT,
                                   selectcolor=self.PANEL, font=("Microsoft YaHei UI", 10, "bold"),
                                   anchor="w", padx=12, pady=7)
            check.pack(fill="x")
            tk.Label(card, text=description, bg=self.CARD, fg=self.MUTED,
                     font=("Microsoft YaHei UI", 9), anchor="w", padx=38).pack(fill="x", pady=(0, 9))

        speed = tk.Frame(wrap, bg=self.BG)
        speed.pack(fill="x", pady=(12, 6))
        tk.Label(speed, text=self.t("frequency"), bg=self.BG, fg=self.TEXT,
                 font=("Microsoft YaHei UI", 10)).pack(side="left")
        interval_var = tk.StringVar(value={350: self.t("fast"), 650: self.t("standard"),
                                           1000: self.t("eco")}.get(self.poll_interval, self.t("standard")))
        interval_box = ttk.Combobox(speed, textvariable=interval_var, state="readonly", width=18,
                                    values=(self.t("fast"), self.t("standard"), self.t("eco")))
        interval_box.pack(side="right")

        buttons = tk.Frame(wrap, bg=self.BG)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text=self.t("cancel"), command=dialog.destroy).pack(side="right")

        def apply() -> None:
            interval_lookup = {self.t("fast"): 350, self.t("standard"): 650, self.t("eco"): 1000}
            updated = {key: variable.get() for key, variable in variables.items()}
            updated["poll_interval"] = interval_lookup[interval_var.get()]
            updated["language"] = "en_US" if language_var.get() == self.t("english") else "zh_CN"
            try:
                configure_windows_startup(bool(updated["start_on_boot"]))
            except OSError as error:
                messagebox.showerror(APP_NAME, f"{self.t('startup_error')}:\n{error}", parent=dialog)
                return
            self.settings.update(updated)
            language_changed = self.language != updated["language"]
            self.language = str(updated["language"])
            self.poll_interval = int(updated["poll_interval"])
            self.set_capture_enabled(bool(updated["auto_capture"]), persist=False)
            save_settings(self.settings)
            dialog.destroy()
            if language_changed:
                self.rebuild_interface()
            self.status.configure(text=f"✓ {self.t('saved')}", foreground=self.ACCENT)
            self.after(1800, lambda: self.set_capture_enabled(self.capture_enabled, persist=False))

        ttk.Button(buttons, text=self.t("save_settings"), style="Accent.TButton", command=apply).pack(side="right", padx=8)

    def on_search(self, *_: object) -> None:
        if self.search_after:
            self.after_cancel(self.search_after)
        self.search_after = self.after(180, self.refresh)

    def refresh(self, select_id: int | None = None) -> None:
        query = self.search_var.get().strip() if hasattr(self, "search_var") else ""
        oldest_first = hasattr(self, "sort_var") and self.sort_var.get() == self.t("oldest")
        rows = self.store.list_clips(query, oldest_first, pinned_only=self.view_mode == "pinned")
        total, today_count = self.store.stats()
        if hasattr(self, "total_label"):
            self.total_label.configure(text=f"全部 {total} 条")
            self.today_label.configure(text=f"今天 {today_count} 条")
        if hasattr(self, "side_count_label"):
            self.side_count_label.configure(text=f"{total} {self.t('items')}")
        current = select_id or self.current_id
        for child in self.card_host.winfo_children():
            child.destroy()
        self.card_widgets.clear()
        self.thumbnail_refs.clear()

        if not rows:
            empty = tk.Label(self.card_host, text=self.t("empty"),
                             bg=self.PANEL, fg=self.MUTED, font=("Microsoft YaHei UI", 11),
                             justify="center", pady=48)
            empty.pack(fill="x")
            return

        ids = [int(row["id"]) for row in rows]
        if current not in ids:
            current = ids[0]
        for row in rows:
            self.create_clip_card(row, int(row["id"]) == current)
        self.card_host.update_idletasks()
        self.card_canvas.configure(scrollregion=self.card_canvas.bbox("all"))
        if current is not None:
            self.select_card(int(current), scroll_to=select_id is not None)

    def create_clip_card(self, row: sqlite3.Row, selected: bool = False) -> None:
        clip_id = int(row["id"])
        bg = self.CARD_SELECTED if selected else self.CARD
        border = self.ACCENT if selected else self.BORDER
        card = tk.Frame(self.card_host, bg=bg, highlightbackground=border,
                        highlightcolor=border, highlightthickness=1, cursor="hand2")
        card.pack(fill="x", padx=(1, 7), pady=6, ipady=4)
        self.card_widgets[clip_id] = card

        top = tk.Frame(card, bg=bg)
        top.pack(fill="x", padx=14, pady=(9, 3))
        kind = self.t("image") if row["clip_type"] == "image" else self.t("text")
        marker = f"★ {self.t('pin_mark')}" if row["pinned"] else f"{kind} · #{clip_id}"
        tk.Label(top, text=marker, bg=bg, fg=self.ACCENT if row["pinned"] else self.MUTED,
                 font=("Microsoft YaHei UI", 9, "bold" if row["pinned"] else "normal")).pack(side="left")
        exact_time = display_time(row["created_at"])
        tk.Label(top, text=exact_time, bg=bg, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(side="right")

        if row["clip_type"] == "image" and row["image_path"] and Image is not None and ImageTk is not None:
            try:
                with Image.open(row["image_path"]) as source:
                    thumb = source.convert("RGB")
                    thumb.thumbnail((390, 150), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(thumb)
                self.thumbnail_refs[clip_id] = photo
                image_label = tk.Label(card, image=photo, bg=bg, padx=14, pady=5, anchor="w")
                image_label.pack(fill="x")
                tk.Label(card, text=row["content"], bg=bg, fg=self.TEXT, anchor="w",
                         font=("Microsoft YaHei UI", 10), padx=14, pady=2).pack(fill="x")
            except OSError:
                tk.Label(card, text=self.t("image_missing"), bg=bg, fg=self.DANGER, anchor="w",
                         font=("Microsoft YaHei UI", 10), padx=14, pady=12).pack(fill="x")
        else:
            clean = " ".join(row["content"].split()) or "（空白内容）"
            preview = clean[:150] + ("…" if len(clean) > 150 else "")
            text_label = tk.Label(card, text=preview, bg=bg, fg=self.TEXT, anchor="w",
                                  justify="left", wraplength=390,
                                  font=("Microsoft YaHei UI", 11), padx=14, pady=5)
            text_label.pack(fill="x")

        bottom = tk.Frame(card, bg=bg)
        bottom.pack(fill="x", padx=14, pady=(3, 9))
        tag_text = f"# {row['tags']}" if row["tags"] else self.t("no_tag")
        tk.Label(bottom, text=tag_text, bg=bg, fg=self.ACCENT if row["tags"] else self.MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        note_text = f"{self.t('has_note')}  ·  {self.t('click_edit')}" if row["note"] else self.t("click_edit")
        tk.Label(bottom, text=note_text, bg=bg, fg=self.MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="right")

        def bind_click(widget: tk.Widget) -> None:
            widget.bind("<Button-1>", lambda _event, cid=clip_id: self.select_card(cid))
            widget.bind("<MouseWheel>", self.on_card_scroll)
            for child in widget.winfo_children():
                bind_click(child)

        bind_click(card)

    def on_card_scroll(self, event: tk.Event) -> str:
        self.card_canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def select_card(self, clip_id: int, scroll_to: bool = False) -> None:
        self.current_id = clip_id
        for cid, card in self.card_widgets.items():
            selected = cid == clip_id
            bg = self.CARD_SELECTED if selected else self.CARD
            border = self.ACCENT if selected else self.BORDER
            card.configure(bg=bg, highlightbackground=border, highlightcolor=border)
            self.recolor_card(card, bg)
        if scroll_to and clip_id in self.card_widgets:
            card = self.card_widgets[clip_id]
            self.card_host.update_idletasks()
            total_height = max(1, self.card_host.winfo_height())
            self.card_canvas.yview_moveto(max(0.0, card.winfo_y() / total_height))
        row = self.store.get(self.current_id)
        if not row:
            return
        self.content.delete("1.0", "end")
        self.content.insert("1.0", row["content"])
        if row["clip_type"] == "image":
            self.content_label.configure(text=self.t("image_preview"))
            self.content.pack_forget()
            self.image_panel.pack(fill="both", expand=True, pady=(6, 10), before=self.meta_frame)
            self.save_image_button.configure(state="normal")
            self.preview_image_ref = None
            try:
                if Image is None or ImageTk is None:
                    raise OSError("图像组件不可用")
                with Image.open(row["image_path"]) as source:
                    preview = source.convert("RGB")
                    preview.thumbnail((680, 360), Image.Resampling.LANCZOS)
                self.preview_image_ref = ImageTk.PhotoImage(preview)
                self.image_preview.configure(image=self.preview_image_ref, text="")
            except OSError:
                self.image_preview.configure(image="", text=self.t("image_missing"))
        else:
            self.content_label.configure(text=self.t("content"))
            self.image_panel.pack_forget()
            self.content.pack(fill="both", expand=True, pady=(6, 10), before=self.meta_frame)
            self.save_image_button.configure(state="disabled")
        self.tags.delete(0, "end")
        self.tags.insert(0, row["tags"])
        self.note.delete(0, "end")
        self.note.insert(0, row["note"])
        self.detail_label.configure(text=f"{self.t('record')} #{row['id']} · {self.t('created')} {display_time(row['created_at'])}")
        self.load_trace()

    def recolor_card(self, widget: tk.Widget, bg: str) -> None:
        try:
            widget.configure(bg=bg)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self.recolor_card(child, bg)

    def load_trace(self) -> None:
        if self.current_id is None:
            return
        self.version_tree.delete(*self.version_tree.get_children())
        for version in self.store.versions(self.current_id):
            self.version_tree.insert("", "end", iid=str(version["id"]),
                                     values=(self.localize_stored(version["reason"]), display_time(version["created_at"])))
        self.event_tree.delete(*self.event_tree.get_children())
        for event in self.store.events(self.current_id):
            self.event_tree.insert("", "end", values=(self.localize_stored(event["action"]), self.localize_stored(event["detail"]),
                                                        display_time(event["created_at"])))

    def localize_stored(self, value: str) -> str:
        if self.language != "en_US":
            return value
        translations = {
            "捕获原文": "Original captured", "捕获截图": "Screenshot captured",
            "手动编辑": "Manual edit", "恢复历史版本": "Restored version",
            "已捕获": "Captured", "已捕获截图": "Screenshot captured", "已编辑": "Edited",
            "已置顶": "Pinned", "取消置顶": "Unpinned", "已恢复": "Restored",
            "已复制": "Copied", "已复制截图": "Image copied", "已另存截图": "Image saved",
            "来自系统剪贴板": "From system clipboard", "保存了新版本": "Saved a new version",
            "从剪贴板库复制到系统剪贴板": "Copied from ClipboardLibrary to the system clipboard",
        }
        return translations.get(value, value)

    def save_current(self) -> None:
        if self.current_id is None:
            return
        value = self.content.get("1.0", "end-1c")
        if not value.strip():
            messagebox.showwarning(APP_NAME, self.t("empty_content"))
            return
        self.store.save(self.current_id, value, self.note.get().strip(), self.tags.get().strip())
        self.refresh(select_id=self.current_id)
        self.load_trace()
        self.status.configure(text="✓ " + ("Changes saved" if self.language == "en_US" else "修改已保存"))
        self.after(1800, lambda: self.set_capture_enabled(self.capture_enabled, persist=False))

    def copy_current(self) -> None:
        if self.current_id is None:
            return
        row = self.store.get(self.current_id)
        if not row:
            return
        if row["clip_type"] == "image":
            try:
                copy_image_to_windows_clipboard(Path(row["image_path"]))
                self.last_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
            except (OSError, RuntimeError) as error:
                messagebox.showerror(APP_NAME, f"{self.t('image_copy_error')}:\n{error}")
                return
            self.store.log(self.current_id, "已复制截图", "从剪贴板库复制到系统剪贴板")
            self.load_trace()
            self.status.configure(text="✓ " + ("Image copied" if self.language == "en_US" else "截图已复制"))
            self.after(1500, lambda: self.set_capture_enabled(self.capture_enabled, persist=False))
            return
        value = self.content.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update_idletasks()
        self.last_seen = value
        self.suppress_clipboard = value
        self.store.log(self.current_id, "已复制", "从剪贴板库复制到系统剪贴板")
        self.load_trace()
        self.status.configure(text="✓ " + ("Copied" if self.language == "en_US" else "已复制"))
        self.after(1500, lambda: self.set_capture_enabled(self.capture_enabled, persist=False))

    def save_image_copy(self) -> None:
        if self.current_id is None:
            return
        row = self.store.get(self.current_id)
        if not row or row["clip_type"] != "image" or not row["image_path"]:
            return
        source = Path(row["image_path"])
        if not source.exists():
            messagebox.showerror(APP_NAME, self.t("image_unavailable"))
            return
        filename = f"ClipboardLibrary-{datetime.now():%Y%m%d-%H%M%S}.png"
        target = filedialog.asksaveasfilename(defaultextension=".png", initialfile=filename,
                                              filetypes=[("PNG 图片", "*.png")])
        if target:
            shutil.copy2(source, target)
            self.store.log(self.current_id, "已另存截图", Path(target).name)
            self.load_trace()

    def pin_current(self) -> None:
        if self.current_id is not None:
            self.store.toggle_pin(self.current_id)
            self.refresh(select_id=self.current_id)
            self.load_trace()

    def delete_current(self) -> None:
        if self.current_id is None:
            return
        if messagebox.askyesno(APP_NAME, self.t("delete_confirm")):
            self.store.delete(self.current_id)
            self.current_id = None
            self.content.delete("1.0", "end")
            self.tags.delete(0, "end")
            self.note.delete(0, "end")
            self.refresh()

    def restore_version(self) -> None:
        if self.current_id is None or not self.version_tree.selection():
            return
        version_id = int(self.version_tree.selection()[0])
        if messagebox.askyesno(APP_NAME, self.t("restore_confirm")):
            current = self.store.get(self.current_id)
            if current:
                self.store.save(self.current_id, current["content"], current["note"], current["tags"])
            self.store.restore(self.current_id, version_id)
            self.select_card(self.current_id)
            self.refresh(select_id=self.current_id)

    def export(self) -> None:
        filename = f"剪贴板库备份-{datetime.now():%Y%m%d-%H%M}.json"
        path = filedialog.asksaveasfilename(defaultextension=".json", initialfile=filename,
                                            filetypes=[("JSON 备份", "*.json")])
        if path:
            self.store.export(path)
            messagebox.showinfo(APP_NAME, f"{self.t('backup_done')}:\n{path}")

    def on_close(self) -> None:
        if self.settings.get("close_to_tray", True) and self.tray_icon is not None:
            self.withdraw()
            return
        self.quit_app()

    def quit_app(self) -> None:
        if self.really_quitting:
            return
        self.really_quitting = True
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.store.db.close()
        self.destroy()


if __name__ == "__main__":
    enable_high_dpi()
    ClipboardLibrary().mainloop()
