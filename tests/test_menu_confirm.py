from paths import ROOT
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import graphics_options as g


class MenuConfirmTests(unittest.TestCase):
    def test_default_and_invalid_values_preserve_cross(self):
        for ini in ({}, {'menu_confirm': 'invalid'}, {'menu_confirm': ''}):
            self.assertEqual(g.startup_options(ini)['menu_confirm'], 'cross')

    def test_circle_is_forwarded_to_runtime(self):
        with patch.dict(os.environ, {}, clear=True):
            options = g.startup_options({'menu_confirm': 'circle'})
            self.assertEqual(g.environment(options)['GOW3_MENU_CONFIRM'], 'circle')

    def test_explicit_environment_override(self):
        with patch.dict(os.environ, {'GOW3_MENU_CONFIRM': 'cross'}):
            options = g.startup_options({'menu_confirm': 'circle'})
            self.assertEqual(g.environment(options)['GOW3_MENU_CONFIRM'], 'cross')

    def test_ini_round_trip_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp, 'gravityrush.ini')
            ini.write_text('menu_confirm=cross\nvsync=0\n')
            g.write_keys(ini, {'menu_confirm': 'circle'})
            self.assertEqual(g.read_ini(ini), {'menu_confirm': 'circle', 'vsync': '0'})

    def test_restart_recovery_keeps_confirm_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            ini, state = Path(tmp, 'gravityrush.ini'), Path(tmp, 'state.json')
            g.write_keys(ini, {'menu_confirm': 'circle'})
            g.prepare(ini, state)
            g.write_keys(ini, {'restart_unconfirmed': '1', 'engine_fps': '120'})
            g.prepare(ini, state)
            options, reverted = g.prepare(ini, state)
            self.assertTrue(reverted)
            self.assertEqual(options['menu_confirm'], 'circle')
