# MQTT RFID + Attendance Gateway

Tato slozka obsahuje jednoduchy Python gateway, ktery:
- cte RFID data z MQTT topicu,
- cte dochazkove udalosti (prichod/odchod),
- cte celkovy snapshot pritomnosti,
- drzi aktualni stav v pameti,
- vystavuje stav pres HTTP (`/state`) a jednoduchy web na `/`.

Format zprav zatim neni pevny. Aplikace je proto napsana tolerantne:
- uklada syrove zpravy,
- zkousi parse JSON,
- pro attendance event/snapshot pouziva vice moznych klicu (`person`, `name`, `room`, `location`, `event`, `action`, ...).

## Pouzita knihovna pro MQTT

Pouzita je stabilni knihovna **paho-mqtt** (`paho-mqtt==2.1.0`).

## Spusteni pres Docker Compose

1. Otevri terminal ve slozce `MQTT`.
2. Spust:

```bash
docker compose up --build
```

3. Otevri monitor:
- `http://localhost:8000/`
- API stav: `http://localhost:8000/state`
- Health: `http://localhost:8000/health`

## Testovani MQTT zprav

Posilani testovacich zprav lze delat treba pres `mosquitto_pub`:

```bash
# RFID zprava
docker exec -it mqtt-broker mosquitto_pub -h localhost -t rfid/reader-1 -m '{"card_id":"A1B2C3","reader":"reader-1"}'

# Attendance event (prichod)
docker exec -it mqtt-broker mosquitto_pub -h localhost -t attendance/events -m '{"person":"Petr","event":"arrive","room":"Lab"}'

# Attendance event (odchod)
docker exec -it mqtt-broker mosquitto_pub -h localhost -t attendance/events -m '{"person":"Petr","event":"leave","room":"Lab"}'

# Attendance snapshot
docker exec -it mqtt-broker mosquitto_pub -h localhost -t attendance/state -m '{"people":[{"person":"Anna","room":"Office","present":true},{"person":"Karel","room":"Lab","present":true}]}'
```

## Konfigurace

Nastaveni je pres `.env`:
- `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`
- `MQTT_TOPIC_RFID`
- `MQTT_TOPIC_ATTENDANCE_EVENTS`
- `MQTT_TOPIC_ATTENDANCE_STATE`
- `MAX_RECENT_MESSAGES`

Viz taky `.env.example`.

## Poznamka k produkci

Pro produkci muzes stejnou app nasadit do libovolneho kontejneroveho hostingu (Docker/Podman/Kubernetes). Dava to reprodukovatelne behy, jednoduche tagovani image a rychle testovani stejneho runtime jako v produkci.
