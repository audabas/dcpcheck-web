"""Find DCPs under a directory and read a few facts from their CPL.

This is only used to show a summary in the UI (type, standard, picture,
duration, sound, size). The actual verification is done by DCP-o-matic.
"""

import hashlib
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

ASSETMAP_NAMES = ("ASSETMAP.xml", "ASSETMAP")
# Synology and macOS litter shares with these.
SKIP_DIRS = {"@eaDir", "#recycle", "#snapshot", ".AppleDouble", "lost+found"}

CONTAINERS = {
    (1998, 1080): "2K Flat",
    (2048, 858): "2K Scope",
    (2048, 1080): "2K Full",
    (3996, 2160): "4K Flat",
    (4096, 1716): "4K Scope",
    (4096, 2160): "4K Full",
}

KINDS = {
    "feature": "Feature",
    "short": "Short",
    "trailer": "Trailer",
    "teaser": "Teaser",
    "advertisement": "Advertisement",
    "transitional": "Transitional",
    "rating": "Rating",
    "psa": "PSA",
    "policy": "Policy",
    "test": "Test",
    "episode": "Episode",
    "promo": "Promo",
    "stereocard": "Stereo card",
    "highlights": "Highlights",
    "event": "Event",
    "clip": "Clip",
}


@dataclass
class Dcp:
    id: str
    name: str
    relpath: str
    path: str
    size: int = 0
    written: int = 0    # bytes actually written, see measure()
    mtime: float = 0.0  # last change to any file in the folder
    facts: dict = field(default_factory=dict)


def dcp_id(relpath):
    return hashlib.sha1(relpath.encode("utf-8", "surrogateescape")).hexdigest()[:12]


def is_dcp(path):
    return any(os.path.isfile(os.path.join(path, n)) for n in ASSETMAP_NAMES)


def find_dcps(root, max_depth=3):
    """Return the DCP folders under root, sorted by name."""
    found = []

    def walk(path, depth):
        if is_dcp(path):
            found.append(path)
            return
        if depth >= max_depth:
            return
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
        except OSError:
            return
        for e in entries:
            if e.name.startswith(".") or e.name in SKIP_DIRS:
                continue
            try:
                if e.is_dir(follow_symlinks=True):
                    walk(e.path, depth + 1)
            except OSError:
                continue

    if os.path.isdir(root):
        walk(root, 0)

    dcps = []
    for path in found:
        rel = os.path.relpath(path, root)
        if rel == ".":
            rel = os.path.basename(os.path.normpath(root))
        dcps.append(describe(path, rel))
    dcps.sort(key=lambda d: d.name.lower())
    return dcps


def describe(path, relpath):
    d = Dcp(id=dcp_id(relpath), name=os.path.basename(os.path.normpath(path)), relpath=relpath, path=path)
    d.size, d.written, d.mtime = measure(path)
    try:
        d.facts = read_facts(path, d.name)
    except Exception:  # A broken CPL is the verifier's business, not ours.
        d.facts = {}
    return d


def measure(path):
    """Return (size, bytes written, last change) of the files in a folder.

    The last change is the newest mtime or ctime: a copy that restores the
    original mtimes still leaves a fresh ctime.

    Some copies give a file its final size before writing it (Windows over
    SMB), others reserve its space on disk first. The bytes written count,
    for each file, the smaller of its size and its space on disk, so they
    grow with the data in both cases. On filesystems that report no space
    on disk at all, they are the size.
    """
    size = written = 0
    has_blocks = False
    newest = 0.0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [n for n in dirnames if n not in SKIP_DIRS and not n.startswith(".")]
        for f in filenames:
            try:
                st = os.stat(os.path.join(dirpath, f))
            except OSError:
                continue
            on_disk = getattr(st, "st_blocks", 0) * 512
            has_blocks = has_blocks or on_disk > 0
            size += st.st_size
            written += min(st.st_size, on_disk)
            newest = max(newest, st.st_mtime, st.st_ctime)
    if not newest:
        try:
            newest = os.stat(path).st_mtime
        except OSError:
            pass
    return size, written if has_blocks else size, newest


def expected_size(path):
    """Total size of the assets listed in the folder's packing lists (PKL),
    or None while no complete PKL is there."""
    sizes = {}
    for pkl in find_xml(path, "PackingList"):
        assets = child(pkl, "AssetList")
        for a in assets if assets is not None else []:
            try:
                sizes[text(a, "Id")] = int(text(a, "Size"))
            except (TypeError, ValueError):
                continue
    return sum(sizes.values()) or None


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child(el, name):
    if el is None:
        return None
    for c in el:
        if local(c.tag) == name:
            return c
    return None


def text(el, name):
    c = child(el, name)
    return c.text.strip() if c is not None and c.text else None


def find_cpls(path):
    return find_xml(path, "CompositionPlaylist")


def find_xml(path, kind):
    """Parse the XML files at the top of a folder whose root element is kind."""
    found = []
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return found
    for n in names:
        if not n.lower().endswith(".xml"):
            continue
        p = os.path.join(path, n)
        try:
            if os.path.getsize(p) > 8 * 1024 * 1024:
                continue
            with open(p, "rb") as f:
                head = f.read(4096)
            if kind.encode() not in head:
                continue
            root = ET.parse(p).getroot()
        except (OSError, ET.ParseError):
            continue
        if local(root.tag) == kind:
            found.append(root)
    return found


