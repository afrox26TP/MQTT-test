from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.config import settings


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AttendanceState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._recent_messages: deque[dict[str, Any]] = deque(maxlen=settings.max_recent_messages)
        self._people: dict[str, dict[str, Any]] = {}
        self._rooms: dict[str, set[str]] = {}

    def add_message(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._recent_messages.appendleft(item)

    def apply_attendance_event(self, event: dict[str, Any]) -> None:
        person = str(event.get("person") or event.get("person_id") or event.get("name") or "").strip()
        if not person:
            return

        room = str(event.get("room") or event.get("location") or "").strip() or None
        event_type = str(event.get("event") or event.get("action") or "").lower().strip()

        if event_type in {"arrive", "arrival", "in", "checkin", "present", "prisiel", "prisel", "prisel_do"}:
            present = True
        elif event_type in {"leave", "out", "checkout", "absent", "odisiel", "odesel", "odchod"}:
            present = False
        else:
            present = bool(event.get("present", True))

        timestamp = str(event.get("timestamp") or event.get("time") or _utc_now_iso())

        with self._lock:
            old_room = self._people.get(person, {}).get("room")
            if old_room and old_room in self._rooms:
                self._rooms[old_room].discard(person)

            self._people[person] = {
                "present": present,
                "room": room,
                "last_event": event_type or ("in" if present else "out"),
                "last_seen": timestamp,
            }

            if present and room:
                self._rooms.setdefault(room, set()).add(person)

    def apply_attendance_snapshot(self, snapshot: dict[str, Any]) -> None:
        people_payload = snapshot.get("people")
        if not isinstance(people_payload, list):
            people_payload = snapshot.get("present")

        if not isinstance(people_payload, list):
            return

        with self._lock:
            self._people.clear()
            self._rooms.clear()

            for row in people_payload:
                if isinstance(row, str):
                    person = row.strip()
                    if not person:
                        continue
                    self._people[person] = {
                        "present": True,
                        "room": None,
                        "last_event": "snapshot",
                        "last_seen": _utc_now_iso(),
                    }
                    continue

                if not isinstance(row, dict):
                    continue

                person = str(row.get("person") or row.get("person_id") or row.get("name") or "").strip()
                if not person:
                    continue

                room = str(row.get("room") or row.get("location") or "").strip() or None
                present = bool(row.get("present", True))
                ts = str(row.get("timestamp") or row.get("time") or _utc_now_iso())

                self._people[person] = {
                    "present": present,
                    "room": room,
                    "last_event": "snapshot",
                    "last_seen": ts,
                }

                if present and room:
                    self._rooms.setdefault(room, set()).add(person)

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            rooms = {room: sorted(list(people)) for room, people in self._rooms.items()}
            present_people = sorted([name for name, info in self._people.items() if info.get("present")])

            return {
                "present_people": present_people,
                "people": dict(self._people),
                "rooms": rooms,
                "recent_messages": list(self._recent_messages),
            }


attendance_state = AttendanceState()
