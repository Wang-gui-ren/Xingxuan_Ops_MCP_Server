from __future__ import annotations

import platform
import socket
import time

import psutil


def collect_system_summary() -> dict:
    boot_time = None
    uptime_seconds = None
    try:
        boot_time = psutil.boot_time()
        uptime_seconds = max(0.0, time.time() - boot_time)
    except Exception:
        pass

    return {
        "platform": platform.system(),
        "hostname": socket.gethostname(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "boot_time": boot_time,
        "uptime_seconds": uptime_seconds,
    }


def collect_cpu_summary() -> dict:
    loadavg = None
    try:
        loadavg = list(getattr(psutil, "getloadavg", lambda: ())())
    except Exception:
        loadavg = None

    return {
        "logical_count": psutil.cpu_count(logical=True),
        "physical_count": psutil.cpu_count(logical=False),
        "percent": psutil.cpu_percent(interval=0.3),
        "loadavg": loadavg,
    }


def collect_memory_summary() -> dict:
    vm = psutil.virtual_memory()
    sm = psutil.swap_memory()
    return {
        "virtual": {
            "total": vm.total,
            "used": vm.used,
            "available": vm.available,
            "percent": vm.percent,
        },
        "swap": {
            "total": sm.total,
            "used": sm.used,
            "free": sm.free,
            "percent": sm.percent,
        },
    }
