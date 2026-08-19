from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.config import Asset, Identifier, PresenceConfig, Reader, settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _event_time(value: Any) -> tuple[datetime, str]:
    """Přijme ukázkový UTC formát i standardní ISO 8601 čas."""
    text = str(value or "").strip()
    if not text:
        now = datetime.now(timezone.utc)
        return now, now.isoformat(timespec="seconds")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"Neplatný time_utc: {text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    return parsed, parsed.isoformat(timespec="seconds")


@dataclass
class IdentifierState:
    direct_zone: str | None = None
    readers: set[str] = field(default_factory=set)
    changed_at: datetime = field(default_factory=lambda: datetime.min.replace(tzinfo=timezone.utc))
    changed_at_text: str = ""


@dataclass(frozen=True)
class Publication:
    topic: str
    payload: dict[str, Any]


class PresenceState:
    """Vlákny bezpečná projekce posledních platných událostí ze čteček.

    Identifier má nejvýše jednu přímou zónu. Přítomnost v rodičích se vždy
    dopočítá při výstupu, a proto se nemůže rozcházet s přímou polohou.
    """

    def __init__(self, config: PresenceConfig) -> None:
        self.config = config
        self._lock = Lock()
        self._identifier_states = {item_id: IdentifierState() for item_id in config.identifiers}
        self._recent_messages: deque[dict[str, Any]] = deque(maxlen=settings.max_recent_messages)
        self._warnings: deque[str] = deque(maxlen=50)

    def add_message(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._recent_messages.appendleft(item)

    def apply_reader_event(self, topic: str, event: dict[str, Any]) -> list[Publication]:
        """Zpracuje událost a vrátí pouze MQTT stavy, které se změnily."""
        reader = self.config.readers_by_topic.get(topic)
        if reader is None:
            raise ValueError(f"Pro topic {topic} není nakonfigurována čtečka")

        event_type = str(event.get("type") or "").strip()
        allowed = {
            "chips-reader": {"sign_in", "sign_out"},
            "rfid-reader": {"rfid_enter", "rfid_leave"},
        }[reader.type]
        if event_type not in allowed:
            raise ValueError(f"Čtečka {reader.id} nepodporuje událost {event_type!r}")

        code = str(event.get("code") or "").strip()
        identifier_type = "chip" if reader.type == "chips-reader" else "rfid"
        identifier = self.config.identifiers_by_code.get((identifier_type, code.casefold()))
        if identifier is None:
            raise ValueError(f"Neznámý {identifier_type} kód {code!r}")

        occurred_at, occurred_at_text = _event_time(event.get("time_utc"))
        with self._lock:
            before = self._status_payloads(occurred_at_text)
            state = self._identifier_states[identifier.id]

            # Opožděná MQTT zpráva nesmí přepsat novější informaci o poloze.
            if occurred_at < state.changed_at:
                self._warnings.appendleft(
                    f"Ignorována starší událost {event_type} pro {identifier.id} z {occurred_at_text}"
                )
                return []

            changed = self._apply_semantics(reader, state, event_type)
            state.changed_at = occurred_at
            state.changed_at_text = occurred_at_text
            if not changed:
                return []

            after = self._status_payloads(occurred_at_text)
            return [
                Publication(topic=topic_name, payload=payload)
                for topic_name, payload in after.items()
                if before.get(topic_name) != payload
            ]

    @staticmethod
    def _apply_semantics(reader: Reader, state: IdentifierState, event_type: str) -> bool:
        old_zone = state.direct_zone
        old_readers = set(state.readers)

        if event_type == "sign_in":
            state.direct_zone = reader.zone_id
        elif event_type == "sign_out":
            # Odhlášení z jiné zóny nesmaže aktuální polohu.
            if state.direct_zone == reader.zone_id:
                state.direct_zone = None
        elif event_type == "rfid_enter":
            state.readers.add(reader.id)
            state.direct_zone = reader.zone_id
        elif event_type == "rfid_leave":
            # Opuštění dosahu antény mění viditelnost, nikoli odvozenou zónu.
            state.readers.discard(reader.id)

        return old_zone != state.direct_zone or old_readers != state.readers

    def _asset_location(self, asset: Asset) -> str | None:
        # Konfliktní identifiery: vyhrává nejnovější událost s polohou.
        states = [self._identifier_states[item_id] for item_id in asset.identifiers]
        if not states:
            return None
        return max(states, key=lambda state: state.changed_at).direct_zone

    def _identifier_payload(self, identifier: Identifier, timestamp: str) -> dict[str, Any]:
        state = self._identifier_states[identifier.id]
        return {
            "time_utc": timestamp,
            "presence": {
                "readers": sorted(state.readers),
                "zones": list(self.config.ancestors(state.direct_zone)),
            },
        }

    def _asset_payload(self, asset: Asset, timestamp: str) -> dict[str, Any]:
        readers: set[str] = set()
        for identifier_id in asset.identifiers:
            readers.update(self._identifier_states[identifier_id].readers)
        return {
            "time_utc": timestamp,
            "presence": {
                "readers": sorted(readers),
                "zones": list(self.config.ancestors(self._asset_location(asset))),
            },
        }

    def _zone_payload(self, zone_id: str, timestamp: str) -> dict[str, Any]:
        identifiers = [
            item.id
            for item in self.config.identifiers.values()
            if zone_id in self.config.ancestors(self._identifier_states[item.id].direct_zone)
        ]
        assets = [
            asset.id
            for asset in self.config.assets.values()
            if zone_id in self.config.ancestors(self._asset_location(asset))
        ]
        return {
            "time_utc": timestamp,
            "presence": {"assets": sorted(assets), "identifiers": sorted(identifiers)},
        }

    def _reader_payload(self, reader_id: str, timestamp: str) -> dict[str, Any]:
        identifiers = [
            item.id
            for item in self.config.identifiers.values()
            if reader_id in self._identifier_states[item.id].readers
        ]
        assets = sorted(
            {
                self.config.asset_by_identifier[item_id].id
                for item_id in identifiers
                if item_id in self.config.asset_by_identifier
            }
        )
        return {
            "time_utc": timestamp,
            "presence": {"assets": assets, "identifiers": sorted(identifiers)},
        }

    def _status_payloads(self, timestamp: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in self.config.identifiers.values():
            result[item.topic_out_status] = self._identifier_payload(item, timestamp)
        for asset in self.config.assets.values():
            result[asset.topic_out_status] = self._asset_payload(asset, timestamp)
        for zone in self.config.zones.values():
            result[zone.topic_out_status] = self._zone_payload(zone.id, timestamp)
        for reader in self.config.readers.values():
            result[reader.topic_out_status] = self._reader_payload(reader.id, timestamp)
        return result

    def all_publications(self) -> list[Publication]:
        """Sestaví retained startovní snapshot všech výstupních topiců."""
        with self._lock:
            return [
                Publication(topic=topic, payload=payload)
                for topic, payload in self._status_payloads(utc_now_iso()).items()
            ]

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            timestamp = utc_now_iso()
            return {
                "policy": "Nejnovější platná událost určuje polohu; RFID leave ruší jen viditelnost.",
                "identifiers": {
                    item.id: self._identifier_payload(item, timestamp)["presence"]
                    for item in self.config.identifiers.values()
                },
                "assets": {
                    asset.id: self._asset_payload(asset, timestamp)["presence"]
                    for asset in self.config.assets.values()
                },
                "zones": {
                    zone.id: self._zone_payload(zone.id, timestamp)["presence"]
                    for zone in self.config.zones.values()
                },
                "readers": {
                    reader.id: self._reader_payload(reader.id, timestamp)["presence"]
                    for reader in self.config.readers.values()
                },
                "warnings": list(self._warnings),
                "recent_messages": list(self._recent_messages),
            }
