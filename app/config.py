from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    mqtt_broker_host: str = os.getenv("MQTT_BROKER_HOST", "mosquitto")
    mqtt_broker_port: int = _env_int("MQTT_BROKER_PORT", 1883)
    mqtt_username: str = os.getenv("MQTT_USERNAME", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_client_id: str = os.getenv("MQTT_CLIENT_ID", "anygate-presence")
    mqtt_qos: int = _env_int("MQTT_QOS", 1)
    config_path: str = os.getenv("PRESENCE_CONFIG", "config/showcase.json")
    max_recent_messages: int = _env_int("MAX_RECENT_MESSAGES", 100)

    def __post_init__(self) -> None:
        if not 1 <= self.mqtt_broker_port <= 65535:
            raise ValueError("MQTT_BROKER_PORT musí být v rozsahu 1–65535")
        if self.mqtt_qos not in {0, 1, 2}:
            raise ValueError("MQTT_QOS musí být 0, 1 nebo 2")
        if self.max_recent_messages < 1:
            raise ValueError("MAX_RECENT_MESSAGES musí být kladné číslo")


@dataclass(frozen=True)
class Zone:
    id: str
    parent: str | None
    readers: tuple[str, ...]
    topic_out_status: str


@dataclass(frozen=True)
class Reader:
    id: str
    type: str
    topic_in: str
    topic_out_status: str
    zone_id: str


@dataclass(frozen=True)
class Identifier:
    id: str
    type: str
    code: str
    topic_out_status: str


@dataclass(frozen=True)
class Asset:
    id: str
    identifiers: tuple[str, ...]
    topic_out_status: str


@dataclass(frozen=True)
class PresenceConfig:
    zones: dict[str, Zone]
    readers: dict[str, Reader]
    identifiers: dict[str, Identifier]
    assets: dict[str, Asset]
    readers_by_topic: dict[str, Reader]
    identifiers_by_code: dict[tuple[str, str], Identifier]
    asset_by_identifier: dict[str, Asset]

    def ancestors(self, zone_id: str | None) -> tuple[str, ...]:
        """Vrátí přímou zónu a postupně všechny její nadřazené zóny."""
        result: list[str] = []
        current = zone_id
        while current is not None:
            result.append(current)
            current = self.zones[current].parent
        return tuple(result)


def _required_text(row: dict[str, Any], key: str, kind: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{kind}: pole '{key}' musí být neprázdný text")
    return value.strip()


def load_presence_config(path: str | Path) -> PresenceConfig:
    """Načte mapu instalace a odmítne nejednoznačné reference."""
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Kořen konfigurace musí být JSON objekt")

    zone_rows = raw.get("zones", [])
    reader_rows = raw.get("readers", [])
    identifier_rows = raw.get("identifiers", [])
    asset_rows = raw.get("assets", [])
    if not all(isinstance(rows, list) for rows in (zone_rows, reader_rows, identifier_rows, asset_rows)):
        raise ValueError("zones, readers, identifiers a assets musí být pole")

    zones: dict[str, Zone] = {}
    for row in zone_rows:
        if not isinstance(row, dict):
            raise ValueError("Každá zóna musí být objekt")
        zone_id = _required_text(row, "id", "Zóna")
        if zone_id in zones:
            raise ValueError(f"Duplicitní zóna: {zone_id}")
        parent = row.get("parent")
        if parent is not None and not isinstance(parent, str):
            raise ValueError(f"Zóna {zone_id}: parent musí být text nebo null")
        readers = row.get("readers", [])
        if not isinstance(readers, list) or not all(isinstance(item, str) for item in readers):
            raise ValueError(f"Zóna {zone_id}: readers musí být pole textů")
        zones[zone_id] = Zone(
            id=zone_id,
            parent=parent,
            readers=tuple(readers),
            topic_out_status=_required_text(row, "topic_out_status", f"Zóna {zone_id}"),
        )

    for zone in zones.values():
        if zone.parent is not None and zone.parent not in zones:
            raise ValueError(f"Zóna {zone.id} odkazuje na neexistujícího rodiče {zone.parent}")
        visited: set[str] = set()
        current: str | None = zone.id
        while current is not None:
            if current in visited:
                raise ValueError(f"Cyklus ve stromu zón u {zone.id}")
            visited.add(current)
            current = zones[current].parent

    reader_to_zone: dict[str, str] = {}
    for zone in zones.values():
        for reader_id in zone.readers:
            if reader_id in reader_to_zone:
                raise ValueError(f"Čtečka {reader_id} je přiřazena více zónám")
            reader_to_zone[reader_id] = zone.id

    readers: dict[str, Reader] = {}
    readers_by_topic: dict[str, Reader] = {}
    for row in reader_rows:
        if not isinstance(row, dict):
            raise ValueError("Každá čtečka musí být objekt")
        reader_id = _required_text(row, "id", "Čtečka")
        reader_type = _required_text(row, "type", f"Čtečka {reader_id}")
        if reader_type not in {"chips-reader", "rfid-reader"}:
            raise ValueError(f"Čtečka {reader_id}: neznámý typ {reader_type}")
        if reader_id in readers:
            raise ValueError(f"Duplicitní čtečka: {reader_id}")
        if reader_id not in reader_to_zone:
            raise ValueError(f"Čtečka {reader_id} není přiřazena žádné zóně")
        reader = Reader(
            id=reader_id,
            type=reader_type,
            topic_in=_required_text(row, "topic_in", f"Čtečka {reader_id}"),
            topic_out_status=_required_text(row, "topic_out_status", f"Čtečka {reader_id}"),
            zone_id=reader_to_zone[reader_id],
        )
        if reader.topic_in in readers_by_topic:
            raise ValueError(f"Vstupní topic {reader.topic_in} používá více čteček")
        readers[reader_id] = reader
        readers_by_topic[reader.topic_in] = reader

    missing_readers = set(reader_to_zone) - set(readers)
    if missing_readers:
        raise ValueError(f"Zóny odkazují na neexistující čtečky: {sorted(missing_readers)}")

    identifiers: dict[str, Identifier] = {}
    identifiers_by_code: dict[tuple[str, str], Identifier] = {}
    for row in identifier_rows:
        if not isinstance(row, dict):
            raise ValueError("Každý identifier musí být objekt")
        identifier_id = _required_text(row, "id", "Identifier")
        identifier_type = _required_text(row, "type", f"Identifier {identifier_id}")
        if identifier_type not in {"chip", "rfid"}:
            raise ValueError(f"Identifier {identifier_id}: neznámý typ {identifier_type}")
        identifier = Identifier(
            id=identifier_id,
            type=identifier_type,
            code=_required_text(row, "code", f"Identifier {identifier_id}"),
            topic_out_status=_required_text(row, "topic_out_status", f"Identifier {identifier_id}"),
        )
        lookup_key = (identifier.type, identifier.code.casefold())
        if identifier_id in identifiers or lookup_key in identifiers_by_code:
            raise ValueError(f"Duplicitní identifier nebo kód: {identifier_id}")
        identifiers[identifier_id] = identifier
        identifiers_by_code[lookup_key] = identifier

    assets: dict[str, Asset] = {}
    asset_by_identifier: dict[str, Asset] = {}
    for row in asset_rows:
        if not isinstance(row, dict):
            raise ValueError("Každý asset musí být objekt")
        asset_id = _required_text(row, "id", "Asset")
        identifier_ids = row.get("identifiers", [])
        if not isinstance(identifier_ids, list) or not all(isinstance(item, str) for item in identifier_ids):
            raise ValueError(f"Asset {asset_id}: identifiers musí být pole textů")
        asset = Asset(
            id=asset_id,
            identifiers=tuple(identifier_ids),
            topic_out_status=_required_text(row, "topic_out_status", f"Asset {asset_id}"),
        )
        if asset_id in assets:
            raise ValueError(f"Duplicitní asset: {asset_id}")
        for identifier_id in asset.identifiers:
            if identifier_id not in identifiers:
                raise ValueError(f"Asset {asset_id} odkazuje na neexistující identifier {identifier_id}")
            if identifier_id in asset_by_identifier:
                raise ValueError(f"Identifier {identifier_id} je přiřazen více assetům")
            asset_by_identifier[identifier_id] = asset
        assets[asset_id] = asset

    output_topics = [item.topic_out_status for item in identifiers.values()]
    output_topics += [item.topic_out_status for item in assets.values()]
    output_topics += [item.topic_out_status for item in zones.values()]
    output_topics += [item.topic_out_status for item in readers.values()]
    if len(output_topics) != len(set(output_topics)):
        raise ValueError("Každý topic_out_status musí být v celé konfiguraci unikátní")

    return PresenceConfig(
        zones=zones,
        readers=readers,
        identifiers=identifiers,
        assets=assets,
        readers_by_topic=readers_by_topic,
        identifiers_by_code=identifiers_by_code,
        asset_by_identifier=asset_by_identifier,
    )


settings = Settings()
