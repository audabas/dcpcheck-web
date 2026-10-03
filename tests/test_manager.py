import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

from dcpcheck.manager import Manager  # noqa: E402
from dcpcheck.server import Config  # noqa: E402


def config(root, data, quiet):
    return Config(
        dcp_root=root, dcp_root_label=root, data_dir=data, verifier="true", verify_args=[],
        html_report=False, max_parallel=1, scan_depth=3, scan_interval=0,
        copy_quiet=quiet, copy_poll=0.1, host="127.0.0.1", port=0, verifier_version="",
    )


class Copies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "dcp")
        self.dcp = os.path.join(self.root, "Film_FTR_2K_SMPTE_OV")
        os.makedirs(self.dcp)
        with open(os.path.join(self.dcp, "ASSETMAP.xml"), "w") as f:
            f.write("<AssetMap/>")
        self.mxf = os.path.join(self.dcp, "j2c_video.mxf")

    def tearDown(self):
        self.tmp.cleanup()

    def manager(self, quiet):
        m = Manager(config(self.root, os.path.join(self.tmp.name, "data"), quiet))
        m.rescan()
        return m

    def grow(self, n):
        with open(self.mxf, "ab") as f:
            f.write(b"\0" * n)

    def only(self, m):
        (d,) = m.dcps.values()
        return d

    def test_old_folder_is_not_copying(self):
        old = time.time() - 3600
        for n in os.listdir(self.dcp):
            os.utime(os.path.join(self.dcp, n), (old, old))
        # ctime can't be set back: give the check a quiet period shorter than the file's age.
        time.sleep(0.2)
        m = self.manager(quiet=0.1)
        self.assertEqual(m.copies, {})
        self.assertIsNone(m.state()["dcps"][0]["copy"])
        self.assertTrue(m.verify(self.only(m).id))

    def test_fresh_folder_is_copying_until_quiet(self):
        m = self.manager(quiet=0.5)
        d = self.only(m)
        self.assertIn(d.id, m.copies)
        self.assertFalse(m.verify(d.id))

        self.grow(1_000_000)
        time.sleep(0.1)
        m.remeasure(d)
        self.grow(1_000_000)
        time.sleep(0.1)
        m.remeasure(d)
        copy = m.state()["dcps"][0]["copy"]
        self.assertGreater(copy["speed"], 0)
        self.assertEqual(d.size, 2_000_000 + len("<AssetMap/>"))

        time.sleep(0.6)
        m.remeasure(d)
        self.assertNotIn(d.id, m.copies)
        self.assertIsNone(m.state()["dcps"][0]["copy"])
        self.assertTrue(m.verify(d.id))

    def test_rescan_notices_growth(self):
        time.sleep(0.2)
        m = self.manager(quiet=0.1)
        self.assertEqual(m.copies, {})
        self.grow(10_000)
        m.rescan()
        self.assertIn(self.only(m).id, m.copies)

    def test_removed_folder_is_forgotten(self):
        m = self.manager(quiet=10)
        self.assertEqual(len(m.copies), 1)
        os.remove(os.path.join(self.dcp, "ASSETMAP.xml"))
        m.rescan()
        self.assertEqual(m.copies, {})


if __name__ == "__main__":
    unittest.main()
