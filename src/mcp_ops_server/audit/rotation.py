from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_ops_server.branding import get_prefixed_env


MANIFEST_VERSION = "xingxuan-mcp-audit-manifest-v1"
LEGACY_MANIFEST_VERSION = "tmp-mcp-audit-manifest-v1"
DEFAULT_MAX_FILE_SIZE_MB = 64.0
DEFAULT_RETENTION_DAYS = 90

_LEGACY_RE = re.compile(r"^audit-(?P<date>\d{8})\.jsonl$")
_SEGMENT_RE = re.compile(r"^audit-(?P<date>\d{8})-(?P<index>\d+)\.jsonl$")


@dataclass(frozen=True)
class AuditRotationPolicy:
    max_file_size_mb: float = DEFAULT_MAX_FILE_SIZE_MB
    retention_days: int = DEFAULT_RETENTION_DAYS

    @property
    def max_file_size_bytes(self) -> int:
        if self.max_file_size_mb <= 0:
            return 0
        return int(self.max_file_size_mb * 1024 * 1024)

    @classmethod
    def from_env(cls) -> "AuditRotationPolicy":
        return cls(
            max_file_size_mb=_float_env("TMP_MCP_AUDIT_ROTATION_MAX_FILE_SIZE_MB", DEFAULT_MAX_FILE_SIZE_MB),
            retention_days=_int_env("TMP_MCP_AUDIT_RETENTION_DAYS", DEFAULT_RETENTION_DAYS),
        )


@dataclass(frozen=True)
class AuditSegment:
    chain_segment_id: str
    audit_file: str
    date_key: str
    segment_index: int
    checked_events: int
    head_hash: str
    file_sha256: str
    file_size_bytes: int
    first_event_timestamp: str | None = None
    last_event_timestamp: str | None = None
    verification_ok: bool = True
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_segment_id": self.chain_segment_id,
            "audit_file": self.audit_file,
            "date_key": self.date_key,
            "segment_index": self.segment_index,
            "checked_events": self.checked_events,
            "head_hash": self.head_hash,
            "file_sha256": self.file_sha256,
            "file_size_bytes": self.file_size_bytes,
            "first_event_timestamp": self.first_event_timestamp,
            "last_event_timestamp": self.last_event_timestamp,
            "verification_ok": self.verification_ok,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class AuditManifest:
    date: str
    date_key: str
    generated_at: str
    segments: list[AuditSegment]
    version: str = MANIFEST_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "date_key": self.date_key,
            "generated_at": self.generated_at,
            "segments": [segment.to_dict() for segment in self.segments],
            "version": self.version,
        }


@dataclass(frozen=True)
class AuditRotationResult:
    rotated: bool
    dry_run: bool
    reason: str
    current_file: str | None
    target_file: str | None
    manifest_file: str | None
    manifest: dict[str, Any] | None
    retention_candidates: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rotated": self.rotated,
            "dry_run": self.dry_run,
            "reason": self.reason,
            "current_file": self.current_file,
            "target_file": self.target_file,
            "manifest_file": self.manifest_file,
            "manifest": self.manifest,
            "retention_candidates": self.retention_candidates,
        }


def today_key() -> str:
    return datetime.now().strftime("%Y%m%d")


def default_manifest_dir(audit_dir: Path) -> Path:
    return audit_dir / "manifests"


def manifest_path(audit_dir: Path, date_key: str) -> Path:
    return default_manifest_dir(audit_dir) / f"audit-manifest-{date_key}.json"


def current_audit_path(
    audit_dir: Path,
    *,
    date_key: str | None = None,
    policy: AuditRotationPolicy | None = None,
) -> Path:
    date_key = date_key or today_key()
    policy = policy or AuditRotationPolicy.from_env()
    audit_dir.mkdir(parents=True, exist_ok=True)

    files = list_audit_files(audit_dir, date_key=date_key)
    if not files:
        return audit_dir / f"audit-{date_key}.jsonl"

    current = files[-1]
    if not _should_rotate(current, policy):
        return current

    return _next_segment_path(audit_dir, date_key, files)


def list_audit_files(audit_dir: Path, *, date_key: str | None = None) -> list[Path]:
    if not audit_dir.exists():
        return []
    files = [path for path in audit_dir.glob("audit-*.jsonl") if path.is_file()]
    if date_key:
        files = [path for path in files if _path_date_key(path) == date_key]
    return sorted(files, key=_audit_sort_key)


def build_audit_manifest(audit_dir: Path, *, date_key: str | None = None) -> AuditManifest:
    date_key = date_key or today_key()
    segments = [_build_segment(path) for path in list_audit_files(audit_dir, date_key=date_key)]
    date_text = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:]}"
    return AuditManifest(
        date=date_text,
        date_key=date_key,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments=segments,
    )


