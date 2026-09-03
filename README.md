# AnyGate Presence

Daemon přijímá MQTT události z čipových a RFID čteček, odvozuje přítomnost identifierů a assetů v hierarchii zón a změněné stavy publikuje zpět do MQTT jako retained zprávy.

## Chování

- `sign_in` přihlásí čip do zóny čtečky, `sign_out` jej odhlásí.
- `rfid_enter` přesune RFID identifier do zóny antény a označí anténu jako aktivní.
- `rfid_leave` zruší pouze aktivní detekci; poslední známá zóna zůstává.
- Přítomnost v podzóně automaticky znamená přítomnost ve všech rodičovských zónách.
- Stav se ukládá do `data/presence_state.json` a po restartu se ověří proti aktuální konfiguraci.
- Konflikt více identifierů jednoho assetu řeší `conflict_policy` v konfiguraci.

Konfigurace instalace Nedvězská je v [config/nedvezska.json](config/nedvezska.json). Vnitřní vstupní čtečka je záměrně ignorována jako duplicita vnější čtečky.

## Spuštění

MQTT broker je dostupný pouze přes AnyGate VPN na adrese `100.65.0.48:1883`.
Před spuštěním aplikace proto připoj VPN: na Linuxu pomocí OpenVPN, na Windows
importováním dodaného OVPN profilu do OpenVPN Community klienta. VPN profil
obsahuje soukromý klíč a nesmí se ukládat do repozitáře.

Vytvoř lokální nastavení a doplň MQTT heslo:

```bash
cp .env.example .env
```

Spuštění přes Docker:

```bash
docker compose up --build -d
```

Spuštění bez Dockeru:

```bash
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Rozhraní

- živý přehled: `http://localhost:8000/`
- testovací administrace a mock události: `http://localhost:8000/admin`
- JSON stav: `http://localhost:8000/state`
- kontrola služby a MQTT připojení: `http://localhost:8000/health`

Administrace funguje i bez brokeru. Hlavní přehled rozlišuje skutečné MQTT zprávy od mock událostí.

## Konfigurace

Připojení a cesty se nastavují v `.env`. Nejdůležitější proměnné jsou `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TLS`, `MQTT_MONITOR_TOPICS`, `PRESENCE_CONFIG` a `DATA_DIR`. Pro privátní broker se používá nešifrované MQTT spojení (`MQTT_TLS=false`); kontrola TLS certifikátu se proto neuplatňuje. `MQTT_MONITOR_TOPICS` je čárkou oddělený seznam MQTT filtrů, jejichž provoz se pouze vypisuje na frontend a neovlivňuje vypočtenou přítomnost.

Konfigurační JSON obsahuje:

- `zones` — strom zón a přiřazené čtečky;
- `readers` — typy čteček a vstupní/výstupní topicy;
- `identifiers` — známé čipy a RFID kódy;
- `assets` — osoby nebo předměty a jejich identifiery;
- `conflict_policy` — `newest_event`, `prefer_chip`, `prefer_rfid` nebo `priority_order`.

## Testy

```bash
python -m unittest discover -s tests -v
```
