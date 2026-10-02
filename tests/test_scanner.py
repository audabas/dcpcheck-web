import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

from dcpcheck import scanner  # noqa: E402


class Scanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        subprocess.run([sys.executable, os.path.join(HERE, "..", "dev", "make_sample_dcps.py"), cls.tmp.name], check=True, capture_output=True)
        os.makedirs(os.path.join(cls.tmp.name, "@eaDir", "x"))
        open(os.path.join(cls.tmp.name, "@eaDir", "x", "ASSETMAP.xml"), "w").close()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_finds_dcps(self):
        dcps = scanner.find_dcps(self.tmp.name)
        self.assertEqual(len(dcps), 4)
        self.assertTrue(all(d.relpath.startswith("Films/") for d in dcps))
        self.assertEqual(len({d.id for d in dcps}), 4)

    def test_depth(self):
        self.assertEqual(scanner.find_dcps(self.tmp.name, max_depth=1), [])

    def test_facts(self):
        by_name = {d.name.split("_")[0]: d.facts for d in scanner.find_dcps(self.tmp.name)}
        self.assertEqual(by_name["LaTraversee"], {
            "standard": "SMPTE", "title": by_name["LaTraversee"]["title"], "kind": "Feature",
            "frame_rate": "24 fps", "duration": "1h 42m", "picture": "2K Flat · 1998×1080", "sound": "5.1",
        })
        self.assertEqual(by_name["LesHautsPlateaux"]["standard"], "Interop")
        self.assertEqual(by_name["LesHautsPlateaux"]["picture"], "2K Scope · 2048×858")
        self.assertEqual(by_name["Festival2026"]["duration"], "45s")
        self.assertEqual(by_name["Festival2026"]["kind"], "Advertisement")

    def test_sound_from_name(self):
        self.assertEqual(scanner.sound_from_name("Film_FTR_F_FR-XX_FR_71-HI_2K_X"), "7.1")
        self.assertIsNone(scanner.sound_from_name("whatever"))


if __name__ == "__main__":
    unittest.main()
