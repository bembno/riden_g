"""Shared stdout-to-rotating-log tee (R2: persistent, bounded logs).

Mirrors print() output into logs/<name>.log with a RotatingFileHandler
(1 MB x 2 backups by default) while keeping the console alive for the
screen session. Usage:

    from log_tee import tee_stdout_to_file
    tee_stdout_to_file("myscript")          # logs next to CWD's parent? no:
                                            # logs/ inside the script dir
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def tee_stdout_to_file(name, base_dir=None, max_bytes=1024 * 1024, backups=2):
    """Tee sys.stdout lines into <base_dir>/logs/<name>.log (rotating)."""
    base_dir = base_dir or os.path.dirname(os.path.abspath(sys.argv[0]))
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    log = logging.getLogger(f"tee.{name}")
    log.setLevel(logging.INFO)
    log.handlers.clear()
    fh = RotatingFileHandler(os.path.join(log_dir, f"{name}.log"),
                             maxBytes=max_bytes, backupCount=backups,
                             encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(fh)

    class _PrintToLog:
        def __init__(self, log):
            self.log = log
            self.buf = ""

        def write(self, s):
            self.buf += s
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                if line.strip():
                    self.log.info(line)

        def flush(self):
            if self.buf.strip():
                self.log.info(self.buf)
                self.buf = ""

    class _Tee:
        def __init__(self, a, b):
            self.a = a
            self.b = b

        def write(self, s):
            for sink in (self.a, self.b):
                try:
                    sink.write(s)
                except Exception:
                    pass

        def flush(self):
            for sink in (self.a, self.b):
                try:
                    sink.flush()
                except Exception:
                    pass

    if not isinstance(sys.stdout, _Tee):  # idempotent
        sys.stdout = _Tee(sys.__stdout__, _PrintToLog(log))
    return log
