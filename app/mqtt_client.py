from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from app.config import settings
from app.state import attendance_state

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _try_parse_json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def _message_to_record(topic: str, payload: bytes) -> dict[str, Any]:
    parsed = _try_parse_json(payload)

    record: dict[str, Any] = {
        "timestamp": _utc_now_iso(),
        "topic": topic,
        "payload_raw": payload.decode("utf-8", errors="replace"),
        "payload_json": parsed,
    }
    return record


class MQTTGateway:
    def __init__(self) -> None:
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.mqtt_client_id)

        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def start(self) -> None:
        logger.info("Connecting to MQTT broker %s:%s", settings.mqtt_broker_host, settings.mqtt_broker_port)
        self.client.connect(settings.mqtt_broker_host, settings.mqtt_broker_port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
        logger.info("MQTT connected with reason code: %s", reason_code)

        subscriptions = [
            (settings.mqtt_topic_rfid, settings.mqtt_qos),
            (settings.mqtt_topic_attendance_events, settings.mqtt_qos),
            (settings.mqtt_topic_attendance_state, settings.mqtt_qos),
        ]
        for topic, qos in subscriptions:
            client.subscribe(topic, qos=qos)
            logger.info("Subscribed to topic: %s (qos=%s)", topic, qos)

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any) -> None:
        logger.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        record = _message_to_record(msg.topic, msg.payload)
        attendance_state.add_message(record)

        payload_json = record.get("payload_json")

        if msg.topic.startswith("rfid/"):
            return

        if msg.topic == settings.mqtt_topic_attendance_events and isinstance(payload_json, dict):
            attendance_state.apply_attendance_event(payload_json)

        if msg.topic == settings.mqtt_topic_attendance_state and isinstance(payload_json, dict):
            attendance_state.apply_attendance_snapshot(payload_json)


mqtt_gateway = MQTTGateway()
