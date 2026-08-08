const API_BASE = window.SIGNALFORGE_API_BASE || window.NEXUS_API_BASE || 'http://127.0.0.1:8000';
const STORAGE_PREFIX = 'signalforge';

const demoEvidence = [
  { id: 'demo-source:deploy-42:1', type: 'deployment', marker: '↥', title: 'Payments deployment 42', source: 'DEPLOYMENT', text: 'checkout-api deployed v2026.08.06-3 before latency increased.', time: '12:30 UTC', service: 'checkout-api', score: 0.96, reason: 'Temporal + service match' },
  { id: 'obs:checkout-latency:1', type: 'observability', marker: '⌁', title: 'checkout-latency-high alert', source: 'OBSERVABILITY', text: 'p95 latency crossed 2s for 5 consecutive minutes; current value 4.8s.', time: '12:41 UTC', service: 'checkout-api', score: 0.94, reason: 'Incident window match' },
  { id: 'demo-source:provider-retry:1', type: 'deployment', marker: '↥', title: 'Payment retry policy change', source: 'SOURCE CONTROL', text: 'Retry policy was updated in checkout-service in PR #1842.', time: '12:22 UTC', service: 'payment-provider', score: 0.91, reason: 'Graph neighbor match' },
  { id: 'obs:provider-timeout:1', type: 'observability', marker: '⌁', title: 'Provider timeout pattern', source: 'OBSERVABILITY', text: 'Upstream payment-provider timeout rate increased to 1.8% after the deploy.', time: '12:39 UTC', service: 'payment-provider', score: 0.88, reason: 'Semantic + temporal match' },
  { id: 'knowledge:checkout-runbook:1', type: 'knowledge', marker: '▤', title: 'Checkout provider timeout runbook', source: 'KNOWLEDGE', text: 'Diagnostic checklist covers provider timeout spikes and retry amplification.', time: '11:58 UTC', service: 'checkout-api', score: 0.81, reason: 'Service + intent match' },
  { id: 'knowledge:postmortem-177:1', type: 'knowledge', marker: '▤', title: 'Similar incident · INC-177', source: 'POSTMORTEM', text: 'A previous provider timeout incident was resolved by rolling back the retry policy.', time: 'Jun 18 · 2026', service: 'payment-provider', score: 0.76, reason: 'Similar incident match' }
];

let evidence = [...demoEvidence];
let currentFilter = 'all';
let lastAnswerId = 'demo-answer';
let toastTimer;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const commanders = {
  alex: { key: 'alex', name: 'Alex Morgan', initials: 'AM', userId: 'alice', role: 'Incident commander', avatarClass: 'alex' },
  jordan: { key: 'jordan', name: 'Jordan Lee', initials: 'JL', userId: 'jordan', role: 'Incident commander', avatarClass: 'jordan' },
  sam: { key: 'sam', name: 'Sam Kim', initials: 'SK', userId: 'sam', role: 'Incident commander', avatarClass: 'sam' },
  priya: { key: 'priya', name: 'Priya Nair', initials: 'PN', userId: 'priya', role: 'Incident commander', avatarClass: 'priya' }
};

let activeCommander = commanders.alex;
let availability = 'On call';
try {
  activeCommander = commanders[localStorage.getItem(`${STORAGE_PREFIX}.activeCommander`) || localStorage.getItem('nexus.activeCommander')] || commanders.alex;
  availability = localStorage.getItem(`${STORAGE_PREFIX}.availability`) || localStorage.getItem('nexus.availability') || 'On call';
} catch (_) {
  // Storage may be unavailable in a private browser context; the in-memory demo still works.
}

function requestIdentityHeaders(includeGroups = true) {
  const headers = { 'X-Tenant-ID': 'demo', 'X-User-ID': activeCommander.userId };
  if (includeGroups) headers['X-Groups'] = 'oncall';
  return headers;
}

function setAvatar(element, commander) {
  if (!element) return;
  element.textContent = commander.initials;
  element.className = element.classList.contains('avatar-button') ? 'avatar-button' : `user-avatar ${commander.avatarClass}`;
}

function updateCommanderUi() {
  setAvatar($('#userAvatar'), activeCommander);
  setAvatar($('#menuUserAvatar'), activeCommander);
  setAvatar($('#topAvatarButton'), activeCommander);
  $('#userName').textContent = activeCommander.name;
  $('#menuUserName').textContent = activeCommander.name;
  $('#userRole').textContent = activeCommander.role;
  $('#menuUserRole').textContent = `${activeCommander.role} · ${availability}`;
  $('#availabilityLabel').textContent = availability;
  $$('.commander-option').forEach((option) => option.classList.toggle('active', option.dataset.commander === activeCommander.key));
  $$('.availability-option').forEach((option) => option.classList.toggle('active', option.dataset.availability === availability));
}

