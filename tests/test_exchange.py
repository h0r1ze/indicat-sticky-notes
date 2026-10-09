import json
import tempfile
import unittest
from pathlib import Path

from indicat_sticky_notes import exchange
from indicat_sticky_notes.storage import Note, dump_notes


class MarkdownTest(unittest.TestCase):
    def test_apply_formats(self):
        text = "привет мир"
        out = exchange.apply_formats(text, [[0, 6, "bold"], [7, 10, "italic"]])
        self.assertEqual(out, "**привет** *мир*")

    def test_formats_do_not_cross_lines_and_skip_blank_ranges(self):
        out = exchange.apply_formats("ab\ncd", [[0, 5, "bold"]])
        self.assertEqual(out, "**ab**\n**cd**")
        self.assertEqual(exchange.apply_formats("a  b", [[1, 3, "bold"]]), "a  b")

    def test_bad_formats_are_ignored(self):
        text = "abc"
        for bad in ([[5, 9, "bold"]], [[2, 1, "bold"]], [[0, 2, "nope"]], [["x"]], [None]):
            self.assertEqual(exchange.apply_formats(text, bad), text)

    def test_note_markdown_has_title_tasks_and_formats(self):
        note = Note(title="Дела", text="☐ молоко\n☑ хлеб\nобычная", group="Дом",
                    formats=[[2, 8, "bold"]])
        md = exchange.note_to_markdown(note)
        self.assertIn("## Дела", md)
        self.assertIn("- [ ] **молоко**", md)
        self.assertIn("- [x] хлеб", md)
        self.assertIn("group: Дом;", md)

    def test_export_skips_blank_and_deleted(self):
        notes = [Note(text="живая"), Note(text=""), Note(text="в корзине", deleted_at=5.0)]
        md = exchange.export_markdown(notes)
        self.assertIn("живая", md)
        self.assertNotIn("в корзине", md)
        self.assertEqual(md.count("\n## "), 1)

    def test_markdown_roundtrip(self):
        original = [
            Note(title="Покупки", text="☐ молоко\n☑ хлеб\nпросто текст", group="Дом",
                 formats=[[2, 8, "bold"], [12, 15, "strike"]]),
            Note(title="Вторая", text="жирное и курсив", formats=[[0, 6, "bold"], [9, 15, "italic"]]),
        ]
        restored = exchange.import_markdown_export(exchange.export_markdown(original))
        self.assertEqual([(n.title, n.text, n.group) for n in restored],
                         [(n.title, n.text, n.group) for n in original])
        self.assertEqual(restored[0].formats, [[2, 8, "bold"], [12, 15, "strike"]])
        self.assertEqual(restored[1].formats, [[0, 6, "bold"], [9, 15, "italic"]])

    def test_empty_export(self):
        self.assertEqual(exchange.import_markdown_export(exchange.export_markdown([])), [])


class TextFilesTest(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(exchange.slug('a/b:c*d?"e"'), "a b c d e")
        self.assertEqual(exchange.slug("  ..  "), "заметка")
        self.assertEqual(len(exchange.slug("я" * 200)), 60)

    def test_export_text_files_unique_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = [Note(text="одно", title="Список"), Note(text="другое", title="Список"),
                     Note(text=""), Note(text="x", deleted_at=1.0)]
            paths = exchange.export_text_files(notes, Path(tmp) / "out")
            self.assertEqual([p.name for p in paths], ["Список.txt", "Список (2).txt"])
            self.assertEqual(paths[1].read_text(encoding="utf-8"), "другое")


class MintTest(unittest.TestCase):
    def test_markup_basic(self):
        text, formats = exchange.mint_markup_to_text("Привет #tag:bold:мир#tag:bold:! ##1")
        self.assertEqual(text, "Привет мир! #1")
        self.assertEqual(formats, [[7, 10, "bold"]])

    def test_markup_checks_and_bullets(self):
        text, _ = exchange.mint_markup_to_text("#check:0 молоко\n#check:1 хлеб\n#bullet:пункт")
        self.assertEqual(text, "☐ молоко\n☑ хлеб\n• пункт")

    def test_markup_unknown_tags_are_dropped_unclosed_are_closed(self):
        text, formats = exchange.mint_markup_to_text(
            "#tag:monospace:код#tag:monospace: #tag:italic:до конца")
        self.assertEqual(text, "код до конца")
        self.assertEqual(formats, [[4, 12, "italic"]])

    def test_markup_plain_text_untouched(self):
        self.assertEqual(exchange.mint_markup_to_text("просто текст"), ("просто текст", []))

    def test_notes_from_mint(self):
        data = {"Active Notes": [{"title": "Untitled", "text": "a", "color": "blue",
                                  "x": 10, "y": 20, "width": 300, "height": 200}],
                "Работа": [{"title": "Отчёт", "text": "#check:1 готов", "color": "red"}]}
        self.assertTrue(exchange.looks_like_mint(data))
        notes = exchange.notes_from_mint(data)
        first, second = notes
        self.assertEqual((first.title, first.group, first.color, first.x, first.width),
                         ("", "", "blue", 10, 300))
        self.assertEqual((second.title, second.group, second.text), ("Отчёт", "Работа", "☑ готов"))
        self.assertEqual(second.color, "#ffb4ab")

    def test_looks_like_mint_rejects_our_format(self):
        self.assertFalse(exchange.looks_like_mint({"version": 1, "notes": []}))
        self.assertFalse(exchange.looks_like_mint({"a": 1}))
        self.assertFalse(exchange.looks_like_mint([]))

    def test_notes_lists_wrapper_is_supported(self):
        data = {"notes_lists": {"Active Notes": [{"text": "x"}]}}
        self.assertTrue(exchange.looks_like_mint(data))
        self.assertEqual(exchange.notes_from_mint(data)[0].text, "x")


class ReadFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        path = self.dir / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_plain_txt_uses_file_name_as_title(self):
        (note,) = exchange.read_notes_file(self.write("идеи.txt", "первая\nвторая\n"))
        self.assertEqual((note.title, note.text), ("идеи", "первая\nвторая"))

    def test_plain_markdown_takes_h1_as_title_and_converts_tasks(self):
        (note,) = exchange.read_notes_file(self.write("a.md", "# План\n\n- [ ] раз\n- [x] два\n"))
        self.assertEqual((note.title, note.text), ("План", "☐ раз\n☑ два"))

    def test_our_json_and_mint_json(self):
        ours = self.write("b.json", dump_notes([Note(text="наша")]))
        self.assertEqual(exchange.read_notes_file(ours)[0].text, "наша")
        mint = self.write("m.json", json.dumps({"Active Notes": [{"text": "минт"}]}))
        self.assertEqual(exchange.read_notes_file(mint)[0].text, "минт")

    def test_our_markdown_export_is_split_into_notes(self):
        md = exchange.export_markdown([Note(title="A", text="1"), Note(title="B", text="2")])
        notes = exchange.read_notes_file(self.write("all.md", md))
        self.assertEqual([n.title for n in notes], ["A", "B"])

    def test_bad_files_raise_value_error(self):
        with self.assertRaises(ValueError):
            exchange.read_notes_file(self.write("x.json", "{нет"))
        with self.assertRaises(ValueError):
            exchange.read_notes_file(self.write("y.json", "[1]"))
        with self.assertRaises(ValueError):
            exchange.read_notes_file(self.dir / "нет-такого.txt")
        (self.dir / "bin.txt").write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaises(ValueError):
            exchange.read_notes_file(self.dir / "bin.txt")


if __name__ == "__main__":
    unittest.main()
