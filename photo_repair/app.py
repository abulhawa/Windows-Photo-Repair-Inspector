"""Compatibility entry point for the desktop application."""

from .ui import PhotoRepairApp, _selection_range, main

__all__ = ["PhotoRepairApp", "_selection_range", "main"]


if __name__ == "__main__":
    main()
