"""Synthetic measurement source (DEMO_SYNTHETIC) and adapter status aggregation."""
from __future__ import annotations

from .lims_adapter import LimsAdapter
from .mqtt_adapter import MqttReadOnly
from .opcua_adapter import OpcUaReadOnlyAdapter


def adapter_status() -> dict:
    return {"synthetic": {"adapter": "synthetic plant twin", "enabled": True, "note": "seeded perturbed twin - SYNTHETIC"},
            "opcua": OpcUaReadOnlyAdapter().status(), "lims": LimsAdapter().status(), "mqtt": MqttReadOnly().status(),
            "historian_replay": {"adapter": "csv historian export", "enabled": True, "file": "datasets/synthetic_live_trace.csv"},
            "plant_command_path": "NONE (by design)"}
