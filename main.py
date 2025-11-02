"""Simple photo metadata viewer."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import threading
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Optional

if not sys.platform.startswith("win"):
    raise SystemExit("This application currently runs on Windows only.")

from tkinter import BooleanVar, Menu, StringVar, Tk, filedialog, messagebox, ttk

import piexif
from PIL import Image
from PIL.ExifTags import TAGS

# Windows file time helpers
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 0x00000003
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_WRITE_ATTRIBUTES = 0x00000100
GENERIC_WRITE = 0x40000000
EPOCH_AS_FILETIME = 11644473600 * 10 ** 7  # seconds to 100-ns intervals offset
HUNDREDS_OF_NANOSECONDS = 10 ** 7

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


kernel32.CreateFileW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.SetFileTime.argtypes = (
    wintypes.HANDLE,
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
    ctypes.POINTER(FILETIME),
)
kernel32.SetFileTime.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel32.CloseHandle.restype = wintypes.BOOL

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


def _timestamp_to_filetime(timestamp: float) -> FILETIME:
    intervals = int(timestamp * HUNDREDS_OF_NANOSECONDS + EPOCH_AS_FILETIME)
    return FILETIME(intervals & 0xFFFFFFFF, intervals >> 32)


def _set_windows_file_times(path: Path, created_ts: float, accessed_ts: float, modified_ts: float) -> None:
    handle = kernel32.CreateFileW(
        str(path),
        FILE_WRITE_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        creation_ft = _timestamp_to_filetime(created_ts)
        access_ft = _timestamp_to_filetime(accessed_ts)
        modified_ft = _timestamp_to_filetime(modified_ts)
        if not kernel32.SetFileTime(
            handle,
            ctypes.byref(creation_ft),
            ctypes.byref(access_ft),
            ctypes.byref(modified_ft),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


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
WRITABLE_TAKEN_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff"}
AnchorLiteral = Literal["nw", "n", "ne", "w", "center", "e", "sw", "s", "se"]


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


def derive_proposed_taken(created: str, filename_date: str, taken: str) -> Optional[str]:
    """Return the proposed Taken At value if eligible, else None."""
    if not created or not filename_date:
        return None
    if taken:
        return None
    if created[:10] != filename_date[:10]:
        return None
    return created


def parse_timestamp(value: str) -> Optional[float]:
    """Parse a YYYY-MM-DD HH:MM:SS string into a Unix timestamp."""
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.timestamp()


@dataclass
class MediaRecord:
    name: str
    size_bytes: int
    created: str
    modified: str
    taken: str
    filename_date: str
    path: str
    media_type: str
    created_ts: float
    modified_ts: float
    taken_ts: Optional[float]
    proposed_taken: Optional[str] = None


def open_file(path: Path) -> None:
    """Open the specified file with the system default handler."""
    os.startfile(str(path))  # type: ignore[attr-defined]


def reveal_in_explorer(path: Path) -> None:
    """Open the folder containing the file."""
    subprocess.Popen(["explorer", "/select,", str(path.resolve())])


class PhotoMetadataViewer:
    """Tkinter GUI that lists photo metadata."""

    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Photo Metadata Viewer")
        self.records: list[MediaRecord] = []
        self.item_to_record: dict[str, MediaRecord] = {}
        self.fix_item_to_record: dict[str, MediaRecord] = {}
        self.columns: tuple[str, ...] = ()
        self.fix_columns: tuple[str, ...] = ()
        self.browser_tab: Optional[ttk.Frame] = None
        self.fix_tab: Optional[ttk.Frame] = None
        self.anomaly_views: dict[str, dict[str, Any]] = {}
        self._context_tree: Optional[ttk.Treeview] = None
        self._context_map: Optional[dict[str, MediaRecord]] = None
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

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.grid(row=1, column=0, columnspan=1, sticky="nsew")

        browser_frame = ttk.Frame(self.notebook)
        fix_frame = ttk.Frame(self.notebook)
        self.browser_tab = browser_frame
        self.fix_tab = fix_frame
        self.notebook.add(browser_frame, text="Library")
        self.notebook.add(fix_frame, text="Taken At Fixes")

        browser_frame.columnconfigure(0, weight=1)
        browser_frame.rowconfigure(0, weight=1)

        columns = ("name", "size", "created", "modified", "taken", "filename_date", "path")
        self.columns = columns
        self.headings = {
            "name": "File",
            "size": "Size",
            "created": "Created At",
            "modified": "Modified At",
            "taken": "Taken At",
            "filename_date": "Filename Date",
            "path": "Location",
        }
        self.column_settings: dict[str, tuple[int, AnchorLiteral]] = {
            "name": (200, "w"),
            "size": (100, "e"),
            "created": (140, "center"),
            "modified": (140, "center"),
            "taken": (140, "center"),
            "filename_date": (140, "center"),
            "path": (240, "w"),
        }
        self.tree = ttk.Treeview(
            browser_frame,
            columns=columns,
            show="headings",
            height=16,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Button-3>", self._on_right_click)
        self._configure_standard_tree(self.tree, self.item_to_record)

        browser_scrollbar = ttk.Scrollbar(browser_frame, orient="vertical", command=self.tree.yview)
        browser_scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=browser_scrollbar.set)

        fix_frame.columnconfigure(0, weight=1)
        fix_frame.rowconfigure(0, weight=1)

        self.fix_columns = ("name", "created", "filename_date", "new_taken", "path")
        self.fix_tree = ttk.Treeview(
            fix_frame,
            columns=self.fix_columns,
            show="headings",
            height=14,
        )
        self.fix_tree.grid(row=0, column=0, sticky="nsew")
        self.fix_tree.bind("<Button-3>", self._on_right_click)
        self.fix_tree.bind("<<TreeviewSelect>>", lambda _: self._update_fix_selection_status(force=True))

        fix_headings = {
            "name": "File",
            "created": "Created At",
            "filename_date": "Filename Date",
            "new_taken": "New Taken At",
            "path": "Location",
        }

        for column, heading in fix_headings.items():
            self.fix_tree.heading(
                column,
                text=heading,
                command=lambda col=column: self._sort_by_column(self.fix_tree, self.fix_item_to_record, col, False),
            )

        self.fix_tree.column("name", width=200, anchor="w")
        self.fix_tree.column("created", width=140, anchor="center")
        self.fix_tree.column("filename_date", width=140, anchor="center")
        self.fix_tree.column("new_taken", width=160, anchor="center")
        self.fix_tree.column("path", width=240, anchor="w")

        fix_scrollbar = ttk.Scrollbar(fix_frame, orient="vertical", command=self.fix_tree.yview)
        fix_scrollbar.grid(row=0, column=1, sticky="ns")
        self.fix_tree.configure(yscrollcommand=fix_scrollbar.set)

        actions_frame = ttk.Frame(fix_frame, padding=(0, 12, 0, 0))
        actions_frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        for col in range(3):
            actions_frame.columnconfigure(col, weight=0)
        actions_frame.columnconfigure(3, weight=1)

        ttk.Button(
            actions_frame,
            text="Apply Selected Fixes",
            command=self._apply_selected_fixes,
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Button(
            actions_frame,
            text="Open File",
            command=self._open_selected_file,
        ).grid(row=0, column=1, sticky="w", padx=(0, 6))
        ttk.Button(
            actions_frame,
            text="Open Location",
            command=self._reveal_selected_file,
        ).grid(row=0, column=2, sticky="w", padx=(0, 6))

        self.fix_status_var = StringVar(value="No fixable files available.")
        ttk.Label(actions_frame, textvariable=self.fix_status_var).grid(row=0, column=3, sticky="e")

        fix_buttons = ttk.Frame(fix_frame, padding=(0, 0, 0, 12))
        fix_buttons.grid(row=2, column=0, columnspan=2, sticky="ew")
        fix_buttons.columnconfigure(0, weight=1)

        ttk.Button(
            fix_buttons,
            text="Set Taken = Filename",
            command=lambda: self._apply_fix_taken_action("filename"),
        ).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=(0, 6))
        ttk.Button(
            fix_buttons,
            text="Set Taken = Created",
            command=lambda: self._apply_fix_taken_action("created"),
        ).grid(row=0, column=1, sticky="w", padx=(0, 6), pady=(0, 6))
        ttk.Button(
            fix_buttons,
            text="Set Created = Taken",
            command=lambda: self._apply_fix_taken_mirror("created"),
        ).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(0, 6))
        ttk.Button(
            fix_buttons,
            text="Set Modified = Taken",
            command=lambda: self._apply_fix_taken_mirror("modified"),
        ).grid(row=1, column=1, sticky="w", padx=(0, 6), pady=(0, 6))
        ttk.Button(
            fix_buttons,
            text="Select All",
            command=lambda: self._select_all_in_tree(self.fix_tree),
        ).grid(row=0, column=2, sticky="w", padx=(0, 6), pady=(0, 6))

        def set_from(target: str, source: str) -> Callable[[MediaRecord], None]:
            return lambda record, t=target, s=source: self._set_timestamp_from_source(record, t, s)

        anomaly_specs: list[tuple[str, Callable[[MediaRecord], bool], list[tuple[str, Callable[[MediaRecord], None]]]]] = [
            (
                "Modified > Created",
                lambda rec: rec.modified_ts > rec.created_ts,
                [
                    ("Set Created = Modified", set_from("created", "modified")),
                    ("Set Modified = Created", set_from("modified", "created")),
                    ("Set Created = Taken At", set_from("created", "taken")),
                    ("Set Modified = Taken At", set_from("modified", "taken")),
                    ("Set Created = Filename", set_from("created", "filename")),
                    ("Set Modified = Filename", set_from("modified", "filename")),
                ],
            ),
            (
                "Created > Modified",
                lambda rec: rec.created_ts > rec.modified_ts,
                [
                    ("Set Modified = Created", set_from("modified", "created")),
                    ("Set Created = Modified", set_from("created", "modified")),
                    ("Set Modified = Taken At", set_from("modified", "taken")),
                    ("Set Created = Taken At", set_from("created", "taken")),
                    ("Set Modified = Filename", set_from("modified", "filename")),
                    ("Set Created = Filename", set_from("created", "filename")),
                ],
            ),
            (
                "Taken > Created",
                lambda rec: rec.taken_ts is not None and rec.taken_ts > rec.created_ts,
                [
                    ("Set Created = Taken At", set_from("created", "taken")),
                    ("Set Taken = Created", set_from("taken", "created")),
                    ("Set Created = Filename", set_from("created", "filename")),
                    ("Set Taken = Filename", set_from("taken", "filename")),
                ],
            ),
            (
                "Taken < Created",
                lambda rec: rec.taken_ts is not None and rec.taken_ts < rec.created_ts,
                [
                    ("Set Created = Taken At", set_from("created", "taken")),
                    ("Set Modified = Taken At", set_from("modified", "taken")),
                    ("Set Taken = Created", set_from("taken", "created")),
                    ("Set Created = Filename", set_from("created", "filename")),
                    ("Set Taken = Filename", set_from("taken", "filename")),
                ],
            ),
        ]

        for label, predicate, actions in anomaly_specs:
            self._create_anomaly_tab(label, predicate, actions)

        self.context_menu = Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Open File", command=self._open_selected_file)
        self.context_menu.add_command(label="Open File Location", command=self._reveal_selected_file)

        footer = ttk.Frame(main_frame)
        footer.grid(row=2, column=0, columnspan=1, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)

        ttk.Label(
            footer,
            text=(
                "Created/Modified come from filesystem timestamps. "
                "Taken At is extracted from EXIF when available. Filename Date is parsed from the filename. "
                "Use the Taken At Fixes tab to fill missing capture times when safe."
            ),
            wraplength=560,
            justify="center",
        ).grid(row=0, column=0, sticky="ew")

    def _configure_standard_tree(self, tree: ttk.Treeview, mapping: dict[str, MediaRecord]) -> None:
        for column in self.columns:
            heading = self.headings[column]
            tree.heading(
                column,
                text=heading,
                command=lambda col=column, tgt_tree=tree, tgt_mapping=mapping: self._sort_by_column(
                    tgt_tree,
                    tgt_mapping,
                    col,
                    False,
                ),
            )
            width, anchor = self.column_settings[column]
            tree.column(column, width=width, anchor=anchor)

    def _create_anomaly_tab(
        self,
        label: str,
        filter_func: Callable[[MediaRecord], bool],
        actions: list[tuple[str, Callable[[MediaRecord], None]]],
    ) -> None:
        frame = ttk.Frame(self.notebook)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        mapping: dict[str, MediaRecord] = {}
        tree = ttk.Treeview(
            frame,
            columns=self.columns,
            show="headings",
            height=14,
        )
        tree.grid(row=0, column=0, sticky="nsew")
        tree.bind("<Button-3>", self._on_right_click)
        tree.bind("<<TreeviewSelect>>", lambda _, lbl=label: self._update_anomaly_selection_status(lbl, force=True))
        self._configure_standard_tree(tree, mapping)

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scrollbar.set)

        controls = ttk.Frame(frame, padding=(0, 12, 0, 0))
        controls.grid(row=1, column=0, columnspan=2, sticky="ew")
        controls.columnconfigure(0, weight=1)

        buttons_frame = ttk.Frame(controls)
        buttons_frame.grid(row=0, column=0, sticky="w")

        status_var = StringVar(value="Select file(s) then choose a fix.")
        ttk.Label(controls, textvariable=status_var).grid(row=0, column=1, sticky="e")

        select_all_btn = ttk.Button(
            controls,
            text="Select All",
            command=lambda t=tree: self._select_all_in_tree(t),
        )
        select_all_btn.grid(row=0, column=2, sticky="e", padx=(8, 0))

        for idx, (action_label, handler) in enumerate(actions):
            ttk.Button(
                buttons_frame,
                text=action_label,
                command=lambda func=handler, lbl=label: self._apply_anomaly_action(lbl, func),
            ).grid(row=idx // 3, column=idx % 3, padx=(0, 6), pady=(0, 6), sticky="w")

        self.notebook.add(frame, text=label)
        self.anomaly_views[label] = {
            "frame": frame,
            "tree": tree,
            "mapping": mapping,
            "label": label,
            "filter": filter_func,
            "status_var": status_var,
            "actions": actions,
        }

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
        self.fix_item_to_record.clear()
        if hasattr(self, "fix_tree"):
            self.fix_tree.delete(*self.fix_tree.get_children())
            self.fix_status_var.set("Scanning for fixable files…")
            if self.fix_tab is not None:
                self.notebook.tab(self.fix_tab, text="Taken At Fixes")
        for view in self.anomaly_views.values():
            view["tree"].delete(*view["tree"].get_children())
            view["mapping"].clear()
            self.notebook.tab(view["frame"], text=view["label"])
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
            created_ts = stats.st_ctime
            modified_ts = stats.st_mtime
            created = format_timestamp(created_ts)
            modified = format_timestamp(modified_ts)
            taken = get_exif_taken_date(path) or ""
            taken_ts = parse_timestamp(taken or "")
            filename_date = extract_date_from_filename(path.name) or ""
            media_type = classify_media(path)
            proposed_taken = derive_proposed_taken(created, filename_date, taken)
            record = MediaRecord(
                name=path.name,
                size_bytes=size_bytes,
                created=created,
                modified=modified,
                taken=taken,
                filename_date=filename_date,
                path=str(path),
                media_type=media_type,
                created_ts=created_ts,
                modified_ts=modified_ts,
                taken_ts=taken_ts,
                proposed_taken=proposed_taken,
            )
            records.append(record)

            self.root.after(0, lambda count=index, tot=total: self._update_progress(count, tot))

        self.root.after(0, lambda: self._finalize_scan(records))

    def _sort_by_column(
        self,
        tree: ttk.Treeview,
        mapping: dict[str, MediaRecord],
        column: str,
        descending: bool,
    ) -> None:
        items = list(tree.get_children(""))
        if not items:
            return

        def get_sort_value(item_id: str):
            record = mapping.get(item_id)
            if record:
                if column == "size":
                    return record.size_bytes
                if column == "taken":
                    return record.taken or ""
                if column == "filename_date":
                    return record.filename_date or ""
                if column == "created":
                    return record.created or ""
                if column == "modified":
                    return record.modified or ""
                if column == "new_taken":
                    return record.proposed_taken or ""
            value = tree.set(item_id, column)
            if isinstance(value, str):
                return value.lower()
            return value

        sorted_items = sorted(items, key=get_sort_value, reverse=descending)

        for position, item_id in enumerate(sorted_items):
            tree.move(item_id, "", position)

        tree.heading(
            column,
            command=lambda col=column: self._sort_by_column(tree, mapping, col, not descending),
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

    def _finalize_scan(self, records: list[MediaRecord]) -> None:
        self.records = records
        if not records:
            self.tree.delete(*self.tree.get_children())
            self.item_to_record.clear()
            if hasattr(self, "fix_tree"):
                self.fix_tree.delete(*self.fix_tree.get_children())
                self.fix_item_to_record.clear()
                self.fix_status_var.set("No fixable files available.")
                if self.fix_tab is not None:
                    self.notebook.tab(self.fix_tab, text="Taken At Fixes")
            for view in self.anomaly_views.values():
                view["tree"].delete(*view["tree"].get_children())
                view["mapping"].clear()
                self.notebook.tab(view["frame"], text=view["label"])
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
                record.name,
                format_size(record.size_bytes),
                record.created,
                record.modified,
                record.taken,
                record.filename_date,
                record.path,
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

        self._render_fix_records()
        self._render_anomaly_views()

    def _record_matches_filters(self, record: MediaRecord) -> bool:
        if self.only_taken_var.get() and not record.taken:
            return False

        media_filter = self.media_filter_var.get()
        if media_filter == "Images" and record.media_type != "image":
            return False
        if media_filter == "Videos" and record.media_type != "video":
            return False

        return True

    def _refresh_tree(self) -> None:
        if not self.records:
            return
        self._render_records()

    def _render_fix_records(self) -> None:
        if not hasattr(self, "fix_tree"):
            return

        self.fix_tree.delete(*self.fix_tree.get_children())
        self.fix_item_to_record.clear()

        fixable = [record for record in self.records if record.proposed_taken]

        if self.fix_tab is not None:
            label = "Taken At Fixes"
            if fixable:
                label = f"{label} ({len(fixable)})"
            self.notebook.tab(self.fix_tab, text=label)

        if not fixable:
            self.fix_status_var.set("No fixable files available.")
            return

        for record in fixable:
            values = (
                record.name,
                record.created,
                record.filename_date,
                record.proposed_taken or "",
                record.path,
            )
            item = self.fix_tree.insert("", "end", values=values)
            self.fix_item_to_record[item] = record

        self.fix_status_var.set("Select the rows to update and click Apply Selected Fixes.")
        self._update_fix_selection_status(force=True)

    def _render_anomaly_views(self) -> None:
        for view in self.anomaly_views.values():
            tree = view["tree"]
            mapping = view["mapping"]
            status_var: Optional[StringVar] = view.get("status_var")
            tree.delete(*tree.get_children())
            mapping.clear()

            subset = [record for record in self.records if view["filter"](record)]

            label = view["label"]
            if subset:
                label = f"{label} ({len(subset)})"
                if status_var is not None:
                    status_var.set("Select file(s) then choose a fix.")
            else:
                if status_var is not None:
                    status_var.set("No matching files.")
            self.notebook.tab(view["frame"], text=label)

            for record in subset:
                values = (
                    record.name,
                    format_size(record.size_bytes),
                    record.created,
                    record.modified,
                    record.taken,
                    record.filename_date,
                    record.path,
                )
                item = tree.insert("", "end", values=values)
                mapping[item] = record

            self._update_anomaly_selection_status(view["label"], force=bool(subset))

    def _timestamp_from_source(self, record: MediaRecord, source: str) -> float:
        if source == "created":
            return record.created_ts
        if source == "modified":
            return record.modified_ts
        if source == "taken":
            if record.taken_ts is None:
                ts = parse_timestamp(record.taken)
                if ts is None:
                    raise ValueError("Taken At timestamp is not available.")
                record.taken_ts = ts
            return record.taken_ts
        if source == "filename":
            ts = parse_timestamp(record.filename_date)
            if ts is None:
                raise ValueError("Filename does not contain a parsable date.")
            return ts
        raise ValueError(f"Unknown source '{source}'.")

    def _set_timestamp_from_source(self, record: MediaRecord, target: str, source: str) -> None:
        timestamp = self._timestamp_from_source(record, source)
        if target == "created":
            self._set_file_times(record, new_created_ts=timestamp)
        elif target == "modified":
            self._set_file_times(record, new_modified_ts=timestamp)
        elif target == "taken":
            self._write_taken_metadata(record, timestamp)
        else:
            raise ValueError(f"Unknown target '{target}'.")

    def _set_file_times(
        self,
        record: MediaRecord,
        new_created_ts: Optional[float] = None,
        new_modified_ts: Optional[float] = None,
    ) -> None:
        path = Path(record.path)
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist.")

        stats = path.stat()
        created_ts = new_created_ts if new_created_ts is not None else record.created_ts
        modified_ts = new_modified_ts if new_modified_ts is not None else record.modified_ts
        accessed_ts = stats.st_atime

        _set_windows_file_times(path, created_ts, accessed_ts, modified_ts)

        if new_created_ts is not None:
            record.created_ts = new_created_ts
            record.created = format_timestamp(new_created_ts)
        if new_modified_ts is not None:
            record.modified_ts = new_modified_ts
            record.modified = format_timestamp(new_modified_ts)

        self._recompute_proposed_taken(record)

    def _write_taken_metadata(self, record: MediaRecord, timestamp: float) -> None:
        path = Path(record.path)
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist.")
        if path.suffix.lower() not in WRITABLE_TAKEN_EXTENSIONS:
            raise ValueError("Taken At updates are supported only for JPEG and TIFF files.")

        new_value = format_timestamp(timestamp)
        new_value_bytes = new_value.replace("-", ":", 2).encode("utf-8")

        try:
            exif_dict = piexif.load(str(path))
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        exif_dict.setdefault("0th", {})
        exif_dict.setdefault("Exif", {})

        exif_dict["0th"][piexif.ImageIFD.DateTime] = new_value_bytes
        exif_dict["Exif"][piexif.ExifIFD.DateTimeOriginal] = new_value_bytes
        exif_dict["Exif"][piexif.ExifIFD.DateTimeDigitized] = new_value_bytes

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, str(path))

        record.taken = new_value
        record.taken_ts = timestamp
        record.proposed_taken = None
        self._recompute_proposed_taken(record)

    def _recompute_proposed_taken(self, record: MediaRecord) -> None:
        record.proposed_taken = derive_proposed_taken(record.created, record.filename_date, record.taken)

    def _apply_anomaly_action(
        self,
        view_label: str,
        handler: Callable[[MediaRecord], None],
    ) -> None:
        view = self.anomaly_views.get(view_label)
        if not view:
            return

        tree: ttk.Treeview = view["tree"]
        mapping: dict[str, MediaRecord] = view["mapping"]
        status_var: Optional[StringVar] = view.get("status_var")

        selection = tree.selection()
        if not selection:
            messagebox.showinfo("Fix Timestamps", "Select at least one row to update.")
            return

        successes = 0
        failures: list[tuple[str, str]] = []

        for item in selection:
            record = mapping.get(item)
            if not record:
                continue
            try:
                handler(record)
                successes += 1
            except Exception as exc:  # pragma: no cover - user-driven IO errors
                failures.append((record.name, str(exc)))

        message = f"Updated {successes} file(s)." if successes else "No files updated."

        if failures:
            summary = "\n".join(f"- {name}: {error}" for name, error in failures[:5])
            if len(failures) > 5:
                summary += f"\n...and {len(failures) - 5} more."
            messagebox.showerror("Fix Timestamps", f"Some updates failed:\n{summary}")

        self._render_records()
        if status_var is not None:
            status_var.set(message)
        self._update_anomaly_selection_status(view_label)

    def _apply_selected_fixes(self) -> None:
        if not hasattr(self, "fix_tree"):
            return

        selection = self.fix_tree.selection()
        if not selection:
            messagebox.showinfo("Taken At Fixes", "Select at least one row to update.")
            return

        successes = 0
        failures: list[tuple[str, str]] = []

        for item in selection:
            record = self.fix_item_to_record.get(item)
            if not record or not record.proposed_taken:
                continue
            try:
                changed = self._apply_taken_fix(record)
            except Exception as exc:  # pragma: no cover - user-driven IO errors
                failures.append((record.name, str(exc)))
                continue
            if changed:
                successes += 1

        if successes:
            messagebox.showinfo("Taken At Fixes", f"Updated Taken At for {successes} file(s).")

        if failures:
            summary = "\n".join(f"- {name}: {error}" for name, error in failures[:5])
            if len(failures) > 5:
                summary += f"\n...and {len(failures) - 5} more."
            messagebox.showerror("Taken At Fixes", f"Some files could not be updated:\n{summary}")

        self._render_records()

    def _apply_taken_fix(self, record: MediaRecord) -> bool:
        if not record.proposed_taken:
            return False

        timestamp = parse_timestamp(record.proposed_taken)
        if timestamp is None:
            raise ValueError("Proposed Taken At value is not a valid timestamp.")

        self._write_taken_metadata(record, timestamp)
        return True

    def _apply_fix_taken_action(self, source: str) -> None:
        selection = self.fix_tree.selection()
        if not selection:
            messagebox.showinfo("Taken At Fixes", "Select at least one row to update.")
            return

        successes = 0
        failures: list[tuple[str, str]] = []

        for item in selection:
            record = self.fix_item_to_record.get(item)
            if not record:
                continue
            try:
                timestamp = self._timestamp_from_source(record, source)
                self._write_taken_metadata(record, timestamp)
                successes += 1
            except Exception as exc:  # pragma: no cover - user-driven IO errors
                failures.append((record.name, str(exc)))

        if failures:
            summary = "\n".join(f"- {name}: {error}" for name, error in failures[:5])
            if len(failures) > 5:
                summary += f"\n...and {len(failures) - 5} more."
            messagebox.showerror("Taken At Fixes", f"Some files could not be updated:\n{summary}")

        msg = (
            f"Updated Taken At for {successes} file(s)." if successes else "No files updated."
        )

        self._render_records()
        if status_var is not None:
            status_var.set(message)
        self.fix_status_var.set(msg)

    def _select_all_in_tree(self, tree: Optional[ttk.Treeview]) -> None:
        if tree is None:
            return
        children = tree.get_children()
        tree.selection_set(children)
        tree.event_generate("<<TreeviewSelect>>")

    def _update_fix_selection_status(self, force: bool = False) -> None:
        if not hasattr(self, "fix_tree"):
            return
        count = len(self.fix_tree.selection())
        if count:
            self.fix_status_var.set(f"{count} file(s) selected.")
        elif force:
            self.fix_status_var.set("Select file(s) then choose a fix.")

    def _update_anomaly_selection_status(self, label: str, force: bool = False) -> None:
        view = self.anomaly_views.get(label)
        if not view:
            return
        tree: ttk.Treeview = view["tree"]
        status_var: Optional[StringVar] = view.get("status_var")
        if status_var is None:
            return
        count = len(tree.selection())
        if count:
            status_var.set(f"{count} file(s) selected.")
        elif force:
            status_var.set("Select file(s) then choose a fix.")

    def _apply_fix_taken_mirror(self, target: str) -> None:
        selection = self.fix_tree.selection()
        if not selection:
            messagebox.showinfo("Taken At Fixes", "Select at least one row to update.")
            return

        successes = 0
        failures: list[tuple[str, str]] = []

        for item in selection:
            record = self.fix_item_to_record.get(item)
            if not record:
                continue
            try:
                if record.taken_ts is None:
                    raise ValueError("Taken At timestamp is not available.")
                if target == "created":
                    self._set_file_times(record, new_created_ts=record.taken_ts)
                elif target == "modified":
                    self._set_file_times(record, new_modified_ts=record.taken_ts)
                else:
                    raise ValueError("Unknown target.")
                successes += 1
            except Exception as exc:  # pragma: no cover - user-driven IO errors
                failures.append((record.name, str(exc)))

        if failures:
            summary = "\n".join(f"- {name}: {error}" for name, error in failures[:5])
            if len(failures) > 5:
                summary += f"\n...and {len(failures) - 5} more."
            messagebox.showerror("Taken At Fixes", f"Some files could not be updated:\n{summary}")

        msg = (
            f"Updated filesystem timestamps for {successes} file(s)."
            if successes
            else "No files updated."
        )

        self._render_records()
        self.fix_status_var.set(msg)

    def _on_right_click(self, event) -> None:
        if not isinstance(event.widget, ttk.Treeview):
            return

        tree = event.widget
        item = tree.identify_row(event.y)
        if not item:
            return
        tree.selection_set(item)
        tree.focus(item)
        if tree is getattr(self, "tree", None):
            self._context_map = self.item_to_record
        elif tree is getattr(self, "fix_tree", None):
            self._context_map = self.fix_item_to_record
        else:
            for view in self.anomaly_views.values():
                if tree is view["tree"]:
                    self._context_map = view["mapping"]
                    break
            else:
                self._context_map = {}
        self._context_tree = tree
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def _get_selected_record(self, tree: ttk.Treeview, mapping: dict[str, MediaRecord]) -> Optional[MediaRecord]:
        selection = tree.selection()
        if not selection:
            return None
        return mapping.get(selection[0])

    def _get_context_record(self) -> Optional[MediaRecord]:
        candidates: list[tuple[Optional[ttk.Treeview], dict[str, MediaRecord]]] = []
        if self._context_tree is not None:
            candidates.append((self._context_tree, self._context_map or {}))
        candidates.append((getattr(self, "tree", None), self.item_to_record))
        if hasattr(self, "fix_tree"):
            candidates.append((self.fix_tree, self.fix_item_to_record))
        for view in self.anomaly_views.values():
            candidates.append((view["tree"], view["mapping"]))

        for tree, mapping in candidates:
            if tree is None:
                continue
            selection = tree.selection()
            if not selection:
                continue
            record = mapping.get(selection[0])
            if record:
                self._context_tree = tree
                self._context_map = mapping
                return record
        return None

    def _open_selected_file(self) -> None:
        record = self._get_context_record()
        if not record:
            messagebox.showinfo("Open File", "Select a file first.")
            return
        path = Path(record.path)
        if not path.exists():
            messagebox.showerror("Open File", f"{path} does not exist.")
            return
        try:
            open_file(path)
        except Exception as exc:  # pragma: no cover - UI path
            messagebox.showerror("Open File", f"Failed to open file:\n{exc}")

    def _reveal_selected_file(self) -> None:
        record = self._get_context_record()
        if not record:
            messagebox.showinfo("Open Location", "Select a file first.")
            return
        path = Path(record.path)
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
