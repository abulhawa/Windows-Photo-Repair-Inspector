"""Tkinter desktop application for inspecting and repairing media timestamps."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import StringVar, Text, Tk, filedialog, messagebox, ttk
from typing import Optional

from .core import MediaRecord, format_size
from .repair import RepairService
from .scanner import scan_directory, scan_file

ISSUE_FILTERS = (
    "All issues",
    "Missing Taken At",
    "Modified > Created",
    "Created > Modified",
    "Taken > Created",
    "Taken < Created",
)


class PhotoRepairApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Photo Metadata Repair Inspector")
        self.root.geometry("1250x720")

        self.records: list[MediaRecord] = []
        self.library_map: dict[str, MediaRecord] = {}
        self.issue_map: dict[str, MediaRecord] = {}
        self.scan_root: Optional[Path] = None
        self.repair_service: Optional[RepairService] = None
        self._scan_generation = 0

        self.status_var = StringVar(value="Select a folder to inspect.")
        self.media_filter_var = StringVar(value="All")
        self.issue_filter_var = StringVar(value=ISSUE_FILTERS[0])

        self._build_ui()

    def _build_ui(self) -> None:
        container = ttk.Frame(self.root, padding=14)
        container.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(container)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(1, weight=1)

        ttk.Button(toolbar, text="Scan Folder…", command=self.request_directory).grid(
            row=0, column=0, padx=(0, 10)
        )
        ttk.Label(toolbar, textvariable=self.status_var).grid(row=0, column=1, sticky="w")

        ttk.Label(toolbar, text="Media:").grid(row=0, column=2, padx=(8, 4))
        media_filter = ttk.Combobox(
            toolbar,
            textvariable=self.media_filter_var,
            values=("All", "Images", "Videos"),
            width=10,
            state="readonly",
        )
        media_filter.grid(row=0, column=3)
        media_filter.bind("<<ComboboxSelected>>", lambda _: self._render())

        self.progress = ttk.Progressbar(container, mode="indeterminate")
        self.progress.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=2, column=0, sticky="nsew")

        library_tab = ttk.Frame(self.notebook)
        issues_tab = ttk.Frame(self.notebook)
        log_tab = ttk.Frame(self.notebook)
        self.notebook.add(library_tab, text="Library")
        self.notebook.add(issues_tab, text="Issues")
        self.notebook.add(log_tab, text="Repair Log")

        self.library_tree = self._build_tree(library_tab, include_issues=False)

        issues_tab.columnconfigure(0, weight=1)
        issues_tab.rowconfigure(1, weight=1)
        issue_controls = ttk.Frame(issues_tab, padding=(0, 0, 0, 8))
        issue_controls.grid(row=0, column=0, sticky="ew")
        ttk.Label(issue_controls, text="Issue:").grid(row=0, column=0, padx=(0, 4))
        issue_filter = ttk.Combobox(
            issue_controls,
            textvariable=self.issue_filter_var,
            values=ISSUE_FILTERS,
            width=22,
            state="readonly",
        )
        issue_filter.grid(row=0, column=1, padx=(0, 12))
        issue_filter.bind("<<ComboboxSelected>>", lambda _: self._render_issues())

        self.issue_tree = self._build_tree(issues_tab, include_issues=True, row=1)

        repair_bar = ttk.Frame(issues_tab, padding=(0, 8, 0, 0))
        repair_bar.grid(row=2, column=0, sticky="ew")
        repairs = [
            ("Created = Taken", "created", "taken"),
            ("Modified = Taken", "modified", "taken"),
            ("Taken = Filename", "taken", "filename"),
            ("Taken = Created", "taken", "created"),
            ("Created = Filename", "created", "filename"),
            ("Modified = Filename", "modified", "filename"),
        ]
        for index, (label, target, source) in enumerate(repairs):
            ttk.Button(
                repair_bar,
                text=label,
                command=lambda t=target, s=source: self.apply_repair(t, s),
            ).grid(row=index // 3, column=index % 3, padx=(0, 6), pady=(0, 6), sticky="w")

        ttk.Button(repair_bar, text="Select All", command=self._select_all_issues).grid(
            row=0, column=3, padx=(12, 6), sticky="w"
        )
        ttk.Button(repair_bar, text="Open File", command=self._open_selected).grid(
            row=1, column=3, padx=(12, 6), sticky="w"
        )
        ttk.Button(repair_bar, text="Open Location", command=self._reveal_selected).grid(
            row=1, column=4, padx=(0, 6), sticky="w"
        )

        log_tab.columnconfigure(0, weight=1)
        log_tab.rowconfigure(0, weight=1)
        self.log_text = Text(log_tab, wrap="none", height=20)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_tab, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set, state="disabled")

        ttk.Label(
            container,
            text=(
                "Repairs are in-place, but the original file is copied first to "
                ".photo-repair-backups inside the scanned folder. Every attempted repair is logged."
            ),
            wraplength=1050,
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))

    def _build_tree(self, parent: ttk.Frame, include_issues: bool, row: int = 0) -> ttk.Treeview:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(row, weight=1)
        columns = ["name", "type", "size", "created", "modified", "taken", "filename"]
        if include_issues:
            columns.append("issues")
        columns.append("path")
        tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="extended")
        tree.grid(row=row, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        scrollbar.grid(row=row, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        headings = {
            "name": "File",
            "type": "Type",
            "size": "Size",
            "created": "Created",
            "modified": "Modified",
            "taken": "Taken At",
            "filename": "Filename Date",
            "issues": "Detected Issues",
            "path": "Location",
        }
        widths = {
            "name": 190,
            "type": 65,
            "size": 80,
            "created": 140,
            "modified": 140,
            "taken": 140,
            "filename": 140,
            "issues": 240,
            "path": 280,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], anchor="w")
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
        self.status_var.set(f"Scanning {root}…")
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
        self.scan_root = root
        self.repair_service = RepairService(root)
        self.records = records
        self.status_var.set(f"Loaded {len(records)} supported media file(s) from {root}.")
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
            record.media_type,
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
        for record in self.records:
            if not self._media_matches(record):
                continue
            item = self.library_tree.insert("", "end", values=self._row_values(record, False))
            self.library_map[item] = record
        self._render_issues()

    def _render_issues(self) -> None:
        self.issue_tree.delete(*self.issue_tree.get_children())
        self.issue_map.clear()
        selected_issue = self.issue_filter_var.get()
        count = 0
        for record in self.records:
            if not self._media_matches(record) or not record.issues:
                continue
            if selected_issue != "All issues" and selected_issue not in record.issues:
                continue
            item = self.issue_tree.insert("", "end", values=self._row_values(record, True))
            self.issue_map[item] = record
            count += 1
        self.notebook.tab(1, text=f"Issues ({count})" if count else "Issues")

    def _select_all_issues(self) -> None:
        self.issue_tree.selection_set(self.issue_tree.get_children())

    def _selected_record(self) -> Optional[MediaRecord]:
        if self.notebook.index("current") == 1:
            selection = self.issue_tree.selection()
            return self.issue_map.get(selection[0]) if selection else None
        selection = self.library_tree.selection()
        return self.library_map.get(selection[0]) if selection else None

    def _open_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("Open File", "Select a file first.")
            return
        try:
            os.startfile(record.path)  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("Open File", str(exc))

    def _reveal_selected(self) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("Open Location", "Select a file first.")
            return
        try:
            subprocess.Popen(["explorer", "/select,", str(Path(record.path).resolve())])
        except OSError as exc:
            messagebox.showerror("Open Location", str(exc))

    def apply_repair(self, target: str, source: str) -> None:
        selection = self.issue_tree.selection()
        if not selection:
            messagebox.showinfo("Repair timestamps", "Select at least one issue row first.")
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
