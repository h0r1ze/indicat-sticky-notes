import unittest

from indicat_sticky_notes import checklist as c


class ChecklistTest(unittest.TestCase):
    def test_toggle_roundtrip(self):
        self.assertEqual(c.toggled("☐ молоко"), "☑ молоко")
        self.assertEqual(c.toggled("☑ молоко"), "☐ молоко")
        self.assertEqual(c.toggled("просто текст"), "просто текст")

    def test_converted(self):
        self.assertEqual(c.converted("[ ] дело"), "☐ дело")
        self.assertEqual(c.converted("[x] дело"), "☑ дело")
        self.assertEqual(c.converted("[X] дело"), "☑ дело")
        self.assertEqual(c.converted("[ ]дело"), "[ ]дело")  # нужен пробел после

    def test_on_enter(self):
        self.assertEqual(c.on_enter("☐ купить хлеб"), c.OFF)
        self.assertEqual(c.on_enter("☑ купить хлеб"), c.OFF)
        self.assertEqual(c.on_enter("☐ "), "")       # пустой пункт завершает список
        self.assertEqual(c.on_enter("☐    "), "")
        self.assertIsNone(c.on_enter("обычная строка"))

    def test_is_done(self):
        self.assertTrue(c.is_done("☑ готово"))
        self.assertFalse(c.is_done("☐ не готово"))


if __name__ == "__main__":
    unittest.main()