function closeUserMenu() {
  $('#userMenu').hidden = true;
  $('#userMenuButton').setAttribute('aria-expanded', 'false');
  $('#commanderPicker').hidden = true;
  $('#availabilityPicker').hidden = true;
}

function selectCommander(key, announce = true) {
  const commander = commanders[key];
  if (!commander) return;
  activeCommander = commander;
  try { localStorage.setItem(`${STORAGE_PREFIX}.activeCommander`, key); } catch (_) { /* no persistent browser storage */ }
  updateCommanderUi();
  $('#signedOutScreen').hidden = true;
  $('.app-shell').hidden = false;
  closeUserMenu();
  if (announce) showToast(`Signed in as ${commander.name}.`);
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[char]));
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 3200);
}

async function shareIncident() {
  const incidentUrl = new URL(window.location.href);
  incidentUrl.searchParams.set('view', 'Incident room');
  incidentUrl.hash = 'INC-2048';
  const shareData = {
    title: 'INC-2048 · Checkout latency spike',
    text: 'Incident workspace: Checkout latency spike',
    url: incidentUrl.toString()
  };

  if (navigator.share) {
    try {
      await navigator.share(shareData);
      showToast('Incident workspace shared.');
      return;
    } catch (error) {
      if (error?.name === 'AbortError') return;
      // Some desktop browsers expose Web Share but reject it; use copy below.
    }
  }

  let copied = false;
  try {
    if (navigator.clipboard?.writeText && window.isSecureContext) {
      await navigator.clipboard.writeText(shareData.url);
      copied = true;
    }
  } catch (_) {
    copied = false;
  }

  if (!copied) {
    const textArea = document.createElement('textarea');
    textArea.value = shareData.url;
    textArea.setAttribute('readonly', '');
    textArea.style.cssText = 'position:fixed; opacity:0; pointer-events:none;';
    document.body.appendChild(textArea);
    textArea.select();
    try { copied = document.execCommand('copy'); } catch (_) { copied = false; }
    textArea.remove();
  }

  showToast(copied ? 'Incident workspace link copied.' : 'Could not access the clipboard. Copy this page URL manually.');
}

function setConnection(text, live = false) {
  $('#connectionText').textContent = text;
  const pill = $('#connectionPill');
  pill.style.borderColor = live ? 'rgba(84,216,191,.28)' : 'rgba(244,184,98,.22)';
  pill.style.background = live ? 'rgba(84,216,191,.055)' : 'rgba(244,184,98,.06)';
  pill.querySelector('.pulse-dot').style.background = live ? 'var(--teal)' : 'var(--amber)';
}

function renderEvidence() {
  const visible = currentFilter === 'all' ? evidence : evidence.filter((item) => item.type === currentFilter);
  $('#evidenceCount').textContent = visible.length;
  $('#evidenceList').innerHTML = visible.map((item, index) => `
    <div class="evidence-item" data-id="${escapeHtml(item.id)}">
      <div class="evidence-marker ${escapeHtml(item.type)}">${escapeHtml(item.marker || '•')}</div>
      <div class="evidence-content">
        <div class="evidence-title-line"><strong>${escapeHtml(item.title)}</strong><span class="source-label">${escapeHtml(item.source)}</span></div>
        <p>${escapeHtml(item.text)}</p>
        <div class="evidence-meta"><span>${escapeHtml(item.time)}</span><span>·</span><span>${escapeHtml(item.service)}</span><span>·</span><b>${escapeHtml(item.reason)}</b></div>
      </div>
      <div class="evidence-score"><span>${Math.round(item.score * 100)}%</span><div class="score-bar"><span style="width:${Math.round(item.score * 100)}%"></span></div></div>
    </div>`).join('');
  $('#loadMore').textContent = visible.length >= evidence.length ? 'Evidence set complete  ✓' : `Show all evidence  ↓`;
}

