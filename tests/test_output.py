import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from dcpcheck.output import OutputParser, parse_note, status_of  # noqa: E402


class ParseNote(unittest.TestCase):
    def test_severities(self):
        self.assertEqual(parse_note("Error: broken")["sev"], "error")
        self.assertEqual(parse_note("Bv2.1 error: not SMPTE")["sev"], "bv21")
        self.assertEqual(parse_note("  Warning: close to the limit")["sev"], "warn")
        self.assertEqual(parse_note("OK: fine")["sev"], "ok")
        self.assertIsNone(parse_note("Checking picture asset hash: /dcp/a.mxf"))

    def test_code_and_file(self):
        n = parse_note("Error: The hash of /dcp/Film/j2c_abc.mxf is wrong (INCORRECT_PICTURE_HASH).")
        self.assertEqual(n["code"], "INCORRECT_PICTURE_HASH")
        self.assertEqual(n["file"], "j2c_abc.mxf")
        self.assertNotIn("code", parse_note("Warning: The DCP is SMPTE."))


class Parser(unittest.TestCase):
    def test_stream(self):
        p = OutputParser()
        kept = p.feed("Checking DCP /dcp/x\nChecking picture asset hash: /dcp/x/j2c")
        self.assertEqual(kept, ["Checking DCP /dcp/x"])
        kept = p.feed(".mxf\n[=====>     ] 4")
        self.assertEqual(p.stage, "Checking picture asset hash: j2c.mxf")
        kept = p.feed("2%\r[==========> ] 87%")
        self.assertEqual(kept, [])
        self.assertEqual(p.progress, 87)
        p.feed("\rError: bad thing in cpl.xml\nWarning: meh\n")
        p.finish()
        self.assertEqual([n["sev"] for n in p.notes], ["error", "warn"])
        self.assertEqual(status_of(p.notes), "error")

    def test_clean(self):
        p = OutputParser()
        p.feed("Checking DCP\nNo errors found.\n")
        self.assertTrue(p.said_clean)
        self.assertEqual(status_of(p.notes), "ok")

    def test_ansi(self):
        p = OutputParser()
        p.feed("\x1b[31mBv2.1 error: subtitle\x1b[0m\n")
        self.assertEqual(p.notes[0]["sev"], "bv21")


if __name__ == "__main__":
    unittest.main()
