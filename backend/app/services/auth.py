from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..models import AuthAuditEvent, AuthSession, User
from ..repositories import AuthAuditRepository, SessionRepository, UserRepository


_PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
_PASSWORD_HASH_ITERATIONS = 260_000


def hash_password(password: str, *, salt: str | None = None, iterations: int = _PASSWORD_HASH_ITERATIONS) -> str:
    selected_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        selected_salt.encode("ascii"),
        iterations,
    ).hex()
    return f"{_PASSWORD_HASH_SCHEME}${iterations}${selected_salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations_raw, salt, expected = password_hash.split("$", 3)
        iterations = int(iterations_raw)
    except ValueError:
        return False
    if scheme != _PASSWORD_HASH_SCHEME or iterations <= 0 or not salt or not expected:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("ascii"),
        iterations,
    ).hex()
    return hmac.compare_digest(actual, expected)


class AuthService:
    _DEFAULT_PASSWORDS = {
        "admin": "admin123",
        "member": "member123",
    }

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        audit_events: AuthAuditRepository | None = None,
    ) -> None:
        self.users = users
        self.sessions = sessions
        self.audit_events = audit_events
        self._failed_logins: dict[str, tuple[int, datetime]] = {}

    def login(self, username: str, password: str) -> tuple[User, AuthSession]:
        login_key = username.strip().lower()
        if self._is_locked(login_key):
            self._record_audit(
                "login_failed",
                success=False,
                username=username,
                reason="too_many_failed_attempts",
            )
            raise ValueError("Too many failed login attempts. Please try again later.")

        user = self._find_user(username)
        if user is None or not self._password_matches(user.id, password):
            self._register_failed_login(login_key)
            self._record_audit(
                "login_failed",
                success=False,
                username=username,
                user_id=user.id if user else "",
                reason="invalid_credentials",
            )
            raise ValueError("用户名或密码错误")
        try:
            self._validate_password_policy(user.id)
        except ValueError as exc:
            self._register_failed_login(login_key)
            self._record_audit(
                "login_failed",
                success=False,
                username=username,
                user_id=user.id,
                reason="password_policy",
            )
            raise exc

        self._clear_failed_login(login_key)
        now = datetime.now(timezone.utc)
        session = AuthSession(
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(minutes=max(settings.auth_session_ttl_minutes, 1)),
        )
        saved_session = self.sessions.save(session)
        self._record_audit(
            "login_succeeded",
            success=True,
            username=username,
            user_id=user.id,
        )
        return user, saved_session

    def get_user_by_token(self, token: str) -> User:
        session = self.sessions.get(token)
        if session is None:
            raise KeyError(token)
        session.last_seen_at = datetime.now(timezone.utc)
        session.expires_at = session.last_seen_at + timedelta(minutes=max(settings.auth_session_ttl_minutes, 1))
        self.sessions.save(session)
        return self.users.ensure(session.user_id)

    def logout(self, token: str) -> None:
        session = self.sessions.get(token)
        deleted = self.sessions.delete(token)
        self._record_audit(
            "logout",
            success=deleted,
            user_id=session.user_id if session else "",
            reason="current_session",
        )

    def revoke_sessions(self, *, token: str | None = None, user_id: str | None = None, actor_id: str = "") -> int:
        if not token and not user_id:
            raise ValueError("token or user_id is required")

        revoked = 0
        target_user_id = user_id or ""
        if token:
            session = self.sessions.get(token)
            if session is not None:
                target_user_id = session.user_id
            if self.sessions.delete(token):
                revoked += 1
        if user_id:
            revoked += self.sessions.delete_for_user(user_id)

        self._record_audit(
            "session_revoked",
            success=revoked > 0,
            user_id=target_user_id,
            actor_id=actor_id,
            reason="admin_revoke",
        )
        return revoked

    def list_audit_events(self, limit: int = 100) -> list[AuthAuditEvent]:
        if self.audit_events is None:
            return []
        return self.audit_events.list(limit=max(1, min(limit, 500)))

    def _find_user(self, username: str) -> User | None:
        needle = username.strip().lower()
        for user in self.users.list():
            if user.id.lower() == needle or user.name.lower() == needle:
                return user
        return None

    def _password_matches(self, user_id: str, password: str) -> bool:
        configured_hash = self._configured_password_hash(user_id)
        if configured_hash:
            return verify_password(password, configured_hash)
        expected = self._configured_password(user_id)
        return bool(expected) and hmac.compare_digest(password, expected)

    def _validate_password_policy(self, user_id: str) -> None:
        if settings.allow_demo_auth:
            return
        if self._configured_password_hash(user_id):
            return
        configured_password = self._configured_password(user_id)
        if configured_password and configured_password == self._DEFAULT_PASSWORDS.get(user_id):
            raise ValueError("当前环境禁止使用默认演示密码，请先通过环境变量配置安全密码")
        raise ValueError("Hashed password configuration is required when demo auth is disabled.")

    @staticmethod
    def _configured_password(user_id: str) -> str:
        return {
            "admin": settings.admin_password,
            "member": settings.member_password,
        }.get(user_id, "")

    @staticmethod
    def _configured_password_hash(user_id: str) -> str:
        return {
            "admin": settings.admin_password_hash,
            "member": settings.member_password_hash,
        }.get(user_id, "")

    def _is_locked(self, login_key: str) -> bool:
        if settings.auth_max_failed_attempts <= 0:
            return False
        record = self._failed_logins.get(login_key)
        if record is None:
            return False
        attempts, locked_until = record
        if attempts < settings.auth_max_failed_attempts:
            return False
        if locked_until > datetime.now(timezone.utc):
            return True
        self._failed_logins.pop(login_key, None)
        return False

    def _register_failed_login(self, login_key: str) -> None:
        if settings.auth_max_failed_attempts <= 0:
            return
        attempts, _ = self._failed_logins.get(login_key, (0, datetime.min.replace(tzinfo=timezone.utc)))
        attempts += 1
        locked_until = datetime.min.replace(tzinfo=timezone.utc)
        if attempts >= settings.auth_max_failed_attempts:
            locked_until = datetime.now(timezone.utc) + timedelta(minutes=max(settings.auth_lockout_minutes, 1))
        self._failed_logins[login_key] = (attempts, locked_until)

    def _clear_failed_login(self, login_key: str) -> None:
        self._failed_logins.pop(login_key, None)

    def _record_audit(
        self,
        event: str,
        *,
        success: bool,
        username: str = "",
        user_id: str = "",
        actor_id: str = "",
        reason: str = "",
    ) -> None:
        if self.audit_events is None:
            return
        self.audit_events.record(
            AuthAuditEvent(
                event=event,
                success=success,
                username=username,
                user_id=user_id,
                actor_id=actor_id,
                reason=reason,
            )
        )
