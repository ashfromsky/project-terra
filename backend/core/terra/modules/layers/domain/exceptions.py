"""Domain exceptions for map layers."""


class LayerNotFoundError(Exception):
    """Raised when a requested layer ID does not exist in the catalog."""


class LayerDatasetUnavailableError(Exception):
    """Raised when a catalog layer has no renderable ingested dataset."""


class LayerRasterProxyError(Exception):
    """Raised when upstream raster rendering or point query fails."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
