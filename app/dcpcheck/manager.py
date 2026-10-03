"""Keeps the list of DCPs, runs verifications one after the other, and
remembers their results in the data directory."""

import codecs
import json
import os
import shutil
import signal
import subprocess
import threading
import time
from collections import deque

from . import scanner
from .output import OutputParser, status_of


def measures(d):
    return d.size, d.written, d.mtime


class Job:
    def __init__(self, dcp, auto=False):
        self.dcp = dcp
        self.auto = auto  # started by itself at the end of a copy
        self.state = "queued"
        self.queued_at = time.time()
        self.started_at = None
        self.proc = None
        self.parser = OutputParser()
        self.cancelled = False

    def public(self):
        p = self.parser
        return {
            "state": self.state,
            "progress": round(p.progress, 1),
            "stage": p.stage,
            "started_at": self.started_at,
            "auto": self.auto,
            "notes_so_far": len(p.notes),
        }


class Copy:
    """A DCP folder that is still being written to, e.g. copied to the NAS."""

    WINDOW = 15  # seconds of samples the speed is averaged over

    def __init__(self, now):
        self.since = now
        self.last_change = now
        self.samples = deque()
        self.expected = None  # total size announced by the PKL, once it has arrived
        self.grew = False     # data was seen arriving, not only a change of dates

    def add(self, now, d, changed, grew):
        if changed:
            self.last_change = now
        self.grew = self.grew or grew
        self.samples.append((now, d.written))
        while len(self.samples) > 2 and now - self.samples[0][0] > self.WINDOW:
            self.samples.popleft()

    def speed(self):
        if len(self.samples) < 2:
            return None
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        return max(0, round((b1 - b0) / (t1 - t0))) if t1 > t0 else None

    def complete(self):
        # A little slack: compressed filesystems store the small XML files in fewer bytes.
        return bool(self.expected and self.samples and self.samples[-1][1] >= self.expected * 0.999)

    def public(self):
        return {
            "since": self.since,
            "speed": self.speed(),
            "copied": self.samples[-1][1] if self.samples else 0,
            "expected": self.expected,
        }


