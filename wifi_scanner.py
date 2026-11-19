"""
wifi_scanner.py - Reads real WiFi signal strength for the WiFi Heat Map app.

WindowsScanner uses Windows' built-in `netsh wlan` command to list every
nearby access point and its signal strength, and returns them as a Sample.

Run this file directly to print one scan as a table:
    python wifi_scanner.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class APReading:
    """One access point (one router radio) heard during a scan."""
    ssid: str               # network name, e.g. "HomeNet" ("" = hidden network)
    bssid: str              # MAC address of the AP radio, e.g. "aa:bb:cc:dd:ee:01"
    signal_percent: int     # Windows signal quality, 0-100 %
    dbm: float              # estimated signal strength in dBm (closer to 0 = stronger)
    channel: int            # WiFi channel number (0 = unknown)
    band: str               # "2.4 GHz", "5 GHz" or "6 GHz"
    connected: bool = False # True if this is the AP we are connected to right now


@dataclass
class Sample:
    """All the readings taken at one spot on the floor plan."""
    x: float                # position on the floor plan (pixels)
    y: float
    timestamp: float        # when the scan happened 
    readings: list[APReading] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ScannerError(Exception):
    """Raised when a WiFi scan fails. The message explains how to fix it."""


# Since Windows 11 24H2, netsh refuses to list WiFi networks unless the
# Location privacy setting is on (WiFi scans can reveal where you are).
LOCATION_HELP = (
    "Windows blocked the WiFi scan because Location access is turned off.\n"
    "Fix: open Settings > Privacy & security > Location, turn on\n"
    "'Location services' and 'Let desktop apps access your location',\n"
    "then run the scan again."
)


# ---------------------------------------------------------------------------
# Signal conversions
# ---------------------------------------------------------------------------

NOISE_FLOOR_DBM = -100.0   # below this, a signal is effectively unusable


def percent_to_dbm(percent: int) -> float:
    """
    Convert Windows signal quality (%) to an estimated dBm value.

    Windows maps signal strength roughly linearly:
        0 %  ~ -100 dBm      100 % ~ -50 dBm
    so:  dBm = (percent / 2) - 100
    """
    percent = max(0, min(100, percent))   # keep within 0-100
    return percent / 2 - 100


def channel_to_band(channel: int) -> str:
    """Guess the band from the channel number. Used only if netsh doesn't report the band."""
    if channel <= 0:
        return ""
    if channel <= 14:
        return "2.4 GHz"
    return "5 GHz"   # 6 GHz reuses channel numbers, so we can't tell it apart from 5 GHz here


# ---------------------------------------------------------------------------
# netsh output parsing (pure functions, easy to unit test)
# ---------------------------------------------------------------------------
# netsh prints lines like "    Signal             : 90%".
# Note: this parser expects English Windows output.

def _split_line(line: str) -> tuple[str | None, str]:
    """Split 'Key : value' into ('Key', 'value'). Only the FIRST ':' splits,
    because BSSIDs (MAC addresses) contain colons too."""
    if ":" not in line:
        return None, ""
    key, value = line.split(":", 1)
    return key.strip(), value.strip()


def _to_int(text: str) -> int:
    """Pull the first whole number out of text like '90%' or '36'. Returns 0 if none."""
    match = re.search(r"-?\d+", text)
    return int(match.group()) if match else 0


def parse_networks(text: str) -> list[APReading]:
    """
    Parse the output of `netsh wlan show networks mode=bssid`.

    The output is grouped: each 'SSID n : name' header is followed by one or
    more 'BSSID n : mac' blocks (one per AP radio), each with Signal, Band, Channel.
    """
    readings: list[APReading] = []
    current_ssid = ""
    current: APReading | None = None   # the BSSID block we're filling in

    for line in text.splitlines():
        key, value = _split_line(line)
        if key is None:
            continue

        if re.fullmatch(r"SSID \d+", key):          # new network
            current_ssid = value
            current = None
        elif re.fullmatch(r"BSSID \d+", key):       # new AP radio in this network
            current = APReading(ssid=current_ssid, bssid=value.lower(),
                                signal_percent=0, dbm=NOISE_FLOOR_DBM,
                                channel=0, band="")
            readings.append(current)
        elif current is not None:                   # a detail line for this AP
            if key == "Signal":
                current.signal_percent = _to_int(value)
                current.dbm = percent_to_dbm(current.signal_percent)
            elif key == "Channel":
                current.channel = _to_int(value)
            elif key == "Band":
                current.band = value

    # Older Windows versions don't print "Band", so guess it from the channel.
    for r in readings:
        if not r.band:
            r.band = channel_to_band(r.channel)
    return readings


