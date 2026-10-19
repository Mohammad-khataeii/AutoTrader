from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class AllocationAdvice:
    accepted: bool
    quote_cap: Decimal
    reasons: tuple[str, ...]
    maximum_observed_correlation: float | None
    profile: str


def allocation_advice(candidate: dict[str, Any], existing: list[dict[str, Any]], *,
                      profile: str = "balanced") -> AllocationAdvice:
    caps = {"conservative": (Decimal(50), .75), "balanced": (Decimal(75), .90), "opportunistic": (Decimal(100), .95)}
    if profile not in caps:
        raise ValueError("unknown_allocation_profile")
    cap, threshold = caps[profile]
    correlations = []
    left = [float(x) for x in candidate.get("return_history_20", [])]
    for metadata in existing:
        if candidate.get("_feature_timestamp") and metadata.get("_feature_timestamp") != candidate["_feature_timestamp"]:
            continue
        right = [float(x) for x in metadata.get("return_history_20", [])]
        if len(left) < 10 or len(left) != len(right):
            continue
        mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
        numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right, strict=True))
        denominator = math.sqrt(sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right))
        if denominator:
            correlations.append(numerator / denominator)
    maximum = max(correlations) if correlations else None
    reasons = ("correlation_concentration_limit",) if maximum is not None and maximum > threshold else ()
    if profile == "conservative" and existing and maximum is None:
        reasons = ("correlation_history_unavailable",)
    return AllocationAdvice(not reasons, cap, reasons, maximum, profile)
