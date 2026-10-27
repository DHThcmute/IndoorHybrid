"""Get *reported* link RSSI on Ubuntu or Windows, never infer dBm from signal %."""
from __future__ import annotations

import platform
import re
import subprocess


def _run(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, errors="replace", timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Cannot execute {' '.join(command)}: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}: {completed.stderr.strip()}"
        )
    return completed.stdout


def _extract(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def _find_linux_interface() -> str:
    text = _run(["iw", "dev"])
    candidates = re.findall(r"^\s*Interface\s+(\S+)", text, re.MULTILINE)
    for candidate in candidates:
        try:
            if "Connected to" in _run(["iw", "dev", candidate, "link"]):
                return candidate
        except RuntimeError:
            pass
    raise RuntimeError("No connected Wi-Fi interface was found via 'iw dev'.")


def read_wifi(interface: str | None = None) -> dict:
    system = platform.system()
    if system == "Linux":
        iface = interface or _find_linux_interface()
        output = _run(["iw", "dev", iface, "link"])
        if "Not connected" in output or "Connected to" not in output:
            raise RuntimeError(f"Wi-Fi interface {iface} is not connected")
        rssi = _extract(r"^\s*signal:\s*(-?\d+(?:\.\d+)?)\s*dBm\b", output)
        bssid = _extract(r"^\s*Connected to\s+([0-9a-f:]{17})", output)
        ssid = _extract(r"^\s*SSID:\s*(.+)$", output)
        if rssi is None:
            raise RuntimeError("'iw link' did not report RSSI in dBm")
        return {"rssi_dbm": float(rssi), "signal_percent": None,
                "bssid": bssid, "ssid": ssid, "interface": iface}

    if system == "Windows":
        # netsh may return an old/constant Rssi: validate before using scientifically.
        output = _run(["netsh", "wlan", "show", "interfaces"])
        if not re.search(r"^\s*State\s*:\s*connected\s*$", output, re.I | re.M):
            raise RuntimeError("No connected Wi-Fi link found in netsh output")
        rssi = _extract(r"^\s*Rssi\s*:\s*(-?\d+(?:\.\d+)?)\s*$", output)
        signal = _extract(r"^\s*Signal\s*:\s*(\d+(?:\.\d+)?)\s*%", output)
        bssid = _extract(r"^\s*(?:AP\s+)?BSSID\s*:\s*([0-9a-f:]{17})", output)
        ssid = _extract(r"^\s*SSID\s*:\s*(.+)$", output)
        iface = _extract(r"^\s*Name\s*:\s*(.+)$", output)
        if rssi is None:
            raise RuntimeError(
                "Windows netsh did not provide genuine Rssi; "
                "not substituting signal % as if it were measured dBm"
            )
        if interface and (iface or "").lower() != interface.lower():
            raise RuntimeError(f"Expected interface {interface!r}, got {iface!r}")
        return {"rssi_dbm": float(rssi),
                "signal_percent": float(signal) if signal is not None else None,
                "bssid": bssid, "ssid": ssid, "interface": iface}

    raise RuntimeError(f"Unsupported operating system: {system}")
