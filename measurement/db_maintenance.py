#!/usr/bin/env python3
"""Nightly DB retention maintenance (run on the measurement Pi).

Prunes old rows from the energy database in batches so the tables stay
bounded and INSERT performance does not degrade over months:

  p1_data : keep P1_KEEP_DAYS   (default 7)   - full telegrams, ~6.7 MB/day
  t_logs  : keep TLOGS_KEEP_DAYS(default 30)  - control-loop samples
  bms_jk  : keep BMS_KEEP_DAYS  (default 90)  - BMS polls, low volume

Deletes run in LIMIT batches to avoid long table locks; a summary line is
written to a rotating log. Safe to re-run; safe to run while the writers
are active (row-level deletes only).

Cron (pi406): 15 3 * * * cd ~/Desktop/prog/measurement && python3 db_maintenance.py

Environment overrides: DB_HOST/DB_USER/DB_PASSWORD/DB_DATABASE,
  P1_KEEP_DAYS, TLOGS_KEEP_DAYS, BMS_KEEP_DAYS, BATCH (rows per delete).
"""
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mysql.connector

DB = {
    "host": os.environ.get("DB_HOST", "192.168.2.33"),
    "user": os.environ.get("DB_USER", "admin"),
    "password": os.environ.get("DB_PASSWORD", "aaa"),
    "database": os.environ.get("DB_DATABASE", "energy"),
}

P1_KEEP_DAYS = int(os.environ.get("P1_KEEP_DAYS", "7"))
TLOGS_KEEP_DAYS = int(os.environ.get("TLOGS_KEEP_DAYS", "30"))
BMS_KEEP_DAYS = int(os.environ.get("BMS_KEEP_DAYS", "90"))
BATCH = int(os.environ.get("BATCH", "5000"))
MAX_BATCHES_PER_TABLE = 200

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_HERE, "logs")
LOG_FILE = os.path.join(LOG_DIR, "db_maintenance.log")


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log = logging.getLogger("dbmaint")
    log.setLevel(logging.INFO)
    fh = RotatingFileHandler(LOG_FILE, maxBytes=1024 * 1024,
                             backupCount=2, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    log.addHandler(ch)
    return log


def prune_table(log, cursor, table, keep_days):
    """Delete rows older than keep_days in batches. Returns rows removed."""
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S",
                            time.gmtime(time.time() - keep_days * 86400))
    total = 0
    for _ in range(MAX_BATCHES_PER_TABLE):
        try:
            n = cursor.execute(
                f"DELETE FROM {table} WHERE created_at < %s LIMIT {BATCH}",
                (cutoff,))
        except Exception as e:
            log.error(f"{table}: delete batch failed: {e}")
            break
        removed = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
        total += removed
        if not removed:
            break
        time.sleep(0.2)  # let the writers breathe between batches
    log.info(f"{table}: pruned {total} rows older than {keep_days} days")
    return total


def main():
    log = setup_logging()
    try:
        conn = mysql.connector.connect(
            host=DB["host"], user=DB["user"], password=DB["password"],
            database=DB["database"], autocommit=True,
            connection_timeout=5, auth_plugin="mysql_native_password")
    except Exception as e:
        log.error(f"connect failed: {e}")
        return 1

    cursor = conn.cursor()
    start = time.monotonic()
    log.info(f"maintenance start: p1={P1_KEEP_DAYS}d tlogs={TLOGS_KEEP_DAYS}d "
             f"bms={BMS_KEEP_DAYS}d batch={BATCH}")

    grand = 0
    grand += prune_table(log, cursor, "p1_data", P1_KEEP_DAYS)
    grand += prune_table(log, cursor, "t_logs", TLOGS_KEEP_DAYS)
    grand += prune_table(log, cursor, "bms_jk", BMS_KEEP_DAYS)

    # report remaining sizes
    try:
        cursor.execute("SELECT table_name, table_rows FROM "
                       "information_schema.tables WHERE table_schema=%s",
                       (DB["database"],))
        for name, rows in cursor.fetchall():
            log.info(f"  {name}: ~{rows} rows remain")
    except Exception as e:
        log.error(f"size query failed: {e}")

    log.info(f"maintenance done: {grand} rows removed in "
             f"{time.monotonic() - start:.1f}s")
    cursor.close()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
