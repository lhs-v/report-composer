import json
import tempfile
import unittest
from pathlib import Path

from composer_lib.memory import Memory


class MemoryTests(unittest.TestCase):
    def test_captions_and_uses_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            m = Memory(Path(tmp) / "memory.json")
            self.assertIsNone(m.caption("R-1"))
            m.set_caption("R-1", ["보이는 것", "이유"], "2026-W43")
            m.mark_used(["R-1", "C-U-1"], "2026-W43")
            m.mark_used(["R-1"], "2026-W44")
            again = Memory(Path(tmp) / "memory.json")
            self.assertEqual(again.caption("R-1"), ["보이는 것", "이유"])
            self.assertEqual(again.weeks_used("R-1"), ["2026-W43", "2026-W44"])
            self.assertEqual(again.weeks_used("C-U-1"), ["2026-W43"])
            self.assertEqual(again.data()["captions"]["R-1"]["week"], "2026-W43")
            raw = json.loads((Path(tmp) / "memory.json").read_text(encoding="utf-8"))
            self.assertEqual(set(raw), {"captions", "used"})

    def test_a_broken_file_is_treated_as_empty_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "memory.json"
            p.write_text("{not json", encoding="utf-8")
            self.assertEqual(Memory(p).data(), {"captions": {}, "used": {}})


if __name__ == "__main__":
    unittest.main()
