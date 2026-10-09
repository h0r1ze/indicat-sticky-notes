import unittest

from indicat_sticky_notes import colors


class ColorsTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(colors.normalize("#AABBCC"), "#aabbcc")
        for bad in (None, "", "yellow", "#abc", "#gggggg", "aabbcc", 5):
            self.assertIsNone(colors.normalize(bad))

    def test_luminance_extremes(self):
        self.assertAlmostEqual(colors.luminance("#000000"), 0.0)
        self.assertAlmostEqual(colors.luminance("#ffffff"), 1.0)

    def test_text_is_dark_on_light_and_light_on_dark(self):
        self.assertEqual(colors.text_color_for("#fff7b8"), colors.DARK_TEXT)
        self.assertEqual(colors.text_color_for("#ffffff"), colors.DARK_TEXT)
        self.assertEqual(colors.text_color_for("#111111"), colors.LIGHT_TEXT)
        self.assertEqual(colors.text_color_for("#1f3a4d"), colors.LIGHT_TEXT)

    def test_text_is_readable_on_every_background(self):
        # Перебор сетки RGB: контраст текста с фоном не ниже 4.5 (AA для основного текста).
        steps = range(0, 256, 17)
        for r in steps:
            for g in steps:
                for b in steps:
                    body = colors.to_hex((r, g, b))
                    text = colors.text_color_for(body)
                    self.assertGreaterEqual(
                        colors.contrast(body, text), 4.5, f"{body} / {text}"
                    )

    def test_bar_is_darker_on_light_and_lighter_on_dark(self):
        light = "#fff7b8"
        dark = "#222222"
        self.assertLess(colors.luminance(colors.bar_for(light)), colors.luminance(light))
        self.assertGreater(colors.luminance(colors.bar_for(dark)), colors.luminance(dark))

    def test_mix_endpoints(self):
        self.assertEqual(colors.mix("#102030", "#ffffff", 0), "#102030")
        self.assertEqual(colors.mix("#102030", "#ffffff", 1), "#ffffff")


if __name__ == "__main__":
    unittest.main()
