import os


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Settings:
    mqtt_broker_host = os.getenv("MQTT_BROKER_HOST", "mosquitto")
    mqtt_broker_port = _to_int(os.getenv("MQTT_BROKER_PORT", "1883"), 1883)
    mqtt_username = os.getenv("MQTT_USERNAME", "")
    mqtt_password = os.getenv("MQTT_PASSWORD", "")
    mqtt_client_id = os.getenv("MQTT_CLIENT_ID", "attendance-rfid-gateway")
    mqtt_qos = _to_int(os.getenv("MQTT_QOS", "1"), 1)

    mqtt_topic_rfid = os.getenv("MQTT_TOPIC_RFID", "rfid/#")
    mqtt_topic_attendance_events = os.getenv("MQTT_TOPIC_ATTENDANCE_EVENTS", "attendance/events")
    mqtt_topic_attendance_state = os.getenv("MQTT_TOPIC_ATTENDANCE_STATE", "attendance/state")

    api_host = os.getenv("API_HOST", "0.0.0.0")
    api_port = _to_int(os.getenv("API_PORT", "8000"), 8000)
    max_recent_messages = _to_int(os.getenv("MAX_RECENT_MESSAGES", "500"), 500)


settings = Settings()
