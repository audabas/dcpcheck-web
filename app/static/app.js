'use strict';

const STATUS = {
  ok: { label: 'OK' },
  warn: { label: 'OK' },
  bv21: { label: 'OK' },
  minor: { label: 'Minor errors' },
  error: { label: 'Critical errors' },
  failed: { label: 'Verifier failed' },
  never: { label: 'Never verified' },
  running: { label: 'Running' },
  queued: { label: 'Queued' },
  copying: { label: 'Copying' }
};
// Without errors a DCP is OK; its Bv2.1 issues and warnings only show as flags.
const PASSED = { ok: 1, bv21: 1, warn: 1 };
// Statuses that show those flags.
const FLAGGED = { ok: 1, bv21: 1, warn: 1, minor: 1 };
// For sorting by status, problems first.
const STATUS_RANK = ['copying', 'running', 'queued', 'failed', 'error', 'minor', 'never', 'bv21', 'warn', 'ok'];
const SORTS = {
  name: { label: 'Name', order: ['A → Z', 'Z → A'] },
  size: { label: 'Size', order: ['Largest first', 'Smallest first'] },
  status: { label: 'Status', order: ['Problems first', 'OK first'] },
  date: { label: 'Last updated', order: ['Newest first', 'Oldest first'] }
};
const SEV = {
  error: { label: 'Critical', title: 'May stop the DCP from being ingested or played' },
  minor: { label: 'Minor error', title: 'An error in the XML or the metadata that should not stop the DCP from playing' },
  bv21: { label: 'Bv2.1', title: 'Not compliant with the ISDCF Bv2.1 recommendations' },
  warn: { label: 'Warning', title: 'Worth checking, should not block playback' }
};
// Order of the notes: errors first. Bv2.1 issues and warnings come last, folded.
const SEV_ORDER = { error: 0, minor: 1, bv21: 2, warn: 3 };
const FOLDED = { bv21: 1, warn: 1 };
// Verifications the server started by itself, and why.
const AUTO_STARTED = { copy: 'Started by itself at the end of the copy.', new: 'Started by itself for this new DCP.' };
const AUTO_RESULT = { copy: 'started after the copy', new: 'started for a new DCP' };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const NOTE_PAGE = 200;
// What a checked KDM is, best first.
const KDM_VERDICT = {
  ok: { label: 'OK', cls: 'ok' },
  not_yet: { label: 'Not valid yet', cls: 'warn' },
  unknown: { label: 'No valid dates', cls: 'warn' },
  expired: { label: 'Expired', cls: 'error' },
  keys: { label: 'Keys missing', cls: 'error' },
  server: { label: 'Not your server', cls: 'error' },
  other: { label: 'Not for this DCP', cls: 'error' }
};
const KDM_ORDER = Object.keys(KDM_VERDICT);

const ui = {
  state: null,
  selected: load('selected'),
  filter: 'all',
  showAll: false,
  showFolded: false, // Bv2.1 issues and warnings unfolded in the "All" view
  sort: SORTS[load('sort')] ? load('sort') : 'name',
  reverse: load('reverse') === '1',
  detail: null,      // full detail (with notes) of the selected DCP
  detailKey: null,   // what that detail was fetched for
  kdm: {},           // DCP id -> KDMs checked against it in this page
  kdmTarget: null,   // DCP the file picker was opened for
  showOtherKdms: false, // KDMs made for other DCPs unfolded
  clockSkew: 0
};

function load(k) { try { return localStorage.getItem('dcpcheck.' + k); } catch (e) { return null; } }
function save(k, v) { try { localStorage.setItem('dcpcheck.' + k, v); } catch (e) { /* private mode */ } }

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}
function pad(n) { return (n < 10 ? '0' : '') + n; }
function fmtDate(ts) {
  const d = new Date(ts * 1000);
  return d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear() + ', ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}
function fmtDay(ts) {
  const d = new Date(ts * 1000);
  return d.getDate() + ' ' + MONTHS[d.getMonth()] + ' ' + d.getFullYear();
}
function fmtDur(s) {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (h) return h + 'h ' + pad(m) + 'm';
  return m ? m + 'm ' + pad(sec) + 's' : sec + 's';
}
function fmtLeft(s) {
  if (s < 60) return 'less than a minute left';
  const m = Math.round(s / 60);
  return 'about ' + (m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + pad(m % 60) + ' min') + ' left';
}
function fmtSize(b) {
  if (!b) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  while (b >= 1000 && i < units.length - 1) { b /= 1000; i++; }
  return (i >= 3 ? b.toFixed(1) : Math.round(b)) + ' ' + units[i];
}
function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ui.clockSkew - ts);
  if (s < 45) return 'just now';
  if (s < 90) return '1 min ago';
  if (s < 3600) return Math.round(s / 60) + ' min ago';
  if (s < 5400) return '1 h ago';
  if (s < 86400) return Math.round(s / 3600) + ' h ago';
  return 'on ' + fmtDate(ts);
}

