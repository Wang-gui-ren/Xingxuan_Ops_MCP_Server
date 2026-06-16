from __future__ import annotations

import base64
import json
import platform
import shutil
import socket
import subprocess
import time
from typing import Any

import psutil

from mcp_ops_server.collectors.disk import collect_disk_summary
from mcp_ops_server.collectors.network import collect_listening_ports
from mcp_ops_server.collectors.processes import collect_top_processes
from mcp_ops_server.collectors.system import (
    collect_cpu_summary,
    collect_memory_summary,
    collect_system_summary,
)
from mcp_ops_server.utils.platform import is_windows


def collect_host_profile(
    target: str = "local",
    platform_hint: str = "auto",
    username: str | None = None,
    port: int | None = None,
    timeout_seconds: int = 15,
) -> dict[str, Any]:
    normalized_target = (target or "local").strip()
    normalized_hint = (platform_hint or "auto").strip().lower()

    if _is_local_target(normalized_target):
        return collect_local_host_profile()

    warnings: list[str] = []
    attempts: list[str] = []

    if normalized_hint in {"auto", "linux"}:
        attempts.append("ssh/linux")
        profile = _collect_remote_linux_profile(
            target=normalized_target,
            username=username,
            port=port,
            timeout_seconds=timeout_seconds,
        )
        if profile["collection"]["success"]:
            return profile
        if profile["collection"].get("error"):
            warnings.append(f"linux probe failed: {profile['collection']['error']}")

    if normalized_hint in {"auto", "windows"}:
        attempts.append("winrm/windows")
        profile = _collect_remote_windows_profile(
            target=normalized_target,
            timeout_seconds=timeout_seconds,
        )
        if profile["collection"]["success"]:
            return profile
        if profile["collection"].get("error"):
            warnings.append(f"windows probe failed: {profile['collection']['error']}")

    return {
        "scope": "remote",
        "target": normalized_target,
        "platform": normalized_hint if normalized_hint != "auto" else "unknown",
        "summary": {},
        "hardware": {},
        "storage": {"disks": []},
        "network": {"interfaces": [], "listening_ports": []},
        "top_processes": [],
        "collection": {
            "mode": "unavailable",
            "success": False,
            "timestamp": time.time(),
            "attempts": attempts,
            "warnings": warnings,
            "error": "Unable to collect remote host profile. Check SSH/WinRM reachability and authentication.",
        },
    }


def collect_local_host_profile() -> dict[str, Any]:
    system = collect_system_summary()
    cpu = collect_cpu_summary()
    memory = collect_memory_summary()

    return {
        "scope": "local",
        "target": "local",
        "platform": system["platform"].lower(),
        "summary": {
            "hostname": system["hostname"],
            "fqdn": socket.getfqdn(),
            "os_family": system["platform"],
            "os_name": _local_os_name(),
            "os_version": _local_os_version(),
            "kernel_version": platform.release(),
            "architecture": system["architecture"],
            "python_version": system["python_version"],
            "boot_time": system["boot_time"],
            "boot_time_iso": _to_iso8601(system["boot_time"]),
            "uptime_seconds": system["uptime_seconds"],
        },
        "hardware": {
            "cpu": {
                "model": _local_cpu_model(),
                "logical_count": cpu["logical_count"],
                "physical_count": cpu["physical_count"],
                "usage_percent": cpu["percent"],
                "loadavg": cpu["loadavg"],
            },
            "memory": {
                "total_bytes": memory["virtual"]["total"],
                "used_bytes": memory["virtual"]["used"],
                "available_bytes": memory["virtual"]["available"],
                "usage_percent": memory["virtual"]["percent"],
                "swap_total_bytes": memory["swap"]["total"],
                "swap_used_bytes": memory["swap"]["used"],
                "swap_free_bytes": memory["swap"]["free"],
                "swap_percent": memory["swap"]["percent"],
            },
        },
        "storage": {
            "disks": collect_disk_summary(),
        },
        "network": {
            "interfaces": _collect_local_interfaces(),
            "listening_ports": collect_listening_ports(limit=10),
        },
        "top_processes": collect_top_processes(limit=5),
        "collection": {
            "mode": "local_psutil",
            "success": True,
            "timestamp": time.time(),
            "warnings": [],
        },
    }


