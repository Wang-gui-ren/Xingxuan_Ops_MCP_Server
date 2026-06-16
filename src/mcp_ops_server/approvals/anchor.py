from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp_ops_server.branding import get_prefixed_env, version_matches
from mcp_ops_server.approvals.store import default_approval_dir
from mcp_ops_server.approvals.verifier import verify_approval_chain
from mcp_ops_server.audit.logger import GENESIS_HASH


ANCHOR_VERSION = "xingxuan-mcp-approval-anchor-v1"
LEGACY_ANCHOR_VERSION = "tmp-mcp-approval-anchor-v1"
APPROVAL_ANCHOR_SECRET_ENV = "XINGXUAN_MCP_APPROVAL_ANCHOR_SECRET"
LEGACY_APPROVAL_ANCHOR_SECRET_ENV = "TMP_MCP_APPROVAL_ANCHOR_SECRET"


@dataclass(frozen=True)
class ApprovalAnchor:
    """审批账本外部锚点。

    锚点记录某个审批 JSONL 文件在某一时刻的链尾 hash 和文件摘要。
    第一版写入本地独立 JSONL；后续可将同一 payload 上传到集中审计或透明日志。
    """

    anchor_id: str
    timestamp: str
    approval_file: str
    checked_records: int
    head_hash: str
    file_sha256: str
    file_size_bytes: int
    signer: str
    signature: str | None
    signature_algorithm: str
    transparency_log_hint: str
    version: str = ANCHOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "timestamp": self.timestamp,
            "approval_file": self.approval_file,
            "checked_records": self.checked_records,
            "head_hash": self.head_hash,
            "file_sha256": self.file_sha256,
            "file_size_bytes": self.file_size_bytes,
            "signer": self.signer,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
            "transparency_log_hint": self.transparency_log_hint,
            "version": self.version,
        }


@dataclass(frozen=True)
class ApprovalAnchorVerification:
    ok: bool
    approval_file: str
    anchor_file: str
    checked_records: int = 0
    anchor_id: str | None = None
    head_hash: str | None = None
    anchored_head_hash: str | None = None
    file_sha256: str | None = None
    anchored_file_sha256: str | None = None
    signature_ok: bool | None = None
    summary: str = ""
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "approval_file": self.approval_file,
            "anchor_file": self.anchor_file,
            "checked_records": self.checked_records,
            "anchor_id": self.anchor_id,
            "head_hash": self.head_hash,
            "anchored_head_hash": self.anchored_head_hash,
            "file_sha256": self.file_sha256,
            "anchored_file_sha256": self.anchored_file_sha256,
            "signature_ok": self.signature_ok,
            "summary": self.summary,
            "errors": self.errors,
        }


def default_anchor_dir(approval_dir: Path | None = None) -> Path:
    configured = get_prefixed_env("TMP_MCP_APPROVAL_ANCHOR_DIR")
    if configured:
        return Path(configured)
    return (approval_dir or default_approval_dir()) / "anchors"


def anchor_file_path(anchor_dir: Path) -> Path:
    return anchor_dir / "anchors.jsonl"


def create_approval_anchor(
    approval_file: Path | None = None,
    *,
    anchor_dir: Path | None = None,
    signer: str = "xingxuan-mcp-local",
    transparency_log_hint: str = "local-jsonl-anchor",
    secret: str | None = None,
) -> ApprovalAnchor:
    ledger = _resolve_approval_file(approval_file)
    verification = verify_approval_chain(ledger)
    if not verification.ok:
        raise ValueError(f"Cannot anchor invalid approval chain: {verification.summary}")
    head_hash = _read_last_event_hash_from_verified_file(ledger)
    file_sha256 = _sha256_file(ledger)
    size = ledger.stat().st_size
    secret = _resolve_secret(secret)

    unsigned = {
        "anchor_id": uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "approval_file": str(ledger),
        "checked_records": verification.checked_records,
        "head_hash": head_hash,
        "file_sha256": file_sha256,
        "file_size_bytes": size,
        "signer": signer,
        "signature_algorithm": "hmac-sha256" if secret else "unsigned",
        "transparency_log_hint": transparency_log_hint,
        "version": ANCHOR_VERSION,
    }
    signature = _sign_anchor_payload(unsigned, secret) if secret else None
    anchor = ApprovalAnchor(signature=signature, **unsigned)
    write_anchor(anchor, anchor_dir=anchor_dir or default_anchor_dir(ledger.parent))
    return anchor


