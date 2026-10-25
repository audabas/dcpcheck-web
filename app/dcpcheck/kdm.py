"""Tell whether a KDM was made for a DCP.

dcpcheck can't decrypt a KDM: its content keys are encrypted for the
certificate of one server, and only that server can read them. But the
public part of a KDM says which composition (CPL) it unlocks, the ids of the
keys it carries, which server it is for and when it can be used. That is
enough to tell whether it was made for the version of the DCP on the disk.
"""

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

from .scanner import child, local, text, uuid_of

MAX_FILE = 1024 * 1024  # A KDM is a few tens of KB.
MAX_FILES = 2000        # Files read from one upload, ZIPs included.
MAX_DEPTH = 2           # A ZIP in a ZIP, as some distributors send.


class NotKdm(ValueError):
    pass


def unpack(name, data, depth=0, budget=None):
    """Return the files of an upload, (name, bytes), and the ones skipped,
    (name, reason). A ZIP is opened, as are the ZIPs it holds."""
    budget = budget if budget is not None else [MAX_FILES]
    if not data.startswith(b"PK\x03\x04"):
        budget[0] -= 1
        return [(name, data)], []
    if depth >= MAX_DEPTH:
        return [], [(name, "a ZIP inside a ZIP inside a ZIP")]
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        infos = z.infolist()
    except (zipfile.BadZipFile, OSError):
        return [], [(name, "damaged ZIP file")]
    files, skipped = [], []
    for info in infos:
        inner = name + " › " + info.filename
        base = info.filename.rsplit("/", 1)[-1]
        if info.is_dir() or info.filename.startswith("__MACOSX/") or base.startswith(".") or not base:
            continue
        if budget[0] <= 0:
            skipped.append((name, "too many files, the others were not read"))
            break
        if info.file_size > MAX_FILE and not base.lower().endswith(".zip"):
            budget[0] -= 1
            skipped.append((inner, "too large for a KDM"))
            continue
        try:
            with z.open(info) as f:
                content = f.read(MAX_FILE * 64 + 1)
        except RuntimeError:  # Encrypted entry
            budget[0] -= 1
            skipped.append((inner, "protected by a password"))
            continue
        except (zipfile.BadZipFile, OSError, EOFError, ValueError, NotImplementedError):
            budget[0] -= 1
            skipped.append((inner, "damaged in the ZIP"))
            continue
        more, more_skipped = unpack(inner, content, depth + 1, budget)
        files += more
        skipped += more_skipped
    return files, skipped


