#!/usr/bin/env bash

# wait until wlan0 gets an IP address
echo "Waiting for Wi-Fi connection..."
while ! hostname -I | grep -qE '([0-9]{1,3}\.){3}[0-9]{1,3}'; do
    sleep 1
done

# small delay just in case
sleep 2

# start in screen
screen -S a -dm bash -c 'cd /home/pi/Desktop/storage && exec python3 riden_inverter_server.py'

# BMS BLE -> MQTT bridge (waits for bluetoothd, tolerates BT being slow at boot)
for i in $(seq 1 12); do
    if bluetoothctl show >/dev/null 2>&1; then break; fi
    sleep 5
done
screen -S bms -dm bash -c 'cd /home/pi/Desktop/storage && exec python3 -u bms_mqtt.py > /tmp/bms_mqtt.log 2>&1'

echo "Server started in screen session 'a'; BMS bridge in 'bms'"
