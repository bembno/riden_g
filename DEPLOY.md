# BMS System Deployment Guide

## Architecture
- **pi407 (storage)**: 192.168.2.42 - Runs `bms_mqtt.py` (BLE → MQTT bridge) + mosquitto broker
- **pi406 (measurement)**: 192.168.2.35 (user `pi`, pass `raspberry`) - Runs `smainbat.py` + `bms_db_logger.py`
- **l3PC (MariaDB host)**: 192.168.2.33 (user `l3`, pass `aaa`) - MariaDB only, no measurement processes
- **MQTT Broker**: 192.168.2.42:1883 (on pi407)
- **MariaDB**: 192.168.2.33:3306 (on l3PC laptop)

## SSH Access
```bash
# pi407 (storage) - key auth
ssh -i ~/.ssh/id_ed25519_pi407 pi@192.168.2.42

# pi406 (measurement) - password auth (user: pi, pass: raspberry)
sshpass -p 'raspberry' ssh pi@192.168.2.35

# l3PC (MariaDB only)
sshpass -p 'aaa' ssh l3@192.168.2.33
```

## Quick Deploy
```bash
# Deploy bridge code to pi407
./deploy.sh bridge

# Deploy logger code to pi406
./deploy.sh logger

# Deploy all
./deploy.sh all
```

## Services Management
```bash
# On pi407 (bridge)
screen -S bms -X quit                    # Stop
cd /home/pi/Desktop/storage && screen -S bms -dm bash -c 'exec python3 -u bms_mqtt.py'  # Start
tail -f /home/pi/Desktop/storage/logs/bms_mqtt.log  # Logs

# On pi406 (logger + control loop)
screen -S bms -X quit                      # Stop logger
cd /home/pi/Desktop/prog/measurement && screen -S bms -dm bash -c 'exec python3 -u bms_db_logger.py'  # Start
tail -f /home/pi/Desktop/prog/measurement/logs/bms_db.log  # Logs
```

## Bluetooth Fix (Critical)
The Pi's built-in Bluetooth (hci0 on UART) enters auto-suspend causing connection drops.

**Runtime fix:**
```bash
echo 'on' > /sys/class/bluetooth/hci0/device/power/control
```

**Persistent fix** (survives reboot) - `/etc/udev/rules.d/99-bluetooth-power.rules`:
```udev
ACTION=="add", SUBSYSTEM=="bluetooth", KERNEL=="hci0", RUN+="/bin/sh -c 'echo on > /sys/class/bluetooth/hci0/device/power/control'"
```

Apply:
```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Verify System Health
```bash
# Check MQTT
mosquitto_sub -t 'bms_jk/status' -C 1 -v
mosquitto_sub -t 'bms_jk/online' -C 1 -v  # Should show "1" when bridge running

# Check DB
mysql -h 192.168.2.33 -u admin -paaa energy -e "SELECT MAX(created_at) FROM bms_jk"

# Check BLE connectivity
bluetoothctl scan on  # Wait 10s
bluetoothctl devices | grep C8:47:80:58:A3:A6
```

## Key Files
| File | Location | Purpose |
|------|----------|---------|
| `bms_mqtt.py` | `/home/pi/Desktop/storage/` | BLE → MQTT bridge (24 h diag log + watchdog) |
| `bms_watchdog.py` | `/home/pi/Desktop/storage/` | Watchdog thresholds/decision logic (unit-tested) |
| `abms_log.txt` | `/home/pi/Desktop/storage/` | JSONL diagnostics: cycle/heartbeat/boot/reset records (24 h window, 8 MB cap) |
| `bms_db_logger.py` | `/home/pi/Desktop/prog/measurement/` | MQTT → DB logger |
| `BmsStorage.py` | `/home/pi/Desktop/prog/measurement/lib/` | DB storage class |
| `protocol.py` | `/home/pi/Desktop/storage/bms_jk/jkbms/` | Frame parser (buffer bounded) |
| `client.py` | `/home/pi/Desktop/storage/bms_jk/jkbms/` | BLE reader with LAST_DIAG phase timings |

## Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `BMS_MAC` | C8:47:80:58:A3:A6 | BMS BLE MAC |
| `JK_PIN` | 1234 | Bonding PIN |
| `BMS_POLL_SECONDS` | 30 | Poll interval |
| `BMS_BROKER` | 192.168.2.42 | MQTT broker (pi407) |
| `BMS_LOG_DIR` | ./logs | Log directory |
| `BMS_DIAG_HOURS` | 24 | abms_log.txt diagnostics window (hours) |
| `BMS_DIAG_MAXBYTES` | 8388608 | abms_log.txt size cap |
| `BMS_WATCHDOG_STUCK_S` | 600 | Reset if no main-loop progress for this long (> worst legit gap ~305 s) |
| `DB_HOST` | 192.168.2.33 | MariaDB host |
| `DB_USER` | admin | MariaDB user |
| `DB_PASSWORD` | aaa | MariaDB password |
| `DB_DATABASE` | energy | Database name |

## Troubleshooting
- **Bridge fails with "device not found"**: Check Bluetooth power management fix above
- **Logger not storing**: Check MQTT connectivity, DB credentials
- **MQTT LWT shows 0**: Bridge crashed or network issue - check `screen -r bms`
- **DB gaps**: Normal during BLE outages (exponential backoff + jitter)