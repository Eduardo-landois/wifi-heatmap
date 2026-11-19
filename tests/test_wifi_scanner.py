"""Unit tests for the netsh parsers in wifi_scanner.py, using sample netsh output.
Run from the project folder with:  python -m unittest
"""

import unittest

from wifi_scanner import parse_interface, parse_networks, percent_to_dbm

# Shortened sample of `netsh wlan show networks mode=bssid`
NETWORKS_OUTPUT = """
Interface name : Wi-Fi
There are 2 networks currently visible.

SSID 1 : HomeNet
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : AA:BB:CC:DD:EE:01
         Signal             : 90%
         Radio type         : 802.11ax
         Band               : 5 GHz
         Channel            : 36
         Basic rates (Mbps) : 6 12 24
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 40%
         Radio type         : 802.11n
         Channel            : 6

SSID 2 :
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    Encryption              : CCMP
    BSSID 1                 : 11:22:33:44:55:66
         Signal             : 15%
         Radio type         : 802.11ac
         Band               : 5 GHz
         Channel            : 149
"""

# Shortened sample of `netsh wlan show interfaces`
INTERFACE_OUTPUT = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201 160MHz
    State                  : connected
    SSID                   : HomeNet
    AP BSSID               : aa:bb:cc:dd:ee:01
    Band                   : 5 GHz
    Channel                : 36
    Signal                 : 94%
    Profile                : HomeNet
"""


class TestConversion(unittest.TestCase):
    def test_percent_to_dbm(self):
        self.assertEqual(percent_to_dbm(100), -50)
        self.assertEqual(percent_to_dbm(50), -75)
        self.assertEqual(percent_to_dbm(0), -100)
        self.assertEqual(percent_to_dbm(150), -50)   # out-of-range values are clamped


class TestParseNetworks(unittest.TestCase):
    def setUp(self):
        self.readings = parse_networks(NETWORKS_OUTPUT)

    def test_finds_every_bssid(self):
        self.assertEqual(len(self.readings), 3)

    def test_first_ap_fields(self):
        ap = self.readings[0]
        self.assertEqual(ap.ssid, "HomeNet")
        self.assertEqual(ap.bssid, "aa:bb:cc:dd:ee:01")   # lowercased
        self.assertEqual(ap.signal_percent, 90)
        self.assertEqual(ap.dbm, -55)
        self.assertEqual(ap.channel, 36)
        self.assertEqual(ap.band, "5 GHz")

    def test_band_guessed_from_channel_when_missing(self):
        self.assertEqual(self.readings[1].band, "2.4 GHz")

    def test_hidden_network_has_empty_ssid(self):
        self.assertEqual(self.readings[2].ssid, "")
        self.assertEqual(self.readings[2].channel, 149)


class TestParseInterface(unittest.TestCase):
    def test_connected(self):
        ap = parse_interface(INTERFACE_OUTPUT)
        self.assertIsNotNone(ap)
        self.assertTrue(ap.connected)
        self.assertEqual(ap.ssid, "HomeNet")
        self.assertEqual(ap.bssid, "aa:bb:cc:dd:ee:01")
        self.assertEqual(ap.signal_percent, 94)
        self.assertEqual(ap.dbm, -53)

    def test_disconnected_returns_none(self):
        text = INTERFACE_OUTPUT.replace("State                  : connected",
                                        "State                  : disconnected")
        self.assertIsNone(parse_interface(text))


if __name__ == "__main__":
    unittest.main()
