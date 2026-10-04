import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app"))

from dcpcheck import kdm, scanner  # noqa: E402
from dcpcheck.manager import Manager  # noqa: E402
from test_manager import config  # noqa: E402

# The public part of an Interop KDM, as DCP-o-matic writes it.
IOP_KDM = """<?xml version="1.0" encoding="UTF-8"?>
<DCinemaSecurityMessage xmlns="http://www.smpte-ra.org/schemas/430-3/2006/ETM" xmlns:dsig="http://www.w3.org/2000/09/xmldsig#">
  <AuthenticatedPublic Id="ID_AuthenticatedPublic">
    <MessageId>urn:uuid:0F1E2D3C-0000-4000-8000-000000000001</MessageId>
    <MessageType>http://www.digicine.com/PROTO-ASDCP-KDM-20040311#</MessageType>
    <AnnotationText>Film :: Cinema :: Screen 2</AnnotationText>
    <IssueDate>2026-10-01T10:00:00+02:00</IssueDate>
    <RequiredExtensions>
      <KDMRequiredExtensions xmlns="http://www.smpte-ra.org/schemas/430-1/2006/KDM">
        <Recipient>
          <X509IssuerSerial><dsig:X509IssuerName>CN=.ca</dsig:X509IssuerName><dsig:X509SerialNumber>1</dsig:X509SerialNumber></X509IssuerSerial>
          <X509SubjectName>dnQualifier=abc\\,d=,CN=SM.ws-1234.DOREMI.example,O=example</X509SubjectName>
        </Recipient>
        <CompositionPlaylistId>urn:uuid:{cpl}</CompositionPlaylistId>
        <ContentTitleText>Film_FTR_F_FR-XX</ContentTitleText>
        <ContentKeysNotValidBefore>{start}</ContentKeysNotValidBefore>
        <ContentKeysNotValidAfter>{end}</ContentKeysNotValidAfter>
        <AuthorizedDeviceInfo><DeviceListDescription>Screen 2</DeviceListDescription></AuthorizedDeviceInfo>
        <KeyIdList>{keys}</KeyIdList>
      </KDMRequiredExtensions>
    </RequiredExtensions>
  </AuthenticatedPublic>
</DCinemaSecurityMessage>
"""
CPL_ID = "8a1b2c3d-0000-4000-8000-00000000000a"
KEYS = ["8a1b2c3d-0000-4000-8000-0000000000b1", "8a1b2c3d-0000-4000-8000-0000000000b2"]
CPLS = [{"id": CPL_ID, "title": "Film", "key_ids": KEYS}]
NOW = 1_790_000_000  # 2026-09-21


def make(cpl=CPL_ID, keys=KEYS, start="2026-09-20T00:00:00+00:00", end="2026-09-30T23:59:59Z"):
    typed = "".join(f"<TypedKeyId><KeyType>MDIK</KeyType><KeyId>urn:uuid:{k.upper()}</KeyId></TypedKeyId>" for k in keys)
    return IOP_KDM.format(cpl=cpl.upper(), keys=typed, start=start, end=end).encode()


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class Parse(unittest.TestCase):
    def test_reads_the_public_part(self):
        k = kdm.parse(make())
        self.assertEqual(k["cpl_id"], CPL_ID)
        self.assertEqual(k["key_ids"], KEYS)
        self.assertEqual(k["title"], "Film_FTR_F_FR-XX")
        self.assertEqual(k["recipient"], "SM.ws-1234.DOREMI.example")
        self.assertEqual(k["device"], "Screen 2")
        self.assertEqual(k["annotation"], "Film :: Cinema :: Screen 2")
        self.assertEqual(k["message_id"], "0f1e2d3c-0000-4000-8000-000000000001")
        self.assertEqual(k["not_after"], 1790812799)

    def test_not_a_kdm(self):
        for data in (b"%PDF-1.4", b"<CompositionPlaylist/>", b"<DCinemaSecurityMessage/>"):
            with self.assertRaises(kdm.NotKdm):
                kdm.parse(data)


class Check(unittest.TestCase):
    def verdict(self, data, cpls=CPLS, now=NOW):
        return kdm.check(kdm.parse(data), cpls, now)["verdict"]

    def test_verdicts(self):
        self.assertEqual(self.verdict(make()), "ok")
        self.assertEqual(self.verdict(make(), now=NOW - 2 * 86400), "not_yet")
        self.assertEqual(self.verdict(make(), now=NOW + 10 * 86400), "expired")
        self.assertEqual(self.verdict(make(cpl="8a1b2c3d-0000-4000-8000-0000000000ff")), "other")
        self.assertEqual(self.verdict(make(keys=KEYS[:1])), "keys")
        self.assertEqual(self.verdict(make(start="tomorrow")), "unknown")
        # Extra keys, for the forensic marking say, are fine.
        self.assertEqual(self.verdict(make(keys=KEYS + ["8a1b2c3d-0000-4000-8000-0000000000b3"])), "ok")

    def test_details(self):
        r = kdm.check(kdm.parse(make(keys=KEYS[:1])), CPLS, NOW)
        self.assertEqual((r["needed"], r["missing"], r["keys"]), (2, 1, 1))
        self.assertNotIn("key_ids", r)


