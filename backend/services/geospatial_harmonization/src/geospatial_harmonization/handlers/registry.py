"""HandlerRegistry dispatching provider/product requests without silent fallback."""

from geospatial_harmonization.domain.exceptions import IncompatibleDatasetError
from geospatial_harmonization.domain.ports import DataHandler


class HandlerRegistry:
    """Registry mapping (provider, product) pairs to specialized DataHandlers."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], DataHandler] = {}
        self._wildcards: dict[str, DataHandler] = {}
        self._capabilities: dict[str, dict[str, str]] = {}

    def register(self, handler: DataHandler) -> None:
        """Register handler for its declared provider and supported products."""
        prov = handler.provider.strip().lower()
        declared = self._capabilities.setdefault(prov, {})
        for prod in handler.supported_products:
            canonical = prod.strip()
            key = canonical.lower()
            declared[key] = canonical
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
        """List registered providers and their canonically cased product identifiers."""
        return {
            prov: tuple(sorted(products.values()))
            for prov, products in sorted(self._capabilities.items())
        }
