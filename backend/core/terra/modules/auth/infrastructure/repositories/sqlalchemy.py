"""SQLAlchemy implementation of UserRepository."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from terra.modules.auth.domain.entities import GitHubProfile, User
from terra.modules.auth.infrastructure.models import UserModel


def _to_domain(model: UserModel) -> User:
    return User(
        id=model.id,
        github_id=model.github_id,
        github_login=model.github_login,
        display_name=model.display_name,
        avatar_url=model.avatar_url,
        email=model.email,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyUserRepository:
    """Async SQLAlchemy persistence adapter for UserRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.id == user_id))
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def get_by_github_id(self, github_id: int) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.github_id == github_id)
        )
        model = result.scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def upsert_by_github_id(self, profile: GitHubProfile) -> User:
        result = await self._session.execute(
            select(UserModel).where(UserModel.github_id == profile.github_id)
        )
        model = result.scalar_one_or_none()
        now = datetime.now(UTC)

        if model is None:
            model = UserModel(
                github_id=profile.github_id,
                github_login=profile.github_login,
                display_name=profile.display_name,
                avatar_url=profile.avatar_url,
                email=profile.email,
                created_at=now,
                updated_at=now,
            )
            self._session.add(model)
        else:
            model.github_login = profile.github_login
            model.display_name = profile.display_name
            model.avatar_url = profile.avatar_url
            if profile.email is not None:
                model.email = profile.email
            model.updated_at = now

        await self._session.commit()
        await self._session.refresh(model)
        return _to_domain(model)