def parse_interface(text: str) -> APReading | None:
    """
    Parse the output of `netsh wlan show interfaces`.

    Returns the AP we're connected to (with connected=True),
    or None if the WiFi adapter isn't connected.
    """
    info: dict[str, str] = {}
    for line in text.splitlines():
        key, value = _split_line(line)
        if key is not None and key not in info:   # keep the first adapter only
            info[key] = value

    if info.get("State", "").lower() != "connected":
        return None

    # Newer Windows prints "AP BSSID", older prints "BSSID".
    bssid = info.get("AP BSSID") or info.get("BSSID", "")
    percent = _to_int(info.get("Signal", "0"))
    channel = _to_int(info.get("Channel", "0"))
    return APReading(ssid=info.get("SSID", ""), bssid=bssid.lower(),
                     signal_percent=percent, dbm=percent_to_dbm(percent),
                     channel=channel, band=info.get("Band") or channel_to_band(channel),
                     connected=True)


# ---------------------------------------------------------------------------
# Real scanner (Windows)
# ---------------------------------------------------------------------------

class WindowsScanner:
    """
    Reads real WiFi signals using Windows' built-in `netsh wlan` command.

    Note: `show networks` returns Windows' most recent background scan, which
    can be a few seconds old. The connected AP's signal (`show interfaces`)
    updates live, so we use it for the connected AP.
    """
    name = "Windows (netsh)"

    def _run_netsh(self, *args: str) -> str:
        """Run `netsh wlan <args>` and return its text output, or raise ScannerError."""
        try:
            result = subprocess.run(
                ["netsh", "wlan", *args],
                capture_output=True, text=True, errors="replace", timeout=15,
                # Don't flash a console window when called from the GUI later.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            raise ScannerError("The 'netsh' command was not found. "
                               "Real scans only work on Windows.") from None
        except subprocess.TimeoutExpired:
            raise ScannerError("netsh took too long to respond.") from None

        output = (result.stdout + result.stderr).strip()
        lowered = output.lower()
        if "location" in lowered and "permission" in lowered:
            raise ScannerError(LOCATION_HELP)
        if result.returncode != 0:
            raise ScannerError(f"netsh failed: {output or 'no output'}")
        return result.stdout

    def scan(self, x: float = 0.0, y: float = 0.0) -> Sample:
        """Scan all visible APs. (x, y) is just recorded with the sample."""
        networks = parse_networks(self._run_netsh("show", "networks", "mode=bssid"))
        connected = parse_interface(self._run_netsh("show", "interfaces"))

        if connected is not None:
            # Mark the connected AP and use its fresher, live signal value.
            for r in networks:
                if r.bssid == connected.bssid:
                    r.connected = True
                    r.signal_percent = connected.signal_percent
                    r.dbm = connected.dbm
                    break
            else:
                networks.append(connected)   # sometimes missing from the cached list

        return Sample(x=x, y=y, timestamp=time.time(), readings=networks)


# ---------------------------------------------------------------------------
# Command-line demo: python wifi_scanner.py
# ---------------------------------------------------------------------------

def print_sample(sample: Sample, scanner_name: str) -> None:
    """Print a Sample as a table, strongest signal first."""
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(sample.timestamp))
    print(f"Scanner: {scanner_name}    Time: {when}\n")

    header = f"  {'SSID':<24} {'BSSID':<17} {'Signal':>6} {'dBm':>7} {'Ch':>4}  Band"
    print(header)
    print("-" * len(header))
    for r in sorted(sample.readings, key=lambda r: r.dbm, reverse=True):
        mark = "*" if r.connected else " "
        ssid = (r.ssid or "<hidden>")[:24]
        print(f"{mark} {ssid:<24} {r.bssid:<17} {r.signal_percent:>5}% "
              f"{r.dbm:>7.1f} {r.channel:>4}  {r.band}")
    print(f"\n{len(sample.readings)} access point(s) found.   * = connected")


if __name__ == "__main__":
    scanner = WindowsScanner()
    try:
        sample = scanner.scan()
    except ScannerError as err:
        # e.g. Location turned off, WiFi off, or not running on Windows
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)
    print_sample(sample, scanner.name)
