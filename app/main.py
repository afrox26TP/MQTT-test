from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.mqtt_client import mqtt_gateway
from app.state import attendance_state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

app = FastAPI(title="RFID + Attendance MQTT Gateway")


@app.on_event("startup")
def on_startup() -> None:
    mqtt_gateway.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    mqtt_gateway.stop()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/state")
def state() -> dict:
    return attendance_state.to_dict()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>MQTT Attendance Monitor</title>
  <style>
    body { font-family: "Segoe UI", Arial, sans-serif; margin: 24px; background: #f6f8fc; color: #172033; }
    .card { background: white; border-radius: 10px; padding: 16px; margin-bottom: 16px; box-shadow: 0 8px 24px rgba(23, 32, 51, 0.08); }
    pre { white-space: pre-wrap; word-break: break-word; font-size: 12px; }
  </style>
</head>
<body>
  <h1>MQTT Attendance Monitor</h1>
  <div class=\"card\">
    <h2>Present People</h2>
    <pre id=\"present\">loading...</pre>
  </div>
  <div class=\"card\">
    <h2>Rooms</h2>
    <pre id=\"rooms\">loading...</pre>
  </div>
  <div class=\"card\">
    <h2>Recent Messages</h2>
    <pre id=\"messages\">loading...</pre>
  </div>

  <script>
    async function refresh() {
      const res = await fetch('/state');
      const data = await res.json();
      document.getElementById('present').textContent = JSON.stringify(data.present_people, null, 2);
      document.getElementById('rooms').textContent = JSON.stringify(data.rooms, null, 2);
      document.getElementById('messages').textContent = JSON.stringify(data.recent_messages.slice(0, 30), null, 2);
    }

    refresh();
    setInterval(refresh, 2000);
  </script>
</body>
</html>
    """