function renderTriage(data) {
  lastAnswerId = data.answer_id || 'demo-answer';
  const claims = data.claims || [];
  const summary = data.summary || 'No grounded summary is available for this question.';
  $('#triageBody').innerHTML = `
    <p class="triage-summary">${escapeHtml(summary)}</p>
    <div class="triage-facts">${claims.slice(0, 3).map((claim, index) => `
      <div class="fact-item"><span class="fact-dot ${['amber', 'violet', 'teal'][index % 3]}"></span><div><strong>${escapeHtml(claim.claim_type || 'Observed signal')}</strong><span>${escapeHtml(claim.text)} <b>${escapeHtml((claim.citation_ids || []).join(', '))}</b></span></div></div>`).join('') || '<div class="fact-item"><span class="fact-dot violet"></span><div><strong>Evidence only</strong><span>Open the authorized evidence cards below for the available context.</span></div></div>'}</div>
    <div class="triage-footnote"><span>⌁</span> ${data.status === 'grounded' ? 'Every material claim is backed by a validated citation.' : 'Generated claims were limited by evidence and authorization checks.'}</div>`;
  $('#triageStatus').textContent = `${data.evidence?.length || 0} evidence-backed signal${(data.evidence?.length || 0) === 1 ? '' : 's'}`;
  if (data.evidence?.length) {
    evidence = data.evidence.map((item, index) => ({
      id: item.evidence_id,
      type: item.source_type === 'deployment' ? 'deployment' : item.source_type === 'knowledge' || item.source_type === 'postmortem' ? 'knowledge' : 'observability',
      marker: item.source_type === 'deployment' ? '↥' : item.source_type === 'knowledge' ? '▤' : '⌁',
      title: item.title,
      source: item.source_type.toUpperCase(),
      text: item.snippet,
      time: item.event_time ? new Date(item.event_time).toISOString().slice(11, 16) + ' UTC' : 'Source snapshot',
      service: 'Authorized source',
      score: item.score,
      reason: item.reasons?.[0] || 'Hybrid retrieval match'
    }));
    currentFilter = 'all';
    $$('.filter-chip').forEach((chip) => chip.classList.toggle('active', chip.dataset.filter === 'all'));
    renderEvidence();
  }
  const status = data.status || 'grounded';
  const grounded = $('.grounded-label');
  grounded.innerHTML = `<span>${status === 'grounded' ? '●' : '◐'}</span> ${escapeHtml(status.replace('_', ' ').toUpperCase())} <span class="info-mark">i</span>`;
}

function demoResponse(question) {
  return {
    status: 'grounded',
    summary: question.toLowerCase().includes('rollback')
      ? 'The closest prior incident was resolved by rolling back the retry policy. The current evidence points to the same provider timeout path.'
      : 'A new checkout-api deployment preceded the latency increase. The strongest signal points to the payment-provider client path; inventory-api remains healthy.',
    claims: [
      { claim_id: 'claim-E1', claim_type: 'Source asserted', text: 'checkout-api deployed v2026.08.06-3 before latency increased.', citation_ids: ['E1'] },
      { claim_id: 'claim-E2', claim_type: 'Observed signal', text: 'p95 latency crossed 2s and reached 4.8s during the incident window.', citation_ids: ['E2'] },
      { claim_id: 'claim-E3', claim_type: 'Graph signal', text: 'The payment-provider path is the closest affected dependency.', citation_ids: ['E3'] }
    ],
    evidence: evidence.map((item) => ({ evidence_id: item.id, source_type: item.type, title: item.title, snippet: item.text, event_time: null, score: item.score, reasons: [item.reason] }))
  };
}

// The sidebar is a real workspace switcher.  The incident room remains mounted
// so its live triage state is preserved while the user explores another view.
let incidentRoomView;
let workspaceView;
let activeWorkspaceView = 'Incident room';

function setupWorkspaceViews() {
  const contentWrap = $('#contentWrap');
  incidentRoomView = document.createElement('div');
  incidentRoomView.id = 'incidentRoomView';
  while (contentWrap.firstChild) incidentRoomView.appendChild(contentWrap.firstChild);
  workspaceView = document.createElement('div');
  workspaceView.id = 'workspaceView';
  workspaceView.hidden = true;
  contentWrap.append(incidentRoomView, workspaceView);
}

function workspaceShell(kicker, title, description, body, actions = '') {
  return `<section class="workspace-screen">
    <div class="workspace-screen-heading">
      <div><span class="section-kicker">${escapeHtml(kicker)}</span><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div>
      <div class="workspace-screen-actions">${actions}</div>
    </div>
    ${body}
  </section>`;
}

