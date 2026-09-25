#!/usr/bin/env bash
# Deploy script for BMS system
# Usage: ./deploy.sh [bridge|logger|all]

set -e

BRIDGE_HOST="192.168.2.42"
BRIDGE_USER="pi"
BRIDGE_KEY="~/.ssh/id_ed25519_pi407"
BRIDGE_PATH="/home/pi/Desktop/storage"

LOGGER_HOST="192.168.2.35"
LOGGER_USER="pi"
LOGGER_PASS="raspberry"
LOGGER_PATH="/home/pi/Desktop/prog/measurement"

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

deploy_bridge() {
    echo "=== Deploying bridge to pi407 ==="
    
    # Copy main bridge script + watchdog decision logic
    scp -i "$BRIDGE_KEY" "$REPO_ROOT/storage/bms_mqtt.py" "$BRIDGE_USER@$BRIDGE_HOST:$BRIDGE_PATH/bms_mqtt.py"
    scp -i "$BRIDGE_KEY" "$REPO_ROOT/storage/bms_watchdog.py" "$BRIDGE_USER@$BRIDGE_HOST:$BRIDGE_PATH/bms_watchdog.py"
    
    # Copy protocol fix + instrumented client (LAST_DIAG phases)
    scp -i "$BRIDGE_KEY" "$REPO_ROOT/storage/bms_jk/jkbms/protocol.py" "$BRIDGE_USER@$BRIDGE_HOST:$BRIDGE_PATH/bms_jk/jkbms/protocol.py"
    scp -i "$BRIDGE_KEY" "$REPO_ROOT/storage/bms_jk/jkbms/client.py" "$BRIDGE_USER@$BRIDGE_HOST:$BRIDGE_PATH/bms_jk/jkbms/client.py"
    
    # Restart bridge service
    ssh -i "$BRIDGE_KEY" "$BRIDGE_USER@$BRIDGE_HOST" "
        screen -S bms -X quit 2>/dev/null || true
        sleep 2
        rm -rf $BRIDGE_PATH/bms_jk/jkbms/__pycache__
        cd $BRIDGE_PATH && screen -S bms -dm bash -c 'exec python3 -u bms_mqtt.py'
        sleep 3
        echo 'Bridge restarted. Status:'
        ps aux | grep bms_mqtt | grep -v grep
    "
    
    echo "Bridge deployed and restarted"
}

deploy_logger() {
    echo "=== Deploying logger to pi406 ==="
    
    # Copy logger script
    sshpass -p "$LOGGER_PASS" scp -o StrictHostKeyChecking=no \
        "$REPO_ROOT/measurement/bms_db_logger.py" "$LOGGER_USER@$LOGGER_HOST:$LOGGER_PATH/bms_db_logger.py"
    
    # Copy BmsStorage
    sshpass -p "$LOGGER_PASS" scp -o StrictHostKeyChecking=no \
        "$REPO_ROOT/measurement/lib/BmsStorage.py" "$LOGGER_USER@$LOGGER_HOST:$LOGGER_PATH/lib/BmsStorage.py"
    
    # Copy P1Storage (for smainbat.py)
    sshpass -p "$LOGGER_PASS" scp -o StrictHostKeyChecking=no \
        "$REPO_ROOT/measurement/lib/P1Storage.py" "$LOGGER_USER@$LOGGER_HOST:$LOGGER_PATH/lib/P1Storage.py"
    
    # Ensure __init__.py exists
    sshpass -p "$LOGGER_PASS" ssh -o StrictHostKeyChecking=no "$LOGGER_USER@$LOGGER_HOST" "
        touch $LOGGER_PATH/lib/__init__.py
    "
    
    # Restart logger service (screen, same as boot script)
    sshpass -p "$LOGGER_PASS" ssh -o StrictHostKeyChecking=no "$LOGGER_USER@$LOGGER_HOST" "
        screen -S bms -X quit 2>/dev/null || true
        sleep 2
        mkdir -p $LOGGER_PATH/logs
        screen -S bms -dm bash -c 'cd $LOGGER_PATH && exec python3 -u bms_db_logger.py'
        sleep 3
        echo 'Logger restarted. Status:'
        screen -ls
        pgrep -af bms_db_logger.py || true
    "
    
    echo "Logger deployed and restarted"
}

deploy_all() {
    deploy_bridge
    deploy_logger
    echo "=== All deployed ==="
}

case "${1:-all}" in
    bridge)
        deploy_bridge
        ;;
    logger)
        deploy_logger
        ;;
    all)
        deploy_all
        ;;
    *)
        echo "Usage: $0 [bridge|logger|all]"
        exit 1
        ;;
esac