function fmtSpeed(b) {
  return b == null ? 'Measuring…' : fmtSize(b).replace('—', '0 B') + '/s';
}

// Share of the copy done, once the PKL has told the final size.
function copyPct(d) {
  const c = d.copy;
  return c && c.expected ? Math.min(100, Math.floor(c.copied / c.expected * 100)) : null;
}

function statusOf(d) {
  if (d.job) return d.job.state === 'running' ? 'running' : 'queued';
  if (d.copy) return 'copying';
  return d.result ? d.result.status : 'never';
}
function statusLabel(d) {
  const st = statusOf(d);
  if (st === 'running') return 'Running · ' + Math.floor(d.job.progress) + '%';
  if (st === 'queued') return 'Queued' + (d.queue_position ? ' · #' + d.queue_position : '');
  if (st === 'copying' && copyPct(d) != null) return 'Copying · ' + copyPct(d) + '%';
  return STATUS[st].label;
}
function plural(n, one, many) { return n + ' ' + (n === 1 ? one : many); }
function flagsHtml(d) {
  const c = (d.result && d.result.counts) || {};
  let html = '';
  if (c.bv21) html += `<span class="flag bv21" title="${esc(plural(c.bv21, 'Bv2.1 issue', 'Bv2.1 issues'))}">${c.bv21} Bv2.1</span>`;
  if (c.warn) html += `<span class="flag warn" title="${esc(plural(c.warn, 'warning', 'warnings'))}">${c.warn} warn.</span>`;
  return html;
}
function kdmHtml(d) {
  return d.facts && d.facts.kdm ? `<span class="flag kdm" title="Encrypted: plays only with a KDM">${ICON_KEY}KDM</span>` : '';
}
function statusHtml(d) {
  const st = statusOf(d);
  const cls = PASSED[st] ? 'ok' : st;
  const live = st === 'running' || st === 'copying';
  return `<span class="status c-${cls}"><span class="dot${live ? ' pulse' : ''}"></span>${esc(statusLabel(d))}</span>${FLAGGED[st] ? flagsHtml(d) : ''}`;
}

function sortedDcps(list) {
  const name = (a, b) => a.relpath.localeCompare(b.relpath, undefined, { numeric: true, sensitivity: 'base' });
  const by = {
    name: name,
    size: (a, b) => b.size - a.size,
    status: (a, b) => STATUS_RANK.indexOf(statusOf(a)) - STATUS_RANK.indexOf(statusOf(b)),
    date: (a, b) => b.mtime - a.mtime
  }[ui.sort];
  const dir = ui.reverse ? -1 : 1;
  return list.slice().sort((a, b) => dir * by(a, b) || name(a, b));
}

async function api(path, method) {
  const opts = method === 'POST' ? { method: 'POST', headers: { 'X-Dcpcheck': '1' } } : { cache: 'no-store' };
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(r.status + ' ' + r.statusText);
  return r.json();
}

// ---- rendering -----------------------------------------------------------

function renderHeader(s) {
  document.getElementById('root').textContent = s.root;
  document.getElementById('scanned').textContent = s.scanning ? 'Scanning…' : (s.scanned_at ? 'Scanned ' + ago(s.scanned_at) : '');
  document.getElementById('count').textContent = s.dcps.length + (s.dcps.length === 1 ? ' folder' : ' folders');
  document.getElementById('version').textContent = s.verifier ? ' ' + s.verifier : '';
  document.getElementById('rescan').disabled = !!s.scanning;
}

function rowClass(d) {
  return 'row' + (d.id === ui.selected ? ' selected' : '');
}

function rowHtml(d) {
  const st = statusOf(d);
  const sel = d.id === ui.selected;
  const running = st === 'running';
  const busy = !!d.job;
  let line;
  if (running) line = 'Verification in progress';
  else if (st === 'queued') line = 'Waiting for the current verification';
  else if (st === 'copying') line = 'Still arriving on the disk';
  else if (d.result && ui.sort !== 'date') line = 'Verified ' + fmtDate(d.result.finished_at);
  else line = 'Updated ' + fmtDate(d.mtime);
  // A verified folder is re-run from its detail, not from the list.
  let side = '';
  if (st === 'copying') {
    side = `<span class="copying" title="Copy in progress: the folder is still growing">${ICON_SPIN}<span class="mono">${esc(fmtSpeed(d.copy.speed))}</span></span>`;
  } else if (busy) {
    side = `<button class="btn btn-sec" type="button" data-key="verify-${esc(d.id)}" disabled>${running ? 'Running' : 'Queued'}</button>`;
  } else if (!d.result) {
    side = `<button class="btn btn-sec" type="button" data-verify="${esc(d.id)}" data-key="verify-${esc(d.id)}" aria-label="${esc('Verify ' + d.name)}">Verify</button>`;
  }
  return `<button class="row-main" type="button" data-select="${esc(d.id)}" data-key="sel-${esc(d.id)}" aria-pressed="${sel}">
<span class="row-name">${esc(d.relpath)}</span>
<span class="row-meta"><span class="row-status">${statusHtml(d)}${kdmHtml(d)}</span><span>${esc(line)}</span><span>${esc(fmtSize(d.size))}</span></span>
${running ? `<span class="bar"><span class="bar-live" style="width:${Math.floor(d.job.progress)}%"></span></span>` : ''}
${st === 'copying' && copyPct(d) != null ? `<span class="bar"><span class="bar-live bar-copy" style="width:${copyPct(d)}%"></span></span>` : ''}
</button>
${side ? `<div class="row-side">${side}</div>` : ''}`;
}

