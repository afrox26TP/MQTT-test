# AnyGate Presence Engine — showcase

Malý daemon, který převádí události z čipových a RFID čteček na jednotný stav přítomnosti. Stav drží v paměti a po každé změně publikuje přes MQTT jako **retained** zprávu. Součástí je jednoduchý webový monitor.

## Co ukázka umí

- načíst a zkontrolovat JSON konfiguraci instalace;
- odvodit přítomnost v celém stromu zón (`chodba → patro → budova`);
- najít identifier podle typu a kódu a z něj příslušný asset;
- zpracovat rozdílnou logiku `chips-reader` a `rfid-reader`;
- publikovat změněné stavy identifierů, assetů, zón a RFID čteček;
- odmítnout neznámé kódy, špatné události a opožděné zprávy;
- zobrazit aktuální stav na `http://localhost:8000`.

Ukázková mapa je v [config/showcase.json](config/showcase.json). Obsahuje budovu, druhé patro, chodbu, konferenční místnost a samostatnou pseudozónu `outside`.

## Jak teče událost systémem

1. MQTT zpráva přijde na `topic_in` konkrétní čtečky.
2. Podle typu čtečky se ověří typ události a dohledá identifier podle dvojice `(type, code)`.
3. Identifier dostane nejvýše jednu přímou zónu. Nadřazené zóny se vždy dopočítají.
4. Asset převezme polohu identifieru s nejnovější platnou událostí.
5. Porovná se stav před a po události a publikují se jen změněné pohledy.

### Význam událostí

| Čtečka | Událost | Chování |
|---|---|---|
| `chips-reader` | `sign_in` | nastaví zónu čtečky |
| `chips-reader` | `sign_out` | odstraní polohu, pokud odpovídá zóně čtečky |
| `rfid-reader` | `rfid_enter` | nastaví zónu a přidá čtečku mezi právě vidící antény |
| `rfid-reader` | `rfid_leave` | odebere pouze vidící anténu; odvozená zóna zůstává |

**Konfliktní identifiery assetu:** vyhrává událost s nejnovějším `time_utc`. Starší opožděná událost stejného identifieru se ignoruje. Tato politika je záměrně soustředěná v [app/state.py](app/state.py), aby ji šlo po zkušenostech z provozu snadno vyměnit.

## Rychlé spuštění

Požadavek: Docker s Compose.

```bash
docker compose up --build
```

- monitor: `http://localhost:8000/`
- celý stav: `http://localhost:8000/state`
- health check: `http://localhost:8000/health`

## Tříkrokové demo

V druhém terminálu lze nasimulovat pohyb Alice.

### 1. RFID ji zachytí na chodbě

```bash
docker exec mqtt-broker mosquitto_pub -h localhost -t showcase/readers/corridor/events -m '{"type":"rfid_enter","code":"30121343500000012354892","time_utc":"2026-08-18 10:00:00"}'
```

Alice je v `corridor`, a tedy také ve `floor-2` a `building`. Čtečka ji právě vidí.

### 2. RFID ji přestane vidět

```bash
docker exec mqtt-broker mosquitto_pub -h localhost -t showcase/readers/corridor/events -m '{"type":"rfid_leave","code":"30121343500000012354892","time_utc":"2026-08-18 10:01:00"}'
```

Pole `readers` se vyprázdní, ale poloha zůstane na chodbě.

### 3. Čipem se přihlásí v konferenční místnosti

```bash
docker exec mqtt-broker mosquitto_pub -h localhost -t showcase/readers/conference/events -m '{"type":"sign_in","code":"a0cd34","time_utc":"2026-08-18 10:02:00"}'
```

Alice má dva identifiery s rozdílnou historií. Pro asset `person-alice` vyhraje novější čipová událost a přesune se do `conference-room`.

Publikované retained zprávy lze sledovat takto:

```bash
docker exec mqtt-broker mosquitto_sub -h localhost -t "showcase/presence/#" -v
```

## Konfigurace

Každá čtečka musí být uvedena právě u jedné zóny. Každý její `topic_in` musí být unikátní. Identifier smí patřit nejvýše jednomu assetu. Při startu se kontrolují také duplicitní ID, neexistující reference a cykly ve stromu zón.

Důležité proměnné prostředí:

| Proměnná | Výchozí hodnota |
|---|---|
| `MQTT_BROKER_HOST` | `mosquitto` |
| `MQTT_BROKER_PORT` | `1883` |
| `MQTT_CLIENT_ID` | `anygate-presence` |
| `MQTT_QOS` | `1` |
| `PRESENCE_CONFIG` | `config/showcase.json` |
| `MAX_RECENT_MESSAGES` | `100` |

## Struktura

- [app/config.py](app/config.py) — datové modely, načtení a validace konfigurace;
- [app/state.py](app/state.py) — doménová pravidla a sestavení výstupních stavů;
- [app/mqtt_client.py](app/mqtt_client.py) — odběr vstupů a retained publikování výstupů;
- [app/main.py](app/main.py) — životní cyklus služby, API a webový monitor;
- [tests/test_presence.py](tests/test_presence.py) — příklady očekávaného chování.

Testy bez dalších závislostí:

```bash
python -m unittest discover -s tests -v
```

## Omezení showcase

Stav je pouze v RAM, takže po restartu začíná prázdný. Produkční verze bude pravděpodobně potřebovat persistentní snapshot, autentizaci/TLS pro MQTT, řízenou aktualizaci konfigurace a dohodnuté chování pro asset bez známé polohy. Pseudozóna `outside` se nyní chová jako běžná samostatná kořenová zóna — asset se do ní dostane pouze explicitní událostí její čtečky.
