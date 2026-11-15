"""Deterministic JSON assessment and spatial artifact writers."""

import hashlib
import json
from pathlib import Path

from terra_scientific.domain.models.result import ScientificAssessmentResult


class JsonArtifactWriter:
    """Writes reproducible JSON assessment manifests to a target directory."""

    def write_assessment_result(
        self,
        result: ScientificAssessmentResult,
        output_dir: Path,
    ) -> dict[str, str]:
        """Persist assessment result JSON and return named artifact path mapping."""
        target_dir = output_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        out_file = target_dir / f"{result.assessment_id}_result.json"
        payload = json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True)
        out_file.write_text(payload, encoding="utf-8")
        sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return {
            "assessment_result_json": str(out_file),
            "assessment_result_sha256": sha,
        }
