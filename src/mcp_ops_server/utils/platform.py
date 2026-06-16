from __future__ import annotations

import platform


def is_windows() -> bool:
    return platform.system().lower() == "windows"


def is_linux() -> bool:
    return platform.system().lower() == "linux"


def current_platform() -> str:
    return platform.system().lower()