function emptyListHtml(s) {
  if (s.scanning && !s.scanned_at) return '<div class="empty-list"><b>Scanning…</b>Looking for DCPs in ' + esc(s.root) + '.</div>';
  return `<div class="empty-list"><b>No DCP found</b>dcpcheck looks for folders containing an ASSETMAP or ASSETMAP.xml file in <span class="mono">${esc(s.root)}</span> and its sub-folders. Check the volume mounted on the container, then rescan.</div>`;
}

const ICON_SPIN = '<svg class="spin" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6" opacity=".25"></circle><path d="M14 8a6 6 0 0 0-6-6"></path></svg>';
const ICON_PLAY = '<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true"><path d="M3 1.8v10.4a.6.6 0 0 0 .9.5l8.4-5.2a.6.6 0 0 0 0-1L3.9 1.3a.6.6 0 0 0-.9.5z"></path></svg>';
const ICON_KEY = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="3.8" cy="8.2" r="2.3"></circle><path d="M5.5 6.5L10.5 1.5M8.5 3.5l1.5 1.5"></path></svg>';
const ICON_KEY_BIG = '<svg width="16" height="16" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="3.8" cy="8.2" r="2.3"></circle><path d="M5.5 6.5L10.5 1.5M8.5 3.5l1.5 1.5"></path></svg>';
const ICON_CHEVRON = '<svg class="chevron" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 2.5L8 6l-3.5 3.5"></path></svg>';
const ICON_OK = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#74D3AE" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9.5"></circle><path d="M7.5 12.5l3 3 6-6.5"></path></svg>';
const ICON_BAD = iconAlert('#FF8A7A');
const ICON_MINOR = iconAlert('#FFA45C');
function iconAlert(color) {
  return `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9.5"></circle><path d="M12 7v6M12 16.5v.2"></path></svg>`;
}
const ICON_NEVER = '<svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="#6B655C" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="8" width="30" height="24" rx="3"></rect><path d="M11 8v24M29 8v24"></path><path d="M17 17.5a3 3 0 1 1 3.8 2.9c-.5.2-.8.6-.8 1.1v.8M20 26v.2"></path></svg>';

function detailHtml(d) {
  const f = d.facts || {};
  const facts = [
    ['Type', f.kind], ['Standard', f.standard], ['Picture', f.picture],
    ['Duration', f.duration], ['Sound', f.sound], ['Size', fmtSize(d.size)],
    ['KDM', f.kdm == null ? null : f.kdm ? 'Required' : 'Not required']
  ];
  if (f.cpls) facts.push(['CPLs', f.cpls]);
  const st = statusOf(d);
  const res = d.result;
  const running = st === 'running';
  const queued = st === 'queued';

  let html = `<div class="card card-pad">
<div style="display: flex; flex-direction: column; gap: 8px">
<span class="eyebrow">Selected folder</span>
<h2 class="sel-name" id="detail-title">${esc(d.relpath)}</h2>
${f.title && f.title !== d.name ? `<span class="sel-title">${esc(f.title)}</span>` : ''}
</div>
<dl class="facts">${facts.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v == null || v === '' ? '—' : v)}</dd></div>`).join('')}</dl>
</div>`;
  if (f.kdm) html += kdmCardHtml(d);

  html += `<div class="card verif"><div class="verif-head">
<div style="display: flex; flex-direction: column; gap: 4px">
<h3>Verification</h3>
<span class="verif-status">${statusHtml(d)}</span>
</div><div class="verif-actions">`;
  if (st === 'copying') {
    // No action while the DCP is still arriving.
  } else if (d.job) {
    html += `<button class="btn btn-sec" type="button" data-cancel="${esc(d.id)}" data-key="cancel">${queued ? 'Remove from queue' : 'Cancel'}</button>`;
  } else {
    html += `<button class="btn btn-pri" type="button" data-verify="${esc(d.id)}" data-key="run">${ICON_PLAY}${res ? 'Re-run verification' : 'Run verification'}</button>`;
  }
  html += '</div></div>';

  if (running) {
    const pct = Math.floor(d.job.progress);
    html += `<div class="running">
