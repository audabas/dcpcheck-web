"""Parse what dcpomatic2_verify_cli prints.

The verifier prints three kinds of things on stdout:

* stage lines, e.g. "Checking picture asset hash: /dcp/Film/j2c_abc.mxf"
* a progress bar redrawn with carriage returns, e.g. "[=====>    ] 42%"
* at the end, one line per note, e.g. "Error: The hash of ... is incorrect."

Errors are then sorted into critical ones, which may stop the DCP from being
ingested or played, and minor ones (XML schema, metadata), which
a server should not mind. See classify().

The exact wording changes between versions, so everything here is tolerant:
anything we do not understand is still kept in the raw log shown in the UI.
"""

import os
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
PROGRESS = re.compile(r"\[[=> #.\-]*\]\s*(\d{1,3}(?:\.\d+)?)\s*%")
PERCENT_ONLY = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*%\s*$")
NOTE = re.compile(
    r"^\s*(?:[-*]\s*)?(?P<sev>error|bv\s*2\.1\s*error|bv2\.1|warning|ok)\s*:\s*(?P<msg>.+)$",
    re.IGNORECASE,
)
CODE = re.compile(r"\b([A-Z][A-Z0-9]+(?:_[A-Z0-9]+){1,})\b")
FILE = re.compile(r"([^\s:'\"()<>]+\.(?:mxf|xml|ttf|otf|png))\b", re.IGNORECASE)
CLEAN = re.compile(r"^\s*(?:no (?:errors|problems|issues) found|dcp is ok)\b", re.IGNORECASE)

SEVERITIES = {"error": "error", "warning": "warn", "ok": "ok"}
LEVELS = ("error", "minor", "bv21", "warn")

# The verifier prints no codes, only libdcp's messages (src/verify.cc,
# note_to_string). These are the errors that should not stop a DCP from
# playing: they are told apart by their wording. Any other error, including
# those of future versions, stays critical.
MINOR_ERRORS = [
    # Schema problems found by Xerces, e.g. an element in the wrong place.
    # Files that cannot be read at all also give a critical FAILED_READ.
    ("INVALID_XML", r"^An XML file is badly formed:"),
    ("INVALID_CONTENT_KIND", r"^<ContentKind> has an invalid value"),
    ("INVALID_MAIN_PICTURE_ACTIVE_AREA", r"^<MainPictureActivea?Area> has an invalid value"),
    ("INVALID_MAIN_SOUND_CONFIGURATION", r"^<MainSoundConfiguration> has an invalid value"),
    ("MISSING_CPL_CONTENT_VERSION", r"^The CPL .* has no <ContentVersion> tag"),
    ("UNEXPECTED_DURATION", r"^There is an? <Duration> node inside a <MainMarkers>"),
    ("UNEXPECTED_ENTRY_POINT", r"^There is an? <EntryPoint> node inside a <MainMarkers>"),
    # Subtitle and closed caption errors stay critical: a screening of a
    # subtitled film can't go on without its subtitles.
]
MINOR_ERRORS = [(code, re.compile(rx)) for code, rx in MINOR_ERRORS]
# Xerces' words for a file that is not even well-formed XML.
NOT_WELL_FORMED = re.compile(
    r"expected end of|unterminated|unexpected end|invalid document structure|not well-formed|no root element",
    re.IGNORECASE,
)


def severity(word):
    w = re.sub(r"\s+", "", word.lower())
    if w.startswith("bv"):
        return "bv21"
    return SEVERITIES[w]


def parse_note(line):
    """Return a note dict if the line is a verification note, else None."""
    m = NOTE.match(line)
    if not m:
        return None
    msg = m.group("msg").strip()
    note = {"sev": severity(m.group("sev")), "msg": msg}
    code = CODE.search(msg)
    if code:
        note["code"] = code.group(1)
    f = FILE.search(msg)
    if f:
        note["file"] = os.path.basename(f.group(1))
    return classify(note)


def classify(note):
    """Turn an error into a minor one ("minor") when it should not stop the
    DCP from playing. Works on stored notes too, so old results benefit."""
    if note["sev"] not in ("error", "minor"):
        return note
    note["sev"] = "error"
    for code, rx in MINOR_ERRORS:
        if rx.search(note["msg"]):
            if code != "INVALID_XML" or not NOT_WELL_FORMED.search(note["msg"]):
                note["sev"] = "minor"
            break
    return note


def short_stage(line):
    """'Checking picture asset hash: /dcp/x/j2c.mxf' -> '... hash: j2c.mxf'."""
    line = line.strip()
    if ": /" in line:
        label, _, path = line.partition(": ")
        return f"{label}: {os.path.basename(path.rstrip('/'))}"
    return line


class OutputParser:
    """Feed it chunks of stdout; it keeps progress, current stage and notes."""

    def __init__(self):
        self.buffer = ""
        self.progress = 0.0
        self.stage = None
        self.notes = []
        self.said_clean = False

    def feed(self, chunk):
        """Parse a chunk; return the lines worth keeping in the log (no progress bars)."""
        self.buffer += ANSI.sub("", chunk)
        *segments, self.buffer = re.split(r"[\r\n]", self.buffer)
        kept = [seg for seg in segments if self.segment(seg)]
        # A progress bar may sit in the buffer without a terminator for a while.
        m = PROGRESS.search(self.buffer)
        if m:
            self.progress = min(100.0, float(m.group(1)))
        return kept

    def finish(self):
        kept = []
        if self.buffer and self.segment(self.buffer):
            kept.append(self.buffer)
        self.buffer = ""
        return kept

    def segment(self, seg):
        """Handle one line; return False if it was only a progress update."""
        if not seg.strip():
            return False
        m = PROGRESS.search(seg) or PERCENT_ONLY.match(seg)
        if m:
            self.progress = min(100.0, float(m.group(1)))
            return False
        note = parse_note(seg)
        if note:
            if note["sev"] != "ok":
                self.notes.append(note)
            return True
        if CLEAN.match(seg):
            self.said_clean = True
            return True
        stage = short_stage(seg)
        if stage != self.stage:
            self.stage = stage
            self.progress = 0.0
        return True


def status_of(notes):
    sevs = {n["sev"] for n in notes}
    for s in LEVELS:
        if s in sevs:
            return s
    return "ok"


def counts_of(notes):
    return {s: sum(1 for n in notes if n["sev"] == s) for s in LEVELS}


def reclassify(result):
    """Apply the current rules to a stored result, made by an older dcpcheck."""
    notes = result.get("notes") or []
    for n in notes:
        classify(n)
    result["counts"] = counts_of(notes)
    if result.get("status") != "failed":
        result["status"] = status_of(notes)
    return result
