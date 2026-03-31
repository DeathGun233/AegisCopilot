from __future__ import annotations

from ..models import User, UserRole
from ..repositories import UserRepository


class UserService:
    def __init__(self, repo: UserRepository) -> None:
        self.repo = repo

    def list_users(self) -> list[User]:
        return self.repo.list()

    def summarize_user(self, user: User) -> dict[str, object]:
        is_admin = user.role == UserRole.admin
        permissions = ["knowledge:read"]
        if is_admin:
            permissions.extend(["knowledge:write", "model:write", "conversation:delete"])
        return {
            **user.model_dump(mode="json"),
            "role_label": "Administrator" if is_admin else "Member",
            "can_manage_knowledge": is_admin,
            "can_manage_models": is_admin,
            "permissions": permissions,
        }

    def list_user_summaries(self) -> list[dict[str, object]]:
        return [self.summarize_user(user) for user in self.list_users()]

    def get_user(self, user_id: str) -> User:
        user = self.repo.get(user_id)
        if user is None:
            raise KeyError(user_id)
        return user
