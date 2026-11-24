"""Unit tests for heatmap.py. Run with: python -m unittest"""

import unittest

import numpy as np

from heatmap import (GOOD_DBM, WEAK_DBM, classify, coverage_summary,
                     idw_grid, make_overlay, signal_at)
from wifi_scanner import NOISE_FLOOR_DBM, APReading, Sample


def ap(ssid, bssid, dbm, connected=False):
    """Small helper to build an APReading without typing every field."""
    return APReading(ssid=ssid, bssid=bssid, signal_percent=0, dbm=dbm,
                     channel=6, band="2.4 GHz", connected=connected)


SAMPLE = Sample(x=0, y=0, timestamp=0, readings=[
    ap("HomeNet", "aa:aa:aa:aa:aa:01", -60, connected=True),
    ap("HomeNet", "aa:aa:aa:aa:aa:02", -55),
    ap("Neighbor", "bb:bb:bb:bb:bb:01", -75),
])


class TestSignalAt(unittest.TestCase):
    def test_connected(self):
        self.assertEqual(signal_at(SAMPLE, "connected"), -60)

    def test_ssid_picks_strongest_ap(self):
        self.assertEqual(signal_at(SAMPLE, "ssid", "HomeNet"), -55)

    def test_bssid_ignores_case(self):
        self.assertEqual(signal_at(SAMPLE, "bssid", "BB:BB:BB:BB:BB:01"), -75)

    def test_strongest(self):
        self.assertEqual(signal_at(SAMPLE, "strongest"), -55)

    def test_not_heard_is_noise_floor(self):
        self.assertEqual(signal_at(SAMPLE, "ssid", "Missing"), NOISE_FLOOR_DBM)
        empty = Sample(x=0, y=0, timestamp=0)
        self.assertEqual(signal_at(empty, "connected"), NOISE_FLOOR_DBM)

    def test_unknown_mode(self):
        with self.assertRaises(ValueError):
            signal_at(SAMPLE, "nope")


class TestIdwGrid(unittest.TestCase):
    def test_shape(self):
        grid = idw_grid([(0, 0, -60)], width=100, height=50, step=10)
        self.assertEqual(grid.shape, (5, 10))   # (rows, cols)

    def test_single_point_fills_everything(self):
        grid = idw_grid([(10, 10, -70)], width=40, height=40, step=4)
        self.assertTrue(np.allclose(grid, -70))

    def test_cell_on_a_point_equals_that_point(self):
        # With step=10 the first cell's center is (5, 5).
        grid = idw_grid([(5, 5, -50), (95, 95, -90)], width=100, height=100, step=10)
        self.assertAlmostEqual(grid[0, 0], -50, places=3)
        self.assertAlmostEqual(grid[-1, -1], -90, places=3)

    def test_values_stay_between_min_and_max(self):
        grid = idw_grid([(0, 0, -50), (100, 0, -90), (50, 80, -70)], 100, 100)
        self.assertGreaterEqual(grid.min(), -90 - 1e-9)
        self.assertLessEqual(grid.max(), -50 + 1e-9)

    def test_closer_point_counts_more(self):
        # The middle cell is nearer the strong point, so it leans strong.
        grid = idw_grid([(0, 5, -50), (100, 5, -90)], width=60, height=10, step=10)
        self.assertGreater(grid[0, 2], -70)

    def test_no_points(self):
        with self.assertRaises(ValueError):
            idw_grid([], 100, 100)


class TestCoverage(unittest.TestCase):
    def test_classify_boundaries(self):
        self.assertEqual(classify(GOOD_DBM), "good")
        self.assertEqual(classify(GOOD_DBM - 0.1), "weak")
        self.assertEqual(classify(WEAK_DBM), "weak")
        self.assertEqual(classify(WEAK_DBM - 0.1), "dead")

    def test_summary(self):
        grid = np.array([[-50.0, -60.0], [-75.0, -95.0]])   # 2 good, 1 weak, 1 dead
        self.assertEqual(coverage_summary(grid),
                         {"good": 50.0, "weak": 25.0, "dead": 25.0})


class TestOverlay(unittest.TestCase):
    def test_size_mode_and_alpha(self):
        grid = np.full((5, 5), -70.0)
        img = make_overlay(grid, width=200, height=100, alpha=80)
        self.assertEqual(img.mode, "RGBA")
        self.assertEqual(img.size, (200, 100))
        self.assertEqual(img.getpixel((10, 10))[3], 80)

    def test_strong_is_green_weak_is_red(self):
        strong = make_overlay(np.full((2, 2), -40.0), 10, 10).getpixel((5, 5))
        weak = make_overlay(np.full((2, 2), -95.0), 10, 10).getpixel((5, 5))
        self.assertGreater(strong[1], strong[0])   # green > red
        self.assertGreater(weak[0], weak[1])       # red > green


if __name__ == "__main__":
    unittest.main()
