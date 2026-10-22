"""JSON serialization without NaN/Infinity (replaced by null) and numpy scalars converted."""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
from fastapi.responses import JSONResponse


def clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    if hasattr(o, "model_dump"):
        return clean(o.model_dump(mode="json"))
    return o


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(clean(content), allow_nan=False, separators=(",", ":")).encode("utf-8")
