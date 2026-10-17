/**
 * Main application logic. All user-supplied text is escaped before it touches innerHTML.
 */
const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const safeUrl = (u) => (/^https?:\/\/[^\s<>"']+$/i.test(u || '') ? u : '');

const CATS = {
  ELECTRICAL: { icon: '⚡', title: 'Electrical & Power Grid' },
  WATER_DRAINAGE: { icon: '💧', title: 'Water Main & Drainage' },
  SEWAGE_MANHOLE: { icon: '⚠️', title: 'Open Sewer & Manhole' },
  GAS_PIPELINE: { icon: '🔥', title: 'Gas & Pipeline Fault' },
  ROADWAY_STRUCTURE: { icon: '🚧', title: 'Roadway & Structural Hazard' }
};
const STEP = { REPORTED: 1, ACKNOWLEDGED: 2, DISPATCHED: 3, ON_SITE_VERIFIED: 4, IN_PROGRESS: 5, RESOLVED: 6 };
const LOG_LABEL = {
  TICKET_CREATED: '📢 Ticket registered by citizen',
  ACKNOWLEDGED: '📋 Acknowledged by control room',
  CREW_DISPATCHED: '🚀 Field crew dispatched',
  ON_SITE_VERIFIED: '🔍 On-site verification completed',
  DUPLICATE_REPORT_REINFORCED: '🛡️ Duplicate report merged',
  RESOLVED: '✅ Hazard resolved'
};

function ago(iso) {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso)) / 60000));
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  if (m < 1440) return `${Math.floor(m / 60)} h ago`;
  return `${Math.floor(m / 1440)} d ago`;
}
const stamp = (iso) => new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

