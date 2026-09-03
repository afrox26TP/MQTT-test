from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

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


class AdminEvent(BaseModel):
  reader_id: str
  identifier_id: str
  event_type: str
  time_utc: str | None = None


class AdminStatus(BaseModel):
  identifier_id: str
  direct_zone: str | None = None
  readers: list[str] = Field(default_factory=list)
  time_utc: str | None = None


@app.get("/health")
def health() -> dict[str, str | bool]:
    return {"status": "ok", "mqtt_connected": mqtt_gateway.connected}


@app.get("/state")
def state() -> dict:
    return presence_state.to_dict()


def _apply_admin_event(reader_id: str, identifier_id: str, event_type: str, time_utc: str | None) -> list[str]:
  reader = presence_config.readers.get(reader_id)
  identifier = presence_config.identifiers.get(identifier_id)
  if reader is None:
    raise ValueError(f"Neznámá čtečka {reader_id!r}")
  if identifier is None:
    raise ValueError(f"Neznámý identifikátor {identifier_id!r}")
  expected_type = "chip" if reader.type == "chips-reader" else "rfid"
  if identifier.type != expected_type:
    raise ValueError(f"Čtečka vyžaduje identifikátor typu {expected_type}")
  payload: dict[str, Any] = {"type": event_type, "code": identifier.code}
  if time_utc:
    payload["time_utc"] = time_utc
  publications = presence_state.apply_reader_event(reader.topic_in, payload)
  mqtt_gateway.publish_all(publications)
  presence_state.add_message({
    "source": "admin",
    "topic": reader.topic_in,
    "payload_json": payload,
    "published_topics": [item.topic for item in publications],
  })
  return [item.topic for item in publications]


@app.get("/admin/config")
def admin_config() -> dict[str, Any]:
  return {
    "readers": [
      {"id": item.id, "type": item.type, "zone": item.zone_id, "topic": item.topic_in}
      for item in presence_config.readers.values()
    ],
    "identifiers": [
      {"id": item.id, "type": item.type, "code": item.code}
      for item in presence_config.identifiers.values()
    ],
    "assets": [
      {"id": item.id, "identifiers": list(item.identifiers)}
      for item in presence_config.assets.values()
    ],
    "zones": [
      {"id": item.id, "parent": item.parent}
      for item in presence_config.zones.values()
    ],
  }


@app.post("/admin/events")
def admin_event(event: AdminEvent) -> dict[str, Any]:
  try:
    topics = _apply_admin_event(
      event.reader_id, event.identifier_id, event.event_type, event.time_utc
    )
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  return {"status": "ok", "published_topics": topics, "state": presence_state.to_dict()}


@app.put("/admin/status")
def admin_status(status: AdminStatus) -> dict[str, Any]:
  try:
    publications = presence_state.set_identifier_state(
      status.identifier_id,
      status.direct_zone,
      set(status.readers),
      status.time_utc,
    )
  except ValueError as exc:
    raise HTTPException(status_code=400, detail=str(exc)) from exc
  mqtt_gateway.publish_all(publications)
  presence_state.add_message({
    "source": "admin-status",
    "identifier_id": status.identifier_id,
    "direct_zone": status.direct_zone,
    "readers": status.readers,
    "published_topics": [item.topic for item in publications],
  })
  return {"status": "ok", "state": presence_state.to_dict()}


@app.delete("/admin/status/{identifier_id}")
def admin_delete_status(identifier_id: str) -> dict[str, Any]:
  try:
    publications = presence_state.clear_identifier_state(identifier_id)
  except ValueError as exc:
    raise HTTPException(status_code=404, detail=str(exc)) from exc
  mqtt_gateway.publish_all(publications)
  return {"status": "ok", "state": presence_state.to_dict()}


@app.post("/admin/reset")
def admin_reset() -> dict[str, Any]:
  publications = presence_state.reset()
  mqtt_gateway.publish_all(publications)
  return {"status": "ok", "state": presence_state.to_dict()}


