"""Export the FastAPI OpenAPI schema without connecting to a database or starting HTTP."""

import argparse
import json
from pathlib import Path
from typing import Any

from terra.config import Settings
from terra.main import create_app


def build_openapi_schema() -> dict[str, Any]:
    """Build the full TERRA Core OpenAPI 3.1 schema in memory."""
    app = create_app(Settings(environment="test"))
    return app.openapi()


def export_openapi_schema(output_path: Path) -> Path:
    """Write formatted OpenAPI JSON to ``output_path`` only when content changes."""
    schema = build_openapi_schema()
    rendered = json.dumps(schema, indent=2) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") == rendered:
        return output_path
    output_path.write_text(rendered, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export TERRA Core OpenAPI specification for frontend contract generation."
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Target path for the exported OpenAPI JSON schema.",
    )
    args = parser.parse_args()
    export_openapi_schema(args.output)


if __name__ == "__main__":
    main()