function distMeters(aLat, aLng, bLat, bLng) {
  const R = 6371000, rad = Math.PI / 180;
  const dLat = (bLat - aLat) * rad, dLng = (bLng - aLng) * rad;
  const x = Math.sin(dLat / 2) ** 2 + Math.cos(aLat * rad) * Math.cos(bLat * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
}

window.App = {
  role: 'citizen',
  filters: { urgency: 'All', status: 'All', sector: 'All', search: '' },
  hazards: [],
  sectors: [],
  category: 'ELECTRICAL',
  urgency: 'Medium',
  busy: false,

  async init() {
    this.bindEvents();
    MapEngine.init('gis-map-mount', (c) => this.setPin(c.lat, c.lng));
    const sec = await API.getSectors().catch(() => null);
    if (sec && sec.ok) {
      this.sectors = sec.data.sectors;
      const opts = this.sectors.map((s) => `<option value="${esc(s.id)}">${esc(s.id)}: ${esc(s.name)}</option>`).join('');
      $('input-sector').innerHTML = opts;
      $('filter-sector').innerHTML = '<option value="All">All Sectors</option>' + opts;
    }
    if (API.pin) {
      const r = await API.crewLogin().catch(() => null);
      if (r && r.ok) this.setRole('dispatcher'); else API.setPin('');
    }
    await this.refresh();
    setInterval(() => { if (!document.hidden) this.refresh(); }, 10000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) this.refresh(); });
  },

  bindEvents() {
    document.querySelectorAll('.nav-btn[data-role]').forEach((btn) =>
      btn.addEventListener('click', () => {
        const role = btn.dataset.role;
        if (role === 'dispatcher' && !API.pin) return this.openModal('modal-login', 'login-pin');
        this.setRole(role);
      }));
    $('btn-crew-out').addEventListener('click', () => { API.setPin(''); this.setRole('citizen'); this.refresh(); });

    document.querySelectorAll('.category-option').forEach((o) =>
      o.addEventListener('click', () => {
        document.querySelectorAll('.category-option').forEach((x) => x.classList.remove('selected'));
        o.classList.add('selected');
        this.category = o.dataset.cat;
      }));
    document.querySelectorAll('.urgency-btn').forEach((b) =>
      b.addEventListener('click', () => {
        document.querySelectorAll('.urgency-btn').forEach((x) => x.classList.remove('selected'));
        b.classList.add('selected');
        this.urgency = b.dataset.level;
      }));

    $('input-photo').addEventListener('input', (e) => this.previewPhoto(e.target.value));
    $('btn-gps-autotag').addEventListener('click', () => this.useGps());
    $('hazard-form').addEventListener('submit', (e) => this.submitHazard(e));
    $('login-form').addEventListener('submit', (e) => this.submitLogin(e));
    $('dispatch-form').addEventListener('submit', (e) => this.submitDispatch(e));
    $('verify-form').addEventListener('submit', (e) => this.submitVerify(e));
    $('resolve-form').addEventListener('submit', (e) => this.submitResolve(e));

    $('input-search').addEventListener('input', (e) => { this.filters.search = e.target.value.trim(); this.renderList(); });
    $('filter-sector').addEventListener('change', (e) => { this.filters.sector = e.target.value; this.renderList(); });
    ['urgency', 'status'].forEach((key) =>
      document.querySelectorAll(`.pill-filter[data-filter="${key}"]`).forEach((p) =>
        p.addEventListener('click', () => {
          document.querySelectorAll(`.pill-filter[data-filter="${key}"]`).forEach((x) => x.classList.remove('active'));
          p.classList.add('active');
          this.filters[key] = p.dataset.val;
          this.renderList();
        })));

    document.querySelectorAll('.modal-close, [data-dismiss="modal"]').forEach((b) => b.addEventListener('click', () => this.closeModals()));
    document.querySelectorAll('.modal-backdrop').forEach((m) => m.addEventListener('click', (e) => { if (e.target === m) this.closeModals(); }));
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') this.closeModals(); });

    // Feed actions (event delegation, no inline handlers)
    const feed = $('incidents-feed-list');
    feed.addEventListener('click', (e) => {
      const el = e.target.closest('[data-act]');
      if (!el) return;
      const id = Number(el.dataset.id);
      const h = this.hazards.find((x) => x.id === id);
      const act = el.dataset.act;
      if (act === 'log') this.openTimeline(id);
      else if (act === 'upvote') this.upvote(id, el);
      else if (act === 'ack') this.acknowledge(id, el);
      else if (act === 'dispatch' && h) this.openAction('modal-dispatch', 'dispatch-hazard-id', id, 'dispatch-modal-title', `Dispatch crew to #${h.ticket_code}`);
      else if (act === 'verify' && h) { $('verify-crew-id').value = h.assigned_crew_id || ''; this.openAction('modal-verify', 'verify-hazard-id', id, 'verify-modal-title', `Log on-site verification: #${h.ticket_code}`); }
      else if (act === 'resolve' && h) { $('resolve-crew-id').value = h.assigned_crew_id || ''; this.openAction('modal-resolve', 'resolve-hazard-id', id, 'resolve-modal-title', `Mark resolved: #${h.ticket_code}`); }
    });
    feed.addEventListener('error', (e) => {
      if (e.target.tagName === 'IMG') e.target.replaceWith(Object.assign(document.createElement('div'), { className: 'thumb-ph', textContent: '📷' }));
    }, true);
  },

  // ---------- roles / auth ----------
  setRole(role) {
    this.role = role;
    document.querySelectorAll('.nav-btn[data-role]').forEach((b) => b.classList.toggle('active', b.dataset.role === role));
    $('btn-crew-out').style.display = API.pin ? '' : 'none';
    this.renderList();
  },
  onAuthLost() {
    this.setRole('citizen');
    this.toast('Crew session ended. Sign in again to continue.', true);
  },
  async submitLogin(e) {
    e.preventDefault();
    const err = $('login-error');
    err.textContent = '';
    API.setPin($('login-pin').value.trim());
    const r = await API.crewLogin().catch((x) => ({ ok: false, data: { message: x.message } }));
    if (!r.ok) { API.setPin(''); err.textContent = r.data.message || 'Sign-in failed.'; return; }
    $('login-pin').value = '';
    this.closeModals();
    this.setRole('dispatcher');
    this.refresh();
    this.toast('Crew mode on.');
  },

  // ---------- geotag ----------
  setPin(lat, lng) {
    lat = Number(Number(lat).toFixed(5)); lng = Number(Number(lng).toFixed(5));
    $('input-lat').value = lat;
    $('input-lng').value = lng;
    const hint = $('pin-status');
    hint.textContent = 'Pin set. Sector chosen from the pin; change it below if needed.';
    hint.classList.add('ok');
    if (this.sectors.length) {
      const nearest = this.sectors.reduce((a, s) => (distMeters(lat, lng, s.lat, s.lng) < distMeters(lat, lng, a.lat, a.lng) ? s : a));
      $('input-sector').value = nearest.id;
    }
  },
  clearPin() {
    $('input-lat').value = ''; $('input-lng').value = '';
    const hint = $('pin-status');
    hint.textContent = 'No pin yet. Click the map or use GPS to mark the hazard.';
    hint.classList.remove('ok');
    MapEngine.clearSelection();
  },
  useGps() {
    if (!navigator.geolocation) return this.toast('GPS is not available in this browser. Click the map instead.', true);
    navigator.geolocation.getCurrentPosition(
      (pos) => { this.setPin(pos.coords.latitude, pos.coords.longitude); MapEngine.updateSelectionMarker(pos.coords.latitude, pos.coords.longitude); MapEngine.focus(pos.coords.latitude, pos.coords.longitude); },
      () => this.toast('Could not read your location. Allow location access or click the map.', true),
      { enableHighAccuracy: true, timeout: 10000 });
  },
  previewPhoto(url) {
    const wrap = $('photo-preview-wrap');
    const u = safeUrl(url.trim());
    wrap.innerHTML = '';
    if (!u) { wrap.style.display = 'none'; return; }
    const img = document.createElement('img');
    img.alt = 'Photo preview'; img.referrerPolicy = 'no-referrer'; img.src = u;
    img.addEventListener('error', () => { wrap.textContent = 'This link does not load as an image.'; });
    wrap.appendChild(img);
    wrap.style.display = '';
  },

  // ---------- data ----------
  async refresh() {
    try {
      const [stats, list] = await Promise.all([API.getStats(), API.getHazards()]);
      $('net-banner').style.display = 'none';
      if (stats.ok) this.updateStats(stats.data);
      if (list.ok) {
        this.hazards = list.data.hazards || [];
        this.renderList();
        MapEngine.renderHazards(this.hazards);
      }
    } catch (e) {
      $('net-banner').style.display = 'block';
    }
  },
  updateStats(s) {
    $('stat-critical').textContent = `${s.critical_active} Critical Outages`;
    $('stat-dispatched').textContent = `${s.dispatched_crews + s.on_site_verified} Crews Deployed`;
    $('stat-resolved').textContent = `${s.resolved_tickets} Resolved`;
    $('stat-prevented').textContent = `${s.duplicates_prevented} Dupes Blocked`;
  },

  // ---------- citizen actions ----------
  showAlert(kind, html) {
    const box = $('submission-alert');
    box.className = `alert-box ${kind}`;
    box.innerHTML = html;
    box.style.display = 'block';
  },
  async submitHazard(e) {
    e.preventDefault();
    if (this.busy) return;
    $('submission-alert').style.display = 'none';
    if (!$('input-lat').value || !$('input-lng').value) {
      this.showAlert('alert-duplicate', '<h4>Mark the location</h4><p>Click the map or use GPS so crews know where to go.</p>');
      return;
    }
    const btn = $('btn-submit-hazard');
    this.busy = true; btn.disabled = true;
    btn.innerHTML = '<span>⏳ Checking for duplicates...</span>';
    const payload = {
      category: this.category,
      landmark: $('input-landmark').value.trim(),
      urgency: this.urgency,
      sector_id: $('input-sector').value,
      latitude: Number($('input-lat').value),
      longitude: Number($('input-lng').value),
      photo_url: $('input-photo').value.trim(),
      description: $('input-desc').value.trim(),
      citizen_contact: $('input-contact').value.trim()
    };
    try {
      const r = await API.submitHazard(payload);
      if (r.status === 409 && r.data.duplicate_rejected) {
        const d = r.data.existing_ticket;
        this.showAlert('alert-duplicate', `
          <h4>⚠️ Already on the board</h4>
          <p>${esc(r.data.message)}</p>
          <div style="margin-top:8px;font-size:0.82rem;background:rgba(0,0,0,0.25);padding:8px;border-radius:6px;">
            <b>Ticket:</b> #${esc(d.ticket_code)} &nbsp;|&nbsp; <b>Status:</b> ${esc(d.status)} &nbsp;|&nbsp;
            <b>Confirmations:</b> ${esc(d.upvotes)} ${d.assigned_crew_id ? `&nbsp;|&nbsp; <b>Crew:</b> ${esc(d.assigned_crew_id)}` : ''}
          </div>`);
        await this.refresh();
        this.highlight(d.id);
      } else if (r.ok) {
        const h = r.data.hazard;
        this.showAlert('alert-success', `
          <h4>✅ Report received</h4>
          <p>Ticket <b>#${esc(h.ticket_code)}</b> is live in <b>${esc(h.sector_name)}</b>. Depot: ${esc(h.sector_depot)}.</p>`);
        $('input-landmark').value = ''; $('input-desc').value = ''; $('input-photo').value = '';
        this.previewPhoto('');
        this.clearPin();
        await this.refresh();
        this.highlight(h.id);
      } else {
        this.showAlert('alert-duplicate', `<h4>Could not submit</h4><p>${esc(r.data.message || 'Submission failed.')}</p>`);
      }
    } catch (err) {
      this.showAlert('alert-duplicate', `<h4>Could not submit</h4><p>${esc(err.message)}</p>`);
    } finally {
      this.busy = false; btn.disabled = false;
      btn.innerHTML = '<span>🚨 Submit Hazard Report</span>';
    }
  },
  highlight(id) {
    const card = $(`hazard-card-${id}`);
    if (!card) return;
    try { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); } catch (e) { /* cosmetic only */ }
    card.style.boxShadow = '0 0 25px #f59e0b';
    setTimeout(() => { card.style.boxShadow = ''; }, 3500);
  },
  async upvote(id, el) {
    el.disabled = true;
    try {
      const r = await API.upvoteHazard(id);
      if (!r.ok) this.toast(r.data.message || 'Could not confirm.', true);
      else if (r.data.already_voted) this.toast('You already confirmed this hazard.');
      await this.refresh();
    } catch (e) { this.toast(e.message, true); el.disabled = false; }
  },

  // ---------- feed ----------
  renderList() {
    const f = this.filters;
    const q = f.search.toLowerCase();
    const items = this.hazards.filter((h) =>
      (f.urgency === 'All' || h.urgency === f.urgency) &&
      (f.status === 'All' || h.status === f.status) &&
      (f.sector === 'All' || h.sector_id === f.sector) &&
      (!q || h.ticket_code.toLowerCase().includes(q) || h.landmark.toLowerCase().includes(q) || (h.description || '').toLowerCase().includes(q)));
    $('feed-count').textContent = `Showing ${items.length} incident${items.length === 1 ? '' : 's'}`;
    $('incidents-feed-list').innerHTML = items.length
      ? items.map((h) => this.card(h)).join('')
      : `<div class="empty-state glass-panel"><div class="empty-icon">🛡️</div>
           <h3>${this.hazards.length ? 'No hazards match these filters' : 'No hazards reported yet'}</h3>
           <p>${this.hazards.length ? 'Change a filter to see more.' : 'Use the form to report the first one.'}</p></div>`;
  },
  actionButtons(h) {
    if (this.role !== 'dispatcher' || !API.pin || h.status === 'RESOLVED') return '';
    const b = (act, cls, label) => `<button class="btn-action ${cls}" data-act="${act}" data-id="${h.id}">${label}</button>`;
    if (h.status === 'REPORTED') return b('ack', 'btn-timeline', '📋 Acknowledge') + b('dispatch', 'btn-dispatch', '🚀 Dispatch crew');
    if (h.status === 'ACKNOWLEDGED') return b('dispatch', 'btn-dispatch', '🚀 Dispatch crew');
    if (h.status === 'DISPATCHED') return b('verify', 'btn-verify', '📋 Log on-site verification');
    return b('resolve', 'btn-resolve', '✅ Mark resolved');
  },
  card(h) {
    const border = h.status === 'RESOLVED' ? 'resolved-border' : { Critical: 'critical-border', Medium: 'medium-border' }[h.urgency] || 'low-border';
    const step = STEP[h.status] || 1;
    const cat = CATS[h.category] || { icon: '⚠️', title: h.category };
    const url = safeUrl(h.photo_url);
    const steps = [['Reported', 1], ['Triaged', 2], ['Dispatched', 3], ['On-Site Verified', 4], ['Resolved', 6]]
      .map(([label, at], i) => `<div class="step-item ${step >= at ? 'completed' : ''} ${at === 6 && step === 6 ? 'resolved' : ''} ${step === at ? 'active' : ''}">
        <div class="step-circle">${i + 1}</div><span class="step-label">${label}</span></div>`).join('');
    return `
      <div class="incident-card ${border}" id="hazard-card-${h.id}">
        <div class="inc-top">
          <div class="inc-meta">
            <span class="ticket-tag">#${esc(h.ticket_code)}</span>
            <span class="sector-tag">${esc(h.sector_id)}</span>
            <span class="time-ago" title="${esc(stamp(h.created_at))}">🕒 ${esc(ago(h.created_at))}</span>
          </div>
          <div class="badge-urgency ${esc(h.urgency.toLowerCase())}">${esc(h.urgency)} Urgency</div>
        </div>
        <div class="inc-content-row">
          <div class="inc-thumbnail" data-act="log" data-id="${h.id}">
            ${url ? `<img src="${esc(url)}" alt="Hazard photo" loading="lazy" referrerpolicy="no-referrer">` : `<div class="thumb-ph">${cat.icon}</div>`}
          </div>
          <div class="inc-details">
            <div class="inc-category-head">${cat.icon} ${esc(cat.title)}</div>
            <div class="inc-landmark">📍 ${esc(h.landmark)}</div>
            <p class="inc-desc">${esc(h.description || 'No additional details provided.')}</p>
          </div>
        </div>
        <div class="status-stepper"><div class="step-connector"></div>${steps}</div>
        <div class="inc-footer">
          <div class="inc-indicators">
            <button class="btn-upvote" data-act="upvote" data-id="${h.id}">👍 ${esc(h.upvotes)} Citizens Confirmed</button>
            ${h.duplicate_reports_count > 0 ? `<span class="duplicate-badge" title="Duplicate reports merged into this ticket">🛡️ ${esc(h.duplicate_reports_count)} Dupes Merged</span>` : ''}
            ${h.assigned_crew_id ? `<span class="crew-badge">👷 ${esc(h.assigned_crew_id)}</span>` : ''}
          </div>
          <div class="action-group">
            <button class="btn-action btn-timeline" data-act="log" data-id="${h.id}">📜 Audit Log (${esc(h.log_count || 1)})</button>
            ${this.actionButtons(h)}
          </div>
        </div>
      </div>`;
  },

  // ---------- timeline ----------
  async openTimeline(id) {
    const body = $('timeline-body');
    body.textContent = 'Loading audit log...';
    this.openModal('modal-timeline');
    try {
      const r = await API.getHazard(id);
      if (!r.ok) { body.textContent = r.data.message || 'Could not load this ticket.'; return; }
      const h = r.data;
      const cat = CATS[h.category] || { icon: '⚠️', title: h.category };
      $('timeline-modal-title').textContent = `Audit trail: #${h.ticket_code}`;
      body.innerHTML = `
        <div style="margin-bottom:1rem;background:var(--bg-card);padding:12px;border-radius:8px;">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <b>${cat.icon} ${esc(cat.title)}</b><span class="badge-urgency ${esc(h.urgency.toLowerCase())}">${esc(h.urgency)}</span>
          </div>
          <p style="font-size:0.85rem;color:#cbd5e1;">📍 ${esc(h.landmark)} (${esc(h.sector_name)})</p>
          ${h.description ? `<p style="font-size:0.82rem;color:#94a3b8;margin-top:4px;">${esc(h.description)}</p>` : ''}
          ${h.citizen_contact ? `<p style="font-size:0.82rem;color:#fde68a;margin-top:6px;">Citizen contact (crew only): ${esc(h.citizen_contact)}</p>` : ''}
        </div>
        <h4 style="font-size:0.85rem;color:#94a3b8;margin-bottom:0.75rem;">Chronological incident log</h4>
        <div class="timeline-list">
          ${h.logs.map((l) => {
            const dot = { ON_SITE_VERIFIED: 'verified', RESOLVED: 'resolved', DUPLICATE_REPORT_REINFORCED: 'duplicate' }[l.action] || '';
            const meta = l.metadata ? Object.entries(l.metadata).filter(([, v]) => v !== null && v !== '' && typeof v !== 'object')
              .map(([k, v]) => `${esc(k.replace(/_/g, ' '))}: ${esc(v)}`).join(' &nbsp;|&nbsp; ') : '';
            return `<div class="timeline-entry"><div class="timeline-dot ${dot}"></div>
              <div class="timeline-content-box">
                <div class="tl-header"><span class="tl-action">${esc(LOG_LABEL[l.action] || l.action)}</span><span class="tl-time">${esc(stamp(l.created_at))}</span></div>
                ${l.crew_id ? `<div class="tl-crew">Logged by: ${esc(l.crew_id)}</div>` : ''}
                <div class="tl-notes">${esc(l.notes)}</div>
                ${meta ? `<div style="margin-top:6px;font-size:0.75rem;background:rgba(0,0,0,0.3);padding:6px;border-radius:4px;color:#60a5fa;">${meta}</div>` : ''}
              </div></div>`;
          }).join('')}
        </div>`;
    } catch (e) { body.textContent = e.message; }
  },

  // ---------- crew actions ----------
  async crewCall(promise, okMsg) {
    try {
      const r = await promise;
      if (!r.ok) {
        this.toast(r.data.message || 'Action failed.', true);
        if (r.status === 409) await this.refresh();
        return false;
      }
      this.closeModals();
      await this.refresh();
      this.toast(okMsg);
      return true;
    } catch (e) { this.toast(e.message, true); return false; }
  },
  acknowledge(id, el) {
    el.disabled = true;
    return this.crewCall(API.acknowledge(id, {}), 'Ticket acknowledged.').then((ok) => { if (!ok) el.disabled = false; });
  },
  submitDispatch(e) {
    e.preventDefault();
    return this.crewCall(API.dispatchCrew($('dispatch-hazard-id').value, {
      crew_id: $('dispatch-crew-id').value, notes: $('dispatch-notes').value.trim()
    }), 'Crew dispatched.');
  },
  submitVerify(e) {
    e.preventDefault();
    return this.crewCall(API.verifyOnSite($('verify-hazard-id').value, {
      crew_id: $('verify-crew-id').value.trim(), verified_severity: $('verify-severity').value,
      safety_perimeter: $('verify-perimeter').checked, estimated_hours: $('verify-hours').value,
      notes: $('verify-notes').value.trim()
    }), 'On-site verification logged.');
  },
  submitResolve(e) {
    e.preventDefault();
    return this.crewCall(API.resolveHazard($('resolve-hazard-id').value, {
      crew_id: $('resolve-crew-id').value.trim(), notes: $('resolve-notes').value.trim(),
      parts_replaced: $('resolve-parts').value.trim()
    }), 'Ticket resolved.');
  },

  // ---------- modals / toast ----------
  openModal(id, focusId) {
    this.closeModals();
    $(id).classList.add('open');
    if (focusId) setTimeout(() => $(focusId).focus(), 50);
  },
  openAction(modalId, hiddenId, hazardId, titleId, title) {
    $(hiddenId).value = hazardId;
    $(titleId).textContent = title;
    ['dispatch-notes', 'verify-notes', 'resolve-notes', 'resolve-parts'].forEach((i) => { if ($(modalId).contains($(i))) $(i).value = ''; });
    this.openModal(modalId);
  },
  closeModals() { document.querySelectorAll('.modal-backdrop').forEach((m) => m.classList.remove('open')); },
  toast(msg, isError) {
    const t = document.createElement('div');
    t.style.cssText = `position:fixed;bottom:20px;right:20px;background:#1e293b;color:#fff;border:1px solid ${isError ? '#ef4444' : '#3b82f6'};padding:12px 18px;border-radius:8px;box-shadow:0 10px 25px rgba(0,0,0,0.5);z-index:1000;font-size:0.9rem;font-weight:600;max-width:min(420px,90vw);`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }
};

window.addEventListener('DOMContentLoaded', () => window.App.init());
