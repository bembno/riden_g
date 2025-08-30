
import socket
import json

class RidenRemote:
    def __init__(self, ip="192.168.2.29", port=6030):
        self.ip = ip
        self.port = port

    def send_command(self, cmd, args=None, kwargs=None):
        command = {"cmd": cmd}
        if args:
            command["args"] = args
        if kwargs:
            command["kwargs"] = kwargs
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self.ip, self.port))
            s.sendall(json.dumps(command).encode())
            data = s.recv(4096)
        try:
            return json.loads(data.decode())
        except Exception as e:
            return {"error": f"Invalid response: {e}", "raw": data.decode(errors='replace')}

    def get_v_set(self):
        resp = self.send_command("get_v_set")
        return resp.get("result", resp)

    def set_v_set(self, v):
        resp = self.send_command("set_v_set", args=[v])
        return resp.get("result", resp)

    # Add more methods as needed, or use send_command for generic calls

if __name__ == "__main__":
    import sys
    import ast
    remote = RidenRemote()
    if len(sys.argv) < 2:
        print("Usage: python riden_remote.py <method> [args_as_python_list] [kwargs_as_python_dict]")
        print("Example: python riden_remote.py set_v_set '[12.5]' '{}'")
        print("Default demo:")
        print("get_v_set:", remote.get_v_set())
        print("set_v_set:", remote.set_v_set(0.5))
    else:
        method = sys.argv[1]
        args = ast.literal_eval(sys.argv[2]) if len(sys.argv) > 2 else []
        kwargs = ast.literal_eval(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(f"Calling {method} with args={args} kwargs={kwargs}")
        func = getattr(remote, method, None)
        if func:
            print(func(*args, **kwargs))
        else:
            print(remote.send_command(method, args=args, kwargs=kwargs))

if __name__ == "__main__":
    import sys
    import ast
    if len(sys.argv) < 2:
        print("Usage: python riden_remote.py <method> [args_as_python_list] [kwargs_as_python_dict]")
        print("Example: python riden_remote.py set_v_set '[12.5]' '{}'")
        print("Default demo:")
        remote = RidenRemote()
        print("get_v_set:", remote.get_v_set())
        print("set_v_set:", remote.set_v_set(0.5))
    else:
        method = sys.argv[1]
        args = ast.literal_eval(sys.argv[2]) if len(sys.argv) > 2 else []
        kwargs = ast.literal_eval(sys.argv[3]) if len(sys.argv) > 3 else {}
        print(f"Calling {method} with args={args} kwargs={kwargs}")
        remote = RidenRemote()
        print(remote.send_command(method, args=args, kwargs=kwargs))
