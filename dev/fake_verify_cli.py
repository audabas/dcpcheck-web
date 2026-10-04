#!/usr/bin/env python3
"""Stand-in for dcpomatic2_verify_cli, for working on the UI without
DCP-o-matic installed. It prints stages, a progress bar and notes the way
the real verifier does. Notes are picked from a ".fake" file in the DCP
(see dev/make_sample_dcps.py): "ERR" gives a critical error, "MINOR" a
minor one, "IOP" Bv2.1 issues, "WARN" a warning.

    VERIFIER=dev/fake_verify_cli.py FAKE_SPEED=5 python3 -m dcpcheck
"""
import os
import sys
import time

args = sys.argv[1:]
report = None
if "-o" in args:
    i = args.index("-o")
    report = args[i + 1]
    del args[i:i + 2]
dcp = args[-1]
name = os.path.basename(os.path.normpath(dcp))
try:
    with open(os.path.join(dcp, ".fake")) as f:
        fake = f.read()
except OSError:
    fake = ""
speed = float(os.environ.get("FAKE_SPEED", "1"))


def bar(amount):
    width = 60
    index = round(amount * width)
    s = "".join("=" if i < index else ">" if i == index else " " for i in range(width))
    print(f"[{s}] {round(amount * 100)}%", end="\r", flush=True)


print("Checking DCP", dcp, flush=True)
print(f"Checking CPL: {dcp}/cpl.xml", flush=True)
for f in sorted(os.listdir(dcp)):
    if f.endswith(".mxf"):
        print(f"Checking picture asset hash: {os.path.join(dcp, f)}", flush=True)
        for i in range(21):
            bar(i / 20)
            time.sleep(0.15 / speed)
        print(flush=True)
print("Checking subtitles", flush=True)
time.sleep(0.3 / speed)

# Like the real verifier, notes come in the order they are found, not by severity.
notes = []
if "WARN" in fake or "ERR" in fake:
    notes.append("Warning: At least one frame of the picture asset j2c_video.mxf is close to the limit of 250Mbit/s.")
if "ERR" in fake:
    notes.append("Error: The hash (QzW2nUJ6XzA8Kz/fT1Rc3h9YbQo=) of the picture asset j2c_video.mxf does not agree with the PKL file (8sVq0pL2mWc4Jd7kHxN5uZr1EyA=).")
if "MINOR" in fake:
    notes.append("Error: An XML file is badly formed: element 'AnnotationText' is not allowed for content model "
                 "'(Id,AnnotationText?,VolumeCount,IssueDate,Issuer,Creator,AssetList)' (ASSETMAP.xml:84)")
if "IOP" in fake:
    notes.append("Bv2.1 error: The DCP is Interop.  Bv2.1 requires SMPTE.")
    notes.append("Bv2.1 error: The subtitle asset sub.xml has no <Language> tag.")
for n in notes:
    print(n)
if not notes:
    print("No errors found.")
if report:
    with open(report, "w") as f:
        f.write("<html><body><h1>Report for %s</h1><ul>%s</ul></body></html>" % (name, "".join("<li>%s</li>" % n for n in notes)))
sys.exit(1 if any(n.startswith("Error") for n in notes) else 0)