@app.post("/admin/demo")
def admin_demo() -> dict[str, Any]:
  reset_publications = presence_state.reset()
  mqtt_gateway.publish_all(reset_publications)
  demo_events = [
    ("chip_venku", "chip-test-alice", "sign_in"),
    ("rfid_pod_schody", "rfid-test-alice", "rfid_enter"),
    ("rfid_u_silnice", "rfid-test-bob", "rfid_enter"),
  ]
  for reader_id, identifier_id, event_type in demo_events:
    _apply_admin_event(reader_id, identifier_id, event_type, None)
  return {"status": "ok", "state": presence_state.to_dict()}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """
<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AnyGate Presence</title>
  <style>
    :root { font-family: Inter, ui-sans-serif, system-ui, sans-serif; color: #18181b; background: #f8fafc; }
    * { box-sizing: border-box; }
    body { max-width: 1100px; margin: 0 auto; padding: 40px 24px 80px; line-height: 1.5; }
    :root[data-theme="dark"] { color: #f4f4f5; background: #09090b; color-scheme: dark; }
    :root[data-theme="dark"] p { color: #a1a1aa; }
    :root[data-theme="dark"] a { color: #e4e4e7; }
    :root[data-theme="dark"] .status, :root[data-theme="dark"] .zone,
    :root[data-theme="dark"] table, :root[data-theme="dark"] pre { background: #18181b; border-color: #3f3f46; }
    :root[data-theme="dark"] th { background: #27272a; color: #d4d4d8; }
    :root[data-theme="dark"] th, :root[data-theme="dark"] td,
    :root[data-theme="dark"] h2 { border-color: #3f3f46; }
    :root[data-theme="dark"] .ok { color: #4ade80; }
    :root[data-theme="dark"] .off, :root[data-theme="dark"] .mismatch { color: #f87171; }
    :root[data-theme="dark"] .match { color: #4ade80; }
    header { display: flex; justify-content: space-between; gap: 20px; align-items: start; margin-bottom: 32px; }
    h1 { margin: 0 0 6px; font-size: 28px; letter-spacing: -.03em; }
    h2 { margin: 38px 0 14px; padding-bottom: 8px; border-bottom: 1px solid #e4e4e7; font-size: 17px; }
    p { margin: 0; color: #52525b; }
    a { color: #18181b; }
    .status { padding: 7px 10px; border: 1px solid #d4d4d8; border-radius: 6px; background: #fff; white-space: nowrap; }
    .ok { color: #166534; }
    .off { color: #b91c1c; }
    .zones { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }
    .zone { padding: 16px; border: 1px solid #e4e4e7; border-radius: 8px; background: #fff; }
    .zone strong { display: block; margin-bottom: 8px; }
    .count { font-size: 28px; font-weight: 700; }
    table { width: 100%; border: 1px solid #e4e4e7; border-collapse: separate; border-spacing: 0; border-radius: 8px; overflow: hidden; background: #fff; font-size: 14px; }
    th, td { padding: 11px 13px; border-bottom: 1px solid #e4e4e7; text-align: left; vertical-align: top; }
    th { background: #f4f4f5; color: #52525b; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
    tbody tr:last-child td { border-bottom: 0; }
    .match { color: #166534; font-weight: 600; }
    .mismatch { color: #b91c1c; font-weight: 600; }
    .unknown { color: #71717a; }
    pre { height: 300px; overflow: auto; padding: 16px; border: 1px solid #e4e4e7; border-radius: 8px; background: #fff; font-size: 12px; white-space: pre-wrap; word-break: break-word; }
    .theme-toggle { min-height: 34px; padding: 5px 10px; border: 1px solid #d4d4d8; border-radius: 6px; background: transparent; color: inherit; cursor: pointer; }
    @media (max-width: 720px) { body { padding: 24px 14px 60px; } header { display: block; } .status { display: inline-block; margin-top: 14px; } table { display: block; overflow-x: auto; white-space: nowrap; } }
  </style>
</head>
<body>
<header>
  <div><h1>AnyGate Presence</h1><p>Aktuální přítomnost podle čipových čteček a RFID antén</p></div>
  <div><button id="theme-toggle" class="theme-toggle" type="button">Tmavý režim</button> &nbsp; <span id="connection" class="status">Načítám MQTT…</span> &nbsp; <a href="/admin">Testovací administrace</a></div>
</header>

<div id="zones" class="zones"></div>

<h2>Pracovníci a porovnání zdrojů</h2>
<table><thead><tr><th>Pracovník</th><th>Výsledná poloha</th><th>Čip</th><th>RFID</th><th>Shoda</th></tr></thead><tbody id="people"></tbody></table>

<h2>RFID antény</h2>
<table><thead><tr><th>Anténa</th><th>Umístění</th><th>Právě zachycuje</th></tr></thead><tbody id="readers"></tbody></table>

<h2>Poslední zprávy brokeru</h2>
<pre id="messages">Zatím žádné zprávy.</pre>

<script>
  let config;
  let logAutoScroll = true;
  const byId = id => document.getElementById(id);
  const td = (row, value) => { const cell=row.insertCell(); cell.textContent=value || '—'; return cell; };
  const log = byId('messages');
  function setTheme(theme) {
    document.documentElement.dataset.theme=theme;
    byId('theme-toggle').textContent=theme === 'dark' ? 'Světlý režim' : 'Tmavý režim';
    localStorage.setItem('theme',theme);
  }
  setTheme(localStorage.getItem('theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  byId('theme-toggle').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  log.addEventListener('scroll', () => { logAutoScroll=log.scrollHeight-log.scrollTop-log.clientHeight < 8; });
  async function get(url) { const response=await fetch(url); if (!response.ok) throw new Error('API není dostupné'); return response.json(); }
  function directZone(value) { return value.zones[0] || null; }
  function inside(zone) { return zone === 'budova' || zone === 'patro_1' || zone === 'patro_2'; }
  function evidence(asset, data, type) {
    const ids=asset.identifiers.map(id => config.identifiers.find(item => item.id === id)).filter(item => item && item.type === type);
    const zones=ids.map(item => directZone(data.identifiers[item.id])).filter(Boolean);
    if (!zones.length) return {text:'bez informace', inside:null};
    const zone=zones[0]; return {text:zone, inside:inside(zone)};
  }
  async function refresh() {
    try {
      const [data,health]=await Promise.all([get('/state'),get('/health')]);
      const connection=byId('connection');
      connection.textContent=health.mqtt_connected ? 'MQTT připojeno' : 'MQTT odpojeno';
      connection.className=`status ${health.mqtt_connected ? 'ok' : 'off'}`;
      byId('zones').replaceChildren(...config.zones.map(zone => {
        const value=data.zones[zone.id], card=document.createElement('section'); card.className='zone';
        const title=document.createElement('strong'); title.textContent=zone.id.replaceAll('_',' ');
        const count=document.createElement('div'); count.className='count'; count.textContent=value.assets.length;
        const detail=document.createElement('p'); detail.textContent=value.assets.join(', ') || 'Nikdo';
        card.append(title,count,detail); return card;
      }));
      const people=byId('people'); people.replaceChildren();
      config.assets.forEach(asset => {
        const row=people.insertRow(), chip=evidence(asset,data,'chip'), rfid=evidence(asset,data,'rfid');
        let verdict='nelze porovnat', css='unknown';
        if (chip.inside !== null && rfid.inside !== null) { const same=chip.inside === rfid.inside; verdict=same ? 'odpovídá' : 'neshoda'; css=same ? 'match' : 'mismatch'; }
        td(row,asset.id); td(row,data.assets[asset.id].zones.join(' → ')); td(row,chip.text); td(row,rfid.text); td(row,verdict).className=css;
      });
      const readers=byId('readers'); readers.replaceChildren();
      config.readers.filter(item => item.type === 'rfid-reader').forEach(reader => {
        const row=readers.insertRow(), value=data.readers[reader.id]; td(row,reader.id); td(row,reader.zone); td(row,value.assets.join(', '));
      });
      const brokerMessages=data.recent_messages.filter(item => item.source !== 'admin' && item.source !== 'admin-status');
      log.textContent=brokerMessages.length ? JSON.stringify(brokerMessages.slice(0,100).reverse(),null,2) : 'Zatím žádné zprávy z brokeru.';
      if (logAutoScroll) log.scrollTop=log.scrollHeight;
    } catch (error) { byId('connection').textContent=error.message; byId('connection').className='status off'; }
  }
  get('/admin/config').then(value => { config=value; refresh(); setInterval(refresh,2000); });
</script>
</body>
</html>
    """


