"""External integration ports for ScientificAssessment execution."""

from typing import Protocol

from terra_scientific.domain.models.dataset import ScientificDataset


class GhsDatasetClient(Protocol):
    """Port for resolving prepared datasets from Geospatial Harmonization Service."""

    async def fetch_dataset(self, dataset_id: str) -> ScientificDataset:
        """Fetch prepared GHS dataset metadata and map it to ScientificDataset."""
        ...
