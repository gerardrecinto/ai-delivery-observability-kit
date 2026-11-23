"""Rate card: how tokens and GPU time turn into dollars."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ModelRate:
    """Prices for one model. Token prices are USD per 1k tokens, GPU price is USD per second."""

    prompt_per_1k: float
    completion_per_1k: float
    gpu_second: float = 0.0


@dataclass(frozen=True)
class RateCard:
    default: ModelRate
    models: dict[str, ModelRate] = field(default_factory=dict)

    def rate_for(self, model: str) -> ModelRate:
        return self.models.get(model, self.default)

    def cost(
        self, model: str, prompt_tokens: int, completion_tokens: int, gpu_seconds: float
    ) -> float:
        if prompt_tokens < 0 or completion_tokens < 0 or gpu_seconds < 0:
            raise ValueError("usage values must be non-negative")
        r = self.rate_for(model)
        return (
            prompt_tokens / 1000 * r.prompt_per_1k
            + completion_tokens / 1000 * r.completion_per_1k
            + gpu_seconds * r.gpu_second
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RateCard:
        def parse(d: dict[str, float]) -> ModelRate:
            return ModelRate(
                prompt_per_1k=float(d["prompt_per_1k"]),
                completion_per_1k=float(d["completion_per_1k"]),
                gpu_second=float(d.get("gpu_second", 0.0)),
            )

        default = parse(data["default"])  # type: ignore[arg-type]
        models_raw: dict[str, dict[str, float]] = data.get("models", {})  # type: ignore[assignment]
        return cls(default=default, models={k: parse(v) for k, v in models_raw.items()})

    @classmethod
    def load(cls, path: str | Path) -> RateCard:
        return cls.from_dict(json.loads(Path(path).read_text()))
