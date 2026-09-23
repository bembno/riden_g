import re

# Read the current file
with open('C:\\pro_git\\riden_g\\storage\\bms_mqtt.py', 'r') as f:
    content = f.read()

# Find start of main() function
main_start_match = re.search(r'^def main\(', content, re.MULTILINE)
if not main_start_match:
    print("ERROR: Could not find def main()")
    exit(1)

main_start = main_start_match.start()

# Find end of main - look for __name__ == "__main__" after main()
main_end = content.find('\nif __name__', main_start)
if main_end == -1:
    main_end = len(content)

print(f"Found main() at line {content[:main_start].count(chr(10))+1}, replacing through line {main_end}")

# New main function (full instrumented version)
new_main = r'''def main():
    _mqtt_client = client

    # ------------------------------------------------------------------
    # Watchdog thread: monitors that the main loop makes progress.
    # If no iteration completes for WATCHDOG_STUCK_S seconds, the process
    # is genuinely stuck (e.g. blocked on BlueZ/DBus beyond the timeout,
    # deadlocked paho, etc.) and is restarted after dumping diagnostics.
    # ------------------------------------------------------------------
    def _bluez_state():
        out = {}
        for p, k in (
            ("/sys/class/bluetooth/hci0/power", "powered"),
            ("/sys/class/bluetooth/hci0/device/power/control", "power_control"),
            ("/sys/class/bluetooth/hci0/address", "hci_address"),
        ):
            try:
                with open(p) as f:
                    out[k] = f.read().strip()
            except Exception:
                out[k] = None
        try:
            r = subprocess.run(
                ["systemctl", "is-active", "bluetooth"],
                capture_output=True, text=True, timeout=5,
            )
            out["bluetooth_service"] = r.stdout.strip() or None
        except Exception:
            out["bluetooth_service"] = None
        return out

    def _rss_kb():
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except Exception:
            pass
        return None

    def _thread_stacks():
        main_id = threading.get_ident()
        stacks = {}
        for tid, frame in sys._current_frames().items():
            frames = []
            for line in traceback.format_stack(frame):
                frames.append(line.strip())
            stacks[str(tid)] = {
                "name": threading.Thread(name=tid).name if tid in [t.ident for t in threading.enumerate()] else "?",
                "main": tid == main_id,
                "frames": frames,
            }
        return stacks

    def _diag_write(rec):
        if time.time() >= _DIAG_END:
            return
        try:
            with open(DIAG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\\n")
        except Exception as e:
            logging.getLogger("bms").warning(f"diag write failed: {e}")

    def _write_cycle_diag(seq, result, err, read_ms, backoff, payload=None):
        rec = {
            "type": "cycle",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "seq": seq,
            "result": result,
            "read_ms": round(read_ms, 1) if read_ms is not None else None,
            "backoff_s": round(backoff, 1),
            "state": {"failures": STATE["failures"], "hard_timeouts": STATE["hard_timeouts"]},
            "sys": {"rss_kb": _rss_kb(), "threads": threading.active_count()},
            "bluez": _bluez_state(),
        }
        if err is not None:
            rec["error"] = err
        if payload is not None:
            rec["bms"] = {
                "v": payload.get("battery_voltage_V"),
                "i": payload.get("current_A"),
                "soc": payload.get("soc"),
            }
        try:
            rec["diag"] = dict(_jk_client.LAST_DIAG)
        except Exception:
            pass
        _diag_write(rec)

    def _mark_progress():
        STATE["last_progress"] = time.time()

    def _restart_process(reason: str):
        global _mqtt_client
        STATE["last_error"] = reason
        logging.getLogger("bms").error(f"RESTARTING bms_mqtt process ({reason})")
        try:
            if _mqtt_client is not None:
                _mqtt_client.publish(TOPIC_ONLINE, "0", retain=True)
                _mqtt_client.loop_stop()
                _mqtt_client.disconnect()
        except Exception:
            pass
        time.sleep(1)
        os.execv(sys.executable, [sys.executable, "-u"] + sys.argv)

    def _watchdog():
        while not _shutdown:
            time.sleep(max(5, WATCHDOG_CHECK_S))
            if _shutdown:
                break
            now = time.time()
            if now - STATE["last_progress"] > WATCHDOG_STUCK_S:
                log.error(
                    "WATCHDOG: no main-loop progress for %.1fs -- dumping diagnostics"
                    % (now - STATE["last_progress"])
                )
                _dump_stuck(log, "watchdog: no main-loop progress")
                STATE["last_progress"] = now
                _restart_process("watchdog: no main-loop progress for %.0fs" % (now - STATE["last_progress"]))

    # ---------------------------------------------------------------------------
    # Start the watchdog thread
    # ---------------------------------------------------------------------------
    watchdog_thread = threading.Thread(
        target=_watchdog, daemon=True, name="bms-watchdog"
    )
    watchdog_thread.start()

    # ---------------------------------------------------------------------------
    # Main loop -- instrumented with progress markers & per-cycle diagnostics
    # ---------------------------------------------------------------------------
    failures = 0
    hard_timeouts = 0
    STATE["cycles"] = 0
    while not _shutdown:
        start = time.monotonic()
        STATE["cycles"] += 1
        seq = STATE["cycles"]

        result = "ok"
        err = None
        read_ms = None
        backoff = 0.0

        try:
            read_start = time.monotonic()
            readings = read_live_with_timeout(MAC, pin=PIN)
            read_ms = time.monotonic() - read_start
            if readings.cell is None:
                raise RuntimeError("no cell frame in readings")

            payload = extract(readings)
            STATE["last_success"] = time.time()
            STATE["failures"] = 0
            STATE["hard_timeouts"] = 0
            client.publish(TOPIC_STATUS, json.dumps(payload))
            if PROMETHEUS_AVAILABLE:
                BLE_READS_TOTAL.labels(result="success").inc()
                BLE_READ_DURATION.observe(read_ms)
                cell = readings.cell
                BMS_VOLTAGE.set(cell.battery_voltage_V)
                BMS_CURRENT.set(cell.current_A)
                BMS_SOC.set(cell.soc)
                BMS_CELL_DELTA_MV.set(cell.delta_cell_mV)
                BMS_MOS_TEMP.set(cell.mos_temp_C or 0)
                BMS_BALANCE_CURRENT.set(cell.balance_current_A or 0)
                BMS_CYCLES.set(cell.cycles or 0)
                BMS_SOH.set(cell.soh or 0)
                BMS_ERRORS.set(len(cell.errors or []))

            line1, line2 = status_lines(payload)
            log.info(line1)
            log.info(line2)

            _mark_progress()
            _write_cycle_diag(seq, "ok", None, read_ms, 0.0, payload)

            if PROMETHEUS_AVAILABLE:
                BLE_READS_TOTAL.labels(result="success").inc()
                BLE_BACKOFF_SECONDS.set(0.0)

            delay = max(0.0, POLL_INTERVAL - (time.monotonic() - start))
            time.sleep(delay)
            _mark_progress()
            _write_cycle_diag(seq, "ok", None, read_ms, 0.0, payload)
            continue

        except TimeoutError as te:
            result = "timeout"
            err = str(te)
            if PROMETHEUS_AVAILABLE:
                BLE_READS_TOTAL.labels(result="timeout").inc()
            hard_timeouts += 1
            log.error(f"BLE HARD TIMEOUT ({hard_timeouts}/"
                      f"{RESTART_AFTER_HARD_TIMEOUTS}): {te}")
            STATE["failures"] += 1
            STATE["hard_timeouts"] = hard_timeouts
            if hard_timeouts >= RESTART_AFTER_HARD_TIMEOUTS:
                _restart_process(f"hard timeout x{hard_timeouts}")
            # Fall through to the generic except below for sleep & diag.
            # The hard-timeout restart above will os.execv and never return.

        except Exception as e:
            result = "error"
            err = str(e)
            STATE["failures"] += 1
            STATE["last_error"] = err
            backoff = min(POLL_INTERVAL * (1 + STATE["failures"]) + random.uniform(0, BACKOFF_JITTER), MAX_BACKOFF)
            if PROMETHEUS_AVAILABLE:
                BLE_READS_TOTAL.labels(result="error").inc()
                BLE_BACKOFF_SECONDS.set(backoff)
            log.error(f"BMS READ FAILED (#{{STATE["failures"]}}): {{e}} | "
                      f"retrying in {{backoff:.0f}}s")
            try:
                client.publish(TOPIC_STATUS, json.dumps({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime()),
                    "error": str(e),
                }))
                if PROMETHEUS_AVAILABLE:
                    MQTT_PUBLISH_TOTAL.labels(topic=TOPIC_STATUS, result="error").inc()
            except Exception as pe:
                log.error(f"publish of error payload failed: {{pe}}")

        # --- common progress/diag after every iteration outcome ----------
        read_ms = read_ms or 0.0
        _mark_progress()
        _write_cycle_diag(seq, result, err, read_ms, backoff)
        # Sleep the remainder of the poll interval (for error/timeout paths
        # the sleep is the backoff; for ok paths it was already done above,
        # but doing it again here is harmless -- we just need a bounded pause).
        if result != "ok":
            time.sleep(backoff)


# End of main()
'''

# Replace from main() start to before __name__ block
new_content = content[:main_start] + new_main

# Write back
with open('C:\\pro_git\\riden_g\\storage\\bms_mqtt.py', 'w') as f:
    f.write(new_content)

print("Replacement complete!")