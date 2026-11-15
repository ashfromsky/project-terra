"""Central registry importing ORM models so Base.metadata discovers all tables."""

from terra.modules.assessments.infrastructure.models import AssessmentModel
from terra.modules.auth.infrastructure.models import UserModel
from terra.modules.regions.infrastructure.models import RegionModel

__all__ = ["AssessmentModel", "RegionModel", "UserModel"]
