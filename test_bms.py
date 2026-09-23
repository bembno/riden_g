#!/usr/bin/env python3
"""Quick BMS system test - run locally to verify deployment"""

import mysql.connector
import subprocess
import sys

def test_db():
    print("Testing MariaDB connection...")
    try:
        conn = mysql.connector.connect(
            host='192.168.2.33', user='admin', password='aaa', database='energy'
        )
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(created_at), COUNT(*) FROM bms_jk WHERE created_at > DATE_SUB(NOW(), INTERVAL 1 HOUR)")
        row = cursor.fetchone()
        print(f"  Latest entry: {row[0]}")
        print(f"  Entries last hour: {row[1]}")
        conn.close()
        return True
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

def test_mqtt_online():
    print("Testing MQTT online topic...")
    try:
        result = subprocess.run(
            ['ssh', '-i', '~/.ssh/id_ed25519_pi407', 'pi@192.168.2.42', 
             'mosquitto_sub -t bms_jk/online -C 1 -v'],
            capture_output=True, text=True, timeout=10
        )
        if '1' in result.stdout:
            print(f"  Bridge online: YES")
            return True
        else:
            print(f"  Bridge online: NO ({result.stdout.strip()})")
            return False
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

def test_mqtt_data():
    print("Testing MQTT data topic...")
    try:
        result = subprocess.run(
            ['ssh', '-i', '~/.ssh/id_ed25519_pi407', 'pi@192.168.2.42', 
             'timeout 5 mosquitto_sub -t bms_jk/status -C 1 -v'],
            capture_output=True, text=True, timeout=15
        )
        if 'battery_voltage_V' in result.stdout:
            print(f"  Data flowing: YES")
            return True
        else:
            print(f"  Data flowing: NO")
            return False
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

def test_bridge_process():
    print("Testing bridge process...")
    try:
        result = subprocess.run(
            ['ssh', '-i', '~/.ssh/id_ed25519_pi407', 'pi@192.168.2.42', 
             'ps aux | grep bms_mqtt | grep -v grep'],
            capture_output=True, text=True, timeout=10
        )
        if 'bms_mqtt.py' in result.stdout:
            print(f"  Bridge running: YES")
            return True
        else:
            print(f"  Bridge running: NO")
            return False
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

def test_logger_process():
    print("Testing logger process...")
    try:
        result = subprocess.run(
            ['sshpass', '-p', 'raspberry', 'ssh', '-o', 'StrictHostKeyChecking=no', 'pi@192.168.2.35', 
             'pgrep -af bms_db_logger.py'],
            capture_output=True, text=True, timeout=10
        )
        if 'bms_db_logger.py' in result.stdout:
            print(f"  Logger running: YES")
            return True
        else:
            print(f"  Logger running: NO")
            return False
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

def test_bluetooth_power():
    print("Testing Bluetooth power management...")
    try:
        result = subprocess.run(
            ['ssh', '-i', '~/.ssh/id_ed25519_pi407', 'pi@192.168.2.42', 
             'cat /sys/class/bluetooth/hci0/device/power/control'],
            capture_output=True, text=True, timeout=10
        )
        if result.stdout.strip() == 'on':
            print(f"  Bluetooth power: ON (correct)")
            return True
        else:
            print(f"  Bluetooth power: {result.stdout.strip()} (should be 'on')")
            return False
    except Exception as e:
        print(f"  FAILED: {e}")
        return False

if __name__ == '__main__':
    tests = [
        test_bluetooth_power,
        test_bridge_process,
        test_logger_process,
        test_mqtt_online,
        test_mqtt_data,
        test_db,
    ]
    
    results = []
    for test in tests:
        results.append(test())
        print()
    
    passed = sum(results)
    total = len(results)
    print(f"=== Summary: {passed}/{total} tests passed ===")
    sys.exit(0 if passed == total else 1)