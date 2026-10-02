#!/usr/bin/env python3
"""Create a few fake DCP folders: just enough XML for the scanner, and sparse
MXF files so that sizes look real without using any disk space. The .fake
file tells dev/fake_verify_cli.py which notes to report."""
import os
import sys
import uuid

SMPTE_CPL = """<?xml version="1.0" encoding="UTF-8"?>
<CompositionPlaylist xmlns="http://www.smpte-ra.org/schemas/429-7/2006/CPL" xmlns:meta="http://www.smpte-ra.org/schemas/429-16/2014/CPL-Metadata">
  <Id>urn:uuid:{id}</Id>
  <ContentTitleText>{title}</ContentTitleText>
  <ContentKind>{kind}</ContentKind>
  <ReelList><Reel><Id>urn:uuid:{id}</Id><AssetList>
    <MainPicture><Id>urn:uuid:{id}</Id><EditRate>24 1</EditRate><IntrinsicDuration>{frames}</IntrinsicDuration><EntryPoint>0</EntryPoint><Duration>{frames}</Duration><FrameRate>24 1</FrameRate><ScreenAspectRatio>{w} {h}</ScreenAspectRatio></MainPicture>
    <meta:CompositionMetadataAsset><meta:MainSoundConfiguration>51/L,R,C,LFE,Ls,Rs</meta:MainSoundConfiguration></meta:CompositionMetadataAsset>
  </AssetList></Reel></ReelList>
</CompositionPlaylist>
"""
IOP_CPL = """<?xml version="1.0" encoding="UTF-8"?>
<CompositionPlaylist xmlns="http://www.digicine.com/PROTO-ASDCP-CPL-20040511#">
  <Id>urn:uuid:{id}</Id>
  <ContentTitleText>{title}</ContentTitleText>
  <ContentKind>{kind}</ContentKind>
  <ReelList><Reel><Id>urn:uuid:{id}</Id><AssetList>
    <MainPicture><Id>urn:uuid:{id}</Id><EditRate>24 1</EditRate><IntrinsicDuration>{frames}</IntrinsicDuration><EntryPoint>0</EntryPoint><Duration>{frames}</Duration><FrameRate>24 1</FrameRate><ScreenAspectRatio>2.39</ScreenAspectRatio></MainPicture>
  </AssetList></Reel></ReelList>
</CompositionPlaylist>
"""

SAMPLES = [
    ("Festival2026_ADV_F_FR-XX_FR_20_2K_20260920_SOS_SMPTE_OV", "advertisement", 45 * 24, 1998, 1080, "smpte", "WARN"),
    ("LaTraversee_FTR-1_F_FR-XX_FR-TP_51_2K_20260911_SOS_SMPTE_OV", "feature", 102 * 60 * 24, 1998, 1080, "smpte", ""),
    ("LesHautsPlateaux_FTR_S_EN-FR_FR_51_2K_20260815_SOS_IOP_OV", "feature", 88 * 60 * 24, 2048, 858, "iop", "IOP"),
    ("MinuitAuPort_FTR-2_F_FR-XX_FR-TP_51_2K_20260902_SOS_SMPTE_OV", "feature", 96 * 60 * 24, 1998, 1080, "smpte", "ERR"),
]

root = sys.argv[1] if len(sys.argv) > 1 else "sample-dcps"
for name, kind, frames, w, h, std, fake in SAMPLES:
    d = os.path.join(root, "Films", name)
    os.makedirs(d, exist_ok=True)
    i = str(uuid.uuid4())
    tpl = SMPTE_CPL if std == "smpte" else IOP_CPL
    with open(os.path.join(d, "cpl.xml"), "w") as f:
        f.write(tpl.format(id=i, title=name, kind=kind, frames=frames, w=w, h=h))
    with open(os.path.join(d, "ASSETMAP.xml" if std == "smpte" else "ASSETMAP"), "w") as f:
        f.write("<AssetMap/>")
    with open(os.path.join(d, ".fake"), "w") as f:
        f.write(fake)
    seconds = frames / 24
    for n, rate in (("j2c_video.mxf", 29_000_000), ("pcm_audio.mxf", 870_000)):
        with open(os.path.join(d, n), "wb") as f:
            f.truncate(int(seconds * rate))
print("Sample DCPs created in", os.path.abspath(root))