def _collect_local_interfaces() -> list[dict[str, Any]]:
    interfaces: list[dict[str, Any]] = []
    for name, addrs in psutil.net_if_addrs().items():
        address_rows: list[dict[str, str]] = []
        for addr in addrs:
            family = getattr(addr.family, "name", str(addr.family))
            address_rows.append(
                {
                    "family": family,
                    "address": addr.address,
                    "netmask": addr.netmask or "",
                }
            )
        interfaces.append(
            {
                "name": name,
                "addresses": address_rows,
            }
        )
    return interfaces


def _local_os_name() -> str:
    if platform.system().lower() == "linux":
        os_release = _read_linux_os_release()
        return os_release.get("PRETTY_NAME") or os_release.get("NAME") or "Linux"
    if platform.system().lower() == "windows":
        release = platform.release()
        return f"Windows {release}".strip()
    return platform.platform()


def _local_os_version() -> str:
    if platform.system().lower() == "linux":
        os_release = _read_linux_os_release()
        return os_release.get("VERSION_ID") or platform.version()
    if platform.system().lower() == "windows":
        win_ver = platform.win32_ver()
        return win_ver[1] or platform.version()
    return platform.version()


def _local_cpu_model() -> str:
    cpu_name = platform.processor().strip()
    if cpu_name:
        return cpu_name

    if platform.system().lower() == "linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass

    return "unknown"


def _read_linux_os_release() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


def _to_iso8601(value: float | None) -> str | None:
    if value is None:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def _collect_remote_linux_profile(
    target: str,
    username: str | None,
    port: int | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    ssh_path = shutil.which("ssh")
    if not ssh_path:
        return _failed_profile(
            scope="remote",
            target=target,
            platform_name="linux",
            mode="ssh",
            error="ssh client is not available on the MCP host.",
        )

    destination = f"{username}@{target}" if username else target
    remote_command = _build_remote_linux_command()
    cmd = [
        ssh_path,
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={timeout_seconds}",
    ]
    if port:
        cmd.extend(["-p", str(port)])
    cmd.extend([destination, remote_command])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 5,
        )
    except Exception as exc:
        return _failed_profile(
            scope="remote",
            target=target,
            platform_name="linux",
            mode="ssh",
            error=str(exc),
        )

    if result.returncode != 0:
        stderr = (result.stderr or "").strip() or "ssh command failed"
        return _failed_profile(
            scope="remote",
            target=target,
            platform_name="linux",
            mode="ssh",
            error=stderr,
        )

    parsed = _parse_json_output(result.stdout)
    if not parsed["ok"]:
        return _failed_profile(
            scope="remote",
            target=target,
            platform_name="linux",
            mode="ssh",
            error=parsed["error"],
        )

    profile = parsed["data"]
    profile["scope"] = "remote"
    profile["target"] = target
    profile["platform"] = "linux"
    profile["collection"] = {
        "mode": "ssh",
        "success": True,
        "timestamp": time.time(),
        "warnings": [],
        "username": username,
        "port": port or 22,
    }
    return profile


