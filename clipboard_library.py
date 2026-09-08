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

    def list_clips(self, query: str = "", oldest_first: bool = False) -> list[sqlite3.Row]:
        direction = "ASC" if oldest_first else "DESC"
        if query:
            like = f"%{query}%"
            return self.db.execute(
                f"""SELECT * FROM clips
                   WHERE content LIKE ? OR note LIKE ? OR tags LIKE ?
                   ORDER BY created_at {direction}, id {direction}""",
                (like, like, like),
            ).fetchall()
        return self.db.execute(
            f"SELECT * FROM clips ORDER BY created_at {direction}, id {direction}"
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
    BG = "#0b0f14"
    PANEL = "#121821"
    CARD = "#1b2430"
    CARD_HOVER = "#222e3c"
    CARD_SELECTED = "#183d3a"
    BORDER = "#2b3746"
    TEXT = "#f5f7fa"
    MUTED = "#93a0b2"
    ACCENT = "#62d6c2"
    DANGER = "#ff8a8a"

    def __init__(self) -> None:
        super().__init__()
        self.settings = load_settings()
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

        self.title(APP_NAME)
        self.geometry("1280x820")
        self.minsize(980, 660)
        self.configure(bg=self.BG)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._style()
        self._build()
        self.bind("<Control-s>", lambda _event: self.save_current())
        self.bind("<Control-f>", lambda _event: self.search_entry.focus_set())
        self.refresh()
        self.create_tray_icon()
        self.after(100, self.poll_tray_commands)
        self.after(350, self.poll_clipboard)
        self.after(80, self.apply_launch_mode)

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
        style.map("TButton", background=[("active", "#303846")])
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#0d2622")
        style.map("Accent.TButton", background=[("active", "#99e6da")])
        style.configure("Danger.TButton", foreground=self.DANGER)
        style.configure("TEntry", fieldbackground=self.CARD, foreground=self.TEXT,
                        insertcolor=self.TEXT, borderwidth=0, padding=9)
        style.configure("Treeview", background=self.PANEL, fieldbackground=self.PANEL,
                        foreground=self.TEXT, rowheight=54, borderwidth=0,
                        font=("Microsoft YaHei UI", 10))
        style.map("Treeview", background=[("selected", "#2b4b48")])
        style.configure("Treeview.Heading", background=self.PANEL, foreground=self.MUTED,
                        borderwidth=0, font=("Microsoft YaHei UI", 9))
        style.configure("TNotebook", background=self.PANEL, borderwidth=0)
        style.configure("TNotebook.Tab", background=self.PANEL, foreground=self.MUTED,
                        padding=(14, 8), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", self.CARD)],
                  foreground=[("selected", self.TEXT)])

    def _build(self) -> None:
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
                        self.status.configure(text="✓ 截图已保存", foreground=self.ACCENT)
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
            self.pause_button.configure(text="暂停监听")
            self.status.configure(text="● 正在监听", foreground=self.ACCENT)
        else:
            self.pause_button.configure(text="继续监听")
            self.status.configure(text="Ⅱ 已暂停", foreground=self.MUTED)
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
                pystray.MenuItem("打开剪贴板库", enqueue("show"), default=True),
                pystray.MenuItem(
                    lambda _item: "继续自动记录" if not self.capture_enabled else "暂停自动记录",
                    enqueue("toggle"),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", enqueue("quit")),
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
        dialog.title("设置 · ClipboardLibrary")
        dialog.geometry("560x520")
        dialog.minsize(520, 470)
        dialog.configure(bg=self.BG)
        dialog.transient(self)
        dialog.grab_set()

        wrap = tk.Frame(dialog, bg=self.BG)
        wrap.pack(fill="both", expand=True, padx=26, pady=22)
        tk.Label(wrap, text="设置", bg=self.BG, fg=self.TEXT,
                 font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        tk.Label(wrap, text="后台运行与自动记录", bg=self.BG, fg=self.MUTED,
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", pady=(2, 16))

        variables = {
            "auto_capture": tk.BooleanVar(value=bool(self.settings["auto_capture"])),
            "start_on_boot": tk.BooleanVar(value=bool(self.settings["start_on_boot"])),
            "start_minimized": tk.BooleanVar(value=bool(self.settings["start_minimized"])),
            "close_to_tray": tk.BooleanVar(value=bool(self.settings["close_to_tray"])),
        }

        options = (
            ("auto_capture", "自动记录剪贴板", "检测到复制或剪切时自动保存文本内容"),
            ("start_on_boot", "登录 Windows 后自动启动", "为当前 Windows 用户添加启动项"),
            ("start_minimized", "开机启动时在后台运行", "不弹出主窗口，仅显示在系统托盘"),
            ("close_to_tray", "关闭窗口后继续运行", "点击关闭按钮时隐藏到系统托盘并继续监听"),
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
        tk.Label(speed, text="监听频率", bg=self.BG, fg=self.TEXT,
                 font=("Microsoft YaHei UI", 10)).pack(side="left")
        interval_var = tk.StringVar(value={350: "快速 · 350 毫秒", 650: "标准 · 650 毫秒",
                                           1000: "节能 · 1000 毫秒"}.get(self.poll_interval, "标准 · 650 毫秒"))
        interval_box = ttk.Combobox(speed, textvariable=interval_var, state="readonly", width=18,
                                    values=("快速 · 350 毫秒", "标准 · 650 毫秒", "节能 · 1000 毫秒"))
        interval_box.pack(side="right")

        buttons = tk.Frame(wrap, bg=self.BG)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="right")

        def apply() -> None:
            interval_lookup = {"快速 · 350 毫秒": 350, "标准 · 650 毫秒": 650, "节能 · 1000 毫秒": 1000}
            updated = {key: variable.get() for key, variable in variables.items()}
            updated["poll_interval"] = interval_lookup[interval_var.get()]
            try:
                configure_windows_startup(bool(updated["start_on_boot"]))
            except OSError as error:
                messagebox.showerror(APP_NAME, f"无法更新 Windows 启动项：\n{error}", parent=dialog)
                return
            self.settings.update(updated)
            self.poll_interval = int(updated["poll_interval"])
            self.set_capture_enabled(bool(updated["auto_capture"]), persist=False)
            save_settings(self.settings)
            dialog.destroy()
            self.status.configure(text="✓ 设置已保存", foreground=self.ACCENT)
            self.after(1800, lambda: self.set_capture_enabled(self.capture_enabled, persist=False))

        ttk.Button(buttons, text="保存设置", style="Accent.TButton", command=apply).pack(side="right", padx=8)

    def on_search(self, *_: object) -> None:
        if self.search_after:
            self.after_cancel(self.search_after)
        self.search_after = self.after(180, self.refresh)

    def refresh(self, select_id: int | None = None) -> None:
        query = self.search_var.get().strip() if hasattr(self, "search_var") else ""
        oldest_first = hasattr(self, "sort_var") and self.sort_var.get() == "最早在前"
        rows = self.store.list_clips(query, oldest_first)
        total, today_count = self.store.stats()
        if hasattr(self, "total_label"):
            self.total_label.configure(text=f"全部 {total} 条")
            self.today_label.configure(text=f"今天 {today_count} 条")
        current = select_id or self.current_id
        for child in self.card_host.winfo_children():
            child.destroy()
        self.card_widgets.clear()
        self.thumbnail_refs.clear()

        if not rows:
            empty = tk.Label(self.card_host, text="暂无匹配记录\n复制一段文字后会自动出现在这里",
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
        kind = "截图" if row["clip_type"] == "image" else "文本"
        marker = "★ 置顶" if row["pinned"] else f"{kind} · #{clip_id}"
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
                tk.Label(card, text="截图文件不可用", bg=bg, fg=self.DANGER, anchor="w",
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
        tag_text = f"# {row['tags']}" if row["tags"] else "未添加标签"
        tk.Label(bottom, text=tag_text, bg=bg, fg=self.ACCENT if row["tags"] else self.MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        note_text = "有备注  ·  点击编辑 →" if row["note"] else "点击编辑 →"
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
            self.content_label.configure(text="截图预览")
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
                self.image_preview.configure(image="", text="截图文件不可用")
        else:
            self.content_label.configure(text="内容")
            self.image_panel.pack_forget()
            self.content.pack(fill="both", expand=True, pady=(6, 10), before=self.meta_frame)
            self.save_image_button.configure(state="disabled")
        self.tags.delete(0, "end")
        self.tags.insert(0, row["tags"])
        self.note.delete(0, "end")
        self.note.insert(0, row["note"])
        self.detail_label.configure(text=f"记录 #{row['id']} · 创建于 {display_time(row['created_at'])}")
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
                                     values=(version["reason"], display_time(version["created_at"])))
        self.event_tree.delete(*self.event_tree.get_children())
        for event in self.store.events(self.current_id):
            self.event_tree.insert("", "end", values=(event["action"], event["detail"],
                                                        display_time(event["created_at"])))

    def save_current(self) -> None:
        if self.current_id is None:
            return
        value = self.content.get("1.0", "end-1c")
        if not value.strip():
            messagebox.showwarning(APP_NAME, "内容不能为空。")
            return
        self.store.save(self.current_id, value, self.note.get().strip(), self.tags.get().strip())
        self.refresh(select_id=self.current_id)
        self.load_trace()
        self.status.configure(text="✓ 修改已保存")
        self.after(1800, lambda: self.status.configure(text="● 正在监听"))

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
                messagebox.showerror(APP_NAME, f"无法复制截图：\n{error}")
                return
            self.store.log(self.current_id, "已复制截图", "从剪贴板库复制到系统剪贴板")
            self.load_trace()
            self.status.configure(text="✓ 截图已复制")
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
        self.status.configure(text="✓ 已复制")
        self.after(1500, lambda: self.status.configure(text="● 正在监听"))

    def save_image_copy(self) -> None:
        if self.current_id is None:
            return
        row = self.store.get(self.current_id)
        if not row or row["clip_type"] != "image" or not row["image_path"]:
            return
        source = Path(row["image_path"])
        if not source.exists():
            messagebox.showerror(APP_NAME, "截图文件不可用。")
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
        if messagebox.askyesno(APP_NAME, "删除这条记录及其所有版本和轨迹？"):
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
        if messagebox.askyesno(APP_NAME, "恢复到这个版本？当前内容也会留在版本历史中。"):
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
            messagebox.showinfo(APP_NAME, f"备份已导出：\n{path}")

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
