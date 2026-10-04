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
        self.assertEqual(len(dcps), 5)
        self.assertTrue(all(d.relpath.startswith("Films/") for d in dcps))
        self.assertEqual(len({d.id for d in dcps}), 5)

    def test_depth(self):
        self.assertEqual(scanner.find_dcps(self.tmp.name, max_depth=1), [])

    def test_facts(self):
        by_name = {d.name.split("_")[0]: d.facts for d in scanner.find_dcps(self.tmp.name)}
        self.assertEqual(by_name["LaTraversee"], {
            "standard": "SMPTE", "title": by_name["LaTraversee"]["title"], "kind": "Feature",
            "frame_rate": "24 fps", "duration": "1h 42m", "picture": "2K Flat · 1998×1080", "sound": "5.1", "kdm": False,
        })
        self.assertEqual(by_name["LesHautsPlateaux"]["standard"], "Interop")
        self.assertEqual(by_name["LesHautsPlateaux"]["picture"], "2K Scope · 2048×858")
        self.assertEqual(by_name["Festival2026"]["duration"], "45s")
        self.assertEqual(by_name["Festival2026"]["kind"], "Advertisement")
        self.assertTrue(by_name["MinuitAuPort"]["kdm"])

    def test_kdm(self):
        cpl = ('<CompositionPlaylist xmlns="http://www.digicine.com/PROTO-ASDCP-CPL-20040511#"><ReelList><Reel><AssetList>'
               '<MainPicture><Id>urn:uuid:1</Id></MainPicture><MainSound><Id>urn:uuid:2</Id>{key}</MainSound>'
               '</AssetList></Reel></ReelList></CompositionPlaylist>')
        with tempfile.TemporaryDirectory() as tmp:
            for key, kdm in (("", False), ("<KeyId>urn:uuid:3</KeyId>", True)):
                with open(os.path.join(tmp, "cpl.xml"), "w") as f:
                    f.write(cpl.format(key=key))
                self.assertIs(scanner.read_facts(tmp, "x")["kdm"], kdm)
            os.remove(os.path.join(tmp, "cpl.xml"))
            self.assertNotIn("kdm", scanner.read_facts(tmp, "x"))

    def test_expected_size(self):
        d = next(d for d in scanner.find_dcps(self.tmp.name) if d.name.startswith("Festival"))
        mxfs = sum(os.path.getsize(os.path.join(d.path, n)) for n in ("j2c_video.mxf", "pcm_audio.mxf", "cpl.xml"))
        self.assertEqual(scanner.expected_size(d.path), mxfs)

    def test_expected_size_needs_a_whole_pkl(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(scanner.expected_size(tmp))
            with open(os.path.join(tmp, "pkl.xml"), "w") as f:
                f.write('<PackingList xmlns="http://www.smpte-ra.org/schemas/429-8/2007/PKL"><AssetList><Asset><Size>12')
            self.assertIsNone(scanner.expected_size(tmp))

    def test_written_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "a.mxf"), "wb") as f:
                f.write(b"x" * 100_000)
            # Given its final size but not written yet, as Windows does over SMB.
            with open(os.path.join(tmp, "b.mxf"), "wb") as f:
                f.truncate(10_000_000)
            size, written, _ = scanner.measure(tmp)
            self.assertEqual(size, 10_100_000)
            if os.stat(os.path.join(tmp, "a.mxf")).st_blocks:
                self.assertEqual(written, 100_000)

    def test_sound_from_name(self):
        self.assertEqual(scanner.sound_from_name("Film_FTR_F_FR-XX_FR_71-HI_2K_X"), "7.1")
        self.assertIsNone(scanner.sound_from_name("whatever"))


if __name__ == "__main__":
    unittest.main()