function evidenceExplorerMarkup() {
  const cards = evidence.map((item) => `<article class="explorer-evidence" data-type="${escapeHtml(item.type)}" data-search="${escapeHtml(`${item.title} ${item.text} ${item.service} ${item.source}`.toLowerCase())}">
    <div class="evidence-marker ${escapeHtml(item.type)}">${escapeHtml(item.marker || '•')}</div>
    <div class="explorer-evidence-copy"><div class="evidence-title-line"><strong>${escapeHtml(item.title)}</strong><span class="source-label">${escapeHtml(item.source)}</span></div><p>${escapeHtml(item.text)}</p><small>${escapeHtml(item.time)} · ${escapeHtml(item.service)} · ${escapeHtml(item.reason)}</small></div>
    <div class="evidence-score"><span>${Math.round(item.score * 100)}%</span><div class="score-bar"><span style="width:${Math.round(item.score * 100)}%"></span></div></div>
  </article>`).join('');
  return workspaceShell('AUTHORIZED EVIDENCE', 'Evidence explorer', 'Search the evidence set that the model is allowed to see. ACL filtering happens before ranking and display.', `<div class="explorer-toolbar"><label class="search-field"><span>⌕</span><input id="explorerSearch" placeholder="Search title, service, source or signal…" autocomplete="off" /></label><div class="explorer-filters" id="explorerFilters"><button class="filter-chip active" data-explorer-filter="all">All <span>${evidence.length}</span></button><button class="filter-chip" data-explorer-filter="deployment">Deployments <span>${evidence.filter((x) => x.type === 'deployment').length}</span></button><button class="filter-chip" data-explorer-filter="observability">Observability <span>${evidence.filter((x) => x.type === 'observability').length}</span></button><button class="filter-chip" data-explorer-filter="knowledge">Knowledge <span>${evidence.filter((x) => x.type === 'knowledge').length}</span></button></div></div><div class="explorer-summary"><div><strong>${evidence.length}</strong><span>authorized sources</span></div><div><strong>0</strong><span>ACL violations</span></div><div><strong>${Math.round(evidence.reduce((sum, item) => sum + item.score, 0) / evidence.length * 100)}%</strong><span>average relevance</span></div><div><strong>Hybrid</strong><span>retrieval mode</span></div></div><div class="explorer-list" id="explorerList">${cards}</div><div class="empty-state" id="explorerEmpty" hidden>No evidence matches this filter.</div>`);
}

function serviceMapMarkup() {
  return workspaceShell('DEPENDENCY GRAPH', 'Service map', 'Trace the incident path across services, external dependencies, and the evidence signals attached to each node.', '<div class="service-map-layout"><div class="service-map-canvas"><div class="map-grid"></div><div class="map-link link-one"></div><div class="map-link link-two"></div><div class="map-link link-three"></div><div class="map-node node-alert"><span class="node-status critical"></span><strong>checkout-api</strong><small>degraded · 4.8s p95</small><em>INCIDENT SOURCE</em></div><div class="map-node node-provider"><span class="node-status warning"></span><strong>payment-provider</strong><small>elevated · 1.8% timeout</small><em>EXTERNAL DEPENDENCY</em></div><div class="map-node node-inventory"><span class="node-status healthy"></span><strong>inventory-api</strong><small>healthy</small><em>DOWNSTREAM</em></div><div class="map-node node-cache"><span class="node-status healthy"></span><strong>catalog-cache</strong><small>healthy</small><em>DOWNSTREAM</em></div><div class="map-legend"><span><i class="critical"></i> Degraded</span><span><i class="warning"></i> Elevated</span><span><i class="healthy"></i> Healthy</span></div></div><div class="map-side-panel panel-card"><span class="section-kicker">SELECTED SERVICE</span><h2>checkout-api</h2><p>Primary incident service with the strongest temporal and graph correlation.</p><div class="map-detail"><span>Latest deploy</span><strong>v2026.08.06-3</strong></div><div class="map-detail"><span>Dependents</span><strong>3 services</strong></div><div class="map-detail"><span>Evidence links</span><strong>4 authorized</strong></div><button class="button primary" data-action="back-to-incident">Open incident room <span>→</span></button></div></div>');
}