<div class="running-line"><span class="running-stage">${esc(d.job.stage || 'Starting the verifier…')}</span><span class="mono">${pct} %</span></div>
<div class="bar big" role="progressbar" aria-label="Progress of the current step" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><span class="bar-live" style="width:${pct}%"></span></div>
<span class="hint">${AUTO_STARTED[d.job.auto] ? AUTO_STARTED[d.job.auto] + ' ' : ''}Running for ${esc(fmtDur(Date.now() / 1000 - ui.clockSkew - d.job.started_at))}. This can take a while. <a href="/api/dcp/${esc(d.id)}/log" target="_blank" rel="noopener">Live output</a></span>
</div>`;
  } else if (st === 'copying') {
    const c = d.copy;
    const pct = copyPct(d);
    let hint;
    if (pct == null) {
      hint = `${fmtSize(c.copied)} so far, growing for ${fmtDur(Date.now() / 1000 - ui.clockSkew - c.since)}. The total size will show once the packing list (PKL) has arrived.`;
    } else {
      const left = c.speed > 0 && c.expected > c.copied ? ', ' + fmtLeft((c.expected - c.copied) / c.speed) : '';
      hint = `${fmtSize(c.copied)} of ${fmtSize(c.expected)}${left}.`;
    }
    html += `<div class="running">
<div class="running-line"><span class="running-stage">This folder is still being copied · <span class="mono c-copying">${esc(fmtSpeed(c.speed))}</span></span>${pct != null ? `<span class="mono c-copying">${pct} %</span>` : ''}</div>
<div class="bar big"${pct != null ? ` role="progressbar" aria-label="Copy progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"` : ''}><span class="bar-live bar-copy" style="width:${pct != null ? pct : 100}%"></span></div>
<span class="hint">${esc(hint)} ${ui.state.auto_verify ? 'The verification will start by itself once the copy is complete.' : 'The verification can start once the folder stops growing.'}</span>
</div>`;
  } else if (queued) {
    html += `<div class="running"><span class="running-stage">Waiting in the queue${d.queue_position ? ' (position ' + d.queue_position + ')' : ''}.</span><span class="hint">Verifications run one after the other so that they don't fight over the disks.</span></div>`;
  }

  if (!res && !d.job && st !== 'copying') {
    html += `<div class="never">${ICON_NEVER}<b>This folder has never been verified</b><span>Run a verification to check the DCP’s structure, its file hashes and its compliance with the Bv2.1 recommendations.</span></div>`;
  }

  if (res) html += resultHtml(d, res);
  html += '</div>';
  return html;
}

