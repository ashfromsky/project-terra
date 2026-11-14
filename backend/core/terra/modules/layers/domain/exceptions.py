"""Domain exceptions for map layers."""


class LayerNotFoundError(Exception):
    """Raised when a requested layer ID does not exist in the catalog."""
