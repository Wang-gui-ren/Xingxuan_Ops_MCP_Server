from __future__ import annotations

import subprocess

from mcp_ops_server.utils.platform import is_linux, is_windows


def get_service_status(service: str) -> dict:
    if is_linux():
        cmd = ["systemctl", "status", service, "--no-pager", "--lines", "20"]
    elif is_windows():
        cmd = ["sc", "query", service]
    else:
        return {
            "service": service,
            "supported": False,
            "summary": "Unsupported platform for service query.",
        }

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {
            "service": service,
            "supported": True,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as exc:
        return {
            "service": service,
            "supported": True,
            "error": str(exc),
        }