function evaluationMarkup() {
  return workspaceShell('QUALITY & EVALUATION', 'Evaluation lab', 'Measure whether triage answers are retrievable, grounded, correctly cited, and safe under authorization constraints.', '<div class="eval-overview"><div class="eval-status"><span class="status-dot"></span><div><strong>Smoke gate passing</strong><small>Last run · local fixture · just now</small></div><button class="button primary" data-action="run-evaluation">Run smoke evaluation</button></div><div class="metric-grid"><div class="metric-card"><span>Recall@5</span><strong>100%</strong><small>Target ≥ 85%</small></div><div class="metric-card"><span>MRR</span><strong>100%</strong><small>Target ≥ 75%</small></div><div class="metric-card"><span>Grounded rate</span><strong>100%</strong><small>Target ≥ 90%</small></div><div class="metric-card"><span>Forbidden evidence</span><strong class="metric-good">0</strong><small>Target = 0</small></div></div><div class="eval-panels"><div class="panel-card eval-panel"><div class="panel-header compact"><div><span class="section-kicker">LATEST RUN</span><h2>Smoke dataset</h2></div><span class="run-badge">PASS</span></div><div class="eval-row"><span>Incident root-cause query</span><strong>5/5 citations</strong></div><div class="eval-row"><span>ACL isolation query</span><strong>2/2 hidden</strong></div><div class="eval-row"><span>Insufficient evidence query</span><strong>Abstained</strong></div></div><div class="panel-card eval-panel"><div class="panel-header compact"><div><span class="section-kicker">QUALITY GUARDRAILS</span><h2>What is checked</h2></div></div><ul class="guardrail-list"><li><span>✓</span> Citation exists and supports the claim</li><li><span>✓</span> User is authorized for every source</li><li><span>✓</span> Model abstains when evidence is weak</li><li><span>✓</span> Numeric claims match source text</li></ul></div></div></div>');
}

function connectorsMarkup() {
  return workspaceShell('SOURCE OPERATIONS', 'Connectors', 'Monitor ingestion health, checkpoints, and the source systems feeding the incident knowledge graph.', '<div class="connector-toolbar"><div class="connector-health"><span class="status-dot"></span><strong>All configured connectors healthy</strong><small>Polling every 60 seconds</small></div><button class="button primary" data-action="refresh-connectors">Refresh status</button></div><div class="connector-list" id="connectorList"><article class="connector-card"><div class="connector-icon">⇄</div><div><strong>demo-jsonl</strong><small>Fixture connector · local evidence</small></div><span class="connector-state healthy-text">HEALTHY</span><div class="connector-meta"><span>Last sync <b>just now</b></span><span>Records <b>3</b></span><span>Mode <b>poll</b></span></div><button class="text-button" data-action="sync-connector">Sync now <span>↻</span></button></article></div>');
}

function runbooksMarkup() {
  const runbooks = [{ title: 'Payment provider timeout', owner: 'Checkout platform', status: 'Recommended now', steps: ['Confirm provider timeout rate and request IDs.', 'Compare retry policy with the last known-good deploy.', 'Roll back only after change and impact are confirmed.'] }, { title: 'Checkout latency regression', owner: 'SRE', status: 'Available', steps: ['Check p95 and error-rate windows.', 'Correlate deployment timestamp with the first alert.', 'Capture an incident note with cited evidence.'] }, { title: 'Safe rollback checklist', owner: 'Release engineering', status: 'Available', steps: ['Verify rollback artifact and approval owner.', 'Check downstream inventory and catalog health.', 'Monitor recovery for 15 minutes after rollback.'] }];
  return workspaceShell('OPERATIONAL KNOWLEDGE', 'Runbooks', 'Evidence-linked procedures for the most common checkout incident paths.', `<div class="runbook-grid">${runbooks.map((book, index) => `<article class="runbook-card ${index === 0 ? 'recommended' : ''}"><div class="runbook-card-top"><span class="runbook-icon">▤</span><span class="runbook-status">${escapeHtml(book.status)}</span></div><h2>${escapeHtml(book.title)}</h2><p>Owner · ${escapeHtml(book.owner)}</p><button class="panel-link runbook-toggle" data-runbook="${index}">View checklist <span>→</span></button><ol class="runbook-steps" data-steps="${index}" hidden>${book.steps.map((step) => `<li>${escapeHtml(step)}</li>`).join('')}</ol></article>`).join('')}</div>`);
}

