"""Compact Tkinter UI for inspecting and repairing media timestamps."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import BooleanVar, Menu, StringVar, Text, Tk, Toplevel, filedialog, messagebox, ttk
from typing import Optional

from .core import MediaRecord, format_size
from .repair import RepairService
from .scanner import scan_directory, scan_file

REVIEW_FILTERS = (
    "All review items",
    "Missing Taken At",
    "Taken > Created",
    "Taken > Modified",
)

REPAIR_METHODS: dict[str, tuple[str, str]] = {
    "Set Taken At from filename": ("taken", "filename"),
    "Set Taken At from Created": ("taken", "created"),
    "Set Created from Taken At": ("created", "taken"),
    "Set Created from filename": ("created", "filename"),
    "Set Modified from Taken At": ("modified", "taken"),
    "Set Modified from filename": ("modified", "filename"),
}

REPAIR_PLACEHOLDER = "Choose a repair method…"
TARGET_LABELS = {"taken": "Taken At", "created": "Created", "modified": "Modified"}
SOURCE_LABELS = {
    "taken": "Taken At",
    "created": "Created",
    "modified": "Modified",
    "filename": "Filename date/time",
}

_SHIFT_MASK = 0x0001
_CTRL_MASK = 0x0004
_PREVIEW_ROWS = 10


def _selection_range(items: tuple[str, ...], anchor: str, target: str) -> tuple[str, ...]:
    """Return the inclusive range between two Treeview item ids."""
    if anchor not in items or target not in items:
        return (target,) if target in items else ()
    start = items.index(anchor)
    end = items.index(target)
    if start > end:
        start, end = end, start
    return items[start : end + 1]


def _record_matches_search(record: MediaRecord, query: str) -> bool:
    """Match the search box against filename or full path, case-insensitively."""
    needle = query.strip().casefold()
    if not needle:
        return True
    return needle in record.name.casefold() or needle in record.path.casefold()


def _record_sort_value(record: MediaRecord, column: str):
    """Return stable sortable values for Treeview columns."""
    if column == "name":
        return record.name.casefold()
    if column == "type":
        return record.media_type.casefold()
    if column == "size":
        return record.size_bytes
    if column == "created":
        return record.created_ts
    if column == "modified":
        return record.modified_ts
    if column == "taken":
        return (record.taken_ts is None, record.taken_ts or 0.0)
    if column == "filename":
        return (record.filename_ts is None, record.filename_ts or 0.0)
    if column == "issues":
        return "; ".join(record.issues).casefold()
    if column == "path":
        return str(Path(record.path).parent).casefold()
    return ""


class PhotoRepairApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Photo Metadata Repair Inspector")
        self.root.geometry("1450x820")
        self.root.minsize(1080, 640)

        self.records: list[MediaRecord] = []
        self.library_map: dict[str, MediaRecord] = {}
        self.issue_map: dict[str, MediaRecord] = {}
        self.selected_review_paths: set[str] = set()
        self.scan_root: Optional[Path] = None
        self.repair_service: Optional[RepairService] = None

        self._scan_generation = 0
        self._scan_cancel_event: Optional[threading.Event] = None
        self._scan_started_at: Optional[float] = None
        self._metadata_started_at: Optional[float] = None
        self._scan_completed = 0
        self._scan_total = 0
        self._review_selection_anchor: Optional[str] = None
        self._filter_after_id: Optional[str] = None
        self._sort_state: dict[int, tuple[str, bool]] = {}

        self.status_var = StringVar(value="Choose a folder to inspect")
        self.summary_var = StringVar(value="No collection loaded")
        self.scan_progress_var = StringVar(value="")
        self.selection_var = StringVar(value="0 selected")
        self.media_filter_var = StringVar(value="All")
        self.issue_filter_var = StringVar(value=REVIEW_FILTERS[0])
        self.search_var = StringVar(value="")
        self.repair_method_var = StringVar(value=REPAIR_PLACEHOLDER)
        self.backup_enabled_var = BooleanVar(value=True)

        self._configure_styles()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")

        default_font = ("Segoe UI", 10)
        self.root.option_add("*Font", default_font)
        self.root.option_add("*Menu.Font", default_font)

        style.configure("TButton", padding=(9, 5))
        style.configure("TCombobox", padding=3)
        style.configure("TEntry", padding=4)
        style.configure("TNotebook", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 7))
        style.configure("Treeview", rowheight=29, font=default_font, borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10), padding=(6, 7))
        style.configure("Summary.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Muted.TLabel", font=("Segoe UI", 9))
        style.configure("Selection.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Primary.TButton", font=("Segoe UI Semibold", 10), padding=(13, 6))
        style.configure("DangerHint.TLabel", font=("Segoe UI Semibold", 9))
        style.configure("DialogTitle.TLabel", font=("Segoe UI Semibold", 15))

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=(14, 10, 14, 8))
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        # Compact top toolbar. The window title already carries the application name.
        toolbar = ttk.Frame(container)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        toolbar.columnconfigure(0, weight=1)

        ttk.Label(toolbar, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=0, column=0, sticky="w", padx=(2, 10)
        )
        self.scan_button = ttk.Button(toolbar, text="Scan folder…", command=self.request_directory)
        self.scan_button.grid(row=0, column=1, padx=(0, 6))
        self.stop_button = ttk.Button(toolbar, text="Stop", command=self.stop_scan, state="disabled")
        self.stop_button.grid(row=0, column=2, padx=(0, 16))

        ttk.Label(toolbar, text="Search").grid(row=0, column=3, padx=(0, 5))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=25)
        self.search_entry.grid(row=0, column=4, padx=(0, 14))
        self.search_entry.bind("<KeyRelease>", self._schedule_filter_render)
        self.search_entry.bind("<Escape>", lambda _: self._clear_search())

        ttk.Label(toolbar, text="Media").grid(row=0, column=5, padx=(0, 5))
        media_filter = ttk.Combobox(
            toolbar,
            textvariable=self.media_filter_var,
            values=("All", "Images", "Videos"),
            width=10,
            state="readonly",
        )
        media_filter.grid(row=0, column=6)
        media_filter.bind("<<ComboboxSelected>>", lambda _: self._render())

        # Compact status line, no surrounding card/border.
        summary = ttk.Frame(container)
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        summary.columnconfigure(0, weight=1)
        ttk.Label(summary, textvariable=self.summary_var, style="Summary.TLabel").grid(
            row=0, column=0, sticky="w", padx=(2, 0)
        )
        ttk.Label(summary, textvariable=self.scan_progress_var, style="Muted.TLabel").grid(
            row=0, column=1, sticky="e", padx=(12, 2)
        )

        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        self.progress.grid_remove()

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=3, column=0, sticky="nsew")

        library_tab = ttk.Frame(self.notebook, padding=(5, 7, 5, 4))
        review_tab = ttk.Frame(self.notebook, padding=(5, 7, 5, 4))
        log_tab = ttk.Frame(self.notebook, padding=(5, 7, 5, 4))
        self.notebook.add(library_tab, text="Library")
        self.notebook.add(review_tab, text="Review")
        self.notebook.add(log_tab, text="Repair log")

        library_tab.columnconfigure(0, weight=1)
        library_tab.rowconfigure(0, weight=1)
        self.library_tree = self._build_tree(library_tab, include_issues=False, row=0)
        self.library_tree.bind("<Button-3>", lambda event: self._show_context_menu(event, False))

        review_tab.columnconfigure(0, weight=1)
        review_tab.rowconfigure(1, weight=1)

        review_tools = ttk.Frame(review_tab)
        review_tools.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        review_tools.columnconfigure(2, weight=1)

        ttk.Label(review_tools, text="Show").grid(row=0, column=0, padx=(1, 5))
        review_filter = ttk.Combobox(
            review_tools,
            textvariable=self.issue_filter_var,
            values=REVIEW_FILTERS,
            width=22,
            state="readonly",
        )
        review_filter.grid(row=0, column=1, padx=(0, 12))
        review_filter.bind("<<ComboboxSelected>>", lambda _: self._render_issues())
        ttk.Label(
            review_tools,
            text="Checkboxes, Ctrl-click, and Shift-click all use the same selection.",
            style="Muted.TLabel",
        ).grid(row=0, column=2, sticky="w")
        ttk.Button(review_tools, text="Select all", command=self._select_all_issues).grid(
            row=0, column=3, padx=(8, 5)
        )
        ttk.Button(review_tools, text="Clear", command=self._clear_review_selection).grid(
            row=0, column=4
        )

        self.issue_tree = self._build_tree(review_tab, include_issues=True, row=1, checkboxes=True)
        self.issue_tree.bind("<Button-1>", self._on_review_click)
        self.issue_tree.bind("<<TreeviewSelect>>", self._sync_review_selection)
        self.issue_tree.bind("<space>", self._toggle_focused_review)
        self.issue_tree.bind("<Double-1>", lambda _: self._open_selected())
        self.issue_tree.bind("<Button-3>", lambda event: self._show_context_menu(event, True))

        # Sticky, compact repair action bar.
        ttk.Separator(review_tab, orient="horizontal").grid(
            row=2, column=0, sticky="ew", pady=(7, 6)
        )
        action_bar = ttk.Frame(review_tab)
        action_bar.grid(row=3, column=0, sticky="ew", pady=(0, 1))
        action_bar.columnconfigure(5, weight=1)

        ttk.Label(action_bar, textvariable=self.selection_var, style="Selection.TLabel").grid(
            row=0, column=0, padx=(1, 12)
        )
        ttk.Label(action_bar, text="Repair").grid(row=0, column=1, padx=(0, 5))
        self.repair_method = ttk.Combobox(
            action_bar,
            textvariable=self.repair_method_var,
            values=tuple(REPAIR_METHODS),
            state="readonly",
            width=32,
        )
        self.repair_method.grid(row=0, column=2, padx=(0, 12))
        self.repair_method.bind("<<ComboboxSelected>>", lambda _: self._update_action_state())

        ttk.Checkbutton(
            action_bar,
            text="Backup originals",
            variable=self.backup_enabled_var,
            command=self._update_action_state,
        ).grid(row=0, column=3, padx=(0, 12))

        self.review_button = ttk.Button(
            action_bar,
            text="Review changes…",
            command=self.review_selected_repair,
            style="Primary.TButton",
            state="disabled",
        )
        self.review_button.grid(row=0, column=4)

        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(0, weight=1)
        self.log_text = Text(
            log_tab,
            wrap="none",
            font=("Consolas", 9),
            borderwidth=0,
            padx=8,
            pady=8,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_tab, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        log_hscroll = ttk.Scrollbar(log_tab, orient="horizontal", command=self.log_text.xview)
        log_hscroll.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(
            yscrollcommand=log_scroll.set,
            xscrollcommand=log_hscroll.set,
            state="disabled",
        )

    def _build_tree(
        self,
        parent: ttk.Frame,
        include_issues: bool,
        row: int = 0,
        *,
        checkboxes: bool = False,
    ) -> ttk.Treeview:
        table = ttk.Frame(parent)
        table.grid(row=row, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        columns: list[str] = []
        if checkboxes:
            columns.append("selected")
        columns.extend(["name", "type", "size", "created", "modified", "taken", "filename"])
        if include_issues:
            columns.append("issues")
        columns.append("path")

        tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            selectmode="extended" if checkboxes else "browse",
        )
        tree.grid(row=0, column=0, sticky="nsew")

        vscroll = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(table, orient="horizontal", command=tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)

        headings = {
            "selected": "Select",
            "name": "File",
            "type": "Type",
            "size": "Size",
            "created": "Created",
            "modified": "Modified",
            "taken": "Taken At",
            "filename": "Filename Date",
            "issues": "Review reason",
            "path": "Location",
        }
        widths = {
            "selected": 56,
            "name": 245,
            "type": 70,
            "size": 90,
            "created": 150,
            "modified": 150,
            "taken": 150,
            "filename": 150,
            "issues": 210,
            "path": 300,
        }
        anchors = {"selected": "center", "size": "e"}

        for column in columns:
            if column == "selected":
                tree.heading(column, text=headings[column])
            else:
                tree.heading(
                    column,
                    text=headings[column],
                    command=lambda c=column, t=tree: self._sort_tree(t, c),
                )
            tree.column(
                column,
                width=widths[column],
                minwidth=50 if column == "selected" else 60,
                anchor=anchors.get(column, "w"),
                stretch=(column == "path"),
            )

        tree.tag_configure("alternate", background="#f6f8fa")
        if not checkboxes:
            tree.bind("<Double-1>", lambda _: self._open_selected())
        return tree

    def _schedule_filter_render(self, _event=None) -> None:
        if self._filter_after_id is not None:
            self.root.after_cancel(self._filter_after_id)
        self._filter_after_id = self.root.after(140, self._apply_filter_render)

    def _apply_filter_render(self) -> None:
        self._filter_after_id = None
        self._render()

    def _clear_search(self) -> str:
        self.search_var.set("")
        self._render()
        return "break"

    def request_directory(self) -> None:
        if self._scan_cancel_event is not None:
            return
        directory = filedialog.askdirectory()
        if not directory:
            return
        root = Path(directory)
        if not root.exists():
            messagebox.showerror("Folder missing", f"{root} does not exist.")
            return

        self._scan_generation += 1
        generation = self._scan_generation
        cancel_event = threading.Event()
        self._scan_cancel_event = cancel_event
        self._scan_started_at = time.perf_counter()
        self._metadata_started_at = None
        self._scan_completed = 0
        self._scan_total = 0

        self.scan_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set(f"Scanning {root}")
        self.summary_var.set("Discovering supported media files…")
        self.scan_progress_var.set("Discovering files")
        self.progress.configure(mode="indeterminate", maximum=100, value=0)
        self.progress.grid()
        self.progress.start(12)

        threading.Thread(
            target=self._scan_worker,
            args=(generation, root, cancel_event),
            daemon=True,
            name="photo-scan-controller",
        ).start()

    def stop_scan(self) -> None:
        cancel_event = self._scan_cancel_event
        if cancel_event is None or cancel_event.is_set():
            return
        cancel_event.set()
        self.stop_button.configure(state="disabled")
        self.status_var.set("Stopping scan…")
        if self._scan_total:
            self.scan_progress_var.set(
                f"{self._scan_completed:,} / {self._scan_total:,}  ·  stopping…"
            )
        else:
            self.scan_progress_var.set("Stopping discovery…")

    def _scan_worker(self, generation: int, root: Path, cancel_event: threading.Event) -> None:
        def report_progress(completed: int, total: int) -> None:
            try:
                self.root.after(
                    0,
                    lambda c=completed, t=total: self._update_scan_progress(generation, c, t),
                )
            except RuntimeError:
                pass

        records = scan_directory(
            root,
            cancel_event=cancel_event,
            progress_callback=report_progress,
        )
        cancelled = cancel_event.is_set()
        try:
            self.root.after(
                0,
                lambda: self._finish_scan(generation, root, records, cancelled),
            )
        except RuntimeError:
            pass

    def _update_scan_progress(self, generation: int, completed: int, total: int) -> None:
        if generation != self._scan_generation:
            return
        self._scan_completed = completed
        self._scan_total = total

        if completed == 0:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=max(total, 1), value=0)
            self._metadata_started_at = time.perf_counter()
            self.summary_var.set(
                f"Found {total:,} supported media files. Reading metadata…"
                if total
                else "No supported media files found"
            )
            self.scan_progress_var.set(f"0 / {total:,}" if total else "")
            return

        self.progress.configure(value=completed)
        percent = (completed / total * 100.0) if total else 100.0
        parts = [f"{completed:,} / {total:,}", f"{percent:.0f}%"]
        if self._metadata_started_at is not None:
            elapsed = max(0.0, time.perf_counter() - self._metadata_started_at)
            parts.append(f"elapsed {self._format_duration(elapsed)}")
            if completed >= 3 and elapsed >= 0.25 and completed < total:
                rate = completed / elapsed
                if rate > 0:
                    remaining = (total - completed) / rate
                    parts.append(f"~{self._format_duration(remaining)} remaining")
        if self._scan_cancel_event is not None and self._scan_cancel_event.is_set():
            parts.append("stopping…")
        self.scan_progress_var.set("  ·  ".join(parts))

    def _finish_scan(
        self,
        generation: int,
        root: Path,
        records: list[MediaRecord],
        cancelled: bool,
    ) -> None:
        if generation != self._scan_generation:
            return
        self.progress.stop()
        self.progress.grid_remove()
        self.scan_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self._scan_cancel_event = None

        elapsed = 0.0
        if self._scan_started_at is not None:
            elapsed = max(0.0, time.perf_counter() - self._scan_started_at)

        if cancelled and not records:
            self.status_var.set("Scan stopped. Previous results kept.")
            self.scan_progress_var.set(f"Stopped after {self._format_duration(elapsed)}")
            return

        self.scan_root = root
        self.repair_service = RepairService(root)
        self.records = records
        self._render()
        self._load_log()

        if cancelled:
            self.status_var.set(f"Partial results: {root}")
            self.scan_progress_var.set(
                f"Stopped at {self._scan_completed:,} / {self._scan_total:,}  ·  "
                f"{self._format_duration(elapsed)}"
            )
        else:
            self.status_var.set(str(root))
            self.scan_progress_var.set(f"Scan complete  ·  {self._format_duration(elapsed)}")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total_seconds = max(0, int(round(seconds)))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _media_matches(self, record: MediaRecord) -> bool:
        selected = self.media_filter_var.get()
        if selected == "Images":
            return record.media_type == "image"
        if selected == "Videos":
            return record.media_type == "video"
        return True

    def _visible(self, record: MediaRecord) -> bool:
        return self._media_matches(record) and _record_matches_search(record, self.search_var.get())

    def _row_values(
        self,
        record: MediaRecord,
        include_issues: bool,
        *,
        checked: bool = False,
    ) -> tuple[str, ...]:
        values: list[str] = []
        if include_issues:
            values.append("☑" if checked else "☐")
        values.extend(
            [
                record.name,
                record.media_type.title(),
                format_size(record.size_bytes),
                record.created,
                record.modified,
                record.taken,
                record.filename_date,
            ]
        )
        if include_issues:
            values.append("; ".join(record.issues))
        # Location intentionally stops at the containing folder; filename is already shown.
        values.append(str(Path(record.path).parent))
        return tuple(values)

    def _render(self) -> None:
        self.library_tree.delete(*self.library_tree.get_children())
        self.library_map.clear()
        visible_records = [record for record in self.records if self._visible(record)]
        for index, record in enumerate(visible_records):
            tags = ("alternate",) if index % 2 else ()
            item = self.library_tree.insert(
                "",
                "end",
                values=self._row_values(record, False),
                tags=tags,
            )
            self.library_map[item] = record
        self._render_issues()
        self._update_summary(visible_records)

    def _render_issues(self) -> None:
        self.selected_review_paths.clear()
        self._review_selection_anchor = None
        self.issue_tree.delete(*self.issue_tree.get_children())
        self.issue_map.clear()
        selected_issue = self.issue_filter_var.get()
        count = 0
        for record in self.records:
            if not self._visible(record) or not record.issues:
                continue
            if selected_issue != "All review items" and selected_issue not in record.issues:
                continue
            tags = ("alternate",) if count % 2 else ()
            item = self.issue_tree.insert(
                "",
                "end",
                values=self._row_values(record, True),
                tags=tags,
            )
            self.issue_map[item] = record
            count += 1
        self.notebook.tab(1, text=f"Review ({count})" if count else "Review")
        self._update_selection_status()

    def _update_summary(self, visible_records: list[MediaRecord]) -> None:
        total = len(visible_records)
        images = sum(record.media_type == "image" for record in visible_records)
        videos = sum(record.media_type == "video" for record in visible_records)
        with_taken = sum(bool(record.taken) for record in visible_records)
        review_count = sum(bool(record.issues) for record in visible_records)
        prefix = "Filtered: " if self.search_var.get().strip() else ""
        self.summary_var.set(
            f"{prefix}{total} media files   |   {images} images   |   {videos} videos   |   "
            f"{with_taken} with capture metadata   |   {review_count} to review"
        )

    def _sort_tree(self, tree: ttk.Treeview, column: str) -> None:
        mapping = self.issue_map if tree is self.issue_tree else self.library_map
        key = id(tree)
        previous_column, previous_descending = self._sort_state.get(key, ("", False))
        descending = not previous_descending if previous_column == column else False

        items = [item for item in tree.get_children() if item in mapping]
        items.sort(
            key=lambda item: _record_sort_value(mapping[item], column),
            reverse=descending,
        )
        for index, item in enumerate(items):
            tree.move(item, "", index)
        self._sort_state[key] = (column, descending)

    def _on_review_click(self, event) -> Optional[str]:
        row = self.issue_tree.identify_row(event.y)
        column = self.issue_tree.identify_column(event.x)
        if not row:
            return None

        self.issue_tree.focus(row)
        items = tuple(self.issue_tree.get_children())
        shift = bool(event.state & _SHIFT_MASK)
        ctrl = bool(event.state & _CTRL_MASK)

        if column == "#1":
            if shift and self._review_selection_anchor:
                selected = _selection_range(items, self._review_selection_anchor, row)
                self.issue_tree.selection_set(selected)
            elif row in self.issue_tree.selection():
                self.issue_tree.selection_remove(row)
            else:
                self.issue_tree.selection_add(row)
                if self._review_selection_anchor is None:
                    self._review_selection_anchor = row
            self._sync_review_selection()
            return "break"

        # Handle row selection ourselves so Shift-click consistently uses the original anchor.
        if shift and self._review_selection_anchor:
            selected = _selection_range(items, self._review_selection_anchor, row)
            if ctrl:
                self.issue_tree.selection_add(selected)
            else:
                self.issue_tree.selection_set(selected)
            self._sync_review_selection()
            return "break"
        if ctrl:
            if row in self.issue_tree.selection():
                self.issue_tree.selection_remove(row)
            else:
                self.issue_tree.selection_add(row)
            self._review_selection_anchor = row
            self._sync_review_selection()
            return "break"

        self.issue_tree.selection_set(row)
        self._review_selection_anchor = row
        self._sync_review_selection()
        return "break"

    def _toggle_focused_review(self, _event=None) -> str:
        row = self.issue_tree.focus()
        if row:
            if row in self.issue_tree.selection():
                self.issue_tree.selection_remove(row)
            else:
                self.issue_tree.selection_add(row)
            if self._review_selection_anchor is None:
                self._review_selection_anchor = row
            self._sync_review_selection()
        return "break"

    def _sync_review_selection(self, _event=None) -> None:
        selected_items = set(self.issue_tree.selection())
        self.selected_review_paths = {
            self.issue_map[item].path for item in selected_items if item in self.issue_map
        }
        for item, record in self.issue_map.items():
            values = list(self.issue_tree.item(item, "values"))
            if not values:
                continue
            expected = "☑" if record.path in self.selected_review_paths else "☐"
            if values[0] != expected:
                values[0] = expected
                self.issue_tree.item(item, values=values)
        self._update_selection_status()

    def _update_selection_status(self) -> None:
        count = len(self.selected_review_paths)
        self.selection_var.set(f"{count} selected")
        self._update_action_state()

    def _update_action_state(self) -> None:
        method_selected = self.repair_method_var.get() in REPAIR_METHODS
        enabled = bool(self.selected_review_paths) and method_selected
        self.review_button.configure(state="normal" if enabled else "disabled")

    def _select_all_issues(self) -> None:
        items = self.issue_tree.get_children()
        if items:
            self.issue_tree.selection_set(items)
            self._review_selection_anchor = items[0]
        self._sync_review_selection()

    def _clear_review_selection(self) -> None:
        selected = self.issue_tree.selection()
        if selected:
            self.issue_tree.selection_remove(selected)
        self._review_selection_anchor = None
        self._sync_review_selection()

    def _show_context_menu(self, event, review: bool) -> None:
        tree = self.issue_tree if review else self.library_tree
        mapping = self.issue_map if review else self.library_map
        row = tree.identify_row(event.y)
        if not row or row not in mapping:
            return
        tree.focus(row)
        record = mapping[row]

        menu = Menu(self.root, tearoff=False)
        if review:
            if row in tree.selection():
                menu.add_command(
                    label="Remove from repair selection",
                    command=lambda item=row: self._remove_review_item(item),
                )
            else:
                menu.add_command(
                    label="Add to repair selection",
                    command=lambda item=row: self._add_review_item(item),
                )
            menu.add_command(
                label="Select only this file",
                command=lambda item=row: self._select_only_review_item(item),
            )
            menu.add_separator()
        else:
            tree.selection_set(row)

        menu.add_command(label="Open file", command=lambda rec=record: self._open_record(rec))
        menu.add_command(label="Show in Explorer", command=lambda rec=record: self._reveal_record(rec))
        menu.add_separator()
        menu.add_command(label="Copy full path", command=lambda rec=record: self._copy_path(rec))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _add_review_item(self, item: str) -> None:
        self.issue_tree.selection_add(item)
        self.issue_tree.focus(item)
        if self._review_selection_anchor is None:
            self._review_selection_anchor = item
        self._sync_review_selection()

    def _remove_review_item(self, item: str) -> None:
        self.issue_tree.selection_remove(item)
        self._sync_review_selection()

    def _select_only_review_item(self, item: str) -> None:
        self.issue_tree.selection_set(item)
        self.issue_tree.focus(item)
        self._review_selection_anchor = item
        self._sync_review_selection()

    def _selected_record(self) -> Optional[MediaRecord]:
        if self.notebook.index("current") == 1:
            selection = self.issue_tree.selection()
            if not selection:
                return None
            focused = self.issue_tree.focus()
            item = focused if focused in selection else selection[0]
            return self.issue_map.get(item)
        selection = self.library_tree.selection()
        return self.library_map.get(selection[0]) if selection else None

    def _open_record(self, record: MediaRecord) -> None:
        try:
            os.startfile(record.path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Open file", str(exc))

    def _reveal_record(self, record: MediaRecord) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", str(Path(record.path).resolve())])
        except OSError as exc:
            messagebox.showerror("Show in Explorer", str(exc))

    def _copy_path(self, record: MediaRecord) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(record.path)
        self.status_var.set(f"Copied path: {record.path}")

    def _open_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("Open file", "Select a file row first.")
            return
        self._open_record(record)

    def _collect_changes(
        self,
        target: str,
        source: str,
    ) -> tuple[
        list[tuple[MediaRecord, str, str]],
        list[MediaRecord],
        list[tuple[MediaRecord, str]],
    ]:
        if self.repair_service is None:
            return [], [], []

        records_by_path = {record.path: record for record in self.issue_map.values()}
        selected_records = [
            records_by_path[path]
            for path in self.selected_review_paths
            if path in records_by_path
        ]
        changes: list[tuple[MediaRecord, str, str]] = []
        unchanged: list[MediaRecord] = []
        unavailable: list[tuple[MediaRecord, str]] = []
        for record in selected_records:
            try:
                before, after = self.repair_service.preview_change(record, target, source)
            except ValueError as exc:
                unavailable.append((record, str(exc)))
                continue
            if before == after:
                unchanged.append(record)
            else:
                changes.append((record, before, after))
        return changes, unchanged, unavailable

    def review_selected_repair(self) -> None:
        method = REPAIR_METHODS.get(self.repair_method_var.get())
        if method is None or not self.selected_review_paths or self.repair_service is None:
            return

        target, source = method
        changes, unchanged, unavailable = self._collect_changes(target, source)
        if not changes:
            if unavailable:
                messagebox.showwarning(
                    "Nothing can be changed",
                    f"The selected method cannot be applied to {len(unavailable)} selected file(s).",
                )
            else:
                messagebox.showinfo(
                    "Nothing to change",
                    "The selected files already have the requested timestamp value.",
                )
            return

        if self._show_change_preview(target, source, changes, unchanged, unavailable):
            self._apply_changes(target, source, changes, unchanged, unavailable)

    def _show_change_preview(
        self,
        target: str,
        source: str,
        changes: list[tuple[MediaRecord, str, str]],
        unchanged: list[MediaRecord],
        unavailable: list[tuple[MediaRecord, str]],
    ) -> bool:
        dialog = Toplevel(self.root)
        dialog.title("Review timestamp changes")
        dialog.transient(self.root)
        dialog.resizable(True, True)
        dialog.geometry("760x500")
        dialog.minsize(620, 420)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(3, weight=1)

        content = ttk.Frame(dialog, padding=(18, 16))
        content.grid(row=0, column=0, rowspan=5, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(3, weight=1)

        ttk.Label(content, text="Review timestamp changes", style="DialogTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            content,
            text=f"{TARGET_LABELS[target]}  ←  {SOURCE_LABELS[source]}",
            style="Summary.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(5, 2))

        summary_parts = [f"{len(changes)} will change"]
        if unchanged:
            summary_parts.append(f"{len(unchanged)} already match")
        if unavailable:
            summary_parts.append(f"{len(unavailable)} unavailable")
        ttk.Label(content, text="  ·  ".join(summary_parts), style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 10)
        )

        preview_frame = ttk.Frame(content)
        preview_frame.grid(row=3, column=0, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        preview = ttk.Treeview(
            preview_frame,
            columns=("file", "before", "after"),
            show="headings",
            selectmode="none",
        )
        preview.heading("file", text="File")
        preview.heading("before", text="Before")
        preview.heading("after", text="After")
        preview.column("file", width=280, stretch=True)
        preview.column("before", width=180, stretch=False)
        preview.column("after", width=180, stretch=False)
        preview.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(preview_frame, orient="vertical", command=preview.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        preview.configure(yscrollcommand=scrollbar.set)

        for record, before, after in changes[:_PREVIEW_ROWS]:
            preview.insert("", "end", values=(record.name, before, after))

        if len(changes) > _PREVIEW_ROWS:
            ttk.Label(
                content,
                text=f"Showing the first {_PREVIEW_ROWS} of {len(changes):,} changes.",
                style="Muted.TLabel",
            ).grid(row=4, column=0, sticky="w", pady=(6, 0))

        backup_on = self.backup_enabled_var.get()
        safety_text = (
            "Backup copies will be created before writing. Existing backups are not overwritten."
            if backup_on
            else "WARNING: Backup is OFF. Files will be changed in place with no recovery copy created by this app."
        )
        ttk.Label(
            content,
            text=safety_text,
            style="Muted.TLabel" if backup_on else "DangerHint.TLabel",
            wraplength=700,
        ).grid(row=5, column=0, sticky="w", pady=(12, 8))
        ttk.Label(
            content,
            text="Every attempted change is still recorded in the CSV repair log.",
            style="Muted.TLabel",
        ).grid(row=6, column=0, sticky="w", pady=(0, 12))

        result = {"apply": False}
        buttons = ttk.Frame(content)
        buttons.grid(row=7, column=0, sticky="e")

        def approve() -> None:
            result["apply"] = True
            dialog.destroy()

        ttk.Button(buttons, text="Cancel", command=dialog.destroy).grid(row=0, column=0, padx=(0, 7))
        ttk.Button(
            buttons,
            text=f"Apply {len(changes):,} change" + ("" if len(changes) == 1 else "s"),
            command=approve,
            style="Primary.TButton",
        ).grid(row=0, column=1)

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        dialog.wait_window()
        return result["apply"]

    def _apply_changes(
        self,
        target: str,
        source: str,
        changes: list[tuple[MediaRecord, str, str]],
        unchanged: list[MediaRecord],
        unavailable: list[tuple[MediaRecord, str]],
    ) -> None:
        if self.repair_service is None:
            return

        create_backup = self.backup_enabled_var.get()
        successes = 0
        failures: list[str] = []
        replacements: dict[str, MediaRecord] = {}

        for record, _, _ in changes:
            try:
                self.repair_service.apply(
                    record,
                    target,
                    source,
                    create_backup=create_backup,
                )
                # Immediately rescan the changed file so all displayed columns reflect disk state.
                replacements[record.path] = scan_file(Path(record.path))
                successes += 1
            except Exception as exc:
                failures.append(f"{record.name}: {exc}")

        if replacements:
            self.records = [replacements.get(record.path, record) for record in self.records]

        self.repair_method_var.set(REPAIR_PLACEHOLDER)
        self._render()
        self._load_log()

        skipped = len(unchanged) + len(unavailable)
        if failures:
            preview = "\n".join(failures[:5])
            if len(failures) > 5:
                preview += f"\n…and {len(failures) - 5} more."
            messagebox.showwarning(
                "Repair completed with errors",
                f"Updated {successes} file(s). Skipped {skipped}.\n\n{preview}",
            )
        else:
            suffix = f" Skipped {skipped}." if skipped else ""
            messagebox.showinfo("Repair complete", f"Updated {successes} file(s).{suffix}")

    def _load_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if self.repair_service is None or not self.repair_service.log_path.exists():
            self.log_text.insert("end", "No repairs have been recorded for this folder.\n")
        else:
            try:
                self.log_text.insert("end", self.repair_service.log_path.read_text(encoding="utf-8"))
            except OSError as exc:
                self.log_text.insert("end", f"Could not read repair log: {exc}\n")
        self.log_text.configure(state="disabled")

    def _on_close(self) -> None:
        if self._scan_cancel_event is not None:
            self._scan_cancel_event.set()
        self.root.destroy()


def main() -> None:
    if not sys.platform.startswith("win"):
        raise SystemExit("Photo Metadata Repair Inspector currently runs on Windows only.")

    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    root = Tk()
    PhotoRepairApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
