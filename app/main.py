from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import load_presence_config, settings
from app.mqtt_client import MQTTGateway
from app.persistence import StateStore
from app.state import PresenceState

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")

presence_config = load_presence_config(settings.config_path)
presence_store = StateStore("presence", data_dir=settings.data_dir)
presence_state = PresenceState(presence_config, store=presence_store)
mqtt_gateway = MQTTGateway(presence_config, presence_state)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    del _app
    mqtt_gateway.start()
    yield
    mqtt_gateway.stop()


app = FastAPI(title="AnyGate Presence Engine", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "mqtt_connected": mqtt_gateway.connected}


@app.get("/state")
def state() -> dict:
    return presence_state.to_dict()


@app.get("/demo")
def demo() -> dict:
    """Nasimuluje ukázková data přímo do stavu (bez MQTT)."""
    now = "2026-08-24 09:00:00"
    events: list[dict] = [
        # Alice pípne čip u vchodu → budova
        ("test/nedvezska/vchod/ctecka_venku", {"type": "sign_in", "code": "AABB001", "time_utc": "2026-08-24 08:00:00"}),
        # RFID v přízemí zachytí Alici → patro_1
        ("test/nedvezska/budova/rfid_budova_pod_schody", {"type": "rfid_enter", "code": "E20000112233445566778801", "time_utc": "2026-08-24 08:01:00"}),
        # RFID v patře zachytí Alici → patro_2
        ("test/nedvezska/budova/rfid_budova_nad_schody", {"type": "rfid_enter", "code": "E20000112233445566778801", "time_utc": "2026-08-24 08:02:00"}),
        # Bob venku u silnice → mimo_budovu
        ("test/nedvezska/budova/rfid_budova_u_silnice", {"type": "rfid_enter", "code": "E20000112233445566778802", "time_utc": "2026-08-24 08:03:00"}),
    ]
    for topic, payload in events:
        try:
            presence_state.apply_reader_event(topic, payload)
        except ValueError:
            pass
    return {"status": "ok", "message": "Demo data nasimulována. Obnov stránku!", "state_url": "/state"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AnyGate Presence</title>
  <style>
    :root{color-scheme:dark;--bg:#08111f;--card:#111d2e;--line:#24344c;--text:#e8f0fc;--muted:#91a4bf;--accent:#49d3a1}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#152945,var(--bg) 45%);color:var(--text);font:15px Segoe UI,Arial,sans-serif}
    main{max-width:1200px;margin:auto;padding:36px 22px}.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px}
    h1{font-size:30px;margin:0}h2{font-size:15px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.live{color:var(--accent)}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.card{background:rgba(17,29,46,.94);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:0 14px 35px #0004}
    .row{padding:10px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}.name{font-weight:650}.meta{color:var(--muted);font-size:13px;margin-top:4px}
    pre{white-space:pre-wrap;word-break:break-word;font-size:12px;color:#b8c8de;max-height:320px;overflow:auto}.wide{grid-column:1/-1}.empty{color:var(--muted)}
  </style>
</head>
<body><main>
  <div class="head"><div><h1>AnyGate Presence</h1><div class="meta">Showcase lokalizačního enginu</div></div><div id="health">načítám…</div></div>
  <div class="grid">
    <section class="card"><h2>Assety</h2><div id="assets"></div></section>
    <section class="card"><h2>Zóny</h2><div id="zones"></div></section>
    <section class="card"><h2>RFID antény</h2><div id="readers"></div></section>
    <section class="card wide"><h2>Poslední MQTT zprávy</h2><pre id="messages">zatím žádné</pre></section>
  </div>
</main><script>
  const rows=(items, detail)=>Object.entries(items).map(([id,value])=>`<div class="row"><div class="name">${id}</div><div class="meta">${detail(value)}</div></div>`).join('')||'<div class="empty">bez dat</div>';
  async function refresh(){
    try{
      const [stateRes,healthRes]=await Promise.all([fetch('/state'),fetch('/health')]);
      const data=await stateRes.json(), health=await healthRes.json();
      document.querySelector('#health').innerHTML=health.mqtt_connected?'<span class="live">● MQTT připojeno</span>':'<span>○ MQTT odpojeno</span>';
      document.querySelector('#assets').innerHTML=rows(data.assets,v=>`zóny: ${v.zones.join(' → ')||'neznámá'} · čtečky: ${v.readers.join(', ')||'—'}`);
      document.querySelector('#zones').innerHTML=rows(data.zones,v=>`${v.assets.length} assetů · ${v.identifiers.length} identifikátorů`);
      document.querySelector('#readers').innerHTML=rows(data.readers,v=>`právě vidí: ${v.identifiers.join(', ')||'nikoho'}`);
      document.querySelector('#messages').textContent=JSON.stringify(data.recent_messages.slice(0,20),null,2);
    }catch(error){document.querySelector('#health').textContent='API nedostupné';}
  }
  refresh();setInterval(refresh,2000);
</script></body></html>
    """
