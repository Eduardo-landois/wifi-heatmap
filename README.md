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
| `heatmap.py` | IDW interpolation, coverage summary, and the colored heat map overlay |
| `main.py` | Tkinter GUI: floor plan, click-to-scan, live heat map and coverage |
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

## Step 2: heat map engine
`heatmap.py` turns survey points into a heat map in four steps:

1. **Pick a signal per spot** (`signal_at`): the connected AP, the strongest AP of one
   SSID, one specific BSSID, or the strongest AP overall. If the chosen network wasn't
   heard at a spot, that spot counts as -100 dBm (a dead zone).
2. **Fill in the gaps with IDW** (`idw_grid`), short for Inverse Distance Weighting.
   Each spot on the map is a weighted average of the measurements, where closer
   measurements count more:

       weight = 1 / distance²
       signal = Σ(weight × dBm) / Σ(weight)

   For speed it estimates one value per 4×4-pixel block, then smooths it back to full size.
3. **Coverage summary** (`coverage_summary`): percent of the area in each band:

   | Rating | Signal |
   |---|---|
   | Good | -67 dBm or stronger |
   | Weak | -80 to -67 dBm |
   | Dead | weaker than -80 dBm |

4. **Overlay** (`make_overlay`): colors the map red → yellow → green (-90 to -50 dBm)
   as a see-through image to lay over the floor plan.

## Step 3: the app (GUI)
```
python main.py
```
1. Click **Load floor plan...** to pick a PNG/JPG, or keep the **Blank grid**.
2. Stand somewhere, then click that spot on the map. The app scans WiFi there and adds a
   dot labeled with the signal in dBm.
3. Walk around and repeat. The heat map and the Good / Weak / Dead percentages in the
   status bar update after every point.
4. Use the **Map** dropdown to choose what to map: the connected network, one network
   (SSID), one access point (BSSID), or the strongest signal at each spot. The second
   dropdown lists the networks heard so far.

The scan runs in a background thread, so the window doesn't freeze while `netsh` works.
Switching floor plans clears your points, because their positions belong to the old plan.
