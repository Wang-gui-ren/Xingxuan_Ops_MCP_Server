from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "critical"]


class ToolEnvelope(BaseModel):
    ok: bool = True
    risk_level: RiskLevel = "low"
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class SystemSummary(BaseModel):
    platform: str
    hostname: str
    architecture: str
    python_version: str
    boot_time: float | None = None
    uptime_seconds: float | None = None


class DiskSummary(BaseModel):
    mountpoint: str
    filesystem: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class ProcessSummary(BaseModel):
    pid: int
    name: str
    username: str | None = None
    status: str | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None


class PortSummary(BaseModel):
    protocol: str
    local_address: str
    pid: int | None = None
    process_name: str | None = None
