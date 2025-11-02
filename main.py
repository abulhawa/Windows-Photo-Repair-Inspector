"""Simple photo metadata viewer."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

if not sys.platform.startswith("win"):
    raise SystemExit("This application currently runs on Windows only.")

try:
    from tkinter import BooleanVar, Menu, StringVar, Tk, filedialog, messagebox, ttk
except ImportError as exc:  # pragma: no cover - tkinter should exist on most systems
    raise RuntimeError("tkinter is required to run this application") from exc

# Pillow is optional; we import lazily so the app still works without it.
try:
    from PIL import Image
    from PIL.ExifTags import TAGS

    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover - pillow may not be installed
    Image = None  # type: ignore
    TAGS = {}
    _PIL_AVAILABLE = False


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".tiff",
    ".heic",
    ".webp",
    ".raw",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".wmv",
    ".m4v",
    ".mpg",
    ".mpeg",
    ".3gp",
    ".webm",
}

SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


def format_size(num_bytes: int) -> str:
    """Return human-readable file size."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"


def format_timestamp(timestamp: float) -> str:
    """Return a human-readable string for a filesystem timestamp."""
    try:
        dt = datetime.fromtimestamp(timestamp)
    except (ValueError, OSError):  # pragma: no cover - platform specific errors
        return ""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def iter_media_files(root: Path) -> Iterable[Path]:
    """Yield supported media files under root."""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def get_exif_taken_date(path: Path) -> Optional[str]:
    """Extract the 'taken at' timestamp from EXIF data if available."""
    if not _PIL_AVAILABLE or Image is None:
        return None

    try:
        with Image.open(path) as img:
            exif_data = img._getexif()  # type: ignore[attr-defined]
    except Exception:
        return None

    if not exif_data:
        return None

    reverse_tags = {v: k for k, v in TAGS.items()}
    for label in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
        tag = reverse_tags.get(label)
        if tag and tag in exif_data:
            value = exif_data.get(tag)
            if isinstance(value, bytes):
                try:
                    value = value.decode()
                except Exception:
                    continue
            if isinstance(value, str):
                return value.strip().replace(":", "-", 2)
    return None


