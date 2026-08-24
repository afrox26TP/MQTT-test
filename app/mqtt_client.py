from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

from app.config import PresenceConfig, settings
from app.state import PresenceState, Publication

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MQTTGateway:
    """Tenká MQTT vrstva; veškerá doménová pravidla zůstávají v PresenceState."""

    def __init__(self, config: PresenceConfig, state: PresenceState) -> None:
        self.config = config
        self.state = state
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.mqtt_client_id)
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def start(self) -> None:
        logger.info("Připojuji MQTT %s:%s (TLS=%s)", settings.mqtt_broker_host, settings.mqtt_broker_port, settings.mqtt_tls)
        if settings.mqtt_tls:
            self.client.tls_set()
            if settings.mqtt_tls_insecure:
                self.client.tls_insecure_set(True)
        try:
            self.client.connect(settings.mqtt_broker_host, settings.mqtt_broker_port, keepalive=60)
        except OSError as exc:
            logger.warning("MQTT broker nedostupný (%s), zkouším znovu za 10 s", exc)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        if self.connected:
            self.client.disconnect()

    def _publish(self, publication: Publication) -> None:
        payload = json.dumps(publication.payload, ensure_ascii=False, separators=(",", ":"))
        info = self.client.publish(
            publication.topic,
            payload=payload,
            qos=settings.mqtt_qos,
            retain=True,
        )
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            logger.error("Publikování na %s selhalo: rc=%s", publication.topic, info.rc)

    def _on_connect(
        self,
        client: mqtt.Client,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        del _userdata, _flags, _properties
        if reason_code != 0:
            logger.error("MQTT připojení selhalo: %s", reason_code)
            return
        self.connected = True
        logger.info("MQTT připojeno")
        for reader in self.config.readers.values():
            client.subscribe(reader.topic_in, qos=settings.mqtt_qos)
            logger.info("Čtečka %s poslouchá %s", reader.id, reader.topic_in)

        # Retained snapshot zajistí, že noví odběratelé dostanou stav ihned.
        for publication in self.state.all_publications():
            self._publish(publication)

    def _on_disconnect(
        self,
        _client: mqtt.Client,
        _userdata: Any,
        _disconnect_flags: Any,
        reason_code: Any,
        _properties: Any,
    ) -> None:
        del _client, _userdata, _disconnect_flags, _properties
        self.connected = False
        logger.warning("MQTT odpojeno: %s", reason_code)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        del _client, _userdata
        raw = msg.payload.decode("utf-8", errors="replace")
        record: dict[str, Any] = {
            "received_at": _utc_now_iso(),
            "topic": msg.topic,
            "payload_raw": raw,
        }
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("payload musí být JSON objekt")
            record["payload_json"] = payload
            publications = self.state.apply_reader_event(msg.topic, payload)
            for publication in publications:
                self._publish(publication)
            record["published_topics"] = [item.topic for item in publications]
        except (json.JSONDecodeError, ValueError) as exc:
            record["error"] = str(exc)
            logger.warning("Neplatná zpráva na %s: %s", msg.topic, exc)
        finally:
            self.state.add_message(record)
