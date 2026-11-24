"""
main.py - WiFi Heat Map / Site Survey app (Tkinter GUI).

How to use:
  1. Load a floor plan image (or keep the blank grid).
  2. Stand somewhere and click that spot on the map: the app scans WiFi there.
  3. Repeat around the building. The heat map redraws after every point.
  4. Pick what to map: the connected network, one SSID, one BSSID, or the strongest signal.

Run:  python main.py
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageTk

from heatmap import classify, coverage_summary, idw_grid, make_overlay, signal_at
from wifi_scanner import Sample, WindowsScanner


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

BLANK_SIZE = (800, 600)        # blank grid size in pixels
GRID_SPACING = 50              # blank grid line spacing in pixels
MAX_PLAN_SIZE = (1200, 800)    # bigger floor plans are shrunk to fit the screen
DOT_RADIUS = 6
DOT_COLORS = {"good": "#1a9850", "weak": "#fdae61", "dead": "#d73027"}

MODES = {                      # dropdown label -> signal_at() mode
    "Connected network": "connected",
    "One network (SSID)": "ssid",
    "One access point (BSSID)": "bssid",
    "Strongest signal": "strongest",
}


def blank_grid(size=BLANK_SIZE, spacing=GRID_SPACING) -> Image.Image:
    """A white image with light gray grid lines, used when there's no floor plan."""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    width, height = size
    for x in range(0, width, spacing):
        draw.line([(x, 0), (x, height)], fill="#dddddd")
    for y in range(0, height, spacing):
        draw.line([(0, y), (width, y)], fill="#dddddd")
    return img


# ---------------------------------------------------------------------------
# The app window
# ---------------------------------------------------------------------------

class HeatmapApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.scanner = WindowsScanner()
        self.samples: list[Sample] = []    # every scan taken so far
        self.plan = blank_grid()           # the floor plan (PIL image)
        self.photo = None                  # Tk version of the picture (must be kept, or Tk erases it)
        self.scanning = False
        self.results: queue.Queue = queue.Queue()   # scan thread -> GUI thread

        self._build_widgets()
        self.redraw()

    # -- layout -------------------------------------------------------------

    def _build_widgets(self):
        bar = ttk.Frame(self.root, padding=4)          # toolbar across the top
        bar.pack(side="top", fill="x")

        ttk.Button(bar, text="Load floor plan...", command=self.load_floor_plan).pack(side="left")
        ttk.Button(bar, text="Blank grid", command=self.use_blank_grid).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear points", command=self.clear_points).pack(side="left")

        ttk.Label(bar, text="   Map:").pack(side="left")
        self.mode_var = tk.StringVar(value="Connected network")
        mode_box = ttk.Combobox(bar, textvariable=self.mode_var, values=list(MODES),
                                state="readonly", width=24)
        mode_box.pack(side="left", padx=4)
        mode_box.bind("<<ComboboxSelected>>", lambda e: self.on_mode_change())

        # Second dropdown: which SSID / BSSID (only used by those two modes).
        self.target_var = tk.StringVar()
        self.target_box = ttk.Combobox(bar, textvariable=self.target_var,
                                       state="disabled", width=32)
        self.target_box.pack(side="left")
        self.target_box.bind("<<ComboboxSelected>>", lambda e: self.redraw())

        self.canvas = tk.Canvas(self.root, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(side="top")
        self.canvas.bind("<Button-1>", self.on_click)  # left click = scan here

        self.status_var = tk.StringVar()               # status bar along the bottom
        ttk.Label(self.root, textvariable=self.status_var, anchor="w",
                  padding=4).pack(side="bottom", fill="x")

    # -- floor plan ---------------------------------------------------------

    def load_floor_plan(self):
        path = filedialog.askopenfilename(
            title="Choose a floor plan image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif"), ("All files", "*.*")])
        if not path:
            return                                     # user pressed Cancel
        try:
            img = Image.open(path).convert("RGB")
        except OSError as err:
            messagebox.showerror("Can't open image", str(err))
            return
        img.thumbnail(MAX_PLAN_SIZE)    # shrink to fit (keeps proportions, never enlarges)
        self._set_plan(img)

    def use_blank_grid(self):
        self._set_plan(blank_grid())

    def _set_plan(self, img: Image.Image):
        """Switch floor plans. Old points belong to the old plan, so they're cleared."""
        if self.samples and not messagebox.askyesno(
                "New floor plan", "Switching floor plans clears your current points. Continue?"):
            return
        self.plan = img
        self.samples.clear()
        self.update_targets()
        self.redraw()

    def clear_points(self):
        if self.samples and messagebox.askyesno("Clear points", "Delete all survey points?"):
            self.samples.clear()
            self.update_targets()
            self.redraw()

    # -- scanning -----------------------------------------------------------

    def on_click(self, event):
        """You clicked where you're standing: scan WiFi there in a background thread."""
        if self.scanning:
            return                                     # one scan at a time
        self.scanning = True
        self.status_var.set(f"Scanning at ({event.x}, {event.y})...")
        self.canvas.config(cursor="watch")
        # netsh takes about a second; running it here would freeze the window.
        threading.Thread(target=self._scan_worker, args=(event.x, event.y),
                         daemon=True).start()
        self.root.after(100, self._check_results)

    def _scan_worker(self, x: int, y: int):
        """Runs in the background thread. Tkinter isn't thread-safe, so this
        never touches the window - it only puts the result in the queue."""
        try:
            self.results.put(self.scanner.scan(x, y))
        except Exception as err:                       # ScannerError, or anything unexpected
            self.results.put(err)

    def _check_results(self):
        """Runs on the GUI thread every 100 ms until the scan result arrives."""
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            self.root.after(100, self._check_results)  # not done yet, check again soon
            return

        self.scanning = False
        self.canvas.config(cursor="crosshair")
        if isinstance(result, Exception):
            messagebox.showerror("Scan failed", str(result))
        else:
            self.samples.append(result)
            self.update_targets()
        self.redraw()

    # -- what to map --------------------------------------------------------

    def on_mode_change(self):
        self.update_targets()
        self.redraw()

    def update_targets(self):
        """Fill the second dropdown with the SSIDs or BSSIDs heard so far."""
        mode = MODES[self.mode_var.get()]
        if mode == "ssid":
            choices = sorted({r.ssid for s in self.samples for r in s.readings if r.ssid})
        elif mode == "bssid":
            pairs = {(r.bssid, r.ssid) for s in self.samples for r in s.readings}
            choices = [f"{bssid}  ({ssid or 'hidden'})" for bssid, ssid in sorted(pairs)]
        else:                                          # connected / strongest need no target
            self.target_box.config(values=[], state="disabled")
            self.target_var.set("")
            return

        self.target_box.config(values=choices, state="readonly")
        if self.target_var.get() not in choices:      # keep the choice if still valid
            self.target_var.set(choices[0] if choices else "")

    def selected_target(self) -> str:
        """The SSID or BSSID chosen in the second dropdown."""
        text = self.target_var.get()
        if MODES[self.mode_var.get()] == "bssid":
            return text.split(" ")[0]                  # "aa:bb:..  (HomeNet)" -> "aa:bb:.."
        return text

    # -- drawing ------------------------------------------------------------

    def redraw(self):
        """Draw the floor plan, the heat map on top, and a dot for every point."""
        mode = MODES[self.mode_var.get()]
        target = self.selected_target()
        width, height = self.plan.size
        picture = self.plan.convert("RGBA")
        show_map = bool(self.samples) and (target != "" or mode in ("connected", "strongest"))

        if show_map:
            values = [signal_at(s, mode, target) for s in self.samples]
            points = [(s.x, s.y, v) for s, v in zip(self.samples, values)]
            grid = idw_grid(points, width, height)
            picture = Image.alpha_composite(picture, make_overlay(grid, width, height))
            c = coverage_summary(grid)
            self.status_var.set(f"{len(self.samples)} point(s)    Good {c['good']:.0f}%    "
                                f"Weak {c['weak']:.0f}%    Dead {c['dead']:.0f}%")
        elif self.samples:
            self.status_var.set("Choose a network in the second dropdown.")
        else:
            self.status_var.set("Click the spot where you're standing to scan WiFi there.")

        self.photo = ImageTk.PhotoImage(picture)
        self.canvas.config(width=width, height=height)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

        if show_map:                                   # dots + labels on top of the heat map
            r = DOT_RADIUS
            for s, v in zip(self.samples, values):
                self.canvas.create_oval(s.x - r, s.y - r, s.x + r, s.y + r,
                                        fill=DOT_COLORS[classify(v)], outline="black")
                self.canvas.create_text(s.x, s.y - r - 8, text=f"{v:.0f} dBm",
                                        font=("Segoe UI", 8))


def main():
    root = tk.Tk()
    root.title("WiFi Heat Map")
    root.resizable(False, False)       # window size follows the floor plan
    HeatmapApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
