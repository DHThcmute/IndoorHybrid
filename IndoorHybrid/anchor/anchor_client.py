"""Cross-platform, label-free RSSI client. Client NEVER receives true phone coordinates."""
from __future__ import annotations
import argparse
import csv
import datetime as datetime
import json
import math
from pathlib import Path
import random
import re
import socket
import time
from wifi_reader import read_wifi

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["session", "anchor_id", "sequence", "captured_utc", "monotonic_ns",
          "rssi_dbm", "signal_percent", "bssid", "ssid", "interface", "hostname",
          "measurement_mode"]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def safe_name(name):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
        raise ValueError("IDs and session may only contain letters, numbers, _ . - (max 64)")
    return name


def send_packet(target, packet):
    host, colon, port = target.rpartition(":")
    if not colon or not host:
        raise ValueError("--server must be HOST:PORT")
    with socket.create_connection((host, int(port)), timeout=2.5) as connection:
        connection.settimeout(2.5)
        connection.sendall((json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8"))
        response = connection.recv(64).strip()
        if response != b"OK":
            raise OSError(f"Server rejected measurement: {response!r}")


def main():
    parser = argparse.ArgumentParser(description="RSSI sensor client; no phone coordinates required")
    parser.add_argument("--id", required=True, help="Unique anchor ID e.g. L1")
    parser.add_argument("--session", default="room_day1")
    parser.add_argument("--server", help="Central collector HOST:PORT. No server => local CSV only")
    parser.add_argument("--interval", type=float, default=1.0, help="Seconds between attempts")
    parser.add_argument("--samples", type=int, default=0, help="0 means continuous, >0 for smoke test")
    parser.add_argument("--iface", help="Ubuntu Wi-Fi interface; auto-detected when omitted")
    parser.add_argument("--simulate", action="store_true", help="FAKE RSSI for software tests only")
    parser.add_argument("--max-errors", type=int, default=30)
    args = parser.parse_args()
    try:
        session, anchor_id = safe_name(args.session), safe_name(args.id)
    except ValueError as exc:
        parser.error(str(exc))
    if args.interval <= 0 or not math.isfinite(args.interval) or args.samples < 0 or args.max_errors < 1:
        parser.error("Interval must be positive, samples >=0, and max-errors >=1")

    destination = ROOT / "data" / "raw" / session
    destination.mkdir(parents=True, exist_ok=True)
    filename = f"{anchor_id}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.csv"
    path = destination / filename
    rng = random.Random(2026 + sum(map(ord, anchor_id)))
    count = 0
    errors = 0
    next_tick = time.monotonic()
    history = []
    already_warned = False
    last_net_problem = None
    print(f"Client {anchor_id} | session={session} | interval={args.interval}s", flush=True)
    print("SIMULATED RSSI - NOT REAL DATA" if args.simulate else "REAL Wi-Fi RSSI", flush=True)
    print(f"Local backup: {path}", flush=True)
    try:
        with path.open("w", encoding="utf-8", newline="") as file:
            csv_writer = csv.DictWriter(file, fieldnames=FIELDS)
            csv_writer.writeheader()
            while args.samples == 0 or count < args.samples:
                try:
                    if args.simulate:
                        reading = {"rssi_dbm": round(-50 + rng.gauss(0, 2), 1),
                                   "signal_percent": None, "bssid": "SIMULATION",
                                   "ssid": "SIMULATION", "interface": "fake"}
                    else:
                        reading = read_wifi(args.iface)
                    rssi = float(reading["rssi_dbm"])
                    if not math.isfinite(rssi) or not -110 <= rssi <= 0:
                        raise ValueError(f"Suspicious RSSI {rssi}")
                    errors = 0
                except (RuntimeError, ValueError, OSError) as exc:
                    errors += 1
                    print(f"[READ ERROR {errors}/{args.max_errors}] {exc}", flush=True)
                    if errors >= args.max_errors:
                        break
                else:
                    count += 1
                    packet = {
                        "protocol_version": 2, "type": "measurement", "session": session,
                        "anchor_id": anchor_id, "sequence": count,
                        "captured_utc": utc_now(), "monotonic_ns": time.monotonic_ns(),
                        "rssi_dbm": rssi, "signal_percent": reading.get("signal_percent"),
                        "bssid": reading.get("bssid"), "ssid": reading.get("ssid"),
                        "interface": reading.get("interface"), "hostname": socket.gethostname(),
                        "measurement_mode": "simulation" if args.simulate else "real",
                    }
                    csv_writer.writerow({field: packet.get(field) for field in FIELDS})
                    file.flush()
                    history.append((rssi, packet["signal_percent"]))
                    history = history[-15:]
                    if len(history) >= 12 and not already_warned:
                        if len({v[0] for v in history}) == 1:
                            print("[WARNING] RSSI same across 12 reads; may be cached/stale.", flush=True)
                            if len({v[1] for v in history}) > 1:
                                print("[WARNING] Signal% changes but RSSI does not. Check Wi-Fi driver.", flush=True)
                            already_warned = True
                    network_status = "LOCAL"
                    if args.server:
                        try:
                            send_packet(args.server, packet)
                            network_status = "SENT"
                            if last_net_problem:
                                print("[NETWORK RECOVERED]", flush=True)
                            last_net_problem = None
                        except (OSError, ValueError) as exc:
                            network_status = "LOCAL ONLY"
                            error = str(exc)
                            if error != last_net_problem:
                                print(f"[NETWORK] {error}; still storing local CSV", flush=True)
                            last_net_problem = error
                    print(f"{anchor_id} #{count:04d} | {rssi:6.1f} dBm | {network_status}", flush=True)
                # Never catch up in a burst after system Sleep or a long Wi-Fi read.
                next_tick = time.monotonic() + args.interval
                time.sleep(max(0.0, next_tick - time.monotonic()))
    except KeyboardInterrupt:
        print("Stopped by user; local CSV retained.")
    print(f"Saved {count} local readings: {path}", flush=True)


if __name__ == "__main__":
    main()