def extract_date_from_filename(filename: str) -> Optional[str]:
    """Try to infer a capture date from common filename patterns."""
    stem = Path(filename).stem
    patterns = [
        r"(20\d{2})([-_.]?)(0[1-9]|1[0-2])\2(0[1-9]|[12]\d|3[01])",
        r"(0[1-9]|1[0-2])([-_.])(0[1-9]|[12]\d|3[01])\2(20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, stem)
        if not match:
            continue

        groups = match.groups()
        if len(groups) == 4:
            if pattern.startswith("(20"):
                year, _, month, day = groups
            else:
                month, _, day, year = groups
            return f"{year}-{month}-{day} 00:00:00"
    return None


def classify_media(path: Path) -> str:
    """Return 'image' or 'video' based on file extension."""
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return "other"


def open_file(path: Path) -> None:
    """Open the specified file with the system default handler."""
    os.startfile(str(path))  # type: ignore[attr-defined]


def reveal_in_explorer(path: Path) -> None:
    """Open the folder containing the file."""
    subprocess.run(["explorer", f"/select,{path.resolve()}"], check=True)


class PhotoMetadataViewer:
    """Tkinter GUI that lists photo metadata."""

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Photo Metadata Viewer")
        self.records: list[tuple[str, int, str, str, str, str, str, str]] = []
        self.item_to_record: dict[str, tuple[str, int, str, str, str, str, str, str]] = {}
        self.columns: tuple[str, ...] = ()
        self._build_ui()

    def _build_ui(self) -> None:
        self.status_var = StringVar(value="Select a folder to begin scanning.")
        self.only_taken_var = BooleanVar(value=False)
        self.media_filter_var = StringVar(value="All")

        main_frame = ttk.Frame(self.root, padding=16)
        main_frame.grid(row=0, column=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(1, weight=1)

        controls = ttk.Frame(main_frame)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        controls.columnconfigure(1, weight=1)

        scan_button = ttk.Button(controls, text="Scan Folder…", command=self.request_directory)
        scan_button.grid(row=0, column=0, padx=(0, 8))

        self.status_label = ttk.Label(controls, textvariable=self.status_var)
        self.status_label.grid(row=0, column=1, sticky="w")

        filter_check = ttk.Checkbutton(
            controls,
            text="Show only Taken At",
            variable=self.only_taken_var,
            command=self._refresh_tree,
        )
        filter_check.grid(row=0, column=2, padx=(8, 0))

        media_filter = ttk.Combobox(
            controls,
            textvariable=self.media_filter_var,
            values=("All", "Images", "Videos"),
            state="readonly",
            width=10,
        )
        media_filter.grid(row=0, column=3, padx=(8, 0))
        media_filter.current(0)
        media_filter.bind("<<ComboboxSelected>>", lambda _: self._refresh_tree())

        self.progress = ttk.Progressbar(controls, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0))

        columns = ("name", "size", "created", "modified", "taken", "filename_date", "path")
        self.columns = columns
        self.tree = ttk.Treeview(
            main_frame,
            columns=columns,
            show="headings",
            height=16,
        )
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<Button-3>", self._on_right_click)
        self.context_menu = Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Open File", command=self._open_selected_file)
        self.context_menu.add_command(label="Open File Location", command=self._reveal_selected_file)

        headings = {
            "name": "File",
            "size": "Size",
            "created": "Created At",
            "modified": "Modified At",
            "taken": "Taken At",
            "filename_date": "Filename Date",
            "path": "Location",
        }

        for column, heading in headings.items():
            self.tree.heading(
                column,
                text=heading,
                command=lambda col=column: self._sort_by_column(col, False),
            )

        self.tree.column("name", width=200, anchor="w")
        self.tree.column("size", width=100, anchor="e")
        self.tree.column("created", width=140, anchor="center")
        self.tree.column("modified", width=140, anchor="center")
        self.tree.column("taken", width=140, anchor="center")
        self.tree.column("filename_date", width=140, anchor="center")
        self.tree.column("path", width=240, anchor="w")

        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(main_frame)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(
            footer,
            text=(
                "Created/Modified come from filesystem timestamps. "
                "Taken At is extracted from EXIF when available. Filename Date is parsed from the filename."
            ),
            wraplength=560,
            justify="center",
        ).grid(row=0, column=0, sticky="ew")

    def request_directory(self) -> None:
        directory = filedialog.askdirectory()
        if not directory:
            return

        selected_path = Path(directory)
        if not selected_path.exists():
            messagebox.showerror("Folder missing", f"{directory} does not exist.")
            return

        self.status_var.set("Scanning…")
        self.records = []
        self.item_to_record.clear()
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(10)
        self.tree.delete(*self.tree.get_children())
        threading.Thread(
            target=self._scan_directory,
            args=(selected_path,),
            daemon=True,
        ).start()

    def _scan_directory(self, directory: Path) -> None:
        records = []
        file_paths = list(iter_media_files(directory))
        total = len(file_paths)

        self.root.after(0, lambda: self._configure_progress(total))

        for index, path in enumerate(file_paths, start=1):
            try:
                stats = path.stat()
            except OSError:
                continue

            size_bytes = stats.st_size
            created = format_timestamp(stats.st_ctime)
            modified = format_timestamp(stats.st_mtime)
            taken = get_exif_taken_date(path) or ""
            filename_date = extract_date_from_filename(path.name) or ""
            media_type = classify_media(path)
            records.append((path.name, size_bytes, created, modified, taken, filename_date, str(path), media_type))

            self.root.after(0, lambda count=index, tot=total: self._update_progress(count, tot))

        self.root.after(0, lambda: self._finalize_scan(records))

    def _sort_by_column(self, column: str, descending: bool) -> None:
        items = list(self.tree.get_children(""))
        if not items:
            return

        def get_sort_value(item_id: str):
            record = self.item_to_record.get(item_id)
            if column == "size" and record:
                return record[1]
            value = self.tree.set(item_id, column)
            if isinstance(value, str):
                return value.lower()
            return value

        sorted_items = sorted(items, key=get_sort_value, reverse=descending)

        for position, item_id in enumerate(sorted_items):
            self.tree.move(item_id, "", position)

        self.tree.heading(
            column,
            command=lambda col=column: self._sort_by_column(col, not descending),
        )

    def _configure_progress(self, total: int) -> None:
        self.progress.stop()
        if total <= 0:
            self.progress.configure(mode="determinate", maximum=1, value=0)
            self.status_var.set("No supported media files found.")
        else:
            self.progress.configure(mode="determinate", maximum=total, value=0)
            self.status_var.set("Scanning… 0/%d" % total)

    def _update_progress(self, processed: int, total: int) -> None:
        if total <= 0:
            return
        self.progress.configure(value=processed)
        self.status_var.set(f"Scanning… {processed}/{total}")

    def _finalize_scan(self, records: list[tuple[str, int, str, str, str, str, str, str]]) -> None:
        self.records = records
        if not records:
            self.tree.delete(*self.tree.get_children())
            self.item_to_record.clear()
            self.status_var.set("No supported media files found.")
            self.progress.configure(value=0)
            return

        self.progress.configure(value=self.progress["maximum"])
        self._render_records()

    def _render_records(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.item_to_record.clear()

        if not self.records:
            self.status_var.set("No supported media files found.")
            return

        display_records = [record for record in self.records if self._record_matches_filters(record)]

        for record in display_records:
            values = (
                record[0],
                format_size(record[1]),
                record[2],
                record[3],
                record[4],
                record[5],
                record[6],
            )
            item = self.tree.insert("", "end", values=values)
            self.item_to_record[item] = record

        total = len(self.records)
        shown = len(display_records)
        if shown == 0:
            self.status_var.set("No files match the current filters.")
            return

        filter_descriptions = []
        if self.only_taken_var.get():
            filter_descriptions.append("Taken At")
        media_filter = self.media_filter_var.get()
        if media_filter != "All":
            filter_descriptions.append(media_filter.lower())

        if filter_descriptions:
            filters_text = " & ".join(filter_descriptions)
            self.status_var.set(f"Loaded {total} file(s). Showing {shown} matching {filters_text}.")
        else:
            self.status_var.set(f"Loaded {total} file(s).")

    def _record_matches_filters(self, record: tuple[str, int, str, str, str, str, str, str]) -> bool:
        if self.only_taken_var.get() and not record[4]:
            return False

        media_filter = self.media_filter_var.get()
        if media_filter == "Images" and record[7] != "image":
            return False
        if media_filter == "Videos" and record[7] != "video":
            return False

        return True

    def _refresh_tree(self) -> None:
        if not self.records:
            return
        self._render_records()

    def _on_right_click(self, event) -> None:
        item = self.tree.identify_row(event.y)
        if not item:
            return
        self.tree.selection_set(item)
        self.tree.focus(item)
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _get_selected_record(self) -> Optional[tuple[str, int, str, str, str, str, str, str]]:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.item_to_record.get(selection[0])

    def _open_selected_file(self) -> None:
        record = self._get_selected_record()
        if not record:
            return
        path = Path(record[-1])
        if not path.exists():
            messagebox.showerror("Open File", f"{path} does not exist.")
            return
        try:
            open_file(path)
        except Exception as exc:  # pragma: no cover - UI path
            messagebox.showerror("Open File", f"Failed to open file:\n{exc}")

    def _reveal_selected_file(self) -> None:
        record = self._get_selected_record()
        if not record:
            return
        path = Path(record[-1])
        if not path.exists():
            messagebox.showerror("Open Location", f"{path} does not exist.")
            return
        try:
            reveal_in_explorer(path)
        except Exception as exc:  # pragma: no cover - UI path
            messagebox.showerror("Open Location", f"Failed to open location:\n{exc}")


def main() -> None:
    if sys.platform.startswith("win"):
        # Improves high DPI rendering on Windows.
        try:
            from ctypes import windll

            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    root = Tk()
    app = PhotoMetadataViewer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
