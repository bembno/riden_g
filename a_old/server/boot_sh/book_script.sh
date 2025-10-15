#!/usr/bin/env bash

# wait until wlan0 gets an IP address
echo "Waiting for Wi-Fi connection..."
while ! hostname -I | grep -qE '([0-9]{1,3}\.){3}[0-9]{1,3}'; do
    sleep 1
done

# small delay just in case
sleep 2

# start in screen
screen -S a -dm bash -c 'cd ~/Desktop/server && exec python3 rid_serv.py'

echo "Server started in screen session 'a'"