def _collect_remote_windows_profile(target: str, timeout_seconds: int) -> dict[str, Any]:
    powershell = _resolve_powershell()
    if not powershell:
        return _failed_profile(
            scope="remote",
            target=target,
            platform_name="windows",
            mode="winrm",
            error="PowerShell is not available on the MCP host.",
        )

    script = _build_remote_windows_script(target=target, timeout_seconds=timeout_seconds)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")

    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 10,
        )
    except Exception as exc:
        return _failed_profile(
            scope="remote",
            target=target,
            platform_name="windows",
            mode="winrm",
            error=str(exc),
        )

    parsed = _parse_json_output(result.stdout)
    if not parsed["ok"]:
        stderr = (result.stderr or "").strip()
        error = parsed["error"]
        if stderr:
            error = f"{error}; stderr={stderr}"
        return _failed_profile(
            scope="remote",
            target=target,
            platform_name="windows",
            mode="winrm",
            error=error,
        )

    data = parsed["data"]
    if "__mcp_error" in data:
        return _failed_profile(
            scope="remote",
            target=target,
            platform_name="windows",
            mode="winrm",
            error=str(data["__mcp_error"]),
        )

    data["scope"] = "remote"
    data["target"] = target
    data["platform"] = "windows"
    data["collection"] = {
        "mode": "winrm",
        "success": True,
        "timestamp": time.time(),
        "warnings": [],
    }
    return data


def _resolve_powershell() -> str | None:
    if is_windows():
        return shutil.which("powershell") or shutil.which("pwsh")
    return shutil.which("pwsh") or shutil.which("powershell")


def _build_remote_linux_command() -> str:
    script = r"""
import json
import os
import platform
import socket
import subprocess
import time


def run(command: str) -> str:
    try:
        return subprocess.check_output(
            command,
            shell=True,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def read_os_release() -> dict[str, str]:
    values = {}
    try:
        with open("/etc/os-release", "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


def cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def uptime_values() -> tuple[float | None, float | None]:
    try:
        with open("/proc/uptime", "r", encoding="utf-8") as handle:
            uptime = float(handle.read().split()[0])
            return time.time() - uptime, uptime
    except Exception:
        return None, None


def memory_values() -> dict[str, int]:
    values = {}
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if ":" not in line:
                    continue
                key, raw_value = line.split(":", 1)
                number = raw_value.strip().split()[0]
                values[key] = int(number) * 1024
    except Exception:
        pass
    return values


def disk_values() -> list[dict]:
    rows = []
    output = run("df -B1 -T -P")
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 7:
            continue
        filesystem, fstype, total, used, free, percent, mountpoint = parts[:7]
        rows.append(
            {
                "device": filesystem,
                "filesystem": fstype,
                "mountpoint": mountpoint,
                "total_bytes": int(total),
                "used_bytes": int(used),
                "free_bytes": int(free),
                "percent": float(percent.rstrip("%")),
            }
        )
    return rows


def interface_values() -> list[dict]:
    interfaces = {}
    output = run("ip -o addr show up")
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name = parts[1]
        family = parts[2]
        address = parts[3]
        interfaces.setdefault(name, {"name": name, "addresses": []})
        interfaces[name]["addresses"].append({"family": family, "address": address})
    return list(interfaces.values())


def listening_ports() -> list[dict]:
    rows = []
    output = run("ss -lntuH")
    for line in output.splitlines()[:10]:
        parts = line.split()
        if len(parts) < 5:
            continue
        rows.append(
            {
                "protocol": parts[0],
                "local_address": parts[4],
            }
        )
    return rows


def top_processes() -> list[dict]:
    rows = []
    output = run("ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -n 6")
    for line in output.splitlines()[1:]:
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        rows.append(
            {
                "pid": int(parts[0]),
                "name": parts[1],
                "cpu_percent": float(parts[2]),
                "memory_percent": float(parts[3]),
            }
        )
    return rows


os_release = read_os_release()
boot_time, uptime_seconds = uptime_values()
meminfo = memory_values()
mem_total = meminfo.get("MemTotal", 0)
mem_available = meminfo.get("MemAvailable", 0)
mem_used = max(mem_total - mem_available, 0)
swap_total = meminfo.get("SwapTotal", 0)
swap_free = meminfo.get("SwapFree", 0)
swap_used = max(swap_total - swap_free, 0)

profile = {
    "summary": {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "os_family": "Linux",
        "os_name": os_release.get("PRETTY_NAME") or os_release.get("NAME") or "Linux",
        "os_version": os_release.get("VERSION_ID") or platform.version(),
        "kernel_version": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "boot_time": boot_time,
        "uptime_seconds": uptime_seconds,
    },
    "hardware": {
        "cpu": {
            "model": cpu_model(),
            "logical_count": os.cpu_count(),
            "physical_count": None,
            "usage_percent": None,
            "loadavg": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        },
        "memory": {
            "total_bytes": mem_total,
            "used_bytes": mem_used,
            "available_bytes": mem_available,
            "usage_percent": round((mem_used / mem_total) * 100, 2) if mem_total else 0,
            "swap_total_bytes": swap_total,
            "swap_used_bytes": swap_used,
            "swap_free_bytes": swap_free,
            "swap_percent": round((swap_used / swap_total) * 100, 2) if swap_total else 0,
        },
    },
    "storage": {
        "disks": disk_values(),
    },
    "network": {
        "interfaces": interface_values(),
        "listening_ports": listening_ports(),
    },
    "top_processes": top_processes(),
}

print(json.dumps(profile, ensure_ascii=False))
"""
    encoded = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return (
        "(command -v python3 >/dev/null 2>&1 && "
        f"python3 -c \"import base64; exec(base64.b64decode('{encoded}'))\") "
        "|| "
        "(command -v python >/dev/null 2>&1 && "
        f"python -c \"import base64; exec(base64.b64decode('{encoded}'))\")"
    )


