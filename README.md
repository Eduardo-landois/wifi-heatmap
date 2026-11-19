# WiFi Heat Map / Site Survey

Final project for CSCI 4345 Computer Networks. A Python (Tkinter) app for Windows
that maps WiFi signal strength across a floor plan.

## Planned features
- Load a floor plan image (PNG/JPG) or use a blank grid
- Click where you're standing to record the WiFi signal at that spot
- IDW interpolation between points, drawn as a red-yellow-green heat map (dBm)
- Filter by the connected network, a specific SSID, or a specific access point (BSSID)
- Coverage summary (% good / weak / dead zone)
- Save/load surveys as JSON, export a PNG report
- Later: walking-line mode, outdoor GPS mode (Garmin FIT files), camera/AI floor plans

## Project structure
| File | Purpose |
|---|---|
| `wifi_scanner.py` | Reads real WiFi signals using Windows' `netsh` command |
| `heatmap.py` | Heat map interpolation and drawing (later step) |
| `main.py` | Tkinter GUI entry point (later step) |
| `tests/` | Unit tests |

## How it measures signal
Windows' `netsh wlan show networks mode=bssid` lists every nearby access point
with a signal quality in percent. We estimate dBm with:

    dBm ≈ (percent / 2) - 100      (100 % ≈ -50 dBm, 0 % ≈ -100 dBm)

## Setup
```
pip install -r requirements.txt
```

## Step 1: run the scanner
Print one scan as a table (* marks the AP you're connected to):
```
python wifi_scanner.py
```
If the scan is blocked, the app prints an error explaining how to fix it. On Windows 11,
turn on **Settings > Privacy & security > Location** ("Location services" and
"Let desktop apps access your location") to allow real WiFi scans.

Run the tests:
```
python -m unittest
```
