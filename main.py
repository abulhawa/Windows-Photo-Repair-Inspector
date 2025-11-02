"""Simple photo metadata viewer."""

from __future__ import annotations

import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

try:
    from tkinter import Tk, ttk, filedialog, messagebox, StringVar
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


SUPPORTED_EXTENSIONS = {
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


class PhotoMetadataViewer:
    """Tkinter GUI that lists photo metadata."""

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Photo Metadata Viewer")
        self._build_ui()

    def _build_ui(self) -> None:
        self.status_var = StringVar(value="Select a folder to begin scanning.")

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

        columns = ("name", "created", "modified", "taken", "path")
        self.tree = ttk.Treeview(
            main_frame,
            columns=columns,
            show="headings",
            height=16,
        )
        self.tree.grid(row=1, column=0, sticky="nsew")

        headings = {
            "name": "File",
            "created": "Created At",
            "modified": "Modified At",
            "taken": "Taken At",
            "path": "Location",
        }

        for column, heading in headings.items():
            self.tree.heading(
                column,
                text=heading,
                command=lambda col=column: self._sort_by_column(col, False),
            )

        self.tree.column("name", width=200, anchor="w")
        self.tree.column("created", width=140, anchor="center")
        self.tree.column("modified", width=140, anchor="center")
        self.tree.column("taken", width=140, anchor="center")
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
                "Taken At is extracted from EXIF when available."
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
        self.tree.delete(*self.tree.get_children())
        threading.Thread(
            target=self._scan_directory,
            args=(selected_path,),
            daemon=True,
        ).start()

    def _scan_directory(self, directory: Path) -> None:
        records = []
        for path in iter_media_files(directory):
            try:
                stats = path.stat()
            except OSError:
                continue

            created = format_timestamp(stats.st_ctime)
            modified = format_timestamp(stats.st_mtime)
            taken = get_exif_taken_date(path) or ""
            records.append((path.name, created, modified, taken, str(path)))

        def update_ui() -> None:
            if not records:
                self.status_var.set("No supported media files found.")
            else:
                self.status_var.set(f"Loaded {len(records)} file(s).")

            for record in records:
                self.tree.insert("", "end", values=record)

        self.root.after(0, update_ui)

    def _sort_by_column(self, column: str, descending: bool) -> None:
        items = list(self.tree.get_children(""))
        indexed = []
        for item in items:
            values = self.tree.item(item)["values"]
            if not values:
                continue
            value = values[self.tree["columns"].index(column)]
            indexed.append((value, item))

        def sort_key(entry: tuple[str, str]) -> tuple[int, str]:
            raw_value = entry[0]
            if isinstance(raw_value, str) and raw_value:
                return (0, raw_value.lower())
            return (1, "")

        indexed.sort(key=sort_key, reverse=descending)

        for position, (_, item) in enumerate(indexed):
            self.tree.move(item, "", position)

        self.tree.heading(
            column,
            command=lambda col=column: self._sort_by_column(col, not descending),
        )


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
