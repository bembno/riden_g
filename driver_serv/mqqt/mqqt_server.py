import socket
import json
import traceback
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

# ---------------- Server Handling ----------------
def client_thread(conn, addr, shutdown_flag, handle_riden_command):
    print(f"[INFO] Connection from {addr}")
    try:
        while not shutdown_flag():
            data = conn.recv(4096)
            if not data:
                break
            try:
                command = json.loads(data.decode())
            except Exception as e:
                response = {"error": f"Invalid JSON: {e}"}
            else:
                response = handle_riden_command(command)
            conn.sendall(json.dumps(response).encode())
    except Exception as e:
        if not shutdown_flag():
            print(f"[WARN] Client error {addr}: {e}")
    finally:
        conn.close()
        print(f"[INFO] Connection closed: {addr}")

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def start_server(handle_riden_command, shutdown_flag, host=None, port=6030, max_workers=20):
    server_socket = None
    if host is None:
        host = get_local_ip()
    free_port(port)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"[INFO] Riden 6030 TCP server listening on {host}:{port}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        try:
            while not shutdown_flag():
                try:
                    server_socket.settimeout(1.0)
                    conn, addr = server_socket.accept()
                except socket.timeout:
                    continue
                except Exception as e:
                    if not shutdown_flag():
                        print(f"[ERROR] Accept failed: {e}")
                    continue

                conn.settimeout(10)
                executor.submit(client_thread, conn, addr, shutdown_flag, handle_riden_command)
        except Exception as e:
            if not shutdown_flag():
                print(f"[ERROR] Server error: {e}")
        finally:
            if server_socket:
                try:
                    server_socket.close()
                    print("[INFO] Server socket closed.")
                except Exception as e:
                    print(f"[WARN] Error closing socket: {e}")

def free_port(port: int):
    while True:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pids = result.stdout.strip().splitlines()
        except Exception as e:
            print(f"[WARN] Error checking port {port}: {e}")
            pids = []

        if not pids:
            break

        for pid in pids:
            try:
                print(f"[INFO] Killing process {pid} using port {port}")
                os.kill(int(pid), signal.SIGKILL)
            except Exception as e:
                print(f"[WARN] Failed to kill process {pid}: {e}")

        time.sleep(0.5)
import threading
import time
import paho.mqtt.client as mqtt

class MQTTServer:
    def __init__(self, broker='localhost', port=1883, topic='riden/status'):
        self.broker = broker
        self.port = port
        self.topic = topic
        self.client = mqtt.Client()
        self.running = False

    def on_connect(self, client, userdata, flags, rc):
        print(f"[MQTT] Connected with result code {rc}")
        client.subscribe(self.topic)

    def on_message(self, client, userdata, msg):
        print(f"[MQTT] Message received: {msg.topic} {msg.payload}")

    def start(self):
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.broker, self.port, 60)
        self.running = True
        threading.Thread(target=self.client.loop_forever, daemon=True).start()

    def stop(self):
        self.running = False
        self.client.disconnect()

    def publish_status(self, status):
        self.client.publish(self.topic, status)
