'use strict';

const STATUS = {
  ok: { label: 'OK' },
  warn: { label: 'OK' },
  bv21: { label: 'OK' },
  error: { label: 'Errors' },
  failed: { label: 'Verifier failed' },
  never: { label: 'Never verified' },
  running: { label: 'Running' },
  queued: { label: 'Queued' },
  copying: { label: 'Copying' }
};
// Without errors a DCP is OK; its Bv2.1 issues and warnings only show as flags.
const PASSED = { ok: 1, bv21: 1, warn: 1 };
// For sorting by status, problems first.
const STATUS_RANK = ['copying', 'running', 'queued', 'failed', 'error', 'never', 'bv21', 'warn', 'ok'];
const SORTS = {
  name: { label: 'Name', order: ['A → Z', 'Z → A'] },
  size: { label: 'Size', order: ['Largest first', 'Smallest first'] },
  status: { label: 'Status', order: ['Problems first', 'OK first'] },
  date: { label: 'Last updated', order: ['Newest first', 'Oldest first'] }
};
const SEV = {
  error: { label: 'Error', title: 'The DCP is broken or may not play' },
  bv21: { label: 'Bv2.1', title: 'Not compliant with the ISDCF Bv2.1 recommendations' },
  warn: { label: 'Warning', title: 'Worth checking, should not block playback' }
};
// Verifications the server started by itself, and why.
const AUTO_STARTED = { copy: 'Started by itself at the end of the copy.', new: 'Started by itself for this new DCP.' };
const AUTO_RESULT = { copy: 'started after the copy', new: 'started for a new DCP' };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const NOTE_PAGE = 200;

