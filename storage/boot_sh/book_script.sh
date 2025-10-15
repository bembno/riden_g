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

echo "Server started in screen session 'a'"
