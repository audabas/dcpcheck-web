import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from dcpcheck.output import OutputParser, parse_note, reclassify, status_of  # noqa: E402


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


class Classify(unittest.TestCase):
    def test_critical(self):
        for msg in (
            "The hash (abc) of the picture asset j2c.mxf does not agree with the PKL file (def).",
            "The file j2c.mxf for an asset in the asset map cannot be found.",
            "Frame 1 (timecode 00:00:00:01) has an invalid JPEG2000 codestream (bad marker).",
            "Something new that dcpcheck has never seen.",
            "An XML file is badly formed: expected end of tag 'Id' (cpl.xml:12)",
        ):
            self.assertEqual(parse_note("Error: " + msg)["sev"], "error", msg)

    def test_minor(self):
        for msg in (
            "An XML file is badly formed: element 'AnnotationText' is not allowed for content model "
            "'(Id,AnnotationText?,VolumeCount,IssueDate,Issuer,Creator,AssetList)' (ASSETMAP:84)",
            "<ContentKind> has an invalid value foo.",
            "The CPL 123 has no <ContentVersion> tag",
            'The font file for font ID "f" was not found, or was not referred to in the ASSETMAP.',
            "At least one subtitle extends outside of its reel.",
        ):
            self.assertEqual(parse_note("Error: " + msg)["sev"], "minor", msg)

    def test_only_errors(self):
        self.assertEqual(parse_note("Bv2.1 error: The subtitle asset 1 has no subtitles.")["sev"], "bv21")
        self.assertEqual(parse_note("Warning: <ContentKind> has an invalid value foo.")["sev"], "warn")

    def test_stored_result(self):
        res = {
            "status": "error",
            "counts": {"error": 1, "bv21": 0, "warn": 1},
            "notes": [
                {"sev": "error", "msg": "An XML file is badly formed: element 'X' is not allowed for content model 'Y' (ASSETMAP:3)"},
                {"sev": "warn", "msg": "meh"},
            ],
        }
        reclassify(res)
        self.assertEqual(res["status"], "minor")
        self.assertEqual(res["counts"], {"error": 0, "minor": 1, "bv21": 0, "warn": 1})
        failed = reclassify({"status": "failed", "notes": []})
        self.assertEqual(failed["status"], "failed")


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
        p.feed("Error: <ContentKind> has an invalid value foo.\n")
        p.finish()
        self.assertEqual([n["sev"] for n in p.notes], ["error", "warn", "minor"])
        self.assertEqual(status_of(p.notes), "error")
        self.assertEqual(status_of(p.notes[1:]), "minor")

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
