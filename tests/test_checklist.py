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


class DashListTest(unittest.TestCase):
    def test_detects_items_with_indent(self):
        self.assertEqual(c.dash_indent("— пункт"), 0)
        self.assertEqual(c.dash_indent("    — вложенный"), 4)
        for not_item in ("— ", "—пункт", "- пункт", "текст — тире", "☐ дело", ""):
            if not_item == "— ":
                self.assertEqual(c.dash_indent(not_item), 0)  # пустой пункт — всё равно пункт
            else:
                self.assertIsNone(c.dash_indent(not_item), not_item)

    def test_hyphen_becomes_long_dash_keeping_indent(self):
        self.assertEqual(c.dash_converted("- молоко"), "— молоко")
        self.assertEqual(c.dash_converted("    - вложенный"), "    — вложенный")
        self.assertEqual(c.dash_converted("- "), "— ")
        for same in ("-молоко", "-- шутка", "слово - слово", "— уже", "☐ дело", ""):
            self.assertEqual(c.dash_converted(same), same, same)

    def test_indent_and_outdent(self):
        line = "— пункт"
        deeper = c.indented(line)
        self.assertEqual(deeper, "    — пункт")
        self.assertEqual(c.indented(deeper), "        — пункт")
        self.assertEqual(c.outdented(deeper), line)
        self.assertEqual(c.outdented(line), line)               # выше некуда
        self.assertEqual(c.indented("обычная строка"), "обычная строка")
        self.assertEqual(c.outdented("   — кривой отступ"), "— кривой отступ")
        line = "— пункт"
        for _ in range(10):
            line = c.indented(line)
        self.assertEqual(c.dash_indent(line), c.MAX_INDENT)     # глубже трёх уровней не уходим

    def test_enter_continues_outdents_or_ends(self):
        self.assertEqual(c.dash_enter("— купить"), ("continue", "— "))
        self.assertEqual(c.dash_enter("    — вложенный"), ("continue", "    — "))
        self.assertEqual(c.dash_enter("        — пусто"[:8] + "— "), ("outdent", "    — "))
        self.assertEqual(c.dash_enter("    — "), ("outdent", "— "))
        self.assertEqual(c.dash_enter("— "), ("end", ""))
        self.assertEqual(c.dash_enter("— "  + "   "), ("end", ""))
        self.assertIsNone(c.dash_enter("обычная строка"))
        self.assertIsNone(c.dash_enter("☐ дело"))


if __name__ == "__main__":
    unittest.main()
