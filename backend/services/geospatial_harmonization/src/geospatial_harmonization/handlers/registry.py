"""HandlerRegistry dispatching provider/product requests without silent fallback."""

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.ports import DataHandler


class HandlerRegistry:
    """Registry mapping (provider, product) pairs to specialized DataHandlers."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], DataHandler] = {}
        self._wildcards: dict[str, DataHandler] = {}

    def register(self, handler: DataHandler) -> None:
        """Register handler for its declared provider and supported products."""
        prov = handler.provider.strip().lower()
        for prod in handler.supported_products:
            key = prod.strip().lower()
            if key == "*":
                self._wildcards[prov] = handler
            else:
                self._handlers[(prov, key)] = handler

    def get(self, provider: str, product: str) -> DataHandler:
        """Resolve exact handler without routing specialized failures to generic fallback."""
        prov = provider.strip().lower()
        prod_key = product.strip().lower()
        handler = self._handlers.get((prov, prod_key)) or self._wildcards.get(prov)
        if handler is None:
            raise IncompatibleDatasetError(
                f"No handler registered for provider='{provider}', product='{product}'"
            )
        return handler

    def list_capabilities(self) -> dict[str, tuple[str, ...]]:
        """List registered providers and their supported product identifiers."""
        grouped: dict[str, list[str]] = {}
        for prov, prod in sorted(self._handlers):
            grouped.setdefault(prov, []).append(prod)
        for prov in sorted(self._wildcards):
            grouped.setdefault(prov, []).append("*")
        return {k: tuple(v) for k, v in grouped.items()}
