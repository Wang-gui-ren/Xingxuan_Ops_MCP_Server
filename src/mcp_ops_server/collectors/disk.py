from __future__ import annotations

import heapq
import os
import time
from pathlib import Path
from typing import Any

import psutil


def collect_disk_summary() -> list[dict]:
    items: list[dict] = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except Exception:
            continue
        items.append(
            {
                "mountpoint": part.mountpoint,
                "filesystem": part.fstype,
                "device": part.device,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent": usage.percent,
            }
        )
    return items


WINDOWS_SKIP_DIR_NAMES = {
    "$recycle.bin",
    "$windows.~bt",
    "$windows.~ws",
    "appdata",
    "application data",
    "config.msi",
    "msocache",
    "pagefile.sys",
    "programdata",
    "recovery",
    "system volume information",
    "windows",
    "windowsapps",
}

POSIX_SKIP_DIRS = {
    "/dev",
    "/proc",
    "/run",
    "/sys",
}


def _safe_limit(value: int, minimum: int = 1, maximum: int = 500) -> int:
    return max(minimum, min(maximum, int(value)))


def _safe_timeout(value: float, minimum: float = 0.5, maximum: float = 60.0) -> float:
    return max(minimum, min(maximum, float(value)))


def _safe_max_files(value: int, minimum: int = 100, maximum: int = 1_000_000) -> int:
    return max(minimum, min(maximum, int(value)))


def _should_skip_dir(path: Path, root: Path) -> bool:
    """跳过高噪声或可能造成全盘扫描卡顿的目录。

    这些目录通常不是运维排障里第一时间要看的业务目录，且 Windows 下
    `C:\Windows`、`System Volume Information`、`AppData` 等路径容易带来
    权限拒绝、海量小文件或重解析点循环。
    """
    name = path.name.lower()
    if name in WINDOWS_SKIP_DIR_NAMES:
        return True

    if os.name != "nt":
        text = str(path)
        return any(text == item or text.startswith(item + os.sep) for item in POSIX_SKIP_DIRS)

    # 如果用户显式扫描某个目录本身，不跳过根目录，只跳过它下面的噪声子树。
    return path != root and name in WINDOWS_SKIP_DIR_NAMES


def _file_result(path: Path, size: int) -> dict[str, Any]:
    # 某些云盘或课件目录会包含特殊 Unicode 空白，Windows 控制台日志可能无法显示。
    safe_path = str(path).replace("\u2005", " ").replace("\u200b", "")
    return {
        "path": safe_path,
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 2),
    }


def find_large_files(
    root_path: str,
    min_size_mb: int = 100,
    limit: int = 20,
    timeout_seconds: float = 8.0,
    max_files_scanned: int = 50_000,
) -> dict[str, Any]:
    """在时间预算内查找大文件。

    该函数面向 MCP 工具调用，优先保证“可返回”和“可解释”，而不是全盘精确扫描。
    算法上使用固定大小的小顶堆维护 Top-K，避免收集所有候选文件后再排序。
    """
    root = Path(root_path).expanduser()
    started = time.perf_counter()
    deadline = started + _safe_timeout(timeout_seconds)
    limit = _safe_limit(limit)
    max_files_scanned = _safe_max_files(max_files_scanned)
    min_size = min_size_mb * 1024 * 1024

    result: dict[str, Any] = {
        "root_path": str(root),
        "min_size_mb": min_size_mb,
        "limit": limit,
        "timeout_seconds": timeout_seconds,
        "max_files_scanned": max_files_scanned,
        "files_scanned": 0,
        "dirs_scanned": 0,
        "dirs_skipped": 0,
        "errors": 0,
        "partial": False,
        "files": [],
    }

    if not root.exists():
        result["error"] = "Root path does not exist."
        return result

    heap: list[tuple[int, str, dict[str, Any]]] = []
    pending = [root]

    while pending:
        if time.perf_counter() >= deadline:
            result["partial"] = True
            result["stop_reason"] = "timeout"
            break
        if result["files_scanned"] >= max_files_scanned:
            result["partial"] = True
            result["stop_reason"] = "max_files_scanned"
            break

        current = pending.pop()
        try:
            if current.is_dir() and _should_skip_dir(current, root):
                result["dirs_skipped"] += 1
                continue
            with os.scandir(current) as entries:
                result["dirs_scanned"] += 1
                for entry in entries:
                    if time.perf_counter() >= deadline:
                        result["partial"] = True
                        result["stop_reason"] = "timeout"
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        result["files_scanned"] += 1
                        if result["files_scanned"] > max_files_scanned:
                            result["partial"] = True
                            result["stop_reason"] = "max_files_scanned"
                            break
                        stat_result = entry.stat(follow_symlinks=False)
                        size = stat_result.st_size
                    except (OSError, PermissionError):
                        result["errors"] += 1
                        continue
                    if size < min_size:
                        continue
                    item = _file_result(Path(entry.path), size)
                    heap_item = (size, item["path"], item)
                    if len(heap) < limit:
                        heapq.heappush(heap, heap_item)
                    elif heap_item[0] > heap[0][0]:
                        heapq.heapreplace(heap, heap_item)
                if result.get("partial"):
                    break
        except (OSError, PermissionError):
            result["errors"] += 1
            continue

    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    result["files"] = [
        item[2]
        for item in heapq.nlargest(limit, heap, key=lambda row: (row[0], row[1]))
    ]
    return result