def timestamp(s):
    """Seconds since the epoch of an xs:dateTime, or None."""
    try:
        t = datetime.fromisoformat((s or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.timestamp() if t.tzinfo else None


def dn_fields(subject):
    """The attributes of a distinguished name such as
    "dnQualifier=8Kq\\+ZJ1n=,CN=SM.ws-1234.DOREMI,O=...", by lower-case name."""
    fields = {}
    for part in re.findall(r"(?:[^,\\]|\\.)+", subject or ""):
        name, _, value = part.partition("=")
        value = re.sub(r"\\(.)", r"\1", value.strip())
        fields.setdefault(name.strip().lower(), value)
    return fields


def parse_servers(spec):
    """Read KDM_SERVERS: "Screen 1=SM.ws-1234.DOREMI; Screen 2=..." gives
    [(name, value)]. A value is the CN or the dnQualifier of a server's
    certificate, with or without "CN=" or "dnQualifier=" before it. A name
    may come back, for a renewed certificate say, or be left out."""
    servers = []
    for entry in re.split(r"[;\n]", spec or ""):
        # The first "=" ends the name: a dnQualifier may end with "=".
        name, _, value = entry.partition("=")
        if not value.strip() or name.strip().lower() in ("cn", "dnqualifier"):
            name, value = "", entry
        value = re.sub(r"(?i)^\s*(cn|dnqualifier)\s*=", "", value).strip()
        if value:
            servers.append((name.strip() or value, value))
    return servers


def server_of(kdm, servers):
    """The name of the server of KDM_SERVERS the KDM was made for, or None."""
    for name, value in servers:
        if (kdm["recipient"] and value.casefold() == kdm["recipient"].casefold()) or value == kdm["dn_qualifier"]:
            return name
    return None


def parse(data):
    """Read the public part of a KDM. Raise NotKdm for any other file."""
    if len(data) > MAX_FILE:
        raise NotKdm("too large for a KDM")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise NotKdm("not an XML file") from None
    if local(root.tag) != "DCinemaSecurityMessage":
        raise NotKdm("an XML file but not a KDM")
    pub = child(root, "AuthenticatedPublic")
    ext = child(child(pub, "RequiredExtensions"), "KDMRequiredExtensions")
    if ext is None:
        raise NotKdm("a security message but not a KDM")
    subject = dn_fields(text(child(ext, "Recipient"), "X509SubjectName"))
    keys = []
    key_list = child(ext, "KeyIdList")
    for el in key_list.iter() if key_list is not None else []:
        if local(el.tag) == "KeyId" and (el.text or "").strip():
            keys.append(uuid_of(el.text))
    return {
        "message_id": uuid_of(text(pub, "MessageId")),
        "annotation": text(pub, "AnnotationText"),
        "issued": timestamp(text(pub, "IssueDate")),
        "cpl_id": uuid_of(text(ext, "CompositionPlaylistId")),
        "title": text(ext, "ContentTitleText"),
        "not_before": timestamp(text(ext, "ContentKeysNotValidBefore")),
        "not_after": timestamp(text(ext, "ContentKeysNotValidAfter")),
        "recipient": subject.get("cn"),
        "dn_qualifier": subject.get("dnqualifier"),
        "device": text(child(ext, "AuthorizedDeviceInfo"), "DeviceListDescription"),
        "key_ids": keys,
    }


def check(kdm, cpls, now, servers=()):
    """Compare a KDM with the CPLs of a DCP (see scanner.read_cpls), and
    with the servers of KDM_SERVERS when there are any.

    The verdict is the worst of: other (made for another CPL), vf (made
    for another CPL that plays encrypted assets of this DCP), server (made
    for a server that is not in the list), keys (some keys of the CPL are
    missing), expired, unknown (no valid dates), not_yet (not valid yet)
    and ok."""
    res = {k: v for k, v in kdm.items() if k != "key_ids"}
    res["keys"] = len(kdm["key_ids"])
    res["server"] = server_of(kdm, servers)
    have = set(kdm["key_ids"])
    cpl = next((c for c in cpls if c["id"] and c["id"] == kdm["cpl_id"]), None)
    if cpl is None:
        # A VF has a CPL of its own but plays the picture and sound of its
        # OV, so its KDM carries the keys of the OV's assets. It doesn't
        # play the OV's CPL, but it is what the server needs to play the VF.
        shared = {k for c in cpls for k in c["key_ids"] if k in have}
        if shared:
            res["verdict"] = "vf"
            res["shared"] = len(shared)
            res["validity"] = validity(kdm, now)
        else:
            res["verdict"] = "other"
        return res
    res["cpl_title"] = cpl["title"]
    res["needed"] = len(cpl["key_ids"])
    res["missing"] = sum(1 for k in cpl["key_ids"] if k not in have)
    if servers and res["server"] is None:
        res["verdict"] = "server"
    elif res["missing"]:
        res["verdict"] = "keys"
    else:
        res["verdict"] = validity(kdm, now)
    return res


def validity(kdm, now):
    """unknown (no valid dates), expired, not_yet (not valid yet) or ok."""
    if kdm["not_before"] is None or kdm["not_after"] is None:
        return "unknown"
    if now > kdm["not_after"]:
        return "expired"
    if now < kdm["not_before"]:
        return "not_yet"
    return "ok"