def write_anchor(anchor: ApprovalAnchor, *, anchor_dir: Path) -> Path:
    anchor_dir.mkdir(parents=True, exist_ok=True)
    path = anchor_file_path(anchor_dir)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(anchor.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        file.write("\n")
    return path


def verify_approval_anchor(
    approval_file: Path | None = None,
    *,
    anchor_dir: Path | None = None,
    secret: str | None = None,
) -> ApprovalAnchorVerification:
    ledger = _resolve_approval_file(approval_file)
    anchor_dir = anchor_dir or default_anchor_dir(ledger.parent)
    anchor_path = anchor_file_path(anchor_dir)
    chain = verify_approval_chain(ledger)
    if not chain.ok:
        return ApprovalAnchorVerification(
            ok=False,
            approval_file=str(ledger),
            anchor_file=str(anchor_path),
            checked_records=chain.checked_records,
            summary=f"审批锚点校验失败：审批账本哈希链本身无效。{chain.summary}",
            errors=chain.errors,
        )

    anchor = find_latest_anchor_for_file(ledger, anchor_path)
    if anchor is None:
        return ApprovalAnchorVerification(
            ok=False,
            approval_file=str(ledger),
            anchor_file=str(anchor_path),
            checked_records=chain.checked_records,
            summary="审批锚点校验失败：未找到对应 approval_file 的锚点记录。",
            errors=[f"anchor not found for file: {ledger}"],
        )

    current_head = _read_last_event_hash_from_verified_file(ledger)
    current_file_sha256 = _sha256_file(ledger)
    errors: list[str] = []
    if current_head != anchor.get("head_hash"):
        errors.append("head_hash mismatch")
    if current_file_sha256 != anchor.get("file_sha256"):
        errors.append("file_sha256 mismatch")

    secret = _resolve_secret(secret)
    signature_ok: bool | None = None
    if anchor.get("signature_algorithm") == "hmac-sha256":
        if not secret:
            signature_ok = False
            errors.append("signature secret missing")
        else:
            signature_ok = _verify_anchor_signature(anchor, secret)
            if not signature_ok:
                errors.append("anchor signature mismatch")
    elif anchor.get("signature_algorithm") == "unsigned":
        signature_ok = None
    else:
        signature_ok = False
        errors.append(f"unsupported signature algorithm: {anchor.get('signature_algorithm')}")

    ok = not errors
    return ApprovalAnchorVerification(
        ok=ok,
        approval_file=str(ledger),
        anchor_file=str(anchor_path),
        checked_records=chain.checked_records,
        anchor_id=str(anchor.get("anchor_id") or ""),
        head_hash=current_head,
        anchored_head_hash=str(anchor.get("head_hash") or ""),
        file_sha256=current_file_sha256,
        anchored_file_sha256=str(anchor.get("file_sha256") or ""),
        signature_ok=signature_ok,
        summary=(
            "审批锚点校验通过：审批账本哈希链、末端 hash、文件摘要和签名均匹配。"
            if ok and signature_ok is True
            else "审批锚点校验通过：审批账本哈希链、末端 hash 和文件摘要匹配；锚点未配置签名。"
            if ok
            else "审批锚点校验失败：审批账本与锚点记录不一致。"
        ),
        errors=errors,
    )


def find_latest_anchor_for_file(approval_file: Path, anchor_path: Path) -> dict[str, Any] | None:
    if not anchor_path.exists():
        return None
    target = str(approval_file)
    latest: dict[str, Any] | None = None
    for line in anchor_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            anchor = json.loads(line)
        except json.JSONDecodeError:
            continue
        if anchor.get("approval_file") == target and version_matches(
            anchor.get("version"),
            ANCHOR_VERSION,
            LEGACY_ANCHOR_VERSION,
        ):
            latest = anchor
    return latest


def _resolve_approval_file(path: Path | None) -> Path:
    if path is None:
        return default_approval_dir() / "approvals.jsonl"
    if path.suffix == ".jsonl":
        return path
    return path / "approvals.jsonl"


def _read_last_event_hash_from_verified_file(approval_file: Path) -> str:
    last_hash = GENESIS_HASH
    for line in approval_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        last_hash = str(record.get("event_hash") or GENESIS_HASH)
    return last_hash


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _resolve_secret(secret: str | None) -> str | None:
    if secret is not None:
        return secret
    return get_prefixed_env(LEGACY_APPROVAL_ANCHOR_SECRET_ENV)


def _sign_anchor_payload(payload_without_signature: dict[str, Any], secret: str) -> str:
    canonical = json.dumps(payload_without_signature, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def _verify_anchor_signature(anchor: dict[str, Any], secret: str) -> bool:
    unsigned = {key: value for key, value in anchor.items() if key != "signature"}
    expected = _sign_anchor_payload(unsigned, secret)
    actual = str(anchor.get("signature") or "")
    return hmac.compare_digest(expected, actual)
