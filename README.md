# riden_g — home battery storage automation

Two Raspberry Pis control a 16S LiFePO4 pack (230 Ah, 46.0–57.5 V) for
grid-neutral operation: a Riden RD6012 power supply charges the battery,
two Soyosource grid-tie inverters (one shared UART) discharge it, and a
PID loop drives the smart-meter import/export toward zero.

## Components

| Pi | Path | Process | Role |
|---|---|---|---|
| pi407 (storage) | `/home/pi/Desktop/storage/` | `riden_inverter_server.py` (screen `a`) | MQTT device server: Riden charger (Modbus RTU, /dev/ttyUSB0), inverters (4800 baud, /dev/ttyUSB1), charge relay (GPIO17) |
| pi407 | same | `bms_mqtt.py` (screen `bms`) | JK BMS BLE poller -> MQTT `bms_jk/status` every 2 min |
| pi406 (measurement) | `/home/pi/Desktop/prog/measurement/` | `smainbat.py` (screen `a`) | Control loop: P1 meter reader, PID, battery guard, DB logging |
| pi406 | same | `bms_db_logger.py` (screen `bms`) | `bms_jk/status` -> MariaDB `energy.bms_jk` |
| pi406 | same | `db_maintenance.py` (cron 03:15) | retention: p1_data 7 d, t_logs 30 d, bms_jk 90 d |

MQTT broker: mosquitto on pi407 (192.168.2.42), topics
`devices/command` / `devices/response` / `bms_jk/status` / `bms_jk/online`.
MariaDB: 192.168.2.33 (l3PC laptop, not a Pi), database `energy` (tables p1_data, t_logs, bms_jk).

## Safety layers (outermost first)

1. **Battery guard** (`lib/battery_guard.py`): SOLAR-ONLY charging policy -
   the battery is never charged from the grid. Voltage-only guard on live
   BMS data; empty pack (<= 46 V) -> discharge blocked (inverter 0 W;
   only solar surplus can recharge it), released as soon as pack > 46 V;
   full pack (>= 58.4 V) -> charge blocked (released <= 54.4 V). Falls
   back to Riden pack voltage when BMS data is >5 min stale.
2. **Watchdog escalation** (server): 60 s MQTT silence -> outputs off;
   5 min silence -> reboot (charger required) or inverter-only steady state.
3. **Software watchdog** (loop): 60 s hang -> reboot.
4. **Stale meter data** -> immediate safe idle (all outputs 0).
5. Hardware backstops: Riden OVP/OCP, BMS OVP/UVP, inverter limits.

## Notes

- **Timezones:** all database timestamps are UTC. The MySQL session
  timezone is set to UTC on connection (`SET time_zone = '+00:00'`).
  Pi console logs run local time (CEST); add +2 h (summer) when
  cross-referencing console logs with DB times.
- **Relay:** GPIO17, active-HIGH wiring. State persists in
  `storage/.pin_state` and is re-applied when the server restarts.
- **BMS:** JK-B2A24S15P over BLE (`C8:47:80:58:A3:A6`, PIN 1234); the
  bridge self-restarts if a BLE read hangs >2 min (BlueZ DBus hangs).
- All device logs live in `logs/*.log` next to each script (rotating,
  1 MB x 3).

## Deploy

Files are edited in this repo and copied to the Pis (paths above); the
boot scripts (`boot_sh/book_script.sh` on each Pi, started via @reboot
crontab) launch the screen sessions. Restart a service with
`screen -S <name> -X quit` + the start command from the boot script.
