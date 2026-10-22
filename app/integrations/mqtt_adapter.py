"""MQTT subscriber template (READ-ONLY; subscribe only, never publish to plant topics).
Broker from env (RHOB_MQTT_BROKER); optional `paho-mqtt` dependency."""
from __future__ import annotations

import os


class MqttReadOnly:
    def __init__(self):
        self.broker = os.getenv("RHOB_MQTT_BROKER", "")

    def status(self):
        try:
            import paho.mqtt.client  # noqa: F401
            lib = True
        except Exception:
            lib = False
        return {"adapter": "mqtt", "enabled": bool(self.broker), "library_installed": lib, "publish_capability": False}