function resultHtml(d, res) {
  const notes = ui.detail && ui.detail.id === d.id && ui.detail.result ? (ui.detail.result.notes || []) : null;
  const c = res.counts || {};
  let html = `<div style="display: flex; flex-direction: column">
<div class="result-head"><span class="eyebrow">${d.job ? 'Previous result' : 'Last result'}</span>
<span class="when">${esc(fmtDate(res.finished_at))}${AUTO_RESULT[res.auto] ? ' · ' + AUTO_RESULT[res.auto] : ''} · took ${esc(fmtDur(res.elapsed))}${res.verifier ? ' · DCP-o-matic ' + esc(res.verifier) : ''}</span></div>`;

  if (res.status === 'failed') {
    html += `<div class="banner bad" style="margin-top: 16px">${ICON_BAD}<div><b>The verification did not complete</b><span>${esc(res.failure || 'The verifier stopped unexpectedly.')}</span></div></div>`;
  } else {
    html += '<div class="counts">' + [['error', 'Critical errors'], ['minor', 'Minor errors'], ['bv21', 'Bv2.1 issues'], ['warn', 'Warnings']].map(([k, label]) =>
      `<div class="count"><b class="${c[k] ? 'c-' + k : ''}">${c[k] || 0}</b><span>${label}</span></div>`).join('') + '</div>';
    if (res.status === 'ok') {
      html += `<div class="banner ok">${ICON_OK}<div><b>No issues found</b><span>DCP-o-matic found nothing wrong with this DCP.</span></div></div>`;
    } else if (PASSED[res.status]) {
      const found = [c.bv21 ? plural(c.bv21, 'Bv2.1 issue', 'Bv2.1 issues') : '', c.warn ? plural(c.warn, 'warning', 'warnings') : ''].filter(Boolean).join(' and ');
      html += `<div class="banner ok">${ICON_OK}<div><b>OK: no errors</b><span>DCP-o-matic found no error in this DCP, only ${esc(found)}. They are worth a look but should not stop it from playing.</span></div></div>`;
    } else if (res.status === 'minor') {
      html += `<div class="banner minor">${ICON_MINOR}<div><b>Should play: minor errors only</b><span>DCP-o-matic found ${esc(plural(c.minor, 'error', 'errors'))} in the XML or the metadata, but no critical one. Servers should accept this DCP; tell whoever made it.</span></div></div>`;
    } else if (res.status === 'error') {
      html += `<div class="banner bad">${ICON_BAD}<div><b>${esc(plural(c.error, 'critical error', 'critical errors'))}</b><span>This DCP may fail to ingest or to play: missing or damaged files, wrong hashes, invalid picture, sound or subtitles. Check it before the screening.</span></div></div>`;
    }
  }

  html += `<div class="links">${res.report ? `<a class="btn btn-sec btn-link" href="/api/dcp/${esc(d.id)}/report" target="_blank" rel="noopener">Full HTML report</a>` : ''}<a class="btn btn-sec btn-link" href="/api/dcp/${esc(d.id)}/log" target="_blank" rel="noopener">Raw output</a></div>`;

  const total = (c.error || 0) + (c.minor || 0) + (c.bv21 || 0) + (c.warn || 0);
  if (res.status !== 'failed' && total > 0) {
    const chips = [['all', 'All', total], ['error', 'Critical', c.error], ['minor', 'Minor', c.minor], ['bv21', 'Bv2.1', c.bv21], ['warn', 'Warnings', c.warn]]
      .filter(([k, , n]) => k === 'all' || n > 0);
    if (!chips.some(([k]) => k === ui.filter)) ui.filter = 'all';
    html += '<div class="chips" role="group" aria-label="Filter by severity">' + chips.map(([k, label, n]) =>
      `<button class="chip" type="button" data-filter="${k}" data-key="chip-${k}" aria-pressed="${k === ui.filter}">${label}<small>${n}</small></button>`).join('') + '</div>';
    if (!notes) {
      html += '<p class="more hint">Loading notes…</p>';
    } else {
      const shown = sortedNotes(notes.filter(n => ui.filter === 'all' || n.sev === ui.filter));
      // In the "All" view, the Bv2.1 issues and warnings stay folded until asked for.
      const fold = ui.filter === 'all' ? shown.filter(n => FOLDED[n.sev]) : [];
      const head = fold.length ? shown.filter(n => !FOLDED[n.sev]) : shown;
      const list = ui.showFolded ? head.concat(fold) : head;
      const visible = ui.showAll ? list : list.slice(0, NOTE_PAGE);
      html += notesHtml(visible.slice(0, head.length));
      if (fold.length) html += foldHtml(fold);
      html += notesHtml(visible.slice(head.length));
      if (visible.length < list.length) {
        html += `<div class="more"><button class="btn btn-sec btn-link" type="button" data-showall="1" data-key="showall">Show all ${list.length} notes</button></div>`;
      }
    }
  }
  return html + '</div>';
}

// ---- KDMs ----------------------------------------------------------------

function kdmCardHtml(d) {
  const k = ui.kdm[d.id] || { items: [], skipped: [], errors: [], busy: 0 };
  const items = k.items.slice().sort((a, b) => KDM_ORDER.indexOf(a.verdict) - KDM_ORDER.indexOf(b.verdict) || a.file.localeCompare(b.file, undefined, { numeric: true }));
  const mine = items.filter(r => r.verdict !== 'other');
  let html = `<div class="card verif kdm-card" data-kdm-drop="${esc(d.id)}"><div class="verif-head">
<div style="display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1 1 280px">
<h3>KDM</h3>
<span class="hint">Drop KDM files or a ZIP of KDMs here to check that they were made for this version of the DCP. Only their public part is read: the keys themselves can only be opened by the server they were made for.${ui.state.kdm_servers && ui.state.kdm_servers.length ? ' Your servers: ' + esc(ui.state.kdm_servers.join(', ')) + '.' : ''}</span>
</div><div class="verif-actions">`;
  if (items.length || k.skipped.length || k.errors.length) html += `<button class="btn btn-sec" type="button" data-kdm-clear="${esc(d.id)}" data-key="kdm-clear">Clear</button>`;
  html += `<button class="btn btn-pri" type="button" data-kdm-pick="${esc(d.id)}" data-key="kdm-pick">${ICON_KEY_BIG}Check KDMs…</button></div></div>`;

  if (k.busy) html += `<div class="running"><span class="running-stage kdm-busy">${ICON_SPIN}Reading ${esc(plural(k.busy, 'file', 'files'))}…</span></div>`;
  if (items.length) {
    const ok = mine.filter(r => r.verdict === 'ok').length;
    let summary;
    if (!mine.length) summary = items.length === 1 ? 'This KDM was not made for this DCP.' : `None of these ${items.length} KDMs was made for this DCP.`;
    else summary = `${plural(mine.length, 'KDM', 'KDMs')} for this DCP, ${ok} valid now` + (items.length > mine.length ? `, and ${plural(items.length - mine.length, 'KDM', 'KDMs')} for other DCPs.` : '.');
    html += `<div class="result-head"><span class="eyebrow">Checked KDMs</span><span class="when">${esc(summary)}</span></div>`;
    // KDMs made for other DCPs (a ZIP often holds several films) stay folded.
    const others = items.filter(r => r.verdict === 'other');
    if (mine.length) html += '<ul class="notes kdms">' + mine.map(r => kdmItemHtml(d, r)).join('') + '</ul>';
    if (others.length) {
      const label = (ui.showOtherKdms ? 'Hide ' : 'Show ') + plural(others.length, 'KDM', 'KDMs') + ' for other DCPs';
      html += `<div class="more fold"><button class="btn btn-sec btn-link" type="button" data-kdm-fold="1" data-key="kdm-fold" aria-expanded="${ui.showOtherKdms}">${ICON_CHEVRON}${esc(label)}</button></div>`;
      if (ui.showOtherKdms) html += '<ul class="notes">' + others.map(r => kdmItemHtml(d, r)).join('') + '</ul>';
    }
  }
  const problems = k.errors.map(e => esc(e)).concat(k.skipped.map(s => `<span class="mono">${esc(s.file)}</span>: ${esc(s.reason)}`));
  if (problems.length) {
    html += `<div class="more kdm-skipped"><span class="hint">${problems.length === 1 ? 'Not checked' : esc(plural(problems.length, 'file', 'files')) + ' not checked'}:</span><ul>${problems.map(p => `<li class="hint">${p}</li>`).join('')}</ul></div>`;
  }
  return html + '</div>';
}

