from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml


DEFAULT_USERS_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "users.yaml"
DEFAULT_USER_SALT = "tmp-mcp-default-salt"


@dataclass
class UserRecord:
    username: str
    password_hash: str
    roles: list[str] = field(default_factory=lambda: ["approver"])
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_login: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> UserRecord:
        allowed = {item.name for item in fields(UserRecord)}
        return UserRecord(**{k: v for k, v in data.items() if k in allowed})


class UserConfig:
    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path or os.environ.get("TMP_MCP_USERS_CONFIG") or DEFAULT_USERS_CONFIG_PATH)
        self.salt = os.environ.get("TMP_MCP_USERS_SALT", DEFAULT_USER_SALT)
        self._users: dict[str, UserRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.config_path.exists():
            self._users = {}
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            users_list = data.get("users", [])
            self._users = {user["username"]: UserRecord.from_dict(user) for user in users_list if isinstance(user, dict)}
        except Exception:
            self._users = {}

    def _save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": "user-config-v1",
            "users": [user.to_dict() for user in self._users.values()],
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            try:
                yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            except TypeError:
                f.seek(0)
                f.truncate()
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")

    @staticmethod
    def hash_password(password: str, salt: str) -> str:
        """Hash password using PBKDF2-SHA256."""
        if not password:
            raise ValueError("password cannot be empty")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
        return f"pbkdf2:sha256:100000${dk.hex()}"

    @staticmethod
    def verify_password(password: str, password_hash: str, salt: str) -> bool:
        """Verify password against hash."""
        if not password_hash.startswith("pbkdf2:sha256:100000$"):
            return False
        try:
            computed = UserConfig.hash_password(password, salt)
            return secrets.compare_digest(computed, password_hash)
        except Exception:
            return False

    def create_user(self, username: str, password: str, roles: list[str] | None = None) -> tuple[bool, str]:
        """Create a new user. Returns (success, message)."""
        if not username or not username.strip():
            return False, "username cannot be empty"
        if not password or len(password) < 6:
            return False, "password must be at least 6 characters"
        if username in self._users:
            return False, f"user '{username}' already exists"
        try:
            password_hash = self.hash_password(password, self.salt)
            user = UserRecord(
                username=username.strip(),
                password_hash=password_hash,
                roles=roles or ["approver"],
            )
            self._users[username] = user
            try:
                self._save()
            except Exception:
                self._users.pop(username, None)
                raise
            return True, f"user '{username}' created successfully"
        except Exception as e:
            return False, f"failed to create user: {str(e)}"

    def verify_user(self, username: str, password: str) -> tuple[bool, str | UserRecord]:
        """Verify user credentials. Returns (success, error_or_user)."""
        if not username or not password:
            return False, "username and password required"
        user = self._users.get(username)
        if not user:
            return False, f"user '{username}' not found"
        if not self.verify_password(password, user.password_hash, self.salt):
            return False, "invalid password"
        return True, user

    def update_last_login(self, username: str) -> None:
        """Update last login timestamp."""
        if username in self._users:
            self._users[username].last_login = datetime.now(timezone.utc).isoformat()
            self._save()

    def get_user(self, username: str) -> UserRecord | None:
        """Get user by username."""
        return self._users.get(username)

    def list_users(self) -> list[dict[str, Any]]:
        """List all users (without password hashes)."""
        return [
            {
                "username": user.username,
                "roles": user.roles,
                "created_at": user.created_at,
                "last_login": user.last_login,
            }
            for user in self._users.values()
        ]

    def delete_user(self, username: str) -> tuple[bool, str]:
        """Delete user by username."""
        if username not in self._users:
            return False, f"user '{username}' not found"
        del self._users[username]
        self._save()
        return True, f"user '{username}' deleted"

    def user_exists(self, username: str) -> bool:
        """Check if user exists."""
        return username in self._users


def get_default_user_config() -> UserConfig:
    """Get or create the default user config."""
    return UserConfig()
