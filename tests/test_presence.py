import unittest
from pathlib import Path

from app.config import load_presence_config
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


if __name__ == "__main__":
    unittest.main()