def standard_of(path, cpl):
    if cpl is not None:
        ns = cpl.tag[1:].split("}")[0] if cpl.tag.startswith("{") else ""
        if "smpte-ra.org" in ns:
            return "SMPTE"
        if "digicine.com" in ns:
            return "Interop"
    if os.path.isfile(os.path.join(path, "ASSETMAP.xml")):
        return "SMPTE"
    if os.path.isfile(os.path.join(path, "ASSETMAP")):
        return "Interop"
    return None


def fmt_duration(seconds):
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m" if s == 0 or m >= 10 else f"{m}m {s:02d}s"
    return f"{s}s"


def picture_label(w, h, stereo):
    label = CONTAINERS.get((w, h))
    out = f"{label} · {w}×{h}" if label else f"{w}×{h}"
    return out + " · 3D" if stereo else out


def picture_from_ratio(ratio, name, stereo):
    four_k = "_4K_" in name.upper()
    for (w, h), label in CONTAINERS.items():
        if label.startswith("4K" if four_k else "2K") and abs(w / h - ratio) < 0.03:
            return picture_label(w, h, stereo)
    return f"{ratio:g}:1" + (" · 3D" if stereo else "")


def sound_from_config(cfg):
    # SMPTE 429-16 MainSoundConfiguration, e.g. "51/L,R,C,LFE,Ls,Rs,-,-,..."
    m = re.match(r"\s*(\d+)\s*/", cfg or "")
    if m:
        return channels_label(m.group(1))
    return None


def channels_label(code):
    return {"10": "1.0", "20": "2.0", "51": "5.1", "71": "7.1", "61": "6.1", "30": "3.0", "40": "4.0"}.get(code, code)


def sound_from_name(name):
    # ISDCF naming convention: ..._FR-XX_FR-TP_51-HI-VI_2K_...
    for part in name.split("_"):
        m = re.fullmatch(r"(10|20|30|40|51|61|71)(-[A-Za-z0-9]+)*", part)
        if m:
            return channels_label(m.group(1))
        if part.upper() in ("IAB", "ATMOS"):
            return "Immersive (" + part + ")"
    return None


def read_facts(path, name):
    cpls = find_cpls(path)
    cpl = cpls[0] if cpls else None
    facts = {"standard": standard_of(path, cpl)}
    if cpl is None:
        return facts

    facts["title"] = text(cpl, "ContentTitleText")
    kind = (text(cpl, "ContentKind") or "").strip()
    facts["kind"] = KINDS.get(kind.lower(), kind.capitalize() or None)
    if len(cpls) > 1:
        facts["cpls"] = len(cpls)

    total = 0.0
    size = None
    ratio = None  # Interop CPLs only give an aspect ratio
    stereo = False
    sound = None
    reels = child(cpl, "ReelList")
    for reel in reels if reels is not None else []:
        assets = child(reel, "AssetList")
        if assets is None:
            continue
        pic = child(assets, "MainPicture")
        if pic is None:
            pic = child(assets, "MainStereoscopicPicture")
            stereo = stereo or pic is not None
        if pic is not None:
            rate = (text(pic, "EditRate") or "24 1").split()
            try:
                fps = float(rate[0]) / float(rate[1] if len(rate) > 1 else 1)
            except (ValueError, ZeroDivisionError):
                fps = 24.0
            frames = text(pic, "Duration")
            if frames is None:
                intrinsic = int(text(pic, "IntrinsicDuration") or 0)
                frames = intrinsic - int(text(pic, "EntryPoint") or 0)
            try:
                total += int(frames) / fps
            except ValueError:
                pass
            if size is None:
                sar = (text(pic, "ScreenAspectRatio") or "").split()
                if len(sar) == 2 and all(x.isdigit() for x in sar):
                    size = (int(sar[0]), int(sar[1]))
                elif len(sar) == 1 and ratio is None:
                    try:
                        ratio = float(sar[0])
                    except ValueError:
                        pass
            facts.setdefault("frame_rate", f"{fps:g} fps")
        meta = child(assets, "CompositionMetadataAsset")
        if meta is not None:
            sound = sound or sound_from_config(text(meta, "MainSoundConfiguration"))
            area = child(meta, "MainPictureStoredArea")
            if area is None:
                area = child(meta, "MainPictureActiveArea")
            if area is not None and size is None:
                try:
                    size = (int(text(area, "Width")), int(text(area, "Height")))
                except (TypeError, ValueError):
                    pass

    if total:
        facts["duration"] = fmt_duration(total)
    if size:
        facts["picture"] = picture_label(size[0], size[1], stereo)
    elif ratio:
        facts["picture"] = picture_from_ratio(ratio, name, stereo)
    elif stereo:
        facts["picture"] = "3D"
    facts["sound"] = sound or sound_from_name(name)
    return {k: v for k, v in facts.items() if v}
