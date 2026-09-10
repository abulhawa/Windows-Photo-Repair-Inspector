"""Tkinter desktop application for inspecting and repairing media timestamps."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import StringVar, Text, Tk, filedialog, messagebox, ttk
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

        self.status_var = StringVar(value="Choose a folder to inspect photo and media timestamps.")
        self.summary_var = StringVar(value="No collection loaded")
        self.scan_progress_var = StringVar(value="")
        self.selection_var = StringVar(value="0 files selected")
        self.media_filter_var = StringVar(value="All")
        self.issue_filter_var = StringVar(value=REVIEW_FILTERS[0])
        self.repair_method_var = StringVar(value=REPAIR_PLACEHOLDER)

        self._configure_styles()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")

        default_font = ("Segoe UI", 10)
        self.root.option_add("*Font", default_font)

        style.configure("TButton", padding=(10, 6))
        style.configure("TCombobox", padding=3)
        style.configure("TNotebook.Tab", padding=(14, 7))
        style.configure("Treeview", rowheight=29, font=default_font)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10), padding=(6, 7))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 17))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 9))
        style.configure("Summary.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("ProgressText.TLabel", font=("Segoe UI", 9))
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Footer.TLabel", font=("Segoe UI", 9))
        style.configure("Apply.TButton", font=("Segoe UI Semibold", 10), padding=(14, 7))

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=(18, 16, 18, 12))
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        title_block = ttk.Frame(header)
        title_block.grid(row=0, column=0, sticky="w")
        ttk.Label(title_block, text="Photo Metadata Repair Inspector", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(title_block, textvariable=self.status_var, style="Subtitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        self.scan_button = ttk.Button(controls, text="Scan Folder…", command=self.request_directory)
        self.scan_button.grid(row=0, column=0, padx=(0, 6))
        self.stop_button = ttk.Button(
            controls, text="Stop", command=self.stop_scan, state="disabled"
        )
        self.stop_button.grid(row=0, column=1, padx=(0, 14))
        ttk.Label(controls, text="Media").grid(row=0, column=2, padx=(0, 6))
        media_filter = ttk.Combobox(
            controls,
            textvariable=self.media_filter_var,
            values=("All", "Images", "Videos"),
            width=10,
            state="readonly",
        )
        media_filter.grid(row=0, column=3)
        media_filter.bind("<<ComboboxSelected>>", lambda _: self._render())

        summary_bar = ttk.Frame(container, padding=(0, 2, 0, 2))
        summary_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        summary_bar.columnconfigure(0, weight=1)
        ttk.Label(summary_bar, textvariable=self.summary_var, style="Summary.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            summary_bar,
            textvariable=self.scan_progress_var,
            style="ProgressText.TLabel",
        ).grid(row=0, column=1, sticky="e")

        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.progress.grid_remove()

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=3, column=0, sticky="nsew")

        library_tab = ttk.Frame(self.notebook, padding=(8, 10, 8, 8))
        review_tab = ttk.Frame(self.notebook, padding=(8, 10, 8, 8))
        log_tab = ttk.Frame(self.notebook, padding=(8, 10, 8, 8))
        self.notebook.add(library_tab, text="Library")
        self.notebook.add(review_tab, text="Review")
        self.notebook.add(log_tab, text="Repair Log")

        library_tab.columnconfigure(0, weight=1)
        library_tab.rowconfigure(0, weight=1)
        self.library_tree = self._build_tree(library_tab, include_issues=False, row=0)

        review_tab.columnconfigure(0, weight=1)
        review_tab.rowconfigure(2, weight=1)

        review_controls = ttk.Frame(review_tab)
        review_controls.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        review_controls.columnconfigure(2, weight=1)
        ttk.Label(review_controls, text="Show", style="Section.TLabel").grid(
            row=0, column=0, padx=(0, 6)
        )
        review_filter = ttk.Combobox(
            review_controls,
            textvariable=self.issue_filter_var,
            values=REVIEW_FILTERS,
            width=22,
            state="readonly",
        )
        review_filter.grid(row=0, column=1, padx=(0, 14))
        review_filter.bind("<<ComboboxSelected>>", lambda _: self._render_issues())
        ttk.Label(
            review_controls,
            text="Only conditions worth checking or repairing are listed here.",
            style="Subtitle.TLabel",
        ).grid(row=0, column=2, sticky="w")
        ttk.Label(review_controls, textvariable=self.selection_var, style="Summary.TLabel").grid(
            row=0, column=3, sticky="e"
        )

        selection_help = ttk.Frame(review_tab)
        selection_help.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        selection_help.columnconfigure(0, weight=1)
        ttk.Label(
            selection_help,
            text="Select files with the checkbox in the first column. Ctrl/Shift is not required.",
            style="Subtitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            selection_help, text="Select all visible", command=self._select_all_issues
        ).grid(row=0, column=1, padx=(8, 6))
        ttk.Button(
            selection_help, text="Clear selection", command=self._clear_review_selection
        ).grid(row=0, column=2)

        self.issue_tree = self._build_tree(
            review_tab, include_issues=True, row=2, checkboxes=True
        )
        self.issue_tree.bind("<Button-1>", self._on_review_click, add="+")
        self.issue_tree.bind("<space>", self._toggle_focused_review)
        self.issue_tree.bind("<Double-1>", lambda _: self._open_selected())

        repair_bar = ttk.LabelFrame(review_tab, text="Repair selected files", padding=(12, 10))
        repair_bar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        repair_bar.columnconfigure(1, weight=1)
        ttk.Label(repair_bar, text="Repair method", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.repair_method = ttk.Combobox(
            repair_bar,
            textvariable=self.repair_method_var,
            values=tuple(REPAIR_METHODS),
            state="readonly",
            width=34,
        )
        self.repair_method.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.repair_method.bind("<<ComboboxSelected>>", lambda _: self._update_apply_state())
        self.apply_button = ttk.Button(
            repair_bar,
            text="Apply repair",
            command=self.apply_selected_repair,
            style="Apply.TButton",
            state="disabled",
        )
        self.apply_button.grid(row=0, column=2, padx=(0, 18))
        ttk.Separator(repair_bar, orient="vertical").grid(
            row=0, column=3, sticky="ns", padx=(0, 14)
        )
        ttk.Button(repair_bar, text="Open file", command=self._open_selected).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(repair_bar, text="Show in Explorer", command=self._reveal_selected).grid(
            row=0, column=5
        )

        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(0, weight=1)
        self.log_text = Text(
            log_tab, wrap="none", font=("Consolas", 9), borderwidth=0, padx=10, pady=10
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

        ttk.Label(
            container,
            text=(
                "Original files are backed up before repair. Every attempted change is recorded "
                "in the CSV repair log."
            ),
            style="Footer.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=(9, 0))

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

        tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
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
        for record in visible_records:
            item = self.library_tree.insert("", "end", values=self._row_values(record, False))
            self.library_map[item] = record
        self._render_issues()
        self._update_summary(visible_records)

    def _render_issues(self) -> None:
        self.selected_review_paths.clear()
        self.issue_tree.delete(*self.issue_tree.get_children())
        self.issue_map.clear()
        selected_issue = self.issue_filter_var.get()
        count = 0
        for record in self.records:
            if not self._media_matches(record) or not record.issues:
                continue
            if selected_issue != "All review items" and selected_issue not in record.issues:
                continue
            item = self.issue_tree.insert(
                "", "end", values=self._row_values(record, True, checked=False)
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
        row = self.issue_tree.identify_row(event.y)
        column = self.issue_tree.identify_column(event.x)
        if not row:
            return None
        self.issue_tree.selection_set(row)
        self.issue_tree.focus(row)
        if column == "#1":
            self._toggle_review_item(row)
            return "break"
        return None

    def _toggle_focused_review(self, _event=None) -> str:
        row = self.issue_tree.focus()
        if row:
            self._toggle_review_item(row)
        return "break"

    def _toggle_review_item(self, item: str) -> None:
        record = self.issue_map.get(item)
        if record is None:
            return
        if record.path in self.selected_review_paths:
            self.selected_review_paths.remove(record.path)
        else:
            self.selected_review_paths.add(record.path)
        values = list(self.issue_tree.item(item, "values"))
        if values:
            values[0] = "☑" if record.path in self.selected_review_paths else "☐"
            self.issue_tree.item(item, values=values)
        self._update_selection_status()

    def _update_selection_status(self) -> None:
        count = len(self.selected_review_paths)
        self.selection_var.set(f"{count} file selected" if count == 1 else f"{count} files selected")
        self._update_apply_state()

    def _update_apply_state(self) -> None:
        method_selected = self.repair_method_var.get() in REPAIR_METHODS
        enabled = bool(self.selected_review_paths) and method_selected
        self.apply_button.configure(state="normal" if enabled else "disabled")

    def _select_all_issues(self) -> None:
        self.selected_review_paths = {record.path for record in self.issue_map.values()}
        for item in self.issue_map:
            values = list(self.issue_tree.item(item, "values"))
            if values:
                values[0] = "☑"
                self.issue_tree.item(item, values=values)
        self._update_selection_status()

    def _clear_review_selection(self) -> None:
        self.selected_review_paths.clear()
        for item in self.issue_map:
            values = list(self.issue_tree.item(item, "values"))
            if values:
                values[0] = "☐"
                self.issue_tree.item(item, values=values)
        self._update_selection_status()

    def _selected_record(self) -> Optional[MediaRecord]:
        if self.notebook.index("current") == 1:
            selection = self.issue_tree.selection()
            return self.issue_map.get(selection[0]) if selection else None
        selection = self.library_tree.selection()
        return self.library_map.get(selection[0]) if selection else None

    def _open_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("Open file", "Click a file row first.")
            return
        try:
            os.startfile(record.path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Open file", str(exc))

    def _reveal_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("Show in Explorer", "Click a file row first.")
            return
        try:
            subprocess.Popen(["explorer", "/select,", str(Path(record.path).resolve())])
        except OSError as exc:
            messagebox.showerror("Show in Explorer", str(exc))

    def apply_selected_repair(self) -> None:
        method_label = self.repair_method_var.get()
        method = REPAIR_METHODS.get(method_label)
        if method is None:
            messagebox.showinfo("Repair timestamps", "Choose a repair method first.")
            return
        if not self.selected_review_paths:
            messagebox.showinfo(
                "Repair timestamps",
                "Select one or more files using the checkbox in the first column.",
            )
            return
        if self.repair_service is None:
            return

        target, source = method
        records_by_path = {record.path: record for record in self.issue_map.values()}
        records = [
            records_by_path[path]
            for path in self.selected_review_paths
            if path in records_by_path
        ]
        if not records:
            messagebox.showinfo(
                "Repair timestamps",
                "The selected files are no longer visible. Select them again.",
            )
            self._clear_review_selection()
            return

        confirmed = messagebox.askyesno(
            "Confirm repair",
            (
                f"{method_label}\n\n"
                f"Files selected: {len(records)}\n\n"
                "An original copy of each file will be preserved under "
                ".photo-repair-backups before any write.\n\n"
                "Apply this repair?"
            ),
        )
        if not confirmed:
            return

        successes = 0
        failures: list[str] = []
        replacements: dict[str, MediaRecord] = {}
        for record in records:
            try:
                self.repair_service.apply(record, target, source)
                replacements[record.path] = scan_file(Path(record.path))
                successes += 1
            except Exception as exc:
                failures.append(f"{record.name}: {exc}")

        if replacements:
            self.records = [replacements.get(record.path, record) for record in self.records]
        self.repair_method_var.set(REPAIR_PLACEHOLDER)
        self._render()
        self._load_log()

        if failures:
            preview = "\n".join(failures[:6])
            if len(failures) > 6:
                preview += f"\n…and {len(failures) - 6} more."
            messagebox.showwarning(
                "Repair completed with errors",
                f"Updated {successes} file(s).\n\n{preview}",
            )
        else:
            messagebox.showinfo("Repair complete", f"Updated {successes} file(s).")

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
