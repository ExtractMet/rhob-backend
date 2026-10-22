"""LIMS adapter template (READ-ONLY). Lab samples are persisted separately from continuous
tags with sample time, analysis time and method. Endpoint/credentials from env only
(RHOB_LIMS_URL, RHOB_LIMS_TOKEN)."""
from __future__ import annotations

import os


class LimsAdapter:
    def __init__(self):
        self.url = os.getenv("RHOB_LIMS_URL", "")

    def status(self):
        return {"adapter": "lims", "enabled": bool(self.url), "write_capability": False}

    def fetch(self, heat_id: str):
        if not self.url:
            raise RuntimeError("LIMS adapter not configured (RHOB_LIMS_URL unset)")
        import httpx
        r = httpx.get(f"{self.url}/samples", params={"heat": heat_id},
                      headers={"Authorization": f"Bearer {os.getenv('RHOB_LIMS_TOKEN', '')}"}, timeout=10)
        r.raise_for_status()
        return r.json()
