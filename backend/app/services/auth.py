from __future__ import annotations

from datetime import datetime, timezone

from ..config import settings
from ..models import AuthSession, User
from ..repositories import SessionRepository, UserRepository


class AuthService:
    def __init__(self, users: UserRepository, sessions: SessionRepository) -> None:
        self.users = users
        self.sessions = sessions

    def login(self, username: str, password: str) -> tuple[User, AuthSession]:
        user = self._find_user(username)
        if user is None or not self._password_matches(user.id, password):
            raise ValueError("invalid username or password")
        session = AuthSession(user_id=user.id)
        return user, self.sessions.save(session)

    def get_user_by_token(self, token: str) -> User:
        session = self.sessions.get(token)
        if session is None:
            raise KeyError(token)
        session.last_seen_at = datetime.now(timezone.utc)
        self.sessions.save(session)
        return self.users.ensure(session.user_id)

    def logout(self, token: str) -> None:
        self.sessions.delete(token)

    def _find_user(self, username: str) -> User | None:
        needle = username.strip().lower()
        for user in self.users.list():
            if user.id.lower() == needle or user.name.lower() == needle:
                return user
        return None

    @staticmethod
    def _password_matches(user_id: str, password: str) -> bool:
        expected = {
            "admin": settings.admin_password,
            "member": settings.member_password,
        }.get(user_id)
        return bool(expected) and password == expected