def write_audit_manifest(audit_dir: Path, *, date_key: str | None = None) -> Path:
    date_key = date_key or today_key()
    manifest = build_audit_manifest(audit_dir, date_key=date_key)
    path = manifest_path(audit_dir, date_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def rotate_audit_logs(
    audit_dir: Path,
    *,
    force: bool = False,
    dry_run: bool = True,
    date_key: str | None = None,
    policy: AuditRotationPolicy | None = None,
) -> AuditRotationResult:
    date_key = date_key or today_key()
    policy = policy or AuditRotationPolicy.from_env()
    audit_dir.mkdir(parents=True, exist_ok=True)
    files = list_audit_files(audit_dir, date_key=date_key)
    current = files[-1] if files else None
    retention = [str(path) for path in find_retention_candidates(audit_dir, policy=policy)]

    if current is None:
        return AuditRotationResult(
            rotated=False,
            dry_run=dry_run,
            reason="no audit file exists for the selected date",
            current_file=None,
            target_file=None,
            manifest_file=None,
            manifest=None,
            retention_candidates=retention,
        )

    should_rotate = force or _should_rotate(current, policy)
    target = _next_segment_path(audit_dir, date_key, files)
    if not should_rotate:
        manifest = build_audit_manifest(audit_dir, date_key=date_key)
        return AuditRotationResult(
            rotated=False,
            dry_run=dry_run,
            reason="current audit file is below rotation threshold",
            current_file=str(current),
            target_file=str(target),
            manifest_file=str(manifest_path(audit_dir, date_key)),
            manifest=manifest.to_dict(),
            retention_candidates=retention,
        )

    if dry_run:
        manifest = build_audit_manifest(audit_dir, date_key=date_key)
        return AuditRotationResult(
            rotated=True,
            dry_run=True,
            reason="dry-run rotation planned",
            current_file=str(current),
            target_file=str(target),
            manifest_file=str(manifest_path(audit_dir, date_key)),
            manifest=manifest.to_dict(),
            retention_candidates=retention,
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(exist_ok=True)
    manifest_file = write_audit_manifest(audit_dir, date_key=date_key)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    return AuditRotationResult(
        rotated=True,
        dry_run=False,
        reason="rotation completed",
        current_file=str(current),
        target_file=str(target),
        manifest_file=str(manifest_file),
        manifest=manifest,
        retention_candidates=retention,
    )


def find_retention_candidates(audit_dir: Path, *, policy: AuditRotationPolicy | None = None) -> list[Path]:
    policy = policy or AuditRotationPolicy.from_env()
    if policy.retention_days <= 0:
        return []
    cutoff = datetime.now().timestamp() - policy.retention_days * 86400
    candidates: list[Path] = []
    for path in list_audit_files(audit_dir):
        if path.stat().st_mtime < cutoff:
            candidates.append(path)
    return candidates


def _build_segment(path: Path) -> AuditSegment:
    from mcp_ops_server.audit.verifier import verify_audit_chain

    verification = verify_audit_chain(path)
    first_ts, last_ts, head_hash = _read_event_bounds(path)
    date_key = _path_date_key(path) or today_key()
    segment_index = _path_segment_index(path)
    return AuditSegment(
        chain_segment_id=f"audit-{date_key}-{segment_index}",
        audit_file=str(path),
        date_key=date_key,
        segment_index=segment_index,
        checked_events=verification.checked_events,
        head_hash=head_hash,
        file_sha256=_sha256_file(path),
        file_size_bytes=path.stat().st_size if path.exists() else 0,
        first_event_timestamp=first_ts,
        last_event_timestamp=last_ts,
        verification_ok=verification.ok,
        errors=verification.errors,
    )


def _read_event_bounds(path: Path) -> tuple[str | None, str | None, str]:
    first_ts: str | None = None
    last_ts: str | None = None
    head_hash = ""
    if not path.exists():
        return first_ts, last_ts, head_hash
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = event.get("timestamp")
        if isinstance(timestamp, str):
            first_ts = first_ts or timestamp
            last_ts = timestamp
        head_hash = str(event.get("event_hash") or head_hash)
    return first_ts, last_ts, head_hash


def _should_rotate(path: Path, policy: AuditRotationPolicy) -> bool:
    threshold = policy.max_file_size_bytes
    return threshold > 0 and path.exists() and path.stat().st_size >= threshold


def _next_segment_path(audit_dir: Path, date_key: str, files: list[Path]) -> Path:
    next_index = max((_path_segment_index(path) for path in files), default=0) + 1
    next_index = max(next_index, 2)
    return audit_dir / f"audit-{date_key}-{next_index}.jsonl"


def _audit_sort_key(path: Path) -> tuple[str, int, str]:
    return (_path_date_key(path) or "", _path_segment_index(path), path.name)


def _path_date_key(path: Path) -> str | None:
    match = _SEGMENT_RE.match(path.name) or _LEGACY_RE.match(path.name)
    if not match:
        return None
    return str(match.group("date"))


def _path_segment_index(path: Path) -> int:
    segment = _SEGMENT_RE.match(path.name)
    if segment:
        return int(segment.group("index"))
    legacy = _LEGACY_RE.match(path.name)
    if legacy:
        return 1
    return 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    if path.exists():
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _float_env(name: str, default: float) -> float:
    value = get_prefixed_env(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    value = get_prefixed_env(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default
