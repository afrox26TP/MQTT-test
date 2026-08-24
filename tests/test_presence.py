import copy
import json
import tempfile
import unittest
from pathlib import Path

from app.config import load_presence_config
from app.persistence import StateStore
from app.state import PresenceState


ROOT = Path(__file__).resolve().parents[1]


class PresenceStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_presence_config(ROOT / "config" / "showcase.json")
        self.state = PresenceState(self.config)

    def test_rfid_leave_keeps_zone_but_removes_reader_visibility(self) -> None:
        topic = "showcase/readers/corridor/events"
        code = "30121343500000012354892"
        self.state.apply_reader_event(
            topic, {"type": "rfid_enter", "code": code, "time_utc": "2026-08-17 11:40:00"}
        )
        self.state.apply_reader_event(
            topic, {"type": "rfid_leave", "code": code, "time_utc": "2026-08-17 11:45:00"}
        )

        identifier = self.state.to_dict()["identifiers"]["rfid-alice"]
        self.assertEqual(identifier["readers"], [])
        self.assertEqual(identifier["zones"], ["corridor", "floor-2", "building"])

    def test_asset_uses_newest_identifier_information(self) -> None:
        self.state.apply_reader_event(
            "showcase/readers/corridor/events",
            {
                "type": "rfid_enter",
                "code": "30121343500000012354892",
                "time_utc": "2026-08-17 11:40:00",
            },
        )
        self.state.apply_reader_event(
            "showcase/readers/conference/events",
            {"type": "sign_in", "code": "a0cd34", "time_utc": "2026-08-17 11:41:00"},
        )

        asset = self.state.to_dict()["assets"]["person-alice"]
        self.assertEqual(asset["zones"], ["conference-room", "floor-2", "building"])

    def test_parent_zone_contains_descendant_presence(self) -> None:
        self.state.apply_reader_event(
            "showcase/readers/corridor/events",
            {
                "type": "rfid_enter",
                "code": "99000000000000000000001",
                "time_utc": "2026-08-17 11:40:00",
            },
        )

        zones = self.state.to_dict()["zones"]
        self.assertIn("projector-1", zones["corridor"]["assets"])
        self.assertIn("projector-1", zones["floor-2"]["assets"])
        self.assertIn("projector-1", zones["building"]["assets"])

    def test_older_event_is_ignored(self) -> None:
        topic = "showcase/readers/corridor/events"
        code = "30121343500000012354892"
        self.state.apply_reader_event(
            topic, {"type": "rfid_enter", "code": code, "time_utc": "2026-08-17 11:45:00"}
        )
        publications = self.state.apply_reader_event(
            topic, {"type": "rfid_leave", "code": code, "time_utc": "2026-08-17 11:40:00"}
        )

        self.assertEqual(publications, [])
        self.assertEqual(self.state.to_dict()["identifiers"]["rfid-alice"]["readers"], ["rfid-corridor"])

    # ── Conflict policy ────────────────────────────────────────

    def test_prefer_chip_policy(self) -> None:
        """Při prefer_chip vyhrává chip identifikátor i přes starší čas."""
        config = load_presence_config(ROOT / "config" / "showcase.json")
        object.__setattr__(config, "conflict_policy", "prefer_chip")
        state = PresenceState(config)

        state.apply_reader_event(
            "showcase/readers/corridor/events",
            {"type": "rfid_enter", "code": "30121343500000012354892", "time_utc": "2026-08-17 11:45:00"},
        )
        state.apply_reader_event(
            "showcase/readers/conference/events",
            {"type": "sign_in", "code": "a0cd34", "time_utc": "2026-08-17 11:40:00"},
        )

        asset = state.to_dict()["assets"]["person-alice"]
        self.assertEqual(asset["zones"], ["conference-room", "floor-2", "building"])

    def test_prefer_rfid_policy(self) -> None:
        """Při prefer_rfid vyhrává RFID identifikátor."""
        config = load_presence_config(ROOT / "config" / "showcase.json")
        object.__setattr__(config, "conflict_policy", "prefer_rfid")
        state = PresenceState(config)

        state.apply_reader_event(
            "showcase/readers/corridor/events",
            {"type": "rfid_enter", "code": "30121343500000012354892", "time_utc": "2026-08-17 11:40:00"},
        )
        state.apply_reader_event(
            "showcase/readers/conference/events",
            {"type": "sign_in", "code": "a0cd34", "time_utc": "2026-08-17 11:45:00"},
        )

        asset = state.to_dict()["assets"]["person-alice"]
        self.assertEqual(asset["zones"], ["corridor", "floor-2", "building"])

    def test_priority_order_policy(self) -> None:
        """Při priority_order vyhrává první identifikátor se známou zónou."""
        config = load_presence_config(ROOT / "config" / "showcase.json")
        object.__setattr__(config, "conflict_policy", "priority_order")
        state = PresenceState(config)

        state.apply_reader_event(
            "showcase/readers/corridor/events",
            {"type": "rfid_enter", "code": "30121343500000012354892", "time_utc": "2026-08-17 11:45:00"},
        )
        state.apply_reader_event(
            "showcase/readers/conference/events",
            {"type": "sign_in", "code": "a0cd34", "time_utc": "2026-08-17 11:40:00"},
        )

        # chip-alice je v assetu první → priority_order použije chip
        asset = state.to_dict()["assets"]["person-alice"]
        self.assertEqual(asset["zones"], ["conference-room", "floor-2", "building"])

    def test_auto_sign_out_on_zone_change(self) -> None:
        """Chip sign_in do jiné zóny automaticky vykopne z předchozí."""
        self.state.apply_reader_event(
            "showcase/readers/conference/events",
            {"type": "sign_in", "code": "a0cd34", "time_utc": "2026-08-17 11:40:00"},
        )
        identifier = self.state.to_dict()["identifiers"]["chip-alice"]
        self.assertEqual(identifier["zones"], ["conference-room", "floor-2", "building"])

        # Opakovaný sign_in do stejné zóny nic nerozbije
        self.state.apply_reader_event(
            "showcase/readers/conference/events",
            {"type": "sign_in", "code": "a0cd34", "time_utc": "2026-08-17 11:45:00"},
        )
        identifier = self.state.to_dict()["identifiers"]["chip-alice"]
        self.assertEqual(identifier["zones"], ["conference-room", "floor-2", "building"])

    def test_persistence_survives_restart(self) -> None:
        """Stav se obnoví z persistentního úložiště po restartu."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore("presence", data_dir=tmpdir)
            state1 = PresenceState(self.config, store=store)

            state1.apply_reader_event(
                "showcase/readers/corridor/events",
                {"type": "rfid_enter", "code": "30121343500000012354892",
                 "time_utc": "2026-08-17 11:40:00"},
            )

            state2 = PresenceState(self.config, store=store)
            identifier = state2.to_dict()["identifiers"]["rfid-alice"]
            self.assertEqual(identifier["zones"], ["corridor", "floor-2", "building"])

    def test_persistence_validates_against_new_config(self) -> None:
        """Po restartu se zahodí identifikátory, které zmizely z konfigurace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore("presence", data_dir=tmpdir)
            state1 = PresenceState(self.config, store=store)

            state1.apply_reader_event(
                "showcase/readers/corridor/events",
                {"type": "rfid_enter", "code": "30121343500000012354892",
                 "time_utc": "2026-08-17 11:40:00"},
            )

            with (ROOT / "config" / "showcase.json").open("r", encoding="utf-8") as f:
                raw = json.load(f)
            raw["identifiers"] = [i for i in raw["identifiers"] if i["id"] != "rfid-alice"]
            for asset in raw["assets"]:
                if asset["id"] == "person-alice":
                    asset["identifiers"] = ["chip-alice"]

            trimmed_path = Path(tmpdir) / "trimmed.json"
            trimmed_path.write_text(json.dumps(raw), encoding="utf-8")
            trimmed_config = load_presence_config(str(trimmed_path))

            state2 = PresenceState(trimmed_config, store=store)
            data = state2.to_dict()
            self.assertNotIn("rfid-alice", data["identifiers"])

if __name__ == "__main__":
    unittest.main()