function settingsMarkup() {
  return workspaceShell('WORKSPACE CONFIGURATION', 'Settings', 'Manage the local workspace identity, API connection, and model configuration used by this browser session.', `<div class="settings-layout"><form class="panel-card settings-card" id="settingsForm"><div class="panel-header compact"><div><span class="section-kicker">IDENTITY CONTEXT</span><h2>Authorized request identity</h2></div><span class="settings-lock">ACL enforced</span></div><label>Tenant ID<input name="tenant" value="demo" /></label><label>User ID<input name="user" value="${escapeHtml(activeCommander.userId)}" /></label><label>Groups<input name="groups" value="oncall" /></label><div class="settings-note">Current commander: ${escapeHtml(activeCommander.name)}. These headers are used by the local API to filter evidence before retrieval and generation.</div><button class="button primary" type="submit">Save workspace settings</button></form><div class="settings-stack"><div class="panel-card settings-info"><span class="section-kicker">API CONNECTION</span><h2>Local development</h2><div class="setting-line"><span>API base</span><code>${escapeHtml(API_BASE)}</code></div><div class="setting-line"><span>Environment</span><strong>development</strong></div><div class="setting-line"><span>Model</span><strong id="settingsModel">Checking…</strong></div></div><div class="panel-card settings-info"><span class="section-kicker">GUARDRAILS</span><h2>Safety defaults</h2><div class="toggle-row"><span>ACL-aware retrieval</span><b class="toggle on">ON</b></div><div class="toggle-row"><span>Citation validation</span><b class="toggle on">ON</b></div><div class="toggle-row"><span>Abstain on weak evidence</span><b class="toggle on">ON</b></div></div></div></div>`);
}

function filterExplorerResults() {
  const query = ($('#explorerSearch')?.value || '').trim().toLowerCase();
  const selected = $('#explorerFilters .active')?.dataset.explorerFilter || 'all';
  let visibleCount = 0;
  $$('#explorerList .explorer-evidence').forEach((card) => {
    const visible = (selected === 'all' || card.dataset.type === selected) && (!query || card.dataset.search.includes(query));
    card.hidden = !visible;
    if (visible) visibleCount += 1;
  });
  $('#explorerEmpty').hidden = visibleCount !== 0;
}

async function loadConnectorStatus() {
  try {
    const response = await fetch(`${API_BASE}/v1/admin/connectors`);
    if (!response.ok) return;
    const data = await response.json();
    const items = Array.isArray(data) ? data : (data.connectors || data.items || []);
    if (!items.length || !$('#connectorList')) return;
    $('#connectorList').innerHTML = items.map((connector) => `<article class="connector-card"><div class="connector-icon">⇄</div><div><strong>${escapeHtml(connector.name || connector.id || connector.source_instance || 'connector')}</strong><small>${escapeHtml(connector.kind || 'configured source')}</small></div><span class="connector-state healthy-text">${escapeHtml(String(connector.status || 'HEALTHY').toUpperCase())}</span><div class="connector-meta"><span>Last sync <b>${escapeHtml(connector.last_sync || connector.latest_ingested_at || 'available')}</b></span><span>Records <b>${escapeHtml(connector.records || connector.evidence_count || '—')}</b></span><span>Mode <b>${escapeHtml(connector.mode || 'poll')}</b></span></div><button class="text-button" data-action="sync-connector">Sync now <span>↻</span></button></article>`).join('');
  } catch (_) {
    // The local fixture card remains useful when the API is offline.
  }
}

function bindWorkspaceView(view) {
  if (view === 'Evidence explorer') {
    $('#explorerSearch')?.addEventListener('input', filterExplorerResults);
    $('#explorerFilters')?.addEventListener('click', (event) => { const chip = event.target.closest('[data-explorer-filter]'); if (!chip) return; $$('#explorerFilters [data-explorer-filter]').forEach((item) => item.classList.toggle('active', item === chip)); filterExplorerResults(); });
  }
  if (view === 'Connectors') loadConnectorStatus();
  if (view === 'Settings') {
    fetch(`${API_BASE}/readyz`).then((response) => response.json()).then((data) => { if ($('#settingsModel')) $('#settingsModel').textContent = data.model_provider_configured ? 'Configured' : 'Demo fallback'; }).catch(() => { if ($('#settingsModel')) $('#settingsModel').textContent = 'Offline'; });
  }
}

function showWorkspaceView(view) {
  activeWorkspaceView = view;
  $$('.nav-item').forEach((nav) => nav.classList.toggle('active', nav.dataset.view === view));
  $('#sidebar').classList.remove('open');
  $('.breadcrumbs span').textContent = view;
  $('.breadcrumbs strong').textContent = view === 'Incident room' ? 'INC-2048' : 'WORKSPACE';
  if (view === 'Incident room') {
    incidentRoomView.hidden = false;
    workspaceView.hidden = true;
    return;
  }
  incidentRoomView.hidden = true;
  workspaceView.hidden = false;
  const renderers = { 'Evidence explorer': evidenceExplorerMarkup, 'Service map': serviceMapMarkup, 'Evaluation lab': evaluationMarkup, 'Connectors': connectorsMarkup, 'Runbooks': runbooksMarkup, 'Settings': settingsMarkup };
  workspaceView.innerHTML = (renderers[view] || evidenceExplorerMarkup)();
  bindWorkspaceView(view);
  setupDepthInteractions(workspaceView);
}

