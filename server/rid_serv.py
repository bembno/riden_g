
import socket
import threading
import json
import traceback
import os
import signal
import subprocess
from riden.riden import Riden
import time


# Robust Riden instance creation
riden = None
server_socket = None  # global
riden_status = {"ok": False, "last_error": None, "ttl": 0}
try:
    riden = Riden()
    riden_status["ok"] = True
except Exception as e:
    riden_status["ok"] = False
    riden_status["last_error"] = f"Init error: {e}"

def error_service():
    global riden
    while True:
        if riden is None:
            try:
                riden = Riden()
                riden_status["ok"] = True
                riden_status["last_error"] = None
                riden_status["ttl"] = 0
            except Exception as e:
                print(f"[ERROR] Could not initialize Riden: {e}")
                riden_status["ok"] = False
                riden_status["last_error"] = f"Init error: {e}"
                riden_status["ttl"] += 1
        else:
            try:
                _ = riden.get_id()
                riden_status["ok"] = True
                riden_status["last_error"] = None
                riden_status["ttl"] = 0
            except Exception as e:
                print(f"[ERROR] Lost connection to Riden: {e}")
                riden_status["ok"] = False
                riden_status["last_error"] = str(e)
                riden_status["ttl"] += 1
                riden = None
        time.sleep(2)

def handle_riden_command(command: dict) -> dict:
    """Dispatch command to Riden class methods."""
    if command.get("cmd") == "get_status":
        return {"status": riden_status}
    if riden is None:
        return {"error": "Riden device not connected", "status": riden_status}
    try:
        method = command.get("cmd")
        args = command.get("args", [])
        kwargs = command.get("kwargs", {})
        if not hasattr(riden, method):
            return {"error": f"Unknown command: {method}"}
        func = getattr(riden, method)
        result = func(*args, **kwargs)
        return {"result": result}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}

def client_thread(conn, addr):
    print(f"Connection from {addr}")
    try:
        while True:
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
        print(f"Error: {e}")
    finally:
        conn.close()
        print(f"Connection closed: {addr}")


def get_local_ip():
    """Detect the local IP address automatically."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't have to be reachable
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def start_server(host=None, port=6030):
    global server_socket
    if host is None:
        host = get_local_ip()
    free_port(port)
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"Riden 6030 TCP server listening on {host}:{port}")
    try:
        while True:
            conn, addr = server_socket.accept()
            t = threading.Thread(target=client_thread, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("Server shutting down.")
    finally:
        close_server()


def close_server():
    global server_socket
    if server_socket:
        try:
            server_socket.close()
            print("Server socket closed.")
        except Exception as e:
            print(f"Error closing socket: {e}")
        finally:
            server_socket = None

def free_port(port: int):
    """
    Check if a TCP port is in use, kill the process using it, and wait until the port is free.
    """
    while True:
        try:
            # Get all PIDs using this port
            result = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            pids = result.stdout.strip().splitlines()
        except Exception as e:
            print(f"Error checking port {port}: {e}")
            pids = []

        if not pids:
            break  # port is free

        for pid in pids:
            try:
                print(f"Killing process {pid} using port {port}")
                os.kill(int(pid), signal.SIGKILL)
            except Exception as e:
                print(f"Failed to kill process {pid}: {e}")

        time.sleep(0.5)


if __name__ == "__main__":
    # Start error service thread
    threading.Thread(target=error_service, daemon=True).start()
    start_server()