function kdmItemHtml(d, r) {
  const v = KDM_VERDICT[r.verdict] || KDM_VERDICT.other;
  const from = r.not_before ? fmtDate(r.not_before) : '?';
  const to = r.not_after ? fmtDate(r.not_after) : '?';
  // With KDM_SERVERS, the name of the server it was made for.
  const made = 'Made for this DCP' + (r.server ? ' and ' + r.server : '');
  let msg;
  if (r.verdict === 'ok') msg = made + ', valid until ' + to + '.';
  else if (r.verdict === 'not_yet') msg = made + ', but valid only from ' + from + '.';
  else if (r.verdict === 'unknown') msg = made + ', but its dates of validity can’t be read.';
  else if (r.verdict === 'expired') msg = made + ', but it expired on ' + to + '.';
  else if (r.verdict === 'server') msg = 'Made for this DCP, but for a server that is not one of yours' + (r.recipient ? ': ' + r.recipient : '') + '. Ask for a KDM made for your server’s certificate.';
  else if (r.verdict === 'keys') msg = made + ', but ' + (r.missing === r.needed ? (r.needed === 1 ? 'the key it needs is' : 'all the keys it needs are') : r.missing + ' of the ' + r.needed + ' keys it needs ' + (r.missing === 1 ? 'is' : 'are')) + ' missing: the DCP won’t play.';
  else if (r.other) msg = 'Made for another DCP of this library:';
  else msg = 'Made for another composition (CPL), perhaps another version of the film' + (r.title ? ': “' + r.title + '”' : '') + '.';
  let html = `<li>
<span class="sev ${v.cls}">${esc(v.label)}</span>
<div class="note-body"><span class="note-msg">${esc(msg)}</span>`;
  if (r.other) {
    const there = r.other.check.verdict === 'ok' ? '' : ' (' + ((KDM_VERDICT[r.other.check.verdict] || {}).label || '').toLowerCase() + ' for it)';
    html += `<span class="kdm-other"><button class="link" type="button" data-select="${esc(r.other.id)}" data-key="kdm-other-${esc(r.message_id)}">${esc(r.other.relpath)}</button>${esc(there)}</span>`;
  }
  const facts = [];
  if (r.server) facts.push('For ' + r.server + (r.recipient ? ' · ' + r.recipient : ''));
  else if (r.recipient || r.device) facts.push('For ' + [r.device, r.recipient].filter(Boolean).filter((x, i, a) => a.indexOf(x) === i).join(' · '));
  if (r.verdict !== 'other') facts.push('Valid ' + from + ' → ' + to);
  if (facts.length) html += `<span class="kdm-facts">${facts.map(x => `<span>${esc(x)}</span>`).join('')}</span>`;
  html += `<span class="note-ref"><span>${esc(r.file)}</span>${r.annotation && r.annotation !== r.title ? `<span>${esc(r.annotation)}</span>` : ''}<span title="Composition (CPL) the KDM is for">CPL ${esc(r.cpl_id || '?')}</span></span>`;
  return html + '</div></li>';
}

function kdmState(id) {
  return ui.kdm[id] || (ui.kdm[id] = { items: [], skipped: [], errors: [], busy: 0 });
}

// The same KDM checked twice replaces the first result.
function addKdm(id, r) {
  const k = kdmState(id);
  const i = r.message_id ? k.items.findIndex(x => x.message_id === r.message_id) : -1;
  if (i >= 0) k.items[i] = r; else k.items.push(r);
}

