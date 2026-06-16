from __future__ import annotations

import heapq
import time

import psutil


def _safe_limit(limit: int, minimum: int = 1, maximum: int = 200) -> int:
    return max(minimum, min(maximum, int(limit)))


def _to_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _to_pid(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _process_score(row: dict) -> tuple[float, float, int]:
    """进程排序分数：优先 CPU，其次内存，最后用 PID 保证堆比较稳定。"""
    return (
        _to_float(row.get("cpu_percent")),
        _to_float(row.get("memory_percent")),
        _to_pid(row.get("pid")),
    )


def collect_top_processes(
    limit: int = 10,
    include_username: bool = True,
    timeout_seconds: float = 3.0,
) -> list[dict]:
    """采集资源占用靠前的进程。

    MCP 工具必须尽快返回，不能因为单个进程属性读取慢而拖垮整次调用。
    这里采用“轻量字段扫描 + 小顶堆 Top-K + 只给 Top-K 补用户名”的策略：

    - 不在第一轮读取 `username`，它在 Windows / 域账户环境下可能较慢。
    - 不对全部进程做完整排序，只维护 `limit` 大小的小顶堆。
    - 设置软超时预算，超过预算就返回已采集到的最佳结果。
    """

    limit = _safe_limit(limit)
    deadline = time.perf_counter() + max(0.2, float(timeout_seconds))
    attrs = ["pid", "name", "status", "cpu_percent", "memory_percent"]
    heap: list[tuple[tuple[float, float, int], dict]] = []

    for proc in psutil.process_iter(attrs=attrs, ad_value=None):
        if time.perf_counter() >= deadline:
            break
        try:
            info = proc.info
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        row = {
            "pid": info.get("pid"),
            "name": info.get("name"),
            "username": None,
            "status": info.get("status"),
            "cpu_percent": _to_float(info.get("cpu_percent")),
            "memory_percent": round(_to_float(info.get("memory_percent")), 2),
        }
        entry = (_process_score(row), row)
        if len(heap) < limit:
            heapq.heappush(heap, entry)
        elif entry[0] > heap[0][0]:
            heapq.heapreplace(heap, entry)

    rows = [entry[1] for entry in heapq.nlargest(limit, heap, key=lambda item: item[0])]

    if include_username:
        for row in rows:
            if time.perf_counter() >= deadline:
                break
            pid = row.get("pid")
            if pid is None:
                continue
            try:
                row["username"] = psutil.Process(int(pid)).username()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                row["username"] = None

    return rows
