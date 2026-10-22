"""READ-ONLY OPC UA adapter template.

Endpoint, security policy and certificates come ONLY from environment variables
(RHOB_OPCUA_ENDPOINT, RHOB_OPCUA_CERT, RHOB_OPCUA_KEY). No write methods exist in this class
by design (no plant actuation from the application). Requires the optional `asyncua`
package and an OT-approved network path (DMZ / data diode / edge gateway)."""
from __future__ import annotations

import os


class OpcUaReadOnlyAdapter:
    def __init__(self):
        self.endpoint = os.getenv("RHOB_OPCUA_ENDPOINT", "")
        self.enabled = bool(self.endpoint)

    def status(self) -> dict:
        try:
            import asyncua  # noqa: F401
            lib = True
        except Exception:
            lib = False
        return {"adapter": "opcua", "enabled": self.enabled, "library_installed": lib, "write_capability": False,
                "endpoint_configured": bool(self.endpoint), "note": "read-only; configure via env; requires OT approval"}

    async def read_tags(self, node_ids: list[str]) -> dict:
        if not self.enabled:
            raise RuntimeError("OPC UA adapter not configured (RHOB_OPCUA_ENDPOINT unset)")
        from asyncua import Client  # optional dependency
        out = {}
        async with Client(url=self.endpoint) as client:
            for nid in node_ids:
                node = client.get_node(nid)
                dv = await node.read_data_value()
                out[nid] = {"value": dv.Value.Value, "source_timestamp": str(dv.SourceTimestamp),
                            "status": str(dv.StatusCode.name)}
        return out
