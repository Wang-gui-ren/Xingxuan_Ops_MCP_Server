from __future__ import annotations

import psutil


def collect_listening_ports(limit: int = 50) -> list[dict]:
    rows: list[dict] = []
    for conn in psutil.net_connections(kind="inet"):
        try:
            if conn.status != psutil.CONN_LISTEN:
                continue
            process_name = None
            if conn.pid:
                try:
                    process_name = psutil.Process(conn.pid).name()
                except Exception:
                    process_name = None
            rows.append(
                {
                    "protocol": "tcp/udp",
                    "local_address": f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "",
                    "pid": conn.pid,
                    "process_name": process_name,
                }
            )
        except Exception:
            continue
    return rows[:limit]
