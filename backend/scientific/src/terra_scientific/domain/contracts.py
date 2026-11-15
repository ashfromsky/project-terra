"""Domain contracts (ports/protocols) decoupling pure math from persistence and transport."""

from pathlib import Path
from typing import Protocol

from terra_scientific.domain.models.dataset import ScientificDataset, ScientificGridStack
from terra_scientific.domain.models.result import ScientificAssessmentResult


class DatasetLoaderPort(Protocol):
    """Loads prepared GHS or local dataset metadata/artifacts into ScientificDataset."""

    def load_dataset(self, dataset_ref: str) -> ScientificDataset:
        """Load one prepared dataset descriptor and time series."""
        ...

    def load_grid_stack(
        self,
        dataset: ScientificDataset,
        variable_name: str,
    ) -> ScientificGridStack | None:
        """Load optional 3D spatial grid stack for raster computations."""
        ...


class ArtifactWriterPort(Protocol):
    """Persists assessment JSON manifests and spatial outputs."""

    def write_assessment_result(
        self,
        result: ScientificAssessmentResult,
        output_dir: Path,
    ) -> dict[str, str]:
        """Serialize assessment artifacts and return named path manifest."""
        ...
