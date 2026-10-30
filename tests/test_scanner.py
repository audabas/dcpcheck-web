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

    def test_mxf_without_assetmap(self):
        with tempfile.TemporaryDirectory() as root:
            for folder, files in {"Arriving": ["j2c_video.mxf"], "Rsync": [".pcm_audio.mxf.Ab12Cd"],
                                  "Done": ["ASSETMAP.xml", "j2c_video.mxf"], "Other": ["notes.txt"]}.items():
                os.makedirs(os.path.join(root, folder, "sub"))
                for n in files:
                    open(os.path.join(root, folder, n), "w").close()
            dcps = {d.name: d.partial for d in scanner.find_dcps(root)}
            self.assertEqual(dcps, {"Arriving": True, "Done": False, "Rsync": True})

    def test_facts(self):
        by_name = {d.name.split("_")[0]: d.facts for d in scanner.find_dcps(self.tmp.name)}
        self.assertEqual(by_name["LaTraversee"], {
            "standard": "SMPTE", "title": by_name["LaTraversee"]["title"], "kind": "Feature",
            "frame_rate": "24 fps", "duration": "1h 42m", "picture": "2K Flat · 1998×1080", "sound": "5.1",
            "audio_language": "French (fr-FR)", "subtitles": "None", "kdm": False,
        })
        # Interop sample: no language in its CPL, so they come from its name.
        self.assertEqual(by_name["LesHautsPlateaux"]["audio_language"], "English (EN)")
        self.assertEqual(by_name["LesHautsPlateaux"]["subtitles"], "French (FR)")
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

    def test_languages_from_the_cpl(self):
        cpl = ('<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429-7/2006/CPL" '
               'xmlns:meta="http://www.smpte-ra.org/schemas/429-16/2014/CPL-Metadata" '
               'xmlns:cc="http://www.smpte-ra.org/schemas/429-12/2008/TT"><ReelList>'
               '<Reel><AssetList><MainSound><Language>en-US</Language></MainSound>'
               '<MainSubtitle><Language>fr-FR</Language></MainSubtitle><cc:MainClosedCaption/>'
               '<meta:CompositionMetadataAsset><meta:MainSubtitleLanguageList>fr-FR de</meta:MainSubtitleLanguageList>'
               '</meta:CompositionMetadataAsset></AssetList></Reel>'
               '<Reel><AssetList><MainSound><Language>en-US</Language></MainSound></AssetList></Reel>'
               '</ReelList></CompositionPlaylist>')
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "cpl.xml"), "w") as f:
                f.write(cpl)
            # The CPL wins over the name.
            facts = scanner.read_facts(tmp, "Film_FTR_F_IT-XX_IT_51_2K")
        self.assertEqual(facts["audio_language"], "English (en-US)")
        self.assertEqual(facts["subtitles"], "French (fr-FR), German (de)")
        self.assertEqual(facts["captions"], "Language not given")

    def test_versions(self):
        # A folder with an original version and a dubbed one, as Bv2.1 CPLs
        # write them: the spoken language is in the MCA labels of the sound.
        cpl = ('<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429-7/2006/CPL" '
               'xmlns:meta="http://www.smpte-ra.org/schemas/429-16/2014/CPL-Metadata" '
               'xmlns:r0="http://www.smpte-ra.org/reg/395/2014/13/1/aaf" xmlns:r1="http://www.smpte-ra.org/reg/335/2012">'
               '<ContentTitleText>{title}</ContentTitleText><ReelList><Reel><AssetList>'
               '<MainPicture><EditRate>24 1</EditRate><Duration>2400</Duration><ScreenAspectRatio>4096 1716</ScreenAspectRatio></MainPicture>'
               '<MainSound><Id>urn:uuid:1</Id></MainSound>{aux}'
               '<meta:CompositionMetadataAsset><meta:MainSoundConfiguration>{config}</meta:MainSoundConfiguration>'
               '<meta:MCASubDescriptors><r0:SoundfieldGroupLabelSubDescriptor><r1:RFC5646SpokenLanguage>{lang}</r1:RFC5646SpokenLanguage>'
               '</r0:SoundfieldGroupLabelSubDescriptor></meta:MCASubDescriptors></meta:CompositionMetadataAsset>'
               '</AssetList></Reel></ReelList></CompositionPlaylist>')
        iab = '<AuxData xmlns="http://www.dolby.com/schemas/2012/AD"><DataType>urn:smpte:ul:060e2b34.04010105.0e090604.00000000</DataType></AuxData>'
        with tempfile.TemporaryDirectory() as tmp:
            for n, title, lang, config, aux in (
                    ("a", "Film_FTR_S_FR-XX_FR_IAB-51-VI_4K_X_VF", "fr", "51/L,R,C,LFE,Ls,Rs,-,VIN", iab),
                    ("b", "Film_FTR_S_EN-XX_OV_51_4K_X_OV", "en", "51/L,R,C,LFE,Ls,Rs,-,-", "")):
                with open(os.path.join(tmp, n + ".xml"), "w") as f:
                    f.write(cpl.format(title=title, lang=lang, config=config, aux=aux))
            facts = scanner.read_facts(tmp, "Film_FTR_S_EN-XX_OV_51_4K_X_OV")
        self.assertEqual(facts["audio_language"], "English (en), French (fr)")
        self.assertEqual(facts["sound"], "5.1, 5.1 · IAB · VI")
        self.assertEqual(facts["cpls"], 2)
        self.assertEqual([(v["title"], v["audio_language"], v["sound"]) for v in facts["versions"]], [
            ("Film_FTR_S_EN-XX_OV_51_4K_X_OV", "English (en)", "5.1"),
            ("Film_FTR_S_FR-XX_FR_IAB-51-VI_4K_X_VF", "French (fr)", "5.1 · IAB · VI"),
        ])

    def test_languages_of_each_cpl_name(self):
        # Without languages in the CPLs, each CPL's own title tells them.
        cpl = ('<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429-7/2006/CPL">'
               '<ContentTitleText>{}</ContentTitleText><ReelList/></CompositionPlaylist>')
        with tempfile.TemporaryDirectory() as tmp:
            for n, title in (("a", "Film_FTR_F_EN-XX_OV_51_2K"), ("b", "Film_FTR_F_FR-XX_FR_51_2K"), ("c", "Film_FTR_F_DE-fr_FR_51_2K")):
                with open(os.path.join(tmp, n + ".xml"), "w") as f:
                    f.write(cpl.format(title))
            facts = scanner.read_facts(tmp, "Film_FTR_F_EN-XX_OV_51_2K")
        self.assertEqual(facts["audio_language"], "German (DE), English (EN), French (FR)")
        self.assertEqual(facts["subtitles"], "French (FR) · burned in")

    def test_languages_from_name(self):
        langs = lambda name: scanner.read_languages([], [name])
        self.assertEqual(langs("Film_FTR_F_FR-XX_FR-TP_51_2K"), {"audio_language": "French (FR)", "subtitles": "None"})
        self.assertEqual(langs("Film_FTR_S-239_EN-fr_FR_51_2K")["subtitles"], "French (FR) · burned in")
        self.assertEqual(langs("Film_FTR_F_EN-FR-DE-CCAP_FR_51_2K"), {
            "audio_language": "English (EN)", "subtitles": "French (FR), German (DE)", "captions": "Language not given",
        })
        self.assertEqual(langs("whatever"), {})

    def test_sound_from_name(self):
        self.assertEqual(scanner.sound_from_name("Film_FTR_F_FR-XX_FR_71-HI_2K_X"), "7.1")
        self.assertIsNone(scanner.sound_from_name("whatever"))


if __name__ == "__main__":
    unittest.main()
