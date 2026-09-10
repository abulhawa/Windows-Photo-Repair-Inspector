"""Tkinter desktop application for inspecting and repairing media timestamps."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import BooleanVar, Menu, StringVar, Text, Tk, filedialog, messagebox, ttk
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

# Tk uses these modifier bits for mouse events on Windows.
_SHIFT_MASK = 0x0001
_CTRL_MASK = 0x0004


def _selection_range(items: tuple[str, ...], anchor: str, target: str) -> tuple[str, ...]:
    """Return the inclusive range between two Treeview item ids."""
    if anchor not in items or target not in items:
        return (target,) if target in items else ()
    start = items.index(anchor)
    end = items.index(target)
    if start > end:
        start, end = end, start
    return items[start : end + 1]


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

        self.status_var = StringVar(value="Choose a folder to inspect photo and media timestamps.")
        self.summary_var = StringVar(value="No collection loaded")
        self.scan_progress_var = StringVar(value="")
        self.selection_var = StringVar(value="0 files selected")
        self.repair_summary_var = StringVar(value="Select files and choose a repair method.")
        self.media_filter_var = StringVar(value="All")
        self.issue_filter_var = StringVar(value=REVIEW_FILTERS[0])
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

        style.configure("TButton", padding=(10, 6))
        style.configure("TCombobox", padding=3)
        style.configure("TNotebook", borderwidth=1)
        style.configure("TNotebook.Tab", padding=(15, 8))
        style.configure("Treeview", rowheight=30, font=default_font)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10), padding=(7, 8))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 18))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 9))
        style.configure("Summary.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("ProgressText.TLabel", font=("Segoe UI", 9))
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Footer.TLabel", font=("Segoe UI", 9))
        style.configure("RepairHint.TLabel", font=("Segoe UI", 9))
        style.configure("Apply.TButton", font=("Segoe UI Semibold", 10), padding=(16, 8))

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=(18, 16, 18, 12))
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        header = ttk.Frame(container, padding=(16, 13), relief="solid", borderwidth=1)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        title_block = ttk.Frame(header)
        title_block.grid(row=0, column=0, sticky="w")
        ttk.Label(title_block, text="Photo Metadata Repair Inspector", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(title_block, textvariable=self.status_var, style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 0)
        )

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, sticky="e")
        self.scan_button = ttk.Button(controls, text="Scan Folder…", command=self.request_directory)
        self.scan_button.grid(row=0, column=0, padx=(0, 6))
        self.stop_button = ttk.Button(
            controls, text="Stop", command=self.stop_scan, state="disabled"
        )
        self.stop_button.grid(row=0, column=1, padx=(0, 18))
        ttk.Separator(controls, orient="vertical").grid(
            row=0, column=2, sticky="ns", padx=(0, 18)
        )
        ttk.Label(controls, text="Media", style="Section.TLabel").grid(
            row=0, column=3, padx=(0, 6)
        )
        media_filter = ttk.Combobox(
            controls,
            textvariable=self.media_filter_var,
            values=("All", "Images", "Videos"),
            width=10,
            state="readonly",
        )
        media_filter.grid(row=0, column=4)
        media_filter.bind("<<ComboboxSelected>>", lambda _: self._render())

        summary_panel = ttk.Frame(container, padding=(13, 9), relief="solid", borderwidth=1)
        summary_panel.grid(row=1, column=0, sticky="ew", pady=(0, 9))
        summary_panel.columnconfigure(0, weight=1)
        ttk.Label(summary_panel, textvariable=self.summary_var, style="Summary.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            summary_panel,
            textvariable=self.scan_progress_var,
            style="ProgressText.TLabel",
        ).grid(row=0, column=1, sticky="e")

        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(0, 9))
        self.progress.grid_remove()

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=3, column=0, sticky="nsew")

        library_tab = ttk.Frame(self.notebook, padding=(10, 12, 10, 10))
        review_tab = ttk.Frame(self.notebook, padding=(10, 12, 10, 10))
        log_tab = ttk.Frame(self.notebook, padding=(10, 12, 10, 10))
        self.notebook.add(library_tab, text="Library")
        self.notebook.add(review_tab, text="Review")
        self.notebook.add(log_tab, text="Repair Log")

        library_tab.columnconfigure(0, weight=1)
        library_tab.rowconfigure(0, weight=1)
        self.library_tree = self._build_tree(library_tab, include_issues=False, row=0)
        self.library_tree.bind("<Button-3>", lambda event: self._show_context_menu(event, False))

        review_tab.columnconfigure(0, weight=1)
        review_tab.rowconfigure(1, weight=1)

        review_tools = ttk.LabelFrame(review_tab, text="Review and selection", padding=(12, 10))
        review_tools.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        review_tools.columnconfigure(3, weight=1)
        ttk.Label(review_tools, text="Show", style="Section.TLabel").grid(
            row=0, column=0, padx=(0, 6)
        )
        review_filter = ttk.Combobox(
            review_tools,
            textvariable=self.issue_filter_var,
            values=REVIEW_FILTERS,
            width=22,
            state="readonly",
        )
        review_filter.grid(row=0, column=1, padx=(0, 14))
        review_filter.bind("<<ComboboxSelected>>", lambda _: self._render_issues())
        ttk.Label(
            review_tools,
            text="Use checkboxes, Ctrl-click, or Shift-click to select multiple files.",
            style="Subtitle.TLabel",
        ).grid(row=0, column=2, sticky="w")
        ttk.Label(review_tools, textvariable=self.selection_var, style="Summary.TLabel").grid(
            row=0, column=3, sticky="e", padx=(14, 10)
        )
        ttk.Button(review_tools, text="Select all", command=self._select_all_issues).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(review_tools, text="Clear selection", command=self._clear_review_selection).grid(
            row=0, column=5
        )

        self.issue_tree = self._build_tree(
            review_tab, include_issues=True, row=1, checkboxes=True
        )
        self.issue_tree.bind("<Button-1>", self._on_review_click)
        self.issue_tree.bind("<<TreeviewSelect>>", self._sync_review_selection)
        self.issue_tree.bind("<space>", self._toggle_focused_review)
        self.issue_tree.bind("<Double-1>", lambda _: self._open_selected())
        self.issue_tree.bind("<Button-3>", lambda event: self._show_context_menu(event, True))

        repair_panel = ttk.LabelFrame(review_tab, text="Repair selected files", padding=(14, 11))
        repair_panel.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        repair_panel.columnconfigure(1, weight=1)

        ttk.Label(repair_panel, text="Repair method", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.repair_method = ttk.Combobox(
            repair_panel,
            textvariable=self.repair_method_var,
            values=tuple(REPAIR_METHODS),
            state="readonly",
            width=34,
        )
        self.repair_method.grid(row=0, column=1, sticky="w", padx=(0, 12))
        self.repair_method.bind("<<ComboboxSelected>>", lambda _: self._update_repair_state())
        self.apply_button = ttk.Button(
            repair_panel,
            text="Apply repair",
            command=self.apply_selected_repair,
            style="Apply.TButton",
            state="disabled",
        )
        self.apply_button.grid(row=0, column=2, padx=(0, 18))
        ttk.Separator(repair_panel, orient="vertical").grid(
            row=0, column=3, rowspan=3, sticky="ns", padx=(0, 14)
        )
        ttk.Button(repair_panel, text="Open file", command=self._open_selected).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(repair_panel, text="Show in Explorer", command=self._reveal_selected).grid(
            row=0, column=5
        )
        ttk.Checkbutton(
            repair_panel,
            text="Create backup before repair (recommended)",
            variable=self.backup_enabled_var,
            command=self._update_repair_state,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(
            repair_panel,
            textvariable=self.repair_summary_var,
            style="RepairHint.TLabel",
        ).grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(0, weight=1)
        self.log_text = Text(
            log_tab,
            wrap="none",
            font=("Consolas", 9),
            borderwidth=1,
            relief="solid",
            padx=10,
            pady=10,
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

        footer = ttk.Frame(container, padding=(10, 7), relief="solid", borderwidth=1)
        footer.grid(row=4, column=0, sticky="ew", pady=(9, 0))
        ttk.Label(
            footer,
            text=(
                "Backups are optional and enabled by default. Every attempted change is recorded "
                "in the CSV repair log."
            ),
            style="Footer.TLabel",
        ).grid(row=0, column=0, sticky="w")

    def _build_tree(
        self,
        parent: ttk.Frame,
        include_issues: bool,
        row: int = 0,
        *,
        checkboxes: bool = False,
    ) -> ttk.Treeview:
        table = ttk.Frame(parent, relief="solid", borderwidth=1)
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
            "selected": 58,
            "name": 245,
            "type": 70,
            "size": 90,
            "created": 150,
            "modified": 150,
            "taken": 150,
            "filename": 150,
            "issues": 210,
            "path": 360,
        }
        anchors = {"selected": "center", "size": "e"}
        for column in columns:
            tree.heading(column, text=headings[column])
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

    def _scan_worker(
        self, generation: int, root: Path, cancel_event: threading.Event
    ) -> None:
        def report_progress(completed: int, total: int) -> None:
            try:
                self.root.after(
                    0,
                    lambda c=completed, t=total: self._update_scan_progress(generation, c, t),
                )
            except RuntimeError:
                pass

        records = scan_directory(
            root, cancel_event=cancel_event, progress_callback=report_progress
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
            if total:
                self.summary_var.set(f"Found {total:,} supported media files. Reading metadata…")
                self.scan_progress_var.set(f"0 / {total:,}  ·  starting metadata scan")
            else:
                self.summary_var.set("No supported media files found")
                self.scan_progress_var.set("")
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
        cancel_event = self._scan_cancel_event
        if cancel_event is not None and cancel_event.is_set():
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
            self.status_var.set("Scan stopped before metadata processing completed. Previous results kept.")
            self.scan_progress_var.set(f"Stopped after {self._format_duration(elapsed)}")
            return

        self.scan_root = root
        self.repair_service = RepairService(root)
        self.records = records
        self._render()
        self._load_log()
        if cancelled:
            total = self._scan_total
            completed = self._scan_completed
            self.status_var.set(f"Scan stopped. Partial results from {root}")
            if total:
                self.scan_progress_var.set(
                    f"Stopped at {completed:,} / {total:,}  ·  {self._format_duration(elapsed)} elapsed"
                )
            else:
                self.scan_progress_var.set(f"Stopped after {self._format_duration(elapsed)}")
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

    def _row_values(
        self, record: MediaRecord, include_issues: bool, *, checked: bool = False
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
        values.append(record.path)
        return tuple(values)

    def _render(self) -> None:
        self.library_tree.delete(*self.library_tree.get_children())
        self.library_map.clear()
        visible_records = [record for record in self.records if self._media_matches(record)]
        for index, record in enumerate(visible_records):
            tags = ("alternate",) if index % 2 else ()
            item = self.library_tree.insert(
                "", "end", values=self._row_values(record, False), tags=tags
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
            if not self._media_matches(record) or not record.issues:
                continue
            if selected_issue != "All review items" and selected_issue not in record.issues:
                continue
            tags = ("alternate",) if count % 2 else ()
            item = self.issue_tree.insert(
                "", "end", values=self._row_values(record, True, checked=False), tags=tags
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
        self.summary_var.set(
            f"{total} media files   |   {images} images   |   {videos} videos   |   "
            f"{with_taken} with capture metadata   |   {review_count} to review"
        )

    def _on_review_click(self, event) -> Optional[str]:
        """Implement predictable checkbox, Ctrl-click and Shift-click selection."""
        row = self.issue_tree.identify_row(event.y)
        if not row:
            return None

        column = self.issue_tree.identify_column(event.x)
        items = tuple(self.issue_tree.get_children())
        selected = set(self.issue_tree.selection())
        shift = bool(event.state & _SHIFT_MASK)
        ctrl = bool(event.state & _CTRL_MASK)

        self.issue_tree.focus(row)

        # Clicking the checkbox toggles exactly that row without disturbing the rest.
        if column == "#1":
            if row in selected:
                self.issue_tree.selection_remove(row)
            else:
                self.issue_tree.selection_add(row)
            self._review_selection_anchor = row
            self._sync_review_selection()
            return "break"

        # Explicitly implement range selection rather than relying on Tk's internal
        # anchor, because our checkbox behaviour otherwise makes Shift-click erratic.
        if shift:
            anchor = self._review_selection_anchor
            if anchor not in items:
                current = self.issue_tree.selection()
                anchor = current[0] if current else row
            range_items = _selection_range(items, anchor, row)
            if ctrl:
                for item in range_items:
                    self.issue_tree.selection_add(item)
            else:
                self.issue_tree.selection_set(range_items)
            self._sync_review_selection()
            return "break"

        if ctrl:
            if row in selected:
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
        self.selection_var.set(f"{count} file selected" if count == 1 else f"{count} files selected")
        self._update_repair_state()

    def _update_repair_state(self) -> None:
        method_label = self.repair_method_var.get()
        method = REPAIR_METHODS.get(method_label)
        count = len(self.selected_review_paths)
        enabled = bool(count) and method is not None
        self.apply_button.configure(state="normal" if enabled else "disabled")
        backup_note = "backup on" if self.backup_enabled_var.get() else "backup OFF"

        if method is None and count == 0:
            self.repair_summary_var.set(f"Select files and choose a repair method. {backup_note}.")
        elif method is None:
            self.repair_summary_var.set(
                f"{count} selected. Choose the timestamp change to apply. {backup_note}."
            )
        elif count == 0:
            target, source = method
            self.repair_summary_var.set(
                f"Ready method: {TARGET_LABELS[target]} ← {SOURCE_LABELS[source]}. "
                f"Select files to continue. {backup_note}."
            )
        else:
            target, source = method
            noun = "file" if count == 1 else "files"
            self.repair_summary_var.set(
                f"Ready: {TARGET_LABELS[target]} ← {SOURCE_LABELS[source]} for {count} {noun}; "
                f"{backup_note}."
            )

    def _select_all_issues(self) -> None:
        items = self.issue_tree.get_children()
        if items:
            self.issue_tree.selection_set(items)
            self._review_selection_anchor = items[0]
            self._sync_review_selection()

    def _clear_review_selection(self) -> None:
        items = self.issue_tree.selection()
        if items:
            self.issue_tree.selection_remove(items)
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
        menu.add_command(
            label="Show in Explorer", command=lambda rec=record: self._reveal_record(rec)
        )
        menu.add_separator()
        menu.add_command(label="Copy full path", command=lambda rec=record: self._copy_path(rec))

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _add_review_item(self, item: str) -> None:
        self.issue_tree.selection_add(item)
        self.issue_tree.focus(item)
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
            if selection:
                focused = self.issue_tree.focus()
                item = focused if focused in selection else selection[0]
                return self.issue_map.get(item)
            return None
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

    def _reveal_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("Show in Explorer", "Select a file row first.")
            return
        self._reveal_record(record)

    def apply_selected_repair(self) -> None:
        method_label = self.repair_method_var.get()
        method = REPAIR_METHODS.get(method_label)
        if method is None:
            messagebox.showinfo("Repair timestamps", "Choose a repair method first.")
            return
        if not self.selected_review_paths:
            messagebox.showinfo(
                "Repair timestamps",
                "Select one or more files using checkboxes, Ctrl-click, or Shift-click.",
            )
            return
        if self.repair_service is None:
            return

        target, source = method
        records_by_path = {record.path: record for record in self.issue_map.values()}
        selected_records = [
            records_by_path[path]
            for path in self.selected_review_paths
            if path in records_by_path
        ]
        if not selected_records:
            messagebox.showinfo(
                "Repair timestamps",
                "The selected files are no longer in the current Review list. Select them again.",
            )
            self._clear_review_selection()
            return

        changes: list[tuple[MediaRecord, str, str]] = []
        unavailable: list[tuple[MediaRecord, str]] = []
        unchanged: list[MediaRecord] = []
        for record in selected_records:
            try:
                before, after = self.repair_service.preview_change(record, target, source)
            except ValueError as exc:
                unavailable.append((record, str(exc)))
                continue
            if before == after:
                unchanged.append(record)
                continue
            changes.append((record, before, after))

        if not changes:
            if unavailable:
                preview = "\n".join(
                    f"• {record.name}: {reason}" for record, reason in unavailable[:5]
                )
                messagebox.showwarning(
                    "Nothing can be changed",
                    "The selected repair method cannot be applied to these files.\n\n" + preview,
                )
            else:
                messagebox.showinfo(
                    "Nothing to change",
                    "The selected files already have the requested timestamp value.",
                )
            return

        target_label = TARGET_LABELS[target]
        source_label = SOURCE_LABELS[source]
        create_backup = self.backup_enabled_var.get()
        lines = [
            "You are about to modify file timestamps.",
            "",
            f"Action: {target_label} ← {source_label}",
            f"Files selected: {len(selected_records)}",
            f"Files that will change: {len(changes)}",
        ]
        if unchanged:
            lines.append(f"Already matching and skipped: {len(unchanged)}")
        if unavailable:
            lines.append(f"Cannot use this method and skipped: {len(unavailable)}")

        lines.extend(["", "Examples:"])
        for record, before, after in changes[:4]:
            lines.append(f"• {record.name}")
            lines.append(f"  {before}  →  {after}")
        if len(changes) > 4:
            lines.append(f"• …and {len(changes) - 4} more")

        lines.extend(["", "Each changed file is modified in place."])
        if create_backup:
            lines.append("Backup: ON. The original is saved under .photo-repair-backups before writing.")
        else:
            lines.extend(
                [
                    "BACKUP: OFF.",
                    "No recovery copy will be created by this application before these files are changed.",
                ]
            )
        lines.extend(
            [
                "Every attempted change is recorded in the CSV repair log.",
                "",
                "Continue?",
            ]
        )

        confirmed = messagebox.askyesno(
            "Confirm timestamp repair",
            "\n".join(lines),
            icon="warning",
            default="no",
        )
        if not confirmed:
            return

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
                replacements[record.path] = scan_file(Path(record.path))
                successes += 1
            except Exception as exc:
                failures.append(f"{record.name}: {exc}")

        if replacements:
            self.records = [replacements.get(record.path, record) for record in self.records]
        self.repair_method_var.set(REPAIR_PLACEHOLDER)
        self._render()
        self._load_log()

        skipped_count = len(unchanged) + len(unavailable)
        backup_suffix = "" if create_backup else " No backups were created."
        if failures:
            preview = "\n".join(failures[:6])
            if len(failures) > 6:
                preview += f"\n…and {len(failures) - 6} more."
            messagebox.showwarning(
                "Repair completed with errors",
                f"Updated {successes} file(s). Skipped {skipped_count}.{backup_suffix}\n\n{preview}",
            )
        else:
            skipped_suffix = f" Skipped {skipped_count}." if skipped_count else ""
            messagebox.showinfo(
                "Repair complete",
                f"Updated {successes} file(s).{skipped_suffix}{backup_suffix}",
            )

    def _load_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        if self.repair_service is None or not self.repair_service.log_path.exists():
            self.log_text.insert("end", "No repairs have been recorded for this folder.\n")
        else:
            try:
                self.log_text.insert(
                    "end", self.repair_service.log_path.read_text(encoding="utf-8")
                )
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
