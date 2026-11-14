"""Central registry importing ORM models so Base.metadata discovers all tables."""

from terra.modules.auth.infrastructure.models import UserModel

__all__ = ["UserModel"]
