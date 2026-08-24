"""
Testovací skript pro publikování událostí do MQTT brokeru.

Použití:
    python scripts/test_publish.py

Sleduj výsledky:
    - Webový monitor: http://localhost:8000/
    - MQTT stavy: subscribuj nedvezska/presence/#
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER = os.getenv("MQTT_BROKER_HOST", "hamqttnedvezska.ag.management.orcave.com")
PORT = int(os.getenv("MQTT_BROKER_PORT", "8883"))
USER = os.getenv("MQTT_USERNAME", "orcave")
PASS = os.getenv("MQTT_PASSWORD", "miracle")
TLS = os.getenv("MQTT_TLS", "true").lower() == "true"
TLS_INSECURE = os.getenv("MQTT_TLS_INSECURE", "true").lower() == "true"

TOPICS = {
    "chip_venku": "test/nedvezska/vchod/ctecka_venku",
    "rfid_garaz": "test/nedvezska/budova/rfid_budova_u_garazi",
    "rfid_silnice": "test/nedvezska/budova/rfid_budova_u_silnice",
    "rfid_prizemi": "test/nedvezska/budova/rfid_budova_pod_schody",
    "rfid_patro": "test/nedvezska/budova/rfid_budova_nad_schody",
}

CODES = {
    "chip_alice": "AABB001",
    "rfid_alice": "E20000112233445566778801",
    "rfid_bob": "E20000112233445566778802",
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def publish(client: mqtt.Client, topic: str, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False)
    info = client.publish(topic, data, qos=1)
    if info.rc == mqtt.MQTT_ERR_SUCCESS:
        print(f"  PUB  {topic}  →  {data}")
    else:
        print(f"  ERR  {topic}  rc={info.rc}")


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-publisher")
    client.username_pw_set(USER, PASS)
    if TLS:
        if TLS_INSECURE:
            client.tls_insecure_set(True)
        client.tls_set()

    print(f"Připojuji {BROKER}:{PORT} (TLS={TLS})...")
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()
    time.sleep(1)

    # ── Scénář ─────────────────────────────────────────────────
    print("\n=== 1. Alice přijde k budově – pípne čip venku ===")
    publish(client, TOPICS["chip_venku"], {
        "type": "sign_in", "code": CODES["chip_alice"], "time_utc": now(),
    })
    time.sleep(0.5)

    print("\n=== 2. RFID u garáže zachytí Alici (je mimo budovu) ===")
    publish(client, TOPICS["rfid_garaz"], {
        "type": "rfid_enter", "code": CODES["rfid_alice"], "time_utc": now(),
    })
    time.sleep(0.5)

    print("\n=== 3. Alice vejde dovnitř – RFID v přízemí ===")
    publish(client, TOPICS["rfid_prizemi"], {
        "type": "rfid_enter", "code": CODES["rfid_alice"], "time_utc": now(),
    })
    time.sleep(0.5)

    print("\n=== 4. RFID u garáže hlásí leave (už ji nevidí) ===")
    publish(client, TOPICS["rfid_garaz"], {
        "type": "rfid_leave", "code": CODES["rfid_alice"], "time_utc": now(),
    })
    time.sleep(0.5)

    print("\n=== 5. Bob přijde – RFID u silnice ===")
    publish(client, TOPICS["rfid_silnice"], {
        "type": "rfid_enter", "code": CODES["rfid_bob"], "time_utc": now(),
    })
    time.sleep(0.5)

    print("\n=== 6. Alice jde do patra ===")
    publish(client, TOPICS["rfid_patro"], {
        "type": "rfid_enter", "code": CODES["rfid_alice"], "time_utc": now(),
    })
    time.sleep(0.5)

    print("\n=== 7. Alice se pípne čipem venku (odchod) ===")
    publish(client, TOPICS["chip_venku"], {
        "type": "sign_out", "code": CODES["chip_alice"], "time_utc": now(),
    })
    time.sleep(0.5)

    print("\n=== HOTOVO – podívej se na http://localhost:8000/ ===")

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
