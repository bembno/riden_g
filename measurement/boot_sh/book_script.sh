#!/usr/bin/env bash

echo "Waiting for Wi-Fi connection..."

while ! hostname -I | grep -qE '([0-9]{1,3}\.){3}[0-9]{1,3}'
do
    sleep 1
done

echo "IP detected"

# Wait for MQTT broker on pi407 (mosquitto may boot after this Pi).
# Without this, bms_db_logger's connect() used to crash at boot.
BROKER_HOST="${BMS_BROKER:-192.168.2.42}"
echo "Waiting for MQTT broker $BROKER_HOST:1883..."
for i in $(seq 1 60); do
    if timeout 1 bash -c "echo >/dev/tcp/$BROKER_HOST/1883" 2>/dev/null; then
        echo "MQTT broker is up"
        break
    fi
    sleep 1
done

sleep 1

screen -S a -dm bash -c "cd ~/Desktop/prog/measurement/ && exec python3 smainbat.py"

# BMS MQTT -> DB logger (rotating log at measurement/logs/bms_db.log)
# Logger also has its own connect-retry as a second line of defense.
screen -S bms -dm bash -c "cd ~/Desktop/prog/measurement/ && exec python3 -u bms_db_logger.py"

echo "Server started in screen session 'a'; BMS logger in 'bms'"
