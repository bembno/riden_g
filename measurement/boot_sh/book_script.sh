#!/usr/bin/env bash

echo "Waiting for Wi-Fi connection..."

while ! hostname -I | grep -qE '([0-9]{1,3}\.){3}[0-9]{1,3}'
do
    sleep 1
done

echo "IP detected"

sleep 2

screen -S a -dm bash -c "cd ~/Desktop/prog/measurement/ && exec python3 smainbat.py"

# BMS MQTT -> DB logger
screen -S bms -dm bash -c "cd ~/Desktop/prog/measurement/ && exec python3 -u bms_db_logger.py > /tmp/bms_db.log 2>&1"

echo "Server started in screen session 'a'; BMS logger in 'bms'"
