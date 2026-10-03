#!/usr/bin/env python3
"""Pretend a DCP is being copied to the NAS: create a DCP folder and make its
MXF file grow at a given speed, to see how dcpcheck shows a copy in progress.

    python3 dev/simulate_copy.py sample-dcps/Films/Arriving_FTR_2K_SMPTE_OV 20MB 30

The last two arguments are the speed per second and the duration in seconds.
The bytes written are real, so keep both small.
"""
import os
import sys
import time

dest = sys.argv[1]
speed = sys.argv[2] if len(sys.argv) > 2 else "20MB"
seconds = float(sys.argv[3]) if len(sys.argv) > 3 else 30
units = {"KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}
rate = int(float(speed.rstrip("KMGB") or 1) * units.get(speed[-2:].upper(), 1))

os.makedirs(dest, exist_ok=True)
with open(os.path.join(dest, "ASSETMAP.xml"), "w") as f:
    f.write("<AssetMap/>")
step = 0.25
chunk = b"\0" * int(rate * step)
end = time.time() + seconds
with open(os.path.join(dest, "j2c_video.mxf"), "ab") as f:
    while time.time() < end:
        f.write(chunk)
        f.flush()
        time.sleep(step)
print("Copy finished:", os.path.abspath(dest))
