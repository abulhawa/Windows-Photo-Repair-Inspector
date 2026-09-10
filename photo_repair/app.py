"""Tkinter desktop application for inspecting and repairing media timestamps."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import Menu, StringVar, Text, Tk, filedialog, messagebox, ttk
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


class PhotoRepairApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Photo Metadata Repair Inspector")
        self.root.geometry("1450x820")
        self.root.minsize(1080, 640)

        self.records: list[MediaRecord] = []
        self.library_map: dict[str, MediaRecord] = {}
        self.issue_map: dict[str, MediaRecord] = {}
        self.scan_root: Optional[Path] = None
        self.repair_service: Optional[RepairService] = None
        self._scan_generation = 0

        self.status_var = StringVar(value="Choose a folder to inspect photo and media timestamps.")
        self.summary_var = StringVar(value="No collection loaded")
        self.selection_var = StringVar(value="No files selected")
        self.media_filter_var = StringVar(value="All")
        self.issue_filter_var = StringVar(value=REVIEW_FILTERS[0])

        self._configure_styles()
        self._build_ui()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")

        default_font = ("Segoe UI", 10)
        self.root.option_add("*Font", default_font)
        self.root.option_add("*Menu.Font", default_font)

        style.configure("TButton", padding=(10, 6))
        style.configure("TMenubutton", padding=(10, 6))
        style.configure("TCombobox", padding=3)
        style.configure("TNotebook.Tab", padding=(14, 7))
        style.configure("Treeview", rowheight=29, font=default_font)
        style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10), padding=(6, 7))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 17))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 9))
        style.configure("Summary.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Section.TLabel", font=("Segoe UI Semibold", 10))
        style.configure("Footer.TLabel", font=("Segoe UI", 9))

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
        ttk.Label(
            title_block,
            text="Photo Metadata Repair Inspector",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            title_block,
            textvariable=self.status_var,
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))

        controls = ttk.Frame(header)
        controls.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Button(controls, text="Scan Folder…", command=self.request_directory).grid(
            row=0, column=0, padx=(0, 14)
        )
        ttk.Label(controls, text="Media").grid(row=0, column=1, padx=(0, 6))
        media_filter = ttk.Combobox(
            controls,
            textvariable=self.media_filter_var,
            values=("All", "Images", "Videos"),
            width=10,
            state="readonly",
        )
        media_filter.grid(row=0, column=2)
        media_filter.bind("<<ComboboxSelected>>", lambda _: self._render())

        summary_bar = ttk.Frame(container, padding=(0, 2, 0, 2))
        summary_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(summary_bar, textvariable=self.summary_var, style="Summary.TLabel").grid(
            row=0, column=0, sticky="w"
        )

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
        review_tab.rowconfigure(1, weight=1)

        review_controls = ttk.Frame(review_tab)
        review_controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
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
        ttk.Label(
            review_controls,
            textvariable=self.selection_var,
            style="Subtitle.TLabel",
        ).grid(row=0, column=3, sticky="e")

        self.issue_tree = self._build_tree(review_tab, include_issues=True, row=1)
        self.issue_tree.bind("<<TreeviewSelect>>", lambda _: self._update_selection_status())

        repair_bar = ttk.LabelFrame(review_tab, text="Selected files", padding=(10, 8))
        repair_bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        repair_bar.columnconfigure(3, weight=1)

        self._build_repair_menu(
            repair_bar,
            column=0,
            label="Set Taken At",
            options=(("From filename", "taken", "filename"), ("From Created", "taken", "created")),
        )
        self._build_repair_menu(
            repair_bar,
            column=1,
            label="Set Created",
            options=(("From Taken At", "created", "taken"), ("From filename", "created", "filename")),
        )
        self._build_repair_menu(
            repair_bar,
            column=2,
            label="Set Modified",
            options=(("From Taken At", "modified", "taken"), ("From filename", "modified", "filename")),
        )

        actions = ttk.Frame(repair_bar)
        actions.grid(row=0, column=4, sticky="e")
        ttk.Button(actions, text="Select all", command=self._select_all_issues).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(actions, text="Open file", command=self._open_selected).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(actions, text="Show in Explorer", command=self._reveal_selected).grid(
            row=0, column=2
        )

        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(0, weight=1)
        self.log_text = Text(
            log_tab,
            wrap="none",
            font=("Consolas", 9),
            borderwidth=0,
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

        ttk.Label(
            container,
            text=(
                "Original files are backed up before repair. Every attempted change is recorded "
                "in the CSV repair log."
            ),
            style="Footer.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=(9, 0))

    def _build_repair_menu(
        self,
        parent: ttk.Frame,
        *,
        column: int,
        label: str,
        options: tuple[tuple[str, str, str], ...],
    ) -> None:
        button = ttk.Menubutton(parent, text=f"{label}  ▾")
        menu = Menu(button, tearoff=False)
        for option_label, target, source in options:
            menu.add_command(
                label=option_label,
                command=lambda t=target, s=source: self.apply_repair(t, s),
            )
        button.configure(menu=menu)
        button.grid(row=0, column=column, padx=(0, 8), sticky="w")

    def _build_tree(self, parent: ttk.Frame, include_issues: bool, row: int = 0) -> ttk.Treeview:
        table = ttk.Frame(parent)
        table.grid(row=row, column=0, sticky="nsew")
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)

        columns = ["name", "type", "size", "created", "modified", "taken", "filename"]
        if include_issues:
            columns.append("issues")
        columns.append("path")

        tree = ttk.Treeview(
            table,
            columns=columns,
            show="headings",
            selectmode="extended",
        )
        tree.grid(row=0, column=0, sticky="nsew")

        vscroll = ttk.Scrollbar(table, orient="vertical", command=tree.yview)
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(table, orient="horizontal", command=tree.xview)
        hscroll.grid(row=1, column=0, sticky="ew")
        tree.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)

        headings = {
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
        anchors = {"size": "e"}

        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(
                column,
                width=widths[column],
                minwidth=60,
                anchor=anchors.get(column, "w"),
                stretch=(column == "path"),
            )

        tree.bind("<Double-1>", lambda _: self._open_selected())
        return tree

    def request_directory(self) -> None:
        directory = filedialog.askdirectory()
        if not directory:
            return
        root = Path(directory)
        if not root.exists():
            messagebox.showerror("Folder missing", f"{root} does not exist.")
            return

        self._scan_generation += 1
        generation = self._scan_generation
        self.status_var.set(f"Scanning {root}")
        self.summary_var.set("Scanning collection…")
        self.progress.grid()
        self.progress.start(10)
        threading.Thread(
            target=self._scan_worker,
            args=(generation, root),
            daemon=True,
        ).start()

    def _scan_worker(self, generation: int, root: Path) -> None:
        records = scan_directory(root)
        self.root.after(0, lambda: self._finish_scan(generation, root, records))

    def _finish_scan(self, generation: int, root: Path, records: list[MediaRecord]) -> None:
        if generation != self._scan_generation:
            return
        self.progress.stop()
        self.progress.grid_remove()
        self.scan_root = root
        self.repair_service = RepairService(root)
        self.records = records
        self.status_var.set(str(root))
        self._render()
        self._load_log()

    def _media_matches(self, record: MediaRecord) -> bool:
        selected = self.media_filter_var.get()
        if selected == "Images":
            return record.media_type == "image"
        if selected == "Videos":
            return record.media_type == "video"
        return True

    def _row_values(self, record: MediaRecord, include_issues: bool) -> tuple[str, ...]:
        values = [
            record.name,
            record.media_type.title(),
            format_size(record.size_bytes),
            record.created,
            record.modified,
            record.taken,
            record.filename_date,
        ]
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
        self.issue_tree.delete(*self.issue_tree.get_children())
        self.issue_map.clear()
        selected_issue = self.issue_filter_var.get()
        count = 0
        for record in self.records:
            if not self._media_matches(record) or not record.issues:
                continue
            if selected_issue != "All review items" and selected_issue not in record.issues:
                continue
            item = self.issue_tree.insert("", "end", values=self._row_values(record, True))
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

    def _update_selection_status(self) -> None:
        count = len(self.issue_tree.selection())
        self.selection_var.set("No files selected" if count == 0 else f"{count} selected")

    def _select_all_issues(self) -> None:
        self.issue_tree.selection_set(self.issue_tree.get_children())
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
            messagebox.showinfo("Open file", "Select a file first.")
            return
        try:
            os.startfile(record.path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Open file", str(exc))

    def _reveal_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("Show in Explorer", "Select a file first.")
            return
        try:
            subprocess.Popen(["explorer", "/select,", str(Path(record.path).resolve())])
        except OSError as exc:
            messagebox.showerror("Show in Explorer", str(exc))

    def apply_repair(self, target: str, source: str) -> None:
        selection = self.issue_tree.selection()
        if not selection:
            messagebox.showinfo("Repair timestamps", "Select at least one review row first.")
            return
        if self.repair_service is None:
            return

        records = [self.issue_map[item] for item in selection if item in self.issue_map]
        operation = f"Set {target.title()} = {source.title()}"
        confirmed = messagebox.askyesno(
            "Confirm repair",
            (
                f"{operation} for {len(records)} selected file(s)?\n\n"
                "An original copy of each file will be preserved under "
                ".photo-repair-backups before any write."
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
            except Exception as exc:  # user-driven filesystem/metadata failures
                failures.append(f"{record.name}: {exc}")

        if replacements:
            self.records = [replacements.get(record.path, record) for record in self.records]
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