async function checkKdms(id, files) {
  const k = kdmState(id);
  k.busy += files.length;
  render();
  for (const file of files) {
    try {
      const r = await fetch('/api/dcp/' + encodeURIComponent(id) + '/kdm', {
        method: 'POST',
        headers: { 'X-Dcpcheck': '1', 'X-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream' },
        body: file
      });
      if (!r.ok) throw new Error(r.status === 413 ? 'too large' : r.status + ' ' + r.statusText);
      const res = await r.json();
      for (const item of res.kdms) {
        addKdm(id, item);
        // Also shown on the DCP it was made for.
        if (item.other) addKdm(item.other.id, item.other.check);
      }
      k.skipped = k.skipped.filter(s => !res.skipped.some(x => x.file === s.file)).concat(res.skipped);
    } catch (e) {
      k.errors.push(file.name + ': ' + (e.message || 'could not be sent'));
    }
    k.busy--;
    render();
  }
}

function sortedNotes(notes) {
  const rank = n => n.sev in SEV_ORDER ? SEV_ORDER[n.sev] : 0;
  return notes.slice().sort((a, b) => rank(a) - rank(b));
}

function notesHtml(notes) {
  if (!notes.length) return '';
  return '<ul class="notes">' + notes.map(n => `<li>
<span class="sev ${esc(n.sev)}" title="${esc(SEV[n.sev] ? SEV[n.sev].title : '')}">${esc(SEV[n.sev] ? SEV[n.sev].label : n.sev)}</span>
<div class="note-body"><span class="note-msg">${esc(n.msg)}</span>${n.code || n.file ? `<span class="note-ref">${n.code ? `<span>${esc(n.code)}</span>` : ''}${n.file ? `<span>${esc(n.file)}</span>` : ''}</span>` : ''}</div>
</li>`).join('') + '</ul>';
}

// The button that shows or hides the Bv2.1 issues and warnings.
function foldHtml(fold) {
  const bv21 = fold.filter(n => n.sev === 'bv21').length;
  const warn = fold.length - bv21;
  const what = [bv21 ? plural(bv21, 'Bv2.1 issue', 'Bv2.1 issues') : '', warn ? plural(warn, 'warning', 'warnings') : ''].filter(Boolean).join(' and ');
  const label = (ui.showFolded ? 'Hide ' : 'Show ') + what;
  return `<div class="more fold"><button class="btn btn-sec btn-link" type="button" data-fold="1" data-key="fold" aria-expanded="${ui.showFolded}">${ICON_CHEVRON}${esc(label)}</button></div>`;
}

// Refocusing must never scroll: the page is redrawn every second while a
// verification runs, and the user may be reading something else.
function refocus(el) {
  if (el && el.isConnected && !el.disabled && document.activeElement !== el) el.focus({ preventScroll: true });
}

function setHtml(el, html) {
  if (el._html === html) return;
  const active = document.activeElement;
  const key = active && el.contains(active) ? active.getAttribute('data-key') : null;
  el.innerHTML = html;
  el._html = html;
  if (key) refocus(el.querySelector('[data-key="' + CSS.escape(key) + '"]'));
}

// Rows are kept and updated one by one, so that a refresh only touches the
// rows that changed and leaves the scroll position alone.
function renderRows(s) {
  const box = document.getElementById('rows');
  if (!s.dcps.length) {
    box._rows = null;
    setHtml(box, emptyListHtml(s));
    return;
  }
  if (!box._rows) {
    box.textContent = '';
    box._html = null;
    box._rows = new Map();
  }
  const active = document.activeElement;
  const seen = new Set();
  sortedDcps(s.dcps).forEach((d, i) => {
    let el = box._rows.get(d.id);
    if (!el) {
      el = document.createElement('div');
      box._rows.set(d.id, el);
    }
    seen.add(d.id);
    const cls = rowClass(d);
    if (el.className !== cls) el.className = cls;
    setHtml(el, rowHtml(d));
    if (box.children[i] !== el) box.insertBefore(el, box.children[i] || null);
  });
  for (const [id, el] of box._rows) {
    if (!seen.has(id)) { el.remove(); box._rows.delete(id); }
  }
  if (active && box.contains(active)) refocus(active);
}

function renderSort() {
  const sel = document.getElementById('sort');
  if (sel.value !== ui.sort) sel.value = ui.sort;
  document.getElementById('sort-dir').textContent = SORTS[ui.sort].order[ui.reverse ? 1 : 0];
}

function render() {
  const s = ui.state;
  if (!s) return;
  renderHeader(s);
  renderSort();
  if (!s.dcps.some(d => d.id === ui.selected)) ui.selected = s.dcps.length ? sortedDcps(s.dcps)[0].id : null;
  renderRows(s);
  const sel = s.dcps.find(d => d.id === ui.selected);
  setHtml(document.getElementById('detail'), sel ? detailHtml(sel) : '');
  if (sel) ensureDetail(sel);
}