class Unpack(unittest.TestCase):
    def test_plain_file(self):
        self.assertEqual(kdm.unpack("a.xml", b"<x/>"), ([("a.xml", b"<x/>")], []))

    def test_zip(self):
        inner = zipped({"c.xml": b"<c/>"})
        data = zipped({"a.xml": b"<a/>", "__MACOSX/._a.xml": b"junk", "dir/.DS_Store": b"", "dir/b.xml": b"<b/>", "more.zip": inner})
        files, skipped = kdm.unpack("kdms.zip", data)
        self.assertEqual([n for n, _ in files], ["kdms.zip › a.xml", "kdms.zip › dir/b.xml", "kdms.zip › more.zip › c.xml"])
        self.assertEqual(skipped, [])

    def test_too_deep_and_damaged(self):
        deep = zipped({"b.zip": zipped({"c.zip": zipped({"d.xml": b"<d/>"})})})
        self.assertEqual(kdm.unpack("a.zip", deep), ([], [("a.zip › b.zip › c.zip", "a ZIP inside a ZIP inside a ZIP")]))
        self.assertEqual(kdm.unpack("a.zip", b"PK\x03\x04broken"), ([], [("a.zip", "damaged ZIP file")]))

    def test_large_file(self):
        files, skipped = kdm.unpack("a.zip", zipped({"film.mxf": b"\0" * (kdm.MAX_FILE + 1)}))
        self.assertEqual((files, skipped), ([], [("a.zip › film.mxf", "too large for a KDM")]))


class Library(unittest.TestCase):
    """The sample DCPs and the sample KDMs of dev/."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = os.path.join(cls.tmp.name, "dcp")
        cls.zip = os.path.join(cls.tmp.name, "kdms.zip")
        for script, args in (("make_sample_dcps.py", [root]), ("make_sample_kdms.py", [root, cls.zip])):
            subprocess.run([sys.executable, os.path.join(HERE, "..", "dev", script)] + args, check=True, capture_output=True)
        cls.m = Manager(config(root, os.path.join(cls.tmp.name, "data"), 20))
        cls.m.cfg.auto_verify = False
        cls.m.rescan()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def dcp(self, prefix):
        return next(d for d in self.m.dcps.values() if d.name.startswith(prefix))

    def test_zip_against_a_dcp(self):
        with open(self.zip, "rb") as f:
            res = self.m.check_kdms(self.dcp("Minuit").id, "kdms.zip", f.read())
        by_file = {r["file"].rsplit("/", 1)[-1]: r for r in res["kdms"]}
        self.assertEqual(len(by_file), 12)
        self.assertEqual(by_file["MinuitAuPort_Salle1.xml"]["verdict"], "ok")
        self.assertEqual(by_file["MinuitAuPort_Salle1.xml"]["recipient"], "SM.salle1.IMB.example.com")
        self.assertEqual(by_file["MinuitAuPort_Salle3_expired.xml"]["verdict"], "expired")
        self.assertEqual(by_file["MinuitAuPort_Salle4_later.xml"]["verdict"], "not_yet")
        self.assertEqual(by_file["MinuitAuPort_Salle5_missing_key.xml"]["verdict"], "keys")
        self.assertEqual(by_file["MinuitAuPort_VOST_Salle1.xml"]["verdict"], "other")
        self.assertNotIn("other", by_file["MinuitAuPort_VOST_Salle1.xml"])
        # A KDM for another DCP of the library says which one.
        other = by_file["LeDernierQuai_Salle1.xml"]
        self.assertEqual(other["verdict"], "other")
        self.assertEqual(other["other"]["id"], self.dcp("LeDernierQuai").id)
        self.assertEqual(other["other"]["check"]["verdict"], "ok")
        self.assertEqual(res["skipped"], [{"file": "kdms.zip › README.txt", "reason": "not an XML file"}])
        self.assertEqual(len(res["cpls"]), 1)

    def test_unknown_dcp(self):
        self.assertIsNone(self.m.check_kdms("000000000000", "a.xml", make()))

    def test_cpls(self):
        (cpl,) = scanner.read_cpls(self.dcp("Minuit").path)
        self.assertEqual(len(cpl["key_ids"]), 1)
        self.assertEqual(scanner.read_cpls(self.dcp("LaTraversee").path)[0]["key_ids"], [])


if __name__ == "__main__":
    unittest.main()
