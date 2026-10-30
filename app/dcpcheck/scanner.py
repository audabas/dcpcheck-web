"""Find DCPs under a directory and read a few facts from their CPL.

This is only used to show a summary in the UI (type, standard, picture,
duration, sound, languages, size, whether a KDM is needed). The actual
verification is done by DCP-o-matic.
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

# Names for the most common language tags, in CPLs (RFC 5646, "fr-FR") and in
# ISDCF names ("FR"). Other tags are shown as they are.
LANGUAGES = {
    "ar": "Arabic", "ca": "Catalan", "cs": "Czech", "da": "Danish", "de": "German",
    "el": "Greek", "en": "English", "es": "Spanish", "eu": "Basque", "fa": "Persian",
    "fi": "Finnish", "fr": "French", "he": "Hebrew", "hi": "Hindi", "hu": "Hungarian",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "nb": "Norwegian", "nl": "Dutch",
    "no": "Norwegian", "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "sv": "Swedish", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian", "zh": "Chinese",
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
    partial: bool = False  # MXF files but no ASSETMAP yet, see find_dcps()
    facts: dict = field(default_factory=dict)


def dcp_id(relpath):
    return hashlib.sha1(relpath.encode("utf-8", "surrogateescape")).hexdigest()[:12]


def is_dcp(path):
    return any(os.path.isfile(os.path.join(path, n)) for n in ASSETMAP_NAMES)


def is_mxf(name):
    """An MXF file, or one still arriving under a temporary name
    (j2c.mxf.filepart, .j2c.mxf.Ab12Cd from rsync...)."""
    name = name.lower()
    return name.endswith(".mxf") or ".mxf." in name


def has_mxf(entries):
    for e in entries:
        try:
            if is_mxf(e.name) and e.is_file(follow_symlinks=True):
                return True
        except OSError:
            continue
    return False


def find_dcps(root, max_depth=3):
    """Return the DCP folders under root, sorted by name.

    A folder with MXF files but no ASSETMAP is returned too, as partial:
    many copies write the ASSETMAP last, or under a temporary name."""
    found = []

    def walk(path, depth):
        if is_dcp(path):
            found.append((path, False))
            return
        try:
            entries = sorted(os.scandir(path), key=lambda e: e.name.lower())
        except OSError:
            return
        if has_mxf(entries):
            found.append((path, True))
            return
        if depth >= max_depth:
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
    for path, partial in found:
        rel = os.path.relpath(path, root)
        if rel == ".":
            rel = os.path.basename(os.path.normpath(root))
        dcps.append(describe(path, rel, partial))
    dcps.sort(key=lambda d: d.name.lower())
    return dcps


def describe(path, relpath, partial=False):
    d = Dcp(id=dcp_id(relpath), name=os.path.basename(os.path.normpath(path)), relpath=relpath, path=path, partial=partial)
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


def uuid_of(s):
    """A UUID without its urn:uuid: prefix, in lower case."""
    s = (s or "").strip().lower()
    return s[len("urn:uuid:"):] if s.startswith("urn:uuid:") else s


def find_cpls(path):
    return find_xml(path, "CompositionPlaylist")


def read_cpls(path):
    """The CPLs of a folder: their id, their title and the ids of the keys
    their encrypted assets need."""
    out = []
    for cpl in find_cpls(path):
        reels = child(cpl, "ReelList")
        keys = []
        for el in reels.iter() if reels is not None else []:
            if local(el.tag) == "KeyId" and (el.text or "").strip() and uuid_of(el.text) not in keys:
                keys.append(uuid_of(el.text))
        out.append({"id": uuid_of(text(cpl, "Id")), "title": text(cpl, "ContentTitleText"), "key_ids": keys})
    return out


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


def encrypted(cpls):
    """True if a CPL lists an encrypted asset, which only plays with a KDM.

    SMPTE and Interop CPLs both give each encrypted reel asset a <KeyId>."""
    for cpl in cpls:
        reels = child(cpl, "ReelList")
        for el in reels.iter() if reels is not None else []:
            if local(el.tag) == "KeyId" and (el.text or "").strip():
                return True
    return False


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


# SMPTE ST 429-18 data essence of Immersive Audio Bitstream (IAB) tracks.
IAB_DATA_TYPE = "060e2b34.04010105.0e090604"


def sound_extras(cpl, cfg):
    """What a CPL adds to its main sound: an IAB track, and the hearing
    impaired (HI) or visually impaired narration (VI) channels its
    MainSoundConfiguration lists."""
    extras = []
    reels = child(cpl, "ReelList")
    for el in reels.iter() if reels is not None else []:
        if local(el.tag) == "AuxData" and IAB_DATA_TYPE in (text(el, "DataType") or "").lower():
            extras.append("IAB")
            break
    channels = (cfg or "").partition("/")[2].split(",")
    extras += [label for code, label in (("HI", "HI"), ("VIN", "VI")) if code in channels]
    return extras


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


def language_label(tag):
    """'fr-FR' -> 'French (fr-FR)', 'FR' -> 'French (FR)'."""
    name = LANGUAGES.get(tag.split("-")[0].lower())
    return f"{name} ({tag})" if name else tag


def cpl_languages(cpls):
    """The language tags the CPLs give their sound, subtitles and closed
    captions, in order of appearance. A track listed without a language
    shows up as an empty list."""
    found = {}

    def add(kind, tags):
        seen = found.setdefault(kind, [])
        seen.extend(t for t in tags if t not in seen)

    for cpl in cpls:
        reels = child(cpl, "ReelList")
        for el in reels.iter() if reels is not None else []:
            kind = {"MainSound": "audio", "MainSubtitle": "subtitles", "MainClosedCaption": "captions"}.get(local(el.tag))
            if kind:
                lang = text(el, "Language")
                add(kind, [lang] if lang else [])
            elif local(el.tag) == "MainSubtitleLanguageList":  # SMPTE 429-16, required by Bv2.1
                add("subtitles", (el.text or "").split())
            elif local(el.tag) == "SoundfieldGroupLabelSubDescriptor":
                # Bv2.1 gives the spoken language in the MCA labels of the
                # sound rather than in a <Language> of the MainSound.
                lang = text(el, "RFC5646SpokenLanguage")
                add("audio", [lang] if lang else [])
    return found


def languages_from_name(name):
    """The languages of an ISDCF name: ..._F_FR-EN_FR-TP_... is French sound
    with English subtitles. XX means none, lower case means burned in and
    CCAP adds closed captions."""
    parts = name.split("_")
    for i, part in enumerate(parts[1:-1], 1):
        if not re.fullmatch(r"[FSC](-\d{2,3})?", part):
            continue
        m = re.fullmatch(r"([A-Za-z]{2,3})((?:-[A-Za-z]{2,3})*?)(-[COco]CAP)?", parts[i + 1])
        if not m:
            return None
        audio, subs = m.group(1), m.group(2).split("-")[1:]
        out = {"audio": [] if audio.upper() == "XX" else [audio.upper()],
               "subtitles": [t.upper() for t in subs if t.upper() != "XX"]}
        out["burned_in"] = any(t.islower() for t in subs)
        out["captions"] = bool(m.group(3))
        return out
    return None


def read_languages(cpls, names):
    """Labels for the sound, subtitle and closed caption languages, from the
    CPLs or, when they do not say, from the ISDCF name of the DCP. Each CPL
    is read on its own, its title first, then the labels of all of them are
    put together."""
    per_cpl = [cpl_language_labels([cpl], (text(cpl, "ContentTitleText"),) + tuple(names)) for cpl in cpls]
    return combine_languages(per_cpl or [cpl_language_labels([], names)])


def cpl_language_labels(cpls, names):
    langs = cpl_languages(cpls)
    isdcf = next((x for x in map(languages_from_name, filter(None, names)) if x), {})
    out = {}
    for kind, key in (("audio", "audio_language"), ("subtitles", "subtitles"), ("captions", "captions")):
        tags = langs.get(kind)
        if tags:
            out[key] = [language_label(t) for t in tags]
        elif kind == "captions":
            if tags is not None or isdcf.get("captions"):
                out[key] = ["Language not given"]
        elif isdcf.get(kind):
            burned = " · burned in" if kind == "subtitles" and isdcf["burned_in"] else ""
            out[key] = [language_label(t) + burned for t in isdcf[kind]]
        elif tags is not None:  # listed in the CPL, without a language
            out[key] = ["Language not given"]
        elif kind in isdcf or (kind == "subtitles" and cpls):
            out[key] = ["None"]
    return out


def combine_languages(labels):
    """One label per kind for several CPLs: the languages of all of them,
    "None" only when none has any."""
    facts = {}
    for one in labels:
        for key, items in one.items():
            seen = facts.setdefault(key, [])
            seen.extend(x for x in items if x not in seen)
    for key, items in facts.items():
        if len(items) > 1 and "None" in items:
            items.remove("None")
        facts[key] = ", ".join(items)
    return facts


def read_facts(path, name):
    cpls = sorted(find_cpls(path), key=lambda c: text(c, "ContentTitleText") or "")
    cpl = cpls[0] if cpls else None
    facts = {"standard": standard_of(path, cpl)}
    if cpl is None:
        return facts

    facts["title"] = text(cpl, "ContentTitleText")
    kind = (text(cpl, "ContentKind") or "").strip()
    facts["kind"] = KINDS.get(kind.lower(), kind.capitalize() or None)
    versions = [cpl_summary(c, name) for c in cpls]
    # Several CPLs (2D and 3D, original and dubbed version...) can share a
    # folder: each fact lists the values of all of them.
    for key in ("frame_rate", "duration", "picture", "sound"):
        values = []
        for v in versions:
            if v.get(key) and v[key] not in values:
                values.append(v[key])
        facts[key] = ", ".join(values)
    facts.update(read_languages(cpls, (name,)))
    if len(cpls) > 1:
        facts["cpls"] = len(cpls)
        for v, c in zip(versions, cpls):
            v.update(read_languages([c], (name,)))
        facts["versions"] = [{k: x for k, x in v.items() if x} for v in versions]
    facts = {k: v for k, v in facts.items() if v}
    facts["kdm"] = encrypted(cpls)
    return facts


def cpl_summary(cpl, name):
    """Title, frame rate, duration, picture and sound of one CPL."""
    out = {"title": text(cpl, "ContentTitleText")}
    total = 0.0
    size = None
    ratio = None  # Interop CPLs only give an aspect ratio
    stereo = False
    sound = None
    config = None
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
            out.setdefault("frame_rate", f"{fps:g} fps")
        meta = child(assets, "CompositionMetadataAsset")
        if meta is not None:
            config = config or text(meta, "MainSoundConfiguration")
            sound = sound or sound_from_config(config)
            area = child(meta, "MainPictureStoredArea")
            if area is None:
                area = child(meta, "MainPictureActiveArea")
            if area is not None and size is None:
                try:
                    size = (int(text(area, "Width")), int(text(area, "Height")))
                except (TypeError, ValueError):
                    pass

    if total:
        out["duration"] = fmt_duration(total)
    if size:
        out["picture"] = picture_label(size[0], size[1], stereo)
    elif ratio:
        out["picture"] = picture_from_ratio(ratio, out["title"] or name, stereo)
    elif stereo:
        out["picture"] = "3D"
    sound = sound or sound_from_name(out["title"] or "") or sound_from_name(name)
    if sound:
        out["sound"] = " · ".join([sound] + [x for x in sound_extras(cpl, config) if x not in sound])
    return out
