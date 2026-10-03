#!/usr/bin/env python3
"""Pretend a DCP is being copied to the NAS: create a DCP folder with a PKL
announcing its final size, and make its MXF file grow at a given speed, to
see how dcpcheck shows a copy in progress.

    python3 dev/simulate_copy.py sample-dcps/Films/Arriving_FTR_2K_SMPTE_OV 20MB 30

The last two arguments are the speed per second and the duration in seconds.
The bytes written are real, so keep both small. With --presize, the MXF file
gets its final size first and is filled afterwards, as Windows does over SMB.
"""
import os
import sys
import time
import uuid

args = [a for a in sys.argv[1:] if a != "--presize"]
presize = len(args) < len(sys.argv) - 1
dest = args[0]
speed = args[1] if len(args) > 1 else "20MB"
seconds = float(args[2]) if len(args) > 2 else 30
units = {"KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}
rate = int(float(speed.upper().rstrip("KMGB") or 1) * units.get(speed[-2:].upper(), 1))
step = 0.25
chunk = b"\1" * int(rate * step)
total = len(chunk) * int(seconds / step)

os.makedirs(dest, exist_ok=True)
with open(os.path.join(dest, "ASSETMAP.xml"), "w") as f:
    f.write("<AssetMap/>")
with open(os.path.join(dest, "pkl.xml"), "w") as f:
    f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<PackingList xmlns="http://www.smpte-ra.org/schemas/429-8/2007/PKL">
  <Id>urn:uuid:{uuid.uuid4()}</Id>
  <AssetList><Asset><Id>urn:uuid:{uuid.uuid4()}</Id><Size>{total}</Size></Asset></AssetList>
</PackingList>
""")
mxf = os.path.join(dest, "j2c_video.mxf")
with open(mxf, "wb") as f:
    if presize:
        f.truncate(total)
    for _ in range(int(seconds / step)):
        f.write(chunk)
        f.flush()
        time.sleep(step)
print("Copy finished:", os.path.abspath(dest))