async function ensureDetail(d) {
  const key = d.id + ':' + (d.result ? d.result.finished_at : '-');
  if (ui.detailKey === key) return;
  ui.detailKey = key;
  if (!d.result) { ui.detail = null; return; }
  try {
    const full = await api('/api/dcp/' + encodeURIComponent(d.id));
    if (ui.detailKey === key) { ui.detail = full; render(); }
  } catch (e) {
    ui.detailKey = null;
  }
}

// ---- data ----------------------------------------------------------------

let timer = null;
async function refresh() {
  clearTimeout(timer);
  let busy = false;
  try {
    const s = await api('/api/state');
    ui.clockSkew = Date.now() / 1000 - s.now;
    ui.state = s;
    busy = s.scanning || s.dcps.some(d => d.job || d.copy);
    render();
  } catch (e) {
    document.getElementById('scanned').textContent = 'Server unreachable, retrying…';
  }
  timer = setTimeout(refresh, busy ? 1000 : 8000);
}

document.addEventListener('click', async ev => {
  const t = ev.target.closest('button');
  if (!t) return;
  if (t.id === 'rescan') {
    t.disabled = true;
    await api('/api/rescan', 'POST').catch(() => {});
    setTimeout(refresh, 300);
  } else if (t.dataset.select) {
    if (ui.selected !== t.dataset.select) { ui.filter = 'all'; ui.showAll = false; ui.showFolded = false; ui.showOtherKdms = false; }
    ui.selected = t.dataset.select;
    save('selected', ui.selected);
    render();
    // Bring the top of the detail into view: below the list on narrow
    // screens, above the viewport on wide ones once the list is scrolled.
    const detail = document.getElementById('detail');
    const top = detail.getBoundingClientRect().top;
    if (top < 0 || top > window.innerHeight * 0.6) detail.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else if (t.dataset.verify) {
    ui.selected = t.dataset.verify;
    save('selected', ui.selected);
    ui.filter = 'all';
    ui.showAll = false;
    ui.showFolded = false;
    t.disabled = true;
    await api('/api/dcp/' + encodeURIComponent(t.dataset.verify) + '/verify', 'POST').catch(() => {});
    refresh();
  } else if (t.dataset.cancel) {
    t.disabled = true;
    await api('/api/dcp/' + encodeURIComponent(t.dataset.cancel) + '/cancel', 'POST').catch(() => {});
    refresh();
  } else if (t.dataset.filter) {
    ui.filter = t.dataset.filter;
    ui.showAll = false;
    render();
  } else if (t.dataset.fold) {
    ui.showFolded = !ui.showFolded;
    render();
  } else if (t.dataset.showall) {
    ui.showAll = true;
    render();
  } else if (t.dataset.kdmPick) {
    ui.kdmTarget = t.dataset.kdmPick;
    document.getElementById('kdm-files').click();
  } else if (t.dataset.kdmFold) {
    ui.showOtherKdms = !ui.showOtherKdms;
    render();
  } else if (t.dataset.kdmClear) {
    delete ui.kdm[t.dataset.kdmClear];
    render();
  }
});

document.getElementById('kdm-files').addEventListener('change', ev => {
  const files = Array.from(ev.target.files || []);
  ev.target.value = '';
  if (files.length && ui.kdmTarget) checkKdms(ui.kdmTarget, files);
});

// Files dropped anywhere on the page are checked against the selected DCP,
// if it needs a KDM. Elsewhere, the browser must not open them.
function kdmDropTarget() {
  const d = ui.state && ui.state.dcps.find(x => x.id === ui.selected);
  return d && d.facts && d.facts.kdm ? d.id : null;
}
function hasFiles(ev) {
  return ev.dataTransfer && Array.from(ev.dataTransfer.types || []).indexOf('Files') >= 0;
}
let dragDepth = 0;
function setDragging(on) {
  document.body.classList.toggle('dragging', on && !!kdmDropTarget());
}
document.addEventListener('dragenter', ev => {
  if (!hasFiles(ev)) return;
  dragDepth++;
  setDragging(true);
});
document.addEventListener('dragleave', ev => {
  if (!hasFiles(ev)) return;
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) setDragging(false);
});
document.addEventListener('dragover', ev => {
  if (!hasFiles(ev)) return;
  ev.preventDefault();
  ev.dataTransfer.dropEffect = kdmDropTarget() ? 'copy' : 'none';
});
document.addEventListener('drop', ev => {
  if (!hasFiles(ev)) return;
  ev.preventDefault();
  dragDepth = 0;
  setDragging(false);
  const id = kdmDropTarget();
  const files = Array.from(ev.dataTransfer.files || []);
  if (id && files.length) checkKdms(id, files);
});

document.getElementById('sort').addEventListener('change', ev => {
  ui.sort = SORTS[ev.target.value] ? ev.target.value : 'name';
  ui.reverse = false;
  save('sort', ui.sort);
  save('reverse', '0');
  render();
});
document.getElementById('sort-dir').addEventListener('click', () => {
  ui.reverse = !ui.reverse;
  save('reverse', ui.reverse ? '1' : '0');
  render();
});

document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
refresh();