def _build_remote_windows_script(target: str, timeout_seconds: int) -> str:
    safe_target = target.replace("'", "''")
    return f"""
$ProgressPreference = 'SilentlyContinue'
$target = '{safe_target}'
$scriptBlock = {{
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    $disks = @(
        Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" | ForEach-Object {{
            $size = [int64]($_.Size)
            $free = [int64]($_.FreeSpace)
            [pscustomobject]@{{
                device = $_.DeviceID
                filesystem = $_.FileSystem
                mountpoint = $_.DeviceID
                total_bytes = $size
                used_bytes = $size - $free
                free_bytes = $free
                percent = if ($size -gt 0) {{ [math]::Round((($size - $free) / $size) * 100, 2) }} else {{ 0 }}
            }}
        }}
    )
    $interfaces = @(
        Get-CimInstance Win32_NetworkAdapterConfiguration | Where-Object {{ $_.IPEnabled }} | ForEach-Object {{
            [pscustomobject]@{{
                name = $_.Description
                mac_address = $_.MACAddress
                addresses = @(
                    @($_.IPAddress) | ForEach-Object {{
                        [pscustomobject]@{{
                            family = if ($_ -like '*:*') {{ 'AF_INET6' }} else {{ 'AF_INET' }}
                            address = $_
                        }}
                    }}
                )
            }}
        }}
    )
    $listeners = @()
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {{
        $listeners = @(
            Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 10 |
            ForEach-Object {{
                $procName = $null
                try {{
                    $procName = (Get-Process -Id $_.OwningProcess -ErrorAction Stop).ProcessName
                }} catch {{
                }}
                [pscustomobject]@{{
                    protocol = 'tcp'
                    local_address = "$($_.LocalAddress):$($_.LocalPort)"
                    pid = $_.OwningProcess
                    process_name = $procName
                }}
            }}
        )
    }}
    $topProcesses = @(
        Get-Process |
        Sort-Object CPU -Descending |
        Select-Object -First 5 |
        ForEach-Object {{
            [pscustomobject]@{{
                pid = $_.Id
                name = $_.ProcessName
                cpu_seconds = if ($_.CPU) {{ [math]::Round($_.CPU, 2) }} else {{ 0 }}
                working_set_bytes = [int64]$_.WorkingSet64
            }}
        }}
    )
    [pscustomobject]@{{
        summary = [pscustomobject]@{{
            hostname = $env:COMPUTERNAME
            fqdn = try {{ [System.Net.Dns]::GetHostByName($env:COMPUTERNAME).HostName }} catch {{ $env:COMPUTERNAME }}
            os_family = 'Windows'
            os_name = $os.Caption
            os_version = $os.Version
            kernel_version = $os.Version
            architecture = $os.OSArchitecture
            python_version = $null
            boot_time = $os.LastBootUpTime.ToUniversalTime().ToString('o')
            uptime_seconds = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalSeconds, 0)
        }}
        hardware = [pscustomobject]@{{
            cpu = [pscustomobject]@{{
                model = $cpu.Name
                logical_count = $cpu.NumberOfLogicalProcessors
                physical_count = $cpu.NumberOfCores
                usage_percent = $null
                loadavg = $null
            }}
            memory = [pscustomobject]@{{
                total_bytes = [int64]$os.TotalVisibleMemorySize * 1024
                free_bytes = [int64]$os.FreePhysicalMemory * 1024
                used_bytes = ([int64]$os.TotalVisibleMemorySize - [int64]$os.FreePhysicalMemory) * 1024
                available_bytes = [int64]$os.FreePhysicalMemory * 1024
                usage_percent = if ($os.TotalVisibleMemorySize -gt 0) {{
                    [math]::Round((($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / $os.TotalVisibleMemorySize) * 100, 2)
                }} else {{
                    0
                }}
                swap_total_bytes = [int64]$os.TotalVirtualMemorySize * 1024
                swap_used_bytes = ([int64]$os.TotalVirtualMemorySize - [int64]$os.FreeVirtualMemory) * 1024
                swap_free_bytes = [int64]$os.FreeVirtualMemory * 1024
                swap_percent = if ($os.TotalVirtualMemorySize -gt 0) {{
                    [math]::Round((($os.TotalVirtualMemorySize - $os.FreeVirtualMemory) / $os.TotalVirtualMemorySize) * 100, 2)
                }} else {{
                    0
                }}
            }}
        }}
        storage = [pscustomobject]@{{
            disks = $disks
        }}
        network = [pscustomobject]@{{
            interfaces = $interfaces
            listening_ports = $listeners
        }}
        top_processes = $topProcesses
    }}
}}
try {{
    $profile = Invoke-Command -ComputerName $target -ScriptBlock $scriptBlock -ErrorAction Stop
    $profile | ConvertTo-Json -Depth 6 -Compress
}} catch {{
    [pscustomobject]@{{ __mcp_error = $_.Exception.Message; timeout_seconds = {timeout_seconds} }} | ConvertTo-Json -Compress
}}
"""


def _parse_json_output(stdout: str) -> dict[str, Any]:
    raw = (stdout or "").strip()
    if not raw:
        return {"ok": False, "error": "empty output from remote command"}

    try:
        return {"ok": True, "data": json.loads(raw)}
    except json.JSONDecodeError as exc:
        snippet = raw[:400]
        return {"ok": False, "error": f"{exc.msg}: {snippet}"}


def _failed_profile(
    scope: str,
    target: str,
    platform_name: str,
    mode: str,
    error: str,
) -> dict[str, Any]:
    return {
        "scope": scope,
        "target": target,
        "platform": platform_name,
        "summary": {},
        "hardware": {},
        "storage": {"disks": []},
        "network": {"interfaces": [], "listening_ports": []},
        "top_processes": [],
        "collection": {
            "mode": mode,
            "success": False,
            "timestamp": time.time(),
            "warnings": [],
            "error": error,
        },
    }


def _is_local_target(target: str) -> bool:
    normalized = target.strip().lower()
    local_names = {
        "",
        "local",
        "localhost",
        "127.0.0.1",
        "::1",
        socket.gethostname().lower(),
        socket.getfqdn().lower(),
    }
    return normalized in local_names