@app.get("/admin", response_class=HTMLResponse)
def admin() -> str:
    return """
<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>AnyGate Presence admin</title>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #18181b;
      background: #f8fafc;
    }
    * { box-sizing: border-box; }
    body {
      max-width: 1180px;
      margin: 0 auto;
      padding: 40px 24px 80px;
      line-height: 1.5;
    }
    h1 { margin: 0 0 6px; font-size: 28px; letter-spacing: -0.03em; }
    h2 {
      margin: 40px 0 14px;
      padding-bottom: 8px;
      border-bottom: 1px solid #e4e4e7;
      font-size: 17px;
    }
    #connection { margin: 0; color: #52525b; }
    #result { min-height: 24px; color: #166534; font-weight: 600; }
    form {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      align-items: end;
      gap: 14px;
      padding: 18px;
      border: 1px solid #e4e4e7;
      border-radius: 8px;
      background: #fff;
    }
    label { display: grid; gap: 6px; color: #52525b; font-size: 13px; font-weight: 600; }
    input, select, button {
      min-height: 38px;
      border: 1px solid #d4d4d8;
      border-radius: 6px;
      background: #fff;
      color: #18181b;
      font: inherit;
    }
    input, select { width: 100%; padding: 7px 10px; }
    select[multiple] { min-height: 112px; }
    input:focus, select:focus, button:focus-visible {
      outline: 2px solid #18181b;
      outline-offset: 2px;
    }
    button {
      width: fit-content;
      padding: 7px 13px;
      border-color: #18181b;
      background: #18181b;
      color: #fff;
      cursor: pointer;
      font-weight: 600;
    }
    button:hover { background: #3f3f46; }
    #reset { border-color: #dc2626; background: #fff; color: #b91c1c; }
    #reset:hover { background: #fef2f2; }
    table {
      width: 100%;
      border: 1px solid #e4e4e7;
      border-collapse: separate;
      border-spacing: 0;
      border-radius: 8px;
      overflow: hidden;
      background: #fff;
      font-size: 14px;
    }
    th, td { padding: 11px 13px; border: 0; border-bottom: 1px solid #e4e4e7; text-align: left; vertical-align: top; }
    th { background: #f4f4f5; color: #52525b; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
    tbody tr:last-child td { border-bottom: 0; }
    tbody tr:hover { background: #fafafa; }
    td button { min-height: 30px; padding: 4px 9px; font-size: 12px; }
    pre {
      max-height: 360px;
      overflow: auto;
      margin: 0;
      padding: 16px;
      border: 1px solid #e4e4e7;
      border-radius: 8px;
      background: #fff;
      color: #3f3f46;
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    @media (max-width: 720px) {
      body { padding: 24px 14px 60px; }
      form { grid-template-columns: 1fr; }
      table { display: block; overflow-x: auto; white-space: nowrap; }
    }
  </style>
</head>
<body>
<h1>AnyGate Presence</h1>
<p><a href="/">← Zpět na živý přehled</a></p>
<p id="connection">Načítám stav...</p>
<p id="result"></p>

<h2>Mock událost čtečky</h2>
<form id="event-form">
  <label>Čtečka <select id="event-reader" required></select></label>
  <label>Identifikátor <select id="event-identifier" required></select></label>
  <label>Událost <select id="event-type" required></select></label>
  <label>Čas UTC <input id="event-time" type="datetime-local" step="1"></label>
  <button>Odeslat událost</button>
</form>

<h2>Přímé nastavení statusu</h2>
<form id="status-form">
  <label>Identifikátor <select id="status-identifier" required></select></label>
  <label>Zóna <select id="status-zone"></select></label>
  <label>Vidí RFID antény <select id="status-readers" multiple size="5"></select></label>
  <label>Čas UTC <input id="status-time" type="datetime-local" step="1"></label>
  <button>Nastavit / přidat status</button>
</form>

<h2>Hromadné akce</h2>
<button id="demo">Vložit demo data</button>
<button id="reset">Smazat všechny statusy</button>

<h2>Assety</h2>
<table border="1"><thead><tr><th>Asset</th><th>Zóny</th><th>Čtečky</th></tr></thead><tbody id="assets"></tbody></table>

<h2>Identifikátory</h2>
<table border="1"><thead><tr><th>Identifikátor</th><th>Typ / kód</th><th>Zóny</th><th>Čtečky</th><th>Akce</th></tr></thead><tbody id="identifiers"></tbody></table>

<h2>Zóny</h2>
<table border="1"><thead><tr><th>Zóna</th><th>Assety</th><th>Identifikátory</th></tr></thead><tbody id="zones"></tbody></table>

<h2>Čtečky</h2>
<table border="1"><thead><tr><th>Čtečka</th><th>Zóna / topic</th><th>Assety</th><th>Identifikátory</th></tr></thead><tbody id="readers"></tbody></table>

<h2>Historie mock a MQTT událostí</h2>
<pre id="messages"></pre>

<script>
  let config;
  const byId = id => document.getElementById(id);
  const option = (value, text) => {
    const item = document.createElement('option'); item.value = value; item.textContent = text; return item;
  };
  const td = (row, value) => { const cell = row.insertCell(); cell.textContent = value || '—'; return cell; };
  async function request(url, options = {}) {
    const response = await fetch(url, options);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || 'Požadavek selhal');
    return body;
  }
  function json(method, body) {
    return {method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  }
  function selectedValues(select) { return [...select.selectedOptions].map(item => item.value); }
  function fillSelect(select, values, emptyText) {
    select.replaceChildren();
    if (emptyText !== undefined) select.append(option('', emptyText));
    values.forEach(item => select.append(option(item.id, item.label || item.id)));
  }
  function syncEventForm() {
    const reader = config.readers.find(item => item.id === byId('event-reader').value);
    const type = reader && reader.type === 'chips-reader' ? 'chip' : 'rfid';
    fillSelect(byId('event-identifier'), config.identifiers.filter(item => item.type === type).map(item => ({id:item.id, label:`${item.id} (${item.code})`})));
    const events = type === 'chip' ? ['sign_in', 'sign_out'] : ['rfid_enter', 'rfid_leave'];
    fillSelect(byId('event-type'), events.map(id => ({id})));
  }
  function renderTable(id, items, render) {
    const body = byId(id); body.replaceChildren();
    Object.entries(items).forEach(([key, value]) => render(body.insertRow(), key, value));
  }
  async function refresh() {
    const [data, health] = await Promise.all([request('/state'), request('/health')]);
    byId('connection').textContent = `Aplikace běží. MQTT: ${health.mqtt_connected ? 'připojeno' : 'odpojeno (mock administrace funguje i tak)'}`;
    renderTable('assets', data.assets, (row, id, value) => { td(row,id); td(row,value.zones.join(' → ')); td(row,value.readers.join(', ')); });
    renderTable('identifiers', data.identifiers, (row, id, value) => {
      const item = config.identifiers.find(entry => entry.id === id); td(row,id); td(row,`${item.type} / ${item.code}`); td(row,value.zones.join(' → ')); td(row,value.readers.join(', '));
      const edit = document.createElement('button'); edit.textContent = 'Upravit'; edit.onclick = () => {
        byId('status-identifier').value = id;
        byId('status-zone').value = value.zones[0] || '';
        [...byId('status-readers').options].forEach(option => { option.selected = value.readers.includes(option.value); });
        byId('status-form').scrollIntoView();
      };
      const remove = document.createElement('button'); remove.textContent = 'Smazat status'; remove.onclick = async () => { await request(`/admin/status/${encodeURIComponent(id)}`, {method:'DELETE'}); await refresh(); };
      td(row,'').replaceChildren(edit, ' ', remove);
    });
    renderTable('zones', data.zones, (row, id, value) => { td(row,id); td(row,value.assets.join(', ')); td(row,value.identifiers.join(', ')); });
    renderTable('readers', data.readers, (row, id, value) => { const item=config.readers.find(entry=>entry.id===id); td(row,id); td(row,`${item.zone} / ${item.topic}`); td(row,value.assets.join(', ')); td(row,value.identifiers.join(', ')); });
    byId('messages').textContent = JSON.stringify(data.recent_messages, null, 2);
  }
  async function run(action) {
    try { await action(); byId('result').textContent = 'Hotovo.'; await refresh(); }
    catch (error) { byId('result').textContent = `Chyba: ${error.message}`; }
  }
  async function init() {
    config = await request('/admin/config');
    fillSelect(byId('event-reader'), config.readers.map(item => ({id:item.id, label:`${item.id} (${item.zone})`})));
    fillSelect(byId('status-identifier'), config.identifiers.map(item => ({id:item.id, label:`${item.id} (${item.type})`})));
    fillSelect(byId('status-zone'), config.zones.map(item => ({id:item.id})), 'bez zóny');
    fillSelect(byId('status-readers'), config.readers.filter(item => item.type === 'rfid-reader').map(item => ({id:item.id, label:`${item.id} (${item.zone})`})));
    syncEventForm(); await refresh();
  }
  byId('event-reader').addEventListener('change', syncEventForm);
  byId('event-form').addEventListener('submit', event => { event.preventDefault(); run(() => request('/admin/events', json('POST', {reader_id:byId('event-reader').value, identifier_id:byId('event-identifier').value, event_type:byId('event-type').value, time_utc:byId('event-time').value || null}))); });
  byId('status-form').addEventListener('submit', event => { event.preventDefault(); run(() => request('/admin/status', json('PUT', {identifier_id:byId('status-identifier').value, direct_zone:byId('status-zone').value || null, readers:selectedValues(byId('status-readers')), time_utc:byId('status-time').value || null}))); });
  byId('demo').addEventListener('click', () => run(() => request('/admin/demo', {method:'POST'})));
  byId('reset').addEventListener('click', () => { if (confirm('Opravdu smazat všechny statusy?')) run(() => request('/admin/reset', {method:'POST'})); });
  init().catch(error => { byId('result').textContent = `Chyba: ${error.message}`; });
</script>
</body>
</html>
    """