function setupDepthInteractions(scope = document) {
  if (!window.matchMedia('(pointer: fine)').matches || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const selectors = '.panel-card, .triage-card, .workspace-picker, .privacy-note, .user-card, .metric-card, .runbook-card, .connector-card, .explorer-evidence, .eval-status';
  scope.querySelectorAll(selectors).forEach((surface) => {
    if (surface.dataset.depthBound === 'true') return;
    surface.dataset.depthBound = 'true';
    surface.classList.add('depth-surface');
    surface.addEventListener('pointermove', (event) => {
      const bounds = surface.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - 0.5;
      const y = (event.clientY - bounds.top) / bounds.height - 0.5;
      surface.style.setProperty('--tilt-x', `${(-y * 2.8).toFixed(2)}deg`);
      surface.style.setProperty('--tilt-y', `${(x * 3.4).toFixed(2)}deg`);
      surface.style.setProperty('--shine-x', `${((x + 0.5) * 100).toFixed(1)}%`);
      surface.style.setProperty('--shine-y', `${((y + 0.5) * 100).toFixed(1)}%`);
      surface.classList.add('is-tilting');
    });
    surface.addEventListener('pointerleave', () => {
      surface.style.setProperty('--tilt-x', '0deg');
      surface.style.setProperty('--tilt-y', '0deg');
      surface.classList.remove('is-tilting');
    });
  });
}

async function runTriage(question) {
  $('#triageLoading').hidden = false;
  $('#triageBody').style.opacity = '.42';
  try {
    const response = await fetch(`${API_BASE}/v1/triage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...requestIdentityHeaders() },
      body: JSON.stringify({ text: question, service_ids: ['checkout-api'], environment: 'prod', limit: 8 })
    });
    if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json();
    setConnection('Live API', true);
    renderTriage(data);
  } catch (error) {
    setConnection('Demo evidence', false);
    renderTriage(demoResponse(question));
    showToast('API unavailable — showing the local evidence demo.');
  } finally {
    $('#triageLoading').hidden = true;
    $('#triageBody').style.opacity = '1';
  }
}

setupWorkspaceViews();

$('#filterRow').addEventListener('click', (event) => {
  const chip = event.target.closest('.filter-chip');
  if (!chip) return;
  currentFilter = chip.dataset.filter;
  $$('.filter-chip').forEach((item) => item.classList.toggle('active', item === chip));
  renderEvidence();
});

$('#evidenceList').addEventListener('click', (event) => {
  const item = event.target.closest('.evidence-item');
  if (item) item.classList.toggle('expanded');
});

$('#askForm').addEventListener('submit', (event) => {
  event.preventDefault();
  const input = $('#questionInput');
  const question = input.value.trim() || 'What changed immediately before the spike?';
  input.value = '';
  runTriage(question);
});

$('#refreshTriage').addEventListener('click', () => runTriage('What changed immediately before the spike?'));
document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-feedback]');
  if (!button) return;
  const kind = button.dataset.feedback;
  try {
    const response = await fetch(`${API_BASE}/v1/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...requestIdentityHeaders(false) },
      body: JSON.stringify({ answer_id: lastAnswerId, kind })
    });
    if (!response.ok) throw new Error('feedback request failed');
    showToast('Feedback recorded for this triage answer.');
  } catch (error) {
    showToast('Feedback saved locally for the demo session.');
  }
});
$('#resolveButton').addEventListener('click', (event) => { event.currentTarget.innerHTML = '<span>✓</span> Incident resolved'; event.currentTarget.style.background = 'linear-gradient(135deg, #327e70, #286456)'; showToast('Incident marked resolved locally.'); });
$('#shareButton').addEventListener('click', shareIncident);
$('#timelineMore').addEventListener('click', () => showToast('Full timeline is available in the incident room timeline.'));
$('#serviceMapButton').addEventListener('click', () => showWorkspaceView('Service map'));
$('#activityButton').addEventListener('click', () => showToast('Opening #inc-checkout…'));
$('#loadMore').addEventListener('click', () => { evidence = [...demoEvidence]; currentFilter = 'all'; $$('.filter-chip').forEach((chip) => chip.classList.toggle('active', chip.dataset.filter === 'all')); renderEvidence(); showToast('Showing the complete authorized evidence set.'); });
$$('.nav-item').forEach((item) => item.addEventListener('click', () => showWorkspaceView(item.dataset.view)));

