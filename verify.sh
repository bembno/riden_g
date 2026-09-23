#!/usr/bin/env bash
# Verify BMS system health

BRIDGE_HOST="192.168.2.42"
BRIDGE_USER="pi"
BRIDGE_KEY="~/.ssh/id_ed25519_pi407"

LOGGER_HOST="192.168.2.35"
LOGGER_USER="pi"
LOGGER_PASS="raspberry"

echo "=== Bridge (pi407) ==="
ssh -i "$BRIDGE_KEY" "$BRIDGE_USER@$BRIDGE_HOST" "
    echo 'Process:'
    ps aux | grep bms_mqtt | grep -v grep
    echo ''
    echo 'MQTT online:'
    mosquitto_sub -t 'bms_jk/online' -C 1 -v 2>/dev/null || echo 'MQTT not responding'
    echo ''
    echo 'Bluetooth power:'
    cat /sys/class/bluetooth/hci0/device/power/control
    echo ''
    echo 'Recent logs:'
    tail -3 /home/pi/Desktop/storage/logs/bms_mqtt.log
"

echo ""
echo "=== Logger (pi406) ==="
sshpass -p "$LOGGER_PASS" ssh -o StrictHostKeyChecking=no "$LOGGER_USER@$LOGGER_HOST" "
    echo 'Process:'
    ps aux | grep bms_db_logger | grep -v grep
    echo ''
    echo 'DB latest:'
    mysql -h 192.168.2.33 -u admin -paaa energy -e \"SELECT MAX(created_at) FROM bms_jk\" 2>/dev/null || echo 'DB query failed'
    echo ''
    echo 'Recent logs:'
    tail -3 /home/pi/Desktop/prog/measurement/logs/bms_db.log 2>/dev/null || echo 'No log file'
"

echo ""
echo "=== MQTT Data ==="
ssh -i "$BRIDGE_KEY" "$BRIDGE_USER@$BRIDGE_HOST" "
    timeout 5 mosquitto_sub -t 'bms_jk/status' -C 1 -v 2>/dev/null | head -c 200
    echo ''
"