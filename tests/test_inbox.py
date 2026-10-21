import tempfile
import unittest
import zipfile
from pathlib import Path

from composer_lib.inbox import extract_week, process_once, scan


def make_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.inbox, self.ws = base / "inbox", base / "ws"
        self.inbox.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_groups_parts_and_knows_when_a_week_is_complete(self):
        make_zip(self.inbox / "2026-W42-light.zip", {"2026-W42/README.md": b"r"})
        make_zip(self.inbox / "2026-W42-part1of2.zip", {"2026-W42/pages/a/preview.png": b"p"})
        states = scan(self.inbox)
        self.assertEqual(list(states), ["2026-W42"])
        self.assertFalse(states["2026-W42"].complete)
        self.assertEqual(states["2026-W42"].missing_parts, [2])
        make_zip(self.inbox / "2026-W42-part2of2.zip", {"2026-W42/pages/a/media/v.mp4": b"v"})
        self.assertTrue(scan(self.inbox)["2026-W42"].complete)

    def test_a_full_zip_alone_is_complete(self):
        make_zip(self.inbox / "2026-W41.zip", {"2026-W41/README.md": b"r"})
        self.assertTrue(scan(self.inbox)["2026-W41"].complete)

    def test_extract_merges_all_zips_and_moves_them_to_done(self):
        make_zip(self.inbox / "2026-W42-light.zip", {"2026-W42/README.md": b"r", "2026-W42/outcomes.json": b"{}"})
        make_zip(self.inbox / "2026-W42-part1of1.zip", {"2026-W42/pages/a/media/v.mp4": b"v"})
        weeks = process_once(self.inbox, self.ws)
        self.assertEqual(weeks, ["2026-W42"])
        self.assertEqual((self.ws / "weeks" / "2026-W42" / "README.md").read_bytes(), b"r")
        self.assertEqual((self.ws / "weeks" / "2026-W42" / "pages" / "a" / "media" / "v.mp4").read_bytes(), b"v")
        self.assertEqual(sorted(p.name for p in (self.inbox / "done").iterdir()), ["2026-W42-light.zip", "2026-W42-part1of1.zip"])
        self.assertEqual(process_once(self.inbox, self.ws), [])      # nothing left: idempotent

    def test_incomplete_week_is_left_in_place(self):
        make_zip(self.inbox / "2026-W42-part1of2.zip", {"2026-W42/x.txt": b"x"})
        self.assertEqual(process_once(self.inbox, self.ws), [])
        self.assertTrue((self.inbox / "2026-W42-part1of2.zip").exists())

    def test_zip_slip_is_rejected(self):
        make_zip(self.inbox / "2026-W40.zip", {"2026-W40/../../evil.txt": b"x"})
        with self.assertRaises(ValueError):
            extract_week(scan(self.inbox)["2026-W40"], self.ws)
        self.assertFalse((self.ws.parent / "evil.txt").exists())


if __name__ == "__main__":
    unittest.main()