class Manager:
    def __init__(self, config):
        self.cfg = config
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)
        self.dcps = {}
        self.scanned_at = None
        self.scanning = False
        self.jobs = {}
        self.queue = deque()
        self.copies = {}  # DCP id -> Copy, for the folders still growing
        os.makedirs(self.path("logs"), exist_ok=True)
        os.makedirs(self.path("reports"), exist_ok=True)
        os.makedirs(self.path("home"), exist_ok=True)
        self.results = self.load_results()

    # ---- persistence -----------------------------------------------------

    def path(self, *parts):
        return os.path.join(self.cfg.data_dir, *parts)

    def load_results(self):
        try:
            with open(self.path("results.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_results(self):
        tmp = self.path("results.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.results, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path("results.json"))

    # ---- scanning --------------------------------------------------------

    def rescan(self):
        with self.lock:
            if self.scanning:
                return
            self.scanning = True
        try:
            started = time.time()
            found = scanner.find_dcps(self.cfg.dcp_root, self.cfg.scan_depth)
            now = time.time()
            with self.lock:
                old = self.dcps
                self.dcps = {d.id: d for d in found}
                for d in found:
                    prev = old.get(d.id)
                    if prev is None:
                        # First time we see it: a copy may be under way if it was just written to.
                        fresh = d.mtime > started - self.cfg.copy_quiet
                        self.track(d, now, fresh, fresh)
                    else:
                        self.track(d, now, measures(d) != measures(prev), d.written > prev.written)
                for dcp_id in list(self.copies):
                    if dcp_id not in self.dcps:
                        del self.copies[dcp_id]
                self.scanned_at = now
        finally:
            with self.lock:
                self.scanning = False

    # ---- copies ----------------------------------------------------------

    def track(self, d, now, changed, grew):
        """Note a new measure of d: changed tells whether it differs from the
        previous one, grew whether more bytes were written."""
        c = self.copies.get(d.id)
        if c is None:
            if not changed:
                return
            c = self.copies[d.id] = Copy(now)
        c.add(now, d, changed, grew)

    def is_copying(self, dcp_id):
        with self.lock:
            return dcp_id in self.copies

    def watch_copies(self):
        """Measure the folders being copied every few seconds until they stop changing."""
        while True:
            time.sleep(self.cfg.copy_poll)
            with self.lock:
                targets = [self.dcps[i] for i in self.copies if i in self.dcps]
            for d in targets:
                try:
                    self.remeasure(d)
                except Exception as e:  # Never let the watcher die.
                    print(f"warning: could not measure {d.path}: {e}", flush=True)

    def remeasure(self, d):
        size, written, mtime = scanner.measure(d.path)
        with self.lock:
            c = self.copies.get(d.id)
            need_expected = c is not None and c.expected is None
        expected = scanner.expected_size(d.path) if need_expected else None
        now = time.time()
        with self.lock:
            c = self.copies.get(d.id)
            if c is None or self.dcps.get(d.id) is not d:
                return
            changed = (size, written, mtime) != measures(d)
            grew = written > d.written
            d.size, d.written, d.mtime = size, written, mtime
            c.expected = c.expected or expected
            self.track(d, now, changed, grew)
            if now - c.last_change < self.cfg.copy_quiet:
                return
            # Only verify what we saw arriving in full: not a folder whose dates
            # merely changed, nor a copy that stopped half-way.
            auto = self.cfg.auto_verify and c.grew and c.complete()
        # The copy is over. Its CPL may have arrived after the scan read the facts.
        try:
            facts = scanner.read_facts(d.path, d.name)
        except Exception:
            facts = d.facts
        with self.lock:
            d.facts = facts
            self.copies.pop(d.id, None)
        if auto:
            self.verify(d.id, auto=True)

    def start(self):
        threading.Thread(target=self.rescan, daemon=True).start()
        for _ in range(max(1, self.cfg.max_parallel)):
            threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.watch_copies, daemon=True).start()
        if self.cfg.scan_interval > 0:
            threading.Thread(target=self.periodic_scan, daemon=True).start()

    def periodic_scan(self):
        while True:
            time.sleep(self.cfg.scan_interval)
            self.rescan()

    # ---- views -----------------------------------------------------------

    def summary(self, d, with_notes=False):
        res = self.results.get(d.relpath)
        if res and not with_notes:
            res = {k: v for k, v in res.items() if k != "notes"}
        job = self.jobs.get(d.id)
        copy = self.copies.get(d.id)
        return {
            "id": d.id,
            "name": d.name,
            "relpath": d.relpath,
            "size": d.size,
            "mtime": d.mtime,
            "facts": d.facts,
            "job": job.public() if job else None,
            "copy": copy.public() if copy else None,
            "queue_position": self.queue.index(d.id) + 1 if d.id in self.queue else None,
            "result": res,
        }

    def state(self):
        with self.lock:
            return {
                "root": self.cfg.dcp_root_label,
                "scanned_at": self.scanned_at,
                "scanning": self.scanning,
                "now": time.time(),
                "verifier": self.cfg.verifier_version,
                "auto_verify": self.cfg.auto_verify,
                "dcps": [self.summary(d) for d in self.dcps.values()],
            }

    def detail(self, dcp_id):
        with self.lock:
            d = self.dcps.get(dcp_id)
            return self.summary(d, with_notes=True) if d else None

    def report_path(self, dcp_id):
        p = self.path("reports", dcp_id + ".html")
        return p if os.path.isfile(p) else None

    def log_path(self, dcp_id):
        with self.lock:
            job = self.jobs.get(dcp_id)
        live = self.path("logs", dcp_id + ".running.log")
        if job and os.path.isfile(live):
            return live
        p = self.path("logs", dcp_id + ".log")
        return p if os.path.isfile(p) else None

    # ---- jobs ------------------------------------------------------------

    def verify(self, dcp_id, auto=False):
        with self.lock:
            d = self.dcps.get(dcp_id)
            if d is None or dcp_id in self.copies:
                return False
            if dcp_id not in self.jobs:
                self.jobs[dcp_id] = Job(d, auto)
                self.queue.append(dcp_id)
                self.wake.notify()
            return True

    def cancel(self, dcp_id):
        with self.lock:
            job = self.jobs.get(dcp_id)
            if job is None:
                return False
            job.cancelled = True
            if job.state == "queued":
                self.queue.remove(dcp_id)
                del self.jobs[dcp_id]
                return True
            proc = job.proc
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            threading.Timer(5, self._kill, args=(proc,)).start()
        return True

    @staticmethod
    def _kill(proc):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def worker(self):
        while True:
            with self.lock:
                while not self.queue:
                    self.wake.wait()
                job = self.jobs[self.queue.popleft()]
                job.state = "running"
                job.started_at = time.time()
            try:
                self.run(job)
            except Exception as e:  # Never let a worker thread die.
                self.record(job, None, failure=f"dcpcheck could not run the verifier: {e}")
            finally:
                with self.lock:
                    self.jobs.pop(job.dcp.id, None)

    def command(self, dcp, report):
        cmd = [self.cfg.verifier] + list(self.cfg.verify_args)
        if report:
            cmd += ["-o", report]
        cmd.append(dcp.path)
        if shutil.which("stdbuf"):
            cmd = ["stdbuf", "-o0", "-e0"] + cmd
        return cmd

    def run(self, job):
        dcp = job.dcp
        log_live = self.path("logs", dcp.id + ".running.log")
        report_tmp = self.path("reports", dcp.id + ".running.html") if self.cfg.html_report else None
        env = dict(os.environ, HOME=self.path("home"), LC_ALL="C.UTF-8")

        cmd = self.command(dcp, report_tmp)
        with open(log_live, "w", encoding="utf-8") as log:
            log.write("$ " + " ".join(cmd) + "\n\n")
            log.flush()
            with self.lock:
                if job.cancelled:
                    return
                job.proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    env=env,
                    start_new_session=True,
                )
            fd = job.proc.stdout.fileno()
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            while True:
                chunk = os.read(fd, 8192)
                if not chunk:
                    break
                with self.lock:
                    lines = job.parser.feed(decoder.decode(chunk))
                if lines:
                    log.write("\n".join(lines) + "\n")
                    log.flush()
            rc = job.proc.wait()
            lines = job.parser.finish()
            if lines:
                log.write("\n".join(lines) + "\n")
            log.write(f"\n[exit code {rc}]\n")

        if job.cancelled:
            for p in (log_live, report_tmp):
                if p and os.path.exists(p):
                    os.remove(p)
            return

        os.replace(log_live, self.path("logs", dcp.id + ".log"))
        has_report = bool(report_tmp and os.path.isfile(report_tmp) and os.path.getsize(report_tmp))
        if has_report:
            os.replace(report_tmp, self.path("reports", dcp.id + ".html"))
        elif report_tmp and os.path.exists(report_tmp):
            os.remove(report_tmp)

        failure = None
        notes = job.parser.notes
        if rc != 0 and not notes and not job.parser.said_clean:
            failure = f"The verifier stopped with exit code {rc} without reporting any result. See the raw output."
        self.record(job, rc, failure=failure, has_report=has_report)

    def record(self, job, rc, failure=None, has_report=False):
        now = time.time()
        notes = job.parser.notes
        result = {
            "finished_at": now,
            "started_at": job.started_at,
            "elapsed": round(now - (job.started_at or now)),
            "status": "failed" if failure else status_of(notes),
            "notes": notes,
            "counts": {s: sum(1 for n in notes if n["sev"] == s) for s in ("error", "bv21", "warn")},
            "exit_code": rc,
            "failure": failure,
            "report": has_report,
            "auto": job.auto,
            "verifier": self.cfg.verifier_version,
        }
        with self.lock:
            self.results[job.dcp.relpath] = result
            self.save_results()