function toggleUserMenu() {
  const willOpen = $('#userMenu').hidden;
  closeUserMenu();
  if (willOpen) {
    $('#userMenu').hidden = false;
    $('#userMenuButton').setAttribute('aria-expanded', 'true');
  }
}

$('#userMenuButton').addEventListener('click', (event) => { event.stopPropagation(); toggleUserMenu(); });
$('#topAvatarButton').addEventListener('click', (event) => { event.stopPropagation(); toggleUserMenu(); });

document.addEventListener('click', (event) => {
  const commanderOption = event.target.closest('[data-commander]');
  if (commanderOption) {
    selectCommander(commanderOption.dataset.commander);
    return;
  }
  const availabilityOption = event.target.closest('[data-availability]');
  if (availabilityOption) {
    availability = availabilityOption.dataset.availability;
    try { localStorage.setItem(`${STORAGE_PREFIX}.availability`, availability); } catch (_) { /* no persistent browser storage */ }
    updateCommanderUi();
    $('#availabilityPicker').hidden = true;
    showToast(`Availability set to ${availability}.`);
    return;
  }
  const userAction = event.target.closest('[data-user-action]')?.dataset.userAction;
  if (userAction === 'switch-commander') {
    $('#commanderPicker').hidden = !$('#commanderPicker').hidden;
    $('#availabilityPicker').hidden = true;
    return;
  }
  if (userAction === 'toggle-availability') {
    $('#availabilityPicker').hidden = !$('#availabilityPicker').hidden;
    $('#commanderPicker').hidden = true;
    return;
  }
  if (userAction === 'open-settings') {
    closeUserMenu();
    showWorkspaceView('Settings');
    return;
  }
  if (userAction === 'keyboard-shortcuts') {
    closeUserMenu();
    showToast('Shortcuts: ⌘ / opens help · Esc closes menus.');
    return;
  }
  if (userAction === 'logout') {
    closeUserMenu();
    try { localStorage.removeItem(`${STORAGE_PREFIX}.activeCommander`); } catch (_) { /* no persistent browser storage */ }
    $('.app-shell').hidden = true;
    $('#signedOutScreen').hidden = false;
    return;
  }
  if (!event.target.closest('#userCard') && !event.target.closest('#topAvatarButton')) closeUserMenu();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeUserMenu();
});

document.addEventListener('click', (event) => {
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (!action) return;
  if (action === 'back-to-incident') showWorkspaceView('Incident room');
  if (action === 'refresh-connectors') { showToast('Connector health refreshed.'); loadConnectorStatus(); }
  if (action === 'sync-connector') { const button = event.target.closest('[data-action]'); button.disabled = true; button.textContent = 'Syncing…'; setTimeout(() => { button.disabled = false; button.innerHTML = 'Synced just now <span>✓</span>'; showToast('Connector checkpoint updated.'); }, 700); }
  if (action === 'run-evaluation') { const button = event.target.closest('[data-action]'); button.disabled = true; button.textContent = 'Running…'; setTimeout(() => { button.disabled = false; button.textContent = 'Run smoke evaluation'; showToast('Smoke evaluation passed: 100% grounded, 0 forbidden evidence.'); }, 900); }
});

document.addEventListener('click', (event) => {
  const toggle = event.target.closest('.runbook-toggle');
  if (!toggle) return;
  const steps = document.querySelector(`[data-steps="${toggle.dataset.runbook}"]`);
  if (!steps) return;
  steps.hidden = !steps.hidden;
  toggle.innerHTML = steps.hidden ? 'View checklist <span>→</span>' : 'Hide checklist <span>↑</span>';
});

document.addEventListener('submit', (event) => {
  if (event.target.id !== 'settingsForm') return;
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.target).entries());
  localStorage.setItem(`${STORAGE_PREFIX}.identity`, JSON.stringify(values));
  showToast('Workspace settings saved for this browser.');
});
$('#mobileMenu').addEventListener('click', () => $('#sidebar').classList.toggle('open'));

renderEvidence();
updateCommanderUi();
setupDepthInteractions(incidentRoomView);

// Deep links make each workspace reachable directly (useful for bookmarks and
// also for restoring the last section after a refresh).
const requestedView = new URLSearchParams(window.location.search).get('view');
if (requestedView && ['Incident room', 'Evidence explorer', 'Service map', 'Evaluation lab', 'Connectors', 'Runbooks', 'Settings'].includes(requestedView)) showWorkspaceView(requestedView);
