"""Parse what dcpomatic2_verify_cli prints.

The verifier prints three kinds of things on stdout:

* stage lines, e.g. "Checking picture asset hash: /dcp/Film/j2c_abc.mxf"
* a progress bar redrawn with carriage returns, e.g. "[=====>    ] 42%"
* at the end, one line per note, e.g. "Error: The hash of ... is incorrect."

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
    for s in ("error", "bv21", "warn"):
        if s in sevs:
            return s
    return "ok"