const ui = {
  state: null,
  selected: load('selected'),
  filter: 'all',
  showAll: false,
  sort: SORTS[load('sort')] ? load('sort') : 'name',
  reverse: load('reverse') === '1',
  detail: null,      // full detail (with notes) of the selected DCP
  detailKey: null,   // what that detail was fetched for
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
function statusHtml(d) {
  const st = statusOf(d);
  const cls = PASSED[st] ? 'ok' : st;
  const live = st === 'running' || st === 'copying';
  return `<span class="status c-${cls}"><span class="dot${live ? ' pulse' : ''}"></span>${esc(statusLabel(d))}</span>${PASSED[st] ? flagsHtml(d) : ''}`;
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
  let side;
  if (st === 'copying') {
    side = `<span class="copying" title="Copy in progress: the folder is still growing">${ICON_SPIN}<span class="mono">${esc(fmtSpeed(d.copy.speed))}</span></span>`;
  } else {
    const action = busy ? (running ? 'Running' : 'Queued') : (d.result ? 'Re-run' : 'Verify');
    const aria = (d.result ? 'Re-run verification of ' : 'Verify ') + d.name;
    side = `<button class="btn btn-sec" type="button" data-verify="${esc(d.id)}" data-key="verify-${esc(d.id)}" aria-label="${esc(aria)}"${busy ? ' disabled' : ''}>${action}</button>`;
  }
  return `<button class="row-main" type="button" data-select="${esc(d.id)}" data-key="sel-${esc(d.id)}" aria-pressed="${sel}">
<span class="row-name">${esc(d.relpath)}</span>
<span class="row-meta"><span class="row-status">${statusHtml(d)}</span><span>${esc(line)}</span><span>${esc(fmtSize(d.size))}</span></span>
${running ? `<span class="bar"><span class="bar-live" style="width:${Math.floor(d.job.progress)}%"></span></span>` : ''}
${st === 'copying' && copyPct(d) != null ? `<span class="bar"><span class="bar-live bar-copy" style="width:${copyPct(d)}%"></span></span>` : ''}
</button>
<div class="row-side">${side}</div>`;
}

function emptyListHtml(s) {
  if (s.scanning && !s.scanned_at) return '<div class="empty-list"><b>Scanning…</b>Looking for DCPs in ' + esc(s.root) + '.</div>';
  return `<div class="empty-list"><b>No DCP found</b>dcpcheck looks for folders containing an ASSETMAP or ASSETMAP.xml file in <span class="mono">${esc(s.root)}</span> and its sub-folders. Check the volume mounted on the container, then rescan.</div>`;
}

const ICON_SPIN = '<svg class="spin" width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6" opacity=".25"></circle><path d="M14 8a6 6 0 0 0-6-6"></path></svg>';
const ICON_PLAY = '<svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true"><path d="M3 1.8v10.4a.6.6 0 0 0 .9.5l8.4-5.2a.6.6 0 0 0 0-1L3.9 1.3a.6.6 0 0 0-.9.5z"></path></svg>';
const ICON_OK = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#74D3AE" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9.5"></circle><path d="M7.5 12.5l3 3 6-6.5"></path></svg>';
const ICON_BAD = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#FF8A7A" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9.5"></circle><path d="M12 7v6M12 16.5v.2"></path></svg>';
const ICON_NEVER = '<svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="#6B655C" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="5" y="8" width="30" height="24" rx="3"></rect><path d="M11 8v24M29 8v24"></path><path d="M17 17.5a3 3 0 1 1 3.8 2.9c-.5.2-.8.6-.8 1.1v.8M20 26v.2"></path></svg>';

function detailHtml(d) {
  const f = d.facts || {};
  const facts = [
    ['Type', f.kind], ['Standard', f.standard], ['Picture', f.picture],
    ['Duration', f.duration], ['Sound', f.sound], ['Size', fmtSize(d.size)]
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
  const c = res.counts || { error: 0, bv21: 0, warn: 0 };
  let html = `<div style="display: flex; flex-direction: column">
<div class="result-head"><span class="eyebrow">${d.job ? 'Previous result' : 'Last result'}</span>
<span class="when">${esc(fmtDate(res.finished_at))}${AUTO_RESULT[res.auto] ? ' · ' + AUTO_RESULT[res.auto] : ''} · took ${esc(fmtDur(res.elapsed))}${res.verifier ? ' · DCP-o-matic ' + esc(res.verifier) : ''}</span></div>`;

  if (res.status === 'failed') {
    html += `<div class="banner bad" style="margin-top: 16px">${ICON_BAD}<div><b>The verification did not complete</b><span>${esc(res.failure || 'The verifier stopped unexpectedly.')}</span></div></div>`;
  } else {
    html += '<div class="counts">' + [['error', 'Errors'], ['bv21', 'Bv2.1 issues'], ['warn', 'Warnings']].map(([k, label]) =>
      `<div class="count"><b class="${c[k] ? 'c-' + k : ''}">${c[k] || 0}</b><span>${label}</span></div>`).join('') + '</div>';
    if (res.status === 'ok') {
      html += `<div class="banner ok">${ICON_OK}<div><b>No issues found</b><span>DCP-o-matic found nothing wrong with this DCP.</span></div></div>`;
    } else if (PASSED[res.status]) {
      const found = [c.bv21 ? plural(c.bv21, 'Bv2.1 issue', 'Bv2.1 issues') : '', c.warn ? plural(c.warn, 'warning', 'warnings') : ''].filter(Boolean).join(' and ');
      html += `<div class="banner ok">${ICON_OK}<div><b>OK: no errors</b><span>DCP-o-matic found no error in this DCP, only ${esc(found)}, listed below. They are worth a look but should not stop it from playing.</span></div></div>`;
    }
  }

  html += `<div class="links">${res.report ? `<a class="btn btn-sec btn-link" href="/api/dcp/${esc(d.id)}/report" target="_blank" rel="noopener">Full HTML report</a>` : ''}<a class="btn btn-sec btn-link" href="/api/dcp/${esc(d.id)}/log" target="_blank" rel="noopener">Raw output</a></div>`;

  const total = (c.error || 0) + (c.bv21 || 0) + (c.warn || 0);
  if (res.status !== 'failed' && total > 0) {
    const chips = [['all', 'All', total], ['error', 'Errors', c.error], ['bv21', 'Bv2.1', c.bv21], ['warn', 'Warnings', c.warn]]
      .filter(([k, , n]) => k === 'all' || n > 0);
    if (!chips.some(([k]) => k === ui.filter)) ui.filter = 'all';
    html += '<div class="chips" role="group" aria-label="Filter by severity">' + chips.map(([k, label, n]) =>
      `<button class="chip" type="button" data-filter="${k}" data-key="chip-${k}" aria-pressed="${k === ui.filter}">${label}<small>${n}</small></button>`).join('') + '</div>';
    if (!notes) {
      html += '<p class="more hint">Loading notes…</p>';
    } else {
      const shown = notes.filter(n => ui.filter === 'all' || n.sev === ui.filter);
      const visible = ui.showAll ? shown : shown.slice(0, NOTE_PAGE);
      html += '<ul class="notes">' + visible.map(n => `<li>
<span class="sev ${esc(n.sev)}" title="${esc(SEV[n.sev] ? SEV[n.sev].title : '')}">${esc(SEV[n.sev] ? SEV[n.sev].label : n.sev)}</span>
<div class="note-body"><span class="note-msg">${esc(n.msg)}</span>${n.code || n.file ? `<span class="note-ref">${n.code ? `<span>${esc(n.code)}</span>` : ''}${n.file ? `<span>${esc(n.file)}</span>` : ''}</span>` : ''}</div>
</li>`).join('') + '</ul>';
      if (visible.length < shown.length) {
        html += `<div class="more"><button class="btn btn-sec btn-link" type="button" data-showall="1" data-key="showall">Show all ${shown.length} notes</button></div>`;
      }
    }
  }
  return html + '</div>';
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
    if (ui.selected !== t.dataset.select) { ui.filter = 'all'; ui.showAll = false; }
    ui.selected = t.dataset.select;
    save('selected', ui.selected);
    render();
    // On narrow screens the detail sits below the list: bring it into view.
    const detail = document.getElementById('detail');
    if (detail.getBoundingClientRect().top > window.innerHeight * 0.6) detail.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else if (t.dataset.verify) {
    ui.selected = t.dataset.verify;
    save('selected', ui.selected);
    ui.filter = 'all';
    ui.showAll = false;
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
  } else if (t.dataset.showall) {
    ui.showAll = true;
    render();
  }
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
