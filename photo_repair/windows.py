"""Windows filesystem timestamp helpers."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Optional

FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 0x00000003
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_WRITE_ATTRIBUTES = 0x00000100
EPOCH_AS_FILETIME = 11644473600 * 10**7
HUNDREDS_OF_NANOSECONDS = 10**7


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _timestamp_to_filetime(timestamp: float) -> FILETIME:
    intervals = int(timestamp * HUNDREDS_OF_NANOSECONDS + EPOCH_AS_FILETIME)
    return FILETIME(intervals & 0xFFFFFFFF, intervals >> 32)


def set_file_times(
    path: Path,
    *,
    created_ts: Optional[float] = None,
    modified_ts: Optional[float] = None,
    accessed_ts: Optional[float] = None,
) -> None:
    """Set Windows file timestamps while preserving unspecified values."""
    if not sys.platform.startswith("win"):
        raise RuntimeError("Filesystem timestamp repair is available only on Windows.")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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

    stats = path.stat()
    creation = created_ts if created_ts is not None else stats.st_ctime
    modified = modified_ts if modified_ts is not None else stats.st_mtime
    accessed = accessed_ts if accessed_ts is not None else stats.st_atime

    handle = kernel32.CreateFileW(
        str(path),
        FILE_WRITE_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    invalid_handle_value = wintypes.HANDLE(-1).value
    if handle == invalid_handle_value:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        creation_ft = _timestamp_to_filetime(creation)
        access_ft = _timestamp_to_filetime(accessed)
        modified_ft = _timestamp_to_filetime(modified)
        if not kernel32.SetFileTime(
            handle,
            ctypes.byref(creation_ft),
            ctypes.byref(access_ft),
            ctypes.byref(modified_ft),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)
