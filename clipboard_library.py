from __future__ import annotations

import json
import os
import sqlite3
import tkinter as tk
import ctypes
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


APP_NAME = "剪贴板库"
DATA_DIR = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ClipboardLibrary"
DB_PATH = DATA_DIR / "clipboard.db"


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
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
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
        self.store = Store()
        self.current_id: int | None = None
        self.card_widgets: dict[int, tk.Frame] = {}
        self.suppress_clipboard: str | None = None
        self.last_seen: str | None = None
        self.last_sequence = 0
        self.capture_enabled = True
        self.search_after: str | None = None

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
        self.after(350, self.poll_clipboard)

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
        ttk.Button(toolbar, text="置顶 / 取消", command=self.pin_current).pack(side="left", padx=7)
        ttk.Button(toolbar, text="删除", style="Danger.TButton", command=self.delete_current).pack(side="right")

        fields = ttk.Frame(right, style="Panel.TFrame")
        fields.pack(fill="both", expand=True, padx=16)
        ttk.Label(fields, text="内容", background=self.PANEL).pack(anchor="w")
        self.content = tk.Text(fields, height=10, wrap="word", undo=True, bg=self.CARD,
                               fg=self.TEXT, insertbackground=self.TEXT, relief="flat",
                               padx=12, pady=10, font=("Microsoft YaHei UI", 11),
                               selectbackground="#315e59")
        self.content.pack(fill="both", expand=True, pady=(6, 10))

        meta = ttk.Frame(fields, style="Panel.TFrame")
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
            self.after(650, self.poll_clipboard)
            return
        try:
            sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
            if sequence != self.last_sequence:
                self.last_sequence = sequence
                value = self.clipboard_get()
                self.last_seen = value
                if value == self.suppress_clipboard:
                    self.suppress_clipboard = None
                else:
                    clip_id = self.store.capture(value)
                    if clip_id:
                        self.refresh(select_id=clip_id)
        except tk.TclError:
            pass
        self.after(650, self.poll_clipboard)

    def toggle_capture(self) -> None:
        self.capture_enabled = not self.capture_enabled
        if self.capture_enabled:
            self.last_sequence = ctypes.windll.user32.GetClipboardSequenceNumber()
            self.pause_button.configure(text="暂停监听")
            self.status.configure(text="● 正在监听", foreground=self.ACCENT)
        else:
            self.pause_button.configure(text="继续监听")
            self.status.configure(text="Ⅱ 已暂停", foreground=self.MUTED)

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
        marker = "★ 置顶" if row["pinned"] else f"记录 #{clip_id}"
        tk.Label(top, text=marker, bg=bg, fg=self.ACCENT if row["pinned"] else self.MUTED,
                 font=("Microsoft YaHei UI", 9, "bold" if row["pinned"] else "normal")).pack(side="left")
        exact_time = display_time(row["created_at"])
        tk.Label(top, text=exact_time, bg=bg, fg=self.MUTED,
                 font=("Segoe UI", 9)).pack(side="right")

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
        self.store.db.close()
        self.destroy()


if __name__ == "__main__":
    enable_high_dpi()
    ClipboardLibrary().mainloop()
