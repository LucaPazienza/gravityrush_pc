"""Keyboard and mouse prompt bindings (scripts/gr_prompt_font.py)."""
import sys
import unittest

from paths import ROOT

sys.path.insert(0, str(ROOT / 'scripts'))
import gr_prompt_font  # noqa: E402


class PromptBindings(unittest.TestCase):
    def test_defaults(self):
        shown = gr_prompt_font.bindings({})
        self.assertEqual(shown['cross'], ('key', 'Space'))
        self.assertEqual(shown['circle'], ('key', 'Shift'))
        self.assertEqual(shown['square'], ('mouse', 'left'))
        self.assertEqual(shown['r1'], ('mouse', 'right'))
        self.assertEqual(shown['l2'], ('key', 'R'))  # side mouse buttons keep the key's prompt
        self.assertEqual(shown['options'], ('key', 'Enter'))

    def test_remaps(self):
        shown = gr_prompt_font.bindings({'GOW3_KEY_MAP': 'cross=Left Ctrl,square=Q',
                                         'GOW3_MOUSE_MAP': 'left=cross,right='})
        self.assertEqual(shown['cross'], ('mouse', 'left'))
        self.assertEqual(shown['square'], ('key', 'Q'))  # the left button no longer presses it
        self.assertEqual(shown['r1'], ('key', '3'))

    def test_labels(self):
        self.assertEqual(gr_prompt_font.key_label('Left Shift'), 'Shift')
        self.assertEqual(gr_prompt_font.key_label('Keypad Enter'), 'Enter')
        self.assertLessEqual(len(gr_prompt_font.key_label('ScrollLock')), 5)


if __name__ == '__main__':
    unittest.main()
