/**
 * FairShare — app.js
 *
 * Navigation flow: Landing (view0) → Upload (viewUpload) → Review (view1) → Assign (view2) → Settle (view3)
 *
 * Engineering problems addressed:
 *   PROBLEM 1 — Per-field confidence scoring + low-confidence highlighting
 *   PROBLEM 2 — Printed vs Calculated discrepancy detection (client-side)
 *   PROBLEM 3 — Proportional tax / SC / discount allocation (not equal split)
 *   PROBLEM 4 — Shared items split by fraction (sum == 1)
 *   PROBLEM 5 — Deterministic zero-loss rounding reconciliation
 *   PROBLEM 6 — Unassigned-items gate blocks calculation
 *   PROBLEM 7 — AI-independent local calc engine + manual entry fallback
 *
 * Design: no initial-letter avatar circles anywhere; color dots/swatches used instead.
 */
class FairShareApp {

  constructor() {
    this.currentView = 'view0';
    this.target = 'calculated';
    this.bill   = this._defaultBill();
    this.uploadedImageURL = null;   // object URL of the uploaded photo
    this.members = [
      { id: 'm1', name: 'Alice',   color: '#2d6a4f' },
      { id: 'm2', name: 'Bob',     color: '#40916c' },
      { id: 'm3', name: 'Charlie', color: '#74c69d' },
    ];
    this.report  = null;
    this.samples = [];
    this._init();
  }

  // ─── Default bill template ────────────────────────────
  _defaultBill() {
    return {
      id: 'bill_' + Math.random().toString(36).slice(2, 8),
      restaurant_name: '',
      bill_number:     '',
      currency:        '₹',
      items:           [],
      taxes:           { cgst: 0, sgst: 0, vat: 0, other_tax: 0, total_tax: 0 },
      service_charge:  0,
      discount:        0,
      tip:             0,
      round_off:       0,
      printed_total:   0,
      calculated_total:0,
      has_math_discrepancy: false,
      discrepancy_amount:   0,
      low_confidence_fields: [],
      overall_confidence:    1,
      is_confirmed_by_user:  false,
    };
  }

  async _init() {
    this._setupDrop();
    await this._fetchSamples();
    await this._checkAIStatus();   // check Gemini availability on load
    this._showView('view0');
  }

  // ─── AI status check (badge on upload page) ──────────
  /**
   * Calls /api/status to see if GEMINI_API_KEY is configured.
   * Updates the badge on the upload page accordingly.
   */
  async _checkAIStatus() {
    try {
      const r = await fetch('/api/status');
      if (!r.ok) return;
      const d = await r.json();
      this.aiEnabled = d.ai_extraction;
      this._renderAIBadge();
    } catch (_) {
      this.aiEnabled = false;
      this._renderAIBadge();
    }
  }

  _renderAIBadge() {
    const badge = document.getElementById('aiBadge');
    const text  = document.getElementById('aiBadgeText');
    if (!badge || !text) return;
    if (this.aiEnabled) {
      badge.className = 'ai-badge active';
      text.textContent = 'Powered by Gemini 3.7 Flash — AI extraction active';
    } else {
      badge.className = 'ai-badge inactive';
      text.textContent = 'No API key — manual entry only';
    }
  }

  // ─── Processing overlay ───────────────────────────────
  _showProcessing() {
    const ov = document.getElementById('processingOverlay');
    if (ov) ov.style.display = 'flex';
    // Animate steps: Analysing → Extracting → Scoring
    this._psStep(1);
    setTimeout(() => this._psStep(2), 1800);
    setTimeout(() => this._psStep(3), 3600);
  }

  _hideProcessing() {
    const ov = document.getElementById('processingOverlay');
    if (ov) ov.style.display = 'none';
    // Reset steps
    [1,2,3].forEach(n => {
      const el = document.getElementById('ps' + n);
      if (el) el.className = 'ps-step';
    });
  }

  _psStep(n) {
    // Mark previous steps as done, current as active
    for (let i = 1; i < n; i++) {
      const el = document.getElementById('ps' + i);
      if (el) el.className = 'ps-step done';
    }
    const cur = document.getElementById('ps' + n);
    if (cur) cur.className = 'ps-step active';
  }

  // ─── View navigation ──────────────────────────────────
  _showView(id) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    this.currentView = id;

    const nav = document.getElementById('appNav');
    nav.style.display = (id === 'view0') ? 'none' : 'flex';

    this._updateNavSteps(id);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  _updateNavSteps(id) {
    const stepMap = { view1: 1, view2: 2, view3: 3 };
    const active  = stepMap[id] || 0;
    [1, 2, 3].forEach(n => {
      const el = document.getElementById('ns' + n);
      if (!el) return;
      el.classList.remove('active', 'done');
      if (n === active) el.classList.add('active');
      else if (n < active) el.classList.add('done');
    });
  }

  goToLanding() { this._showView('view0'); }
  goToUpload()  { this._showView('viewUpload'); }

  goToStep(n) {
    const id = n === 1 ? 'view1' : n === 2 ? 'view2' : 'view3';
    this._showView(id);
    if (n === 1) this._renderStep1();
    if (n === 2) this._renderStep2();
    if (n === 3 && this.report) this._renderStep3();
  }

  // ─── Samples ──────────────────────────────────────────
  async _fetchSamples() {
    try {
      const r = await fetch('/api/benchmarks');
      if (!r.ok) return;
      const d = await r.json();
      this.samples = d.benchmarks || [];
      this._renderSamplePickers();
    } catch (_) {}
  }

  _renderSamplePickers() {
    const sel   = document.getElementById('sampleSelect');
    const chips = document.getElementById('sampleChips');

    const labels = {
      dim_light:                  'Dim lighting',
      crumpled_paper:             'Crumpled paper',
      steep_angle:                'Steep angle',
      faded_thermal:              'Faded print',
      handwritten_notes:          'Handwritten tip',
      dual_script:                'Bilingual bill',
      multi_photo_stitched:       'Long bill (2 photos)',
      math_error_on_bill:         'Printed total error ⚠️',
      promotional_discounts:      'Heavy discount',
      split_taxes:                'Split GST',
      seven_people_complex_split: '7-person dinner',
      high_density_items:         'Busy café (14 items)',
    };

    if (sel) {
      this.samples.forEach(b => {
        const o = document.createElement('option');
        o.value = b.test_id;
        o.textContent = labels[b.condition] || b.title;
        sel.appendChild(o);
      });
    }

    if (chips) {
      const show = ['seven_people_complex_split', 'math_error_on_bill', 'high_density_items', 'dim_light', 'faded_thermal'];
      this.samples.filter(b => show.includes(b.condition)).forEach(b => {
        const c = document.createElement('button');
        c.className = 'chip chip-with-image';
        
        // Add thumbnail if image URL available
        if (b.image_url) {
          const thumb = document.createElement('img');
          thumb.src = b.image_url;
          thumb.className = 'chip-thumbnail';
          thumb.alt = '';
          c.appendChild(thumb);
        }
        
        const label = document.createElement('span');
        label.textContent = labels[b.condition] || b.condition;
        c.appendChild(label);
        
        c.onclick = () => this.loadSampleAndGo(b.test_id);
        chips.appendChild(c);
      });
    }
  }

  /** Load a sample and jump straight to Review (used from landing CTA and chips). */
  loadSampleAndGo(id) {
    const s = this.samples.find(b => b.test_id === id);
    if (!s || !s.bill_data) return;
    
    // Store the bill image URL if available
    if (s.image_url) {
      this.uploadedImageURL = s.image_url;
    }
    
    this._loadBillData(s.bill_data);
    if (id === 'B11' && this.bill.items.length >= 7) {
      this.bill.items[0].assigned_members = ['m1', 'm2'];
      this.bill.items[1].assigned_members = ['m3'];
    }
    this._recompute();
    this._renderStep1();
    this._showView('view1');
    const sel = document.getElementById('sampleSelect');
    if (sel) sel.value = id;
  }

  /** Called from nav dropdown. */
  loadSample(id) { if (id) this.loadSampleAndGo(id); }

  _loadBillData(data) {
    this.bill = JSON.parse(JSON.stringify(data));
    if (!this.bill.taxes)                        this.bill.taxes = {};
    if (this.bill.taxes.vat       === undefined) this.bill.taxes.vat       = 0;
    if (this.bill.taxes.other_tax === undefined) this.bill.taxes.other_tax = 0;
    if (this.bill.round_off       === undefined) this.bill.round_off       = 0;
    this.bill.is_confirmed_by_user = false;
    this.bill.items.forEach((it, i) => {
      if (!it.id)               it.id = 'i' + i;
      if (!it.assigned_members) it.assigned_members = [];
    });
  }

  // ─── PROBLEM 7: Manual entry mode ────────────────────
  clearBill() {
    if (this.uploadedImageURL) {
      URL.revokeObjectURL(this.uploadedImageURL);
      this.uploadedImageURL = null;
    }
    this.bill = this._defaultBill();
    this.bill.items = [{
      id: 'i_new', name: '', quantity: 1,
      unit_price: 0, total_price: 0, confidence: 1, assigned_members: []
    }];
    this._recompute();
    this._renderStep1();
    this._showView('view1');
  }

  // ─── PROBLEM 2: Math recompute ────────────────────────
  _recompute() {
    const b = this.bill;
    b.subtotal = this._r(b.items.reduce((s, i) => s + (+i.total_price || 0), 0));

    const cgst     = +b.taxes.cgst      || 0;
    const sgst     = +b.taxes.sgst      || 0;
    const vat      = +b.taxes.vat       || 0;
    const otherTax = +b.taxes.other_tax || 0;
    let   totalTax = +b.taxes.total_tax || 0;
    if (!totalTax) { totalTax = cgst + sgst + vat + otherTax; b.taxes.total_tax = this._r(totalTax); }

    const calc = this._r(
      b.subtotal
      - (+b.discount      || 0)
      + totalTax
      + (+b.service_charge || 0)
      + (+b.tip            || 0)
      + (+b.round_off      || 0)
    );
    b.calculated_total    = calc;
    const diff            = this._r(calc - (+b.printed_total || 0));
    b.has_math_discrepancy = Math.abs(diff) > 0.01;
    b.discrepancy_amount   = diff;
  }

  _r(n, d = 2) { return Math.round(n * 10 ** d) / 10 ** d; }
  _fmt(n)      { return (this.bill.currency || '₹') + Math.abs(n).toFixed(2); }
  _esc(s)      { return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

  // ─── File upload / drag-drop ─────────────────────────
  _setupDrop() {
    const z = document.getElementById('dropzone');
    if (!z) return;
    ['dragenter','dragover'].forEach(e =>
      z.addEventListener(e, ev => { ev.preventDefault(); z.classList.add('drag-over'); })
    );
    ['dragleave','drop'].forEach(e =>
      z.addEventListener(e, ev => { ev.preventDefault(); z.classList.remove('drag-over'); })
    );
    z.addEventListener('drop', ev => { const f = ev.dataTransfer.files[0]; if (f) this._upload(f); });
  }

  handleFile(e) { const f = e.target.files[0]; if (f) this._upload(f); }

  async _upload(file) {
    // Show preview immediately — before waiting for API
    if (this.uploadedImageURL) URL.revokeObjectURL(this.uploadedImageURL);
    this.uploadedImageURL = URL.createObjectURL(file);

    // Show processing overlay while Gemini works
    this._showProcessing();

    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch('/api/extract', { method: 'POST', body: fd });
      this._hideProcessing();
      if (r.ok) {
        const data = await r.json();
        this._loadBillData(data);
        this._recompute();
        this._renderStep1();
        this._showView('view1');
      } else {
        this.clearBill();
      }
    } catch (_) {
      this._hideProcessing();
      this.clearBill();
    }
  }

  // ─── STEP 1 render ───────────────────────────────────
  _renderStep1() {
    const b = this.bill;

    // Image preview panel
    const panel = document.getElementById('imagePanel');
    const img   = document.getElementById('billPreviewImg');
    if (this.uploadedImageURL && panel && img) {
      img.src = this.uploadedImageURL;
      panel.style.display = 'block';
    } else if (panel) {
      panel.style.display = 'none';
    }

    document.getElementById('rName').value        = b.restaurant_name || '';
    document.getElementById('rInvoice').value     = b.bill_number     || '';
    document.getElementById('rCurrency').value    = b.currency        || '₹';
    document.getElementById('tCGST').value        = (b.taxes.cgst      || 0).toFixed(2);
    document.getElementById('tSGST').value        = (b.taxes.sgst      || 0).toFixed(2);
    document.getElementById('tVAT').value         = (b.taxes.vat       || 0).toFixed(2);
    document.getElementById('tOther').value       = (b.taxes.other_tax || 0).toFixed(2);
    document.getElementById('tTotal').value       = (b.taxes.total_tax || 0).toFixed(2);
    document.getElementById('fSC').value          = (b.service_charge  || 0).toFixed(2);
    document.getElementById('fDisc').value        = (b.discount        || 0).toFixed(2);
    document.getElementById('fTip').value         = (b.tip             || 0).toFixed(2);
    document.getElementById('fRoundOff').value    = (b.round_off       || 0).toFixed(2);
    document.getElementById('fPrinted').value     = (b.printed_total   || 0).toFixed(2);
    document.getElementById('calcDisplay').textContent = this._fmt(b.calculated_total);

    // Items table
    const tbody = document.getElementById('itemsBody');
    tbody.innerHTML = '';
    b.items.forEach((it, i) => {
      const conf    = +it.confidence || 1;
      const cls     = conf >= 0.85 ? 'high' : conf >= 0.60 ? 'med' : 'low';
      const confPct = Math.round(conf * 100);
      const tr      = document.createElement('tr');
      tr.innerHTML  = `
        <td><input class="t-input" value="${this._esc(it.name)}" oninput="app._itemField(${i},'name',this.value)" placeholder="Item name"></td>
        <td><input class="t-input qty" type="number" min="0.5" step="0.5" value="${it.quantity || 1}" oninput="app._itemField(${i},'quantity',this.value)"></td>
        <td><input class="t-input num" type="number" step="0.01" value="${(+it.unit_price || 0).toFixed(2)}" oninput="app._itemField(${i},'unit_price',this.value)"></td>
        <td><input class="t-input num" type="number" step="0.01" value="${(+it.total_price || 0).toFixed(2)}" oninput="app._itemField(${i},'total_price',this.value)"></td>
        <td class="conf-cell">
          <span class="conf-dot ${cls}"></span>
          <span class="conf-pct conf-pct-${cls}">${confPct}%</span>
        </td>
        <td><button class="btn-icon" title="Remove item" onclick="app._delItem(${i})">✕</button></td>
      `;
      tbody.appendChild(tr);
    });

    // PROBLEM 2 banner
    this._refreshMathBanner();

    // AI extraction banner — visible when image was uploaded
    const aiBanner = document.getElementById('aiExtractionBanner');
    const aiConfText = document.getElementById('aiConfidenceText');
    if (aiBanner) {
      if (this.uploadedImageURL && this.aiEnabled) {
        aiBanner.style.display = 'flex';
        const pct = Math.round((+b.overall_confidence || 1) * 100);
        if (aiConfText) aiConfText.textContent = ` · Overall confidence: ${pct}%`;
      } else {
        aiBanner.style.display = 'none';
      }
    }

    // PROBLEM 1 banner
    const lowConf = b.items.filter(it => (+it.confidence || 1) < 0.75);
    const ca      = document.getElementById('confAlert');
    if (lowConf.length) {
      ca.style.display = 'flex';
      document.getElementById('confAlertText').textContent =
        `${lowConf.length} item${lowConf.length > 1 ? 's look' : ' looks'} unclear (< 75% confidence) — review before confirming`;
    } else {
      ca.style.display = 'none';
    }
  }

  _refreshMathBanner() {
    const b  = this.bill;
    const ma = document.getElementById('mathAlert');
    if (b.has_math_discrepancy) {
      ma.style.display = 'flex';
      document.getElementById('dPrinted').textContent = this._fmt(b.printed_total);
      document.getElementById('dCalc').textContent    = this._fmt(b.calculated_total);
      const d = b.discrepancy_amount;
      document.getElementById('dDiff').textContent    = (d > 0 ? '+' : '−') + this._fmt(d);
    } else {
      ma.style.display = 'none';
    }
  }

  _itemField(i, field, val) {
    const it = this.bill.items[i];
    if (!it) return;
    if (field === 'name') { it.name = val; return; }
    const n = parseFloat(val) || 0;
    if      (field === 'quantity')    { it.quantity    = n; it.total_price = this._r(n * (+it.unit_price || 0)); }
    else if (field === 'unit_price')  { it.unit_price  = n; it.total_price = this._r((+it.quantity || 1) * n); }
    else if (field === 'total_price') { it.total_price = n; it.unit_price  = it.quantity ? this._r(n / (+it.quantity || 1)) : n; }
    this._recompute();
    document.getElementById('calcDisplay').textContent = this._fmt(this.bill.calculated_total);
    this._refreshMathBanner();
  }

  addItem() {
    this.bill.items.push({ id: 'i_' + Date.now(), name: '', quantity: 1, unit_price: 0, total_price: 0, confidence: 1, assigned_members: [] });
    this._renderStep1();
  }

  _delItem(i) { this.bill.items.splice(i, 1); this._recompute(); this._renderStep1(); }

  updateMeta() {
    this.bill.restaurant_name = document.getElementById('rName').value;
    this.bill.bill_number     = document.getElementById('rInvoice').value;
    this.bill.currency        = document.getElementById('rCurrency').value;
  }

  updateFin() {
    const b        = this.bill;
    const cgst     = parseFloat(document.getElementById('tCGST').value)     || 0;
    const sgst     = parseFloat(document.getElementById('tSGST').value)     || 0;
    const vat      = parseFloat(document.getElementById('tVAT').value)      || 0;
    const otherTax = parseFloat(document.getElementById('tOther').value)    || 0;
    const totalTax = parseFloat(document.getElementById('tTotal').value)    || 0;

    b.taxes.cgst      = cgst;
    b.taxes.sgst      = sgst;
    b.taxes.vat       = vat;
    b.taxes.other_tax = otherTax;
    b.taxes.total_tax = totalTax || this._r(cgst + sgst + vat + otherTax);
    b.service_charge  = parseFloat(document.getElementById('fSC').value)       || 0;
    b.discount        = parseFloat(document.getElementById('fDisc').value)      || 0;
    b.tip             = parseFloat(document.getElementById('fTip').value)        || 0;
    b.round_off       = parseFloat(document.getElementById('fRoundOff').value)  || 0;
    b.printed_total   = parseFloat(document.getElementById('fPrinted').value)   || 0;

    this._recompute();
    document.getElementById('calcDisplay').textContent = this._fmt(b.calculated_total);
    this._refreshMathBanner();
  }

  setTarget(v) { this.target = v; }

  // PROBLEM 3 (lock): set confirmed before moving to assign
  confirm() {
    this._recompute();
    this.bill.is_confirmed_by_user = true;
    this.goToStep(2);
  }

  // ─── STEP 2 ──────────────────────────────────────────
  addMember() {
    const inp  = document.getElementById('newName');
    const name = inp.value.trim();
    if (!name) return;
    // Palette of greens / earthy tones
    const colors = ['#2d6a4f','#40916c','#52b788','#74c69d','#b7791f','#6b5234','#8b5cf6','#0369a1'];
    this.members.push({ id: 'm_' + Date.now(), name, color: colors[this.members.length % colors.length] });
    inp.value = '';
    this._renderStep2();
  }

  removeMember(id) {
    if (this.members.length < 2) return;
    this.members = this.members.filter(m => m.id !== id);
    this.bill.items.forEach(it => { it.assigned_members = (it.assigned_members || []).filter(x => x !== id); });
    this._renderStep2();
  }

  _toggle(itemIdx, memberId) {
    const it = this.bill.items[itemIdx];
    if (!it) return;
    if (!it.assigned_members) it.assigned_members = [];
    const idx = it.assigned_members.indexOf(memberId);
    if (idx >= 0) it.assigned_members.splice(idx, 1);
    else          it.assigned_members.push(memberId);
    this._renderStep2();
  }

  _assignToAll(itemIdx) {
    this.bill.items[itemIdx].assigned_members = this.members.map(m => m.id);
    this._renderStep2();
  }

  assignAll() {
    const allIds = this.members.map(m => m.id);
    this.bill.items.forEach(it => { if (!(it.assigned_members || []).length) it.assigned_members = [...allIds]; });
    this._renderStep2();
  }

  _renderStep2() {
    // Members bar — color dot + name, no avatar circle
    const bar = document.getElementById('membersBar');
    bar.innerHTML = '';
    this.members.forEach(m => {
      const tag = document.createElement('div');
      tag.className = 'member-tag';
      tag.innerHTML = `
        <span class="member-dot" style="background:${m.color}"></span>
        <span>${this._esc(m.name)}</span>
        <button class="remove-btn" onclick="app.removeMember('${m.id}')">✕</button>
      `;
      bar.appendChild(tag);
    });

    // PROBLEM 6: unassigned gate
    const unassigned = this.bill.items.filter(it => !(it.assigned_members || []).length);
    const banner     = document.getElementById('unassignBanner');
    const calcBtn    = document.getElementById('calcBtn');
    if (unassigned.length) {
      banner.style.display = 'flex';
      document.getElementById('unassignText').textContent =
        `${unassigned.length} item${unassigned.length > 1 ? 's aren\'t' : ' isn\'t'} assigned yet.`;
      calcBtn.disabled = true;
    } else {
      banner.style.display = 'none';
      calcBtn.disabled = false;
    }

    // Assignment rows
    const list = document.getElementById('assignList');
    list.innerHTML = '';
    this.bill.items.forEach((it, idx) => {
      const assigned     = it.assigned_members || [];
      const isUnassigned = !assigned.length;
      const perPerson    = assigned.length ? this._r(it.total_price / assigned.length) : 0;

      let sub = '';
      if (!isUnassigned) {
        if (assigned.length === 1) {
          const who = this.members.find(m => m.id === assigned[0]);
          sub = `Only ${who ? who.name : '?'}`;
        } else {
          sub = `${this.bill.currency}${perPerson.toFixed(2)} each · ${assigned.length} people`;
        }
      }

      // Toggle pills — color dot + name only, no initial circle
      const pills = this.members.map(m => {
        const on = assigned.includes(m.id);
        return `<button class="toggle-pill ${on ? 'on' : ''}" onclick="app._toggle(${idx},'${m.id}')">
          <span class="pill-dot" style="background:${m.color}"></span>
          ${this._esc(m.name)}
        </button>`;
      }).join('');

      const row = document.createElement('div');
      row.className = `assign-row${isUnassigned ? ' unassigned' : ''}`;
      row.innerHTML = `
        <div class="assign-item-info">
          <div class="assign-item-name">${this._esc(it.name) || '<em style="color:var(--ink-4)">Unnamed item</em>'}</div>
          ${sub ? `<div class="assign-item-sub">${sub}</div>` : ''}
        </div>
        <div class="toggle-pills">${pills}<button class="all-btn" onclick="app._assignToAll(${idx})">All</button></div>
        <div class="assign-item-price">${this.bill.currency}${(+it.total_price || 0).toFixed(2)}</div>
      `;
      list.appendChild(row);
    });
  }

  // ─── STEP 3: Calculation (Problems 3, 4, 5) ─────────
  async calculate() {
    try {
      const res = await fetch('/api/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ bill: this.bill, members: this.members, target_total_source: this.target })
      });
      this.report = res.ok ? await res.json() : this._localCalc();
    } catch (_) {
      this.report = this._localCalc();
    }
    this._renderStep3();
    this.goToStep(3);
  }

  /**
   * Local mirror of the Python proportional engine (PROBLEMS 3, 4, 5).
   * Runs entirely in the browser — no server required.
   *
   * PROBLEM 3: weight(person) = BaseShare / TotalBase
   *   TaxShare = TotalTax × weight  (NOT TotalTax / N)
   *
   * PROBLEM 4: share_fraction = 1 / number_of_assignees
   *   sum(fractions per item) == 1.0
   *
   * PROBLEM 5: after rounding, any drift assigned to largest consumer first.
   *   sum(final_totals) == target_total exactly.
   */
  _localCalc() {
    const b           = this.bill;
    const targetTotal = this.target === 'calculated' ? b.calculated_total : b.printed_total;
    const base = {}, shares = {};
    this.members.forEach(m => { base[m.id] = 0; shares[m.id] = []; });

    // PROBLEM 4
    b.items.forEach(it => {
      const ass  = it.assigned_members || [];
      if (!ass.length) return;
      const frac = 1 / ass.length;
      ass.forEach(mid => {
        if (base[mid] === undefined) return;
        base[mid] += it.total_price * frac;
        shares[mid].push({ item_id: it.id, item_name: it.name, share_fraction: frac, share_amount: this._r(it.total_price * frac) });
      });
    });

    const totalBase = Object.values(base).reduce((s, v) => s + v, 0);

    // PROBLEM 3
    const settlements = this.members.map(m => {
      const bs   = base[m.id] || 0;
      const w    = totalBase > 0 ? bs / totalBase : 1 / this.members.length;
      const tax  = (b.taxes.total_tax   || 0) * w;
      const sc   = (b.service_charge    || 0) * w;
      const disc = (b.discount          || 0) * w;
      const tip  = (b.tip               || 0) * w;
      const raw  = bs - disc + sc + tax + tip;
      return {
        member_id: m.id, member_name: m.name, avatar_color: m.color,
        assigned_items: shares[m.id],
        base_subtotal:        this._r(bs),
        consumption_weight:   this._r(w, 4),
        tax_share:            this._r(tax),
        service_charge_share: this._r(sc),
        discount_share:       this._r(disc),
        tip_share:            this._r(tip),
        raw_total: raw, final_total: this._r(raw), rounding_adjustment: 0
      };
    });

    // PROBLEM 5: deterministic rounding reconciliation
    const notes     = [];
    let   sum       = this._r(settlements.reduce((s, m) => s + m.final_total, 0));
    const diffCents = Math.round((targetTotal - sum) * 100);
    if (Math.abs(diffCents) > 0) {
      const step   = diffCents > 0 ? 0.01 : -0.01;
      const sorted = [...settlements].sort((a, bm) => bm.base_subtotal - a.base_subtotal);
      for (let i = 0; i < Math.abs(diffCents); i++) {
        const m    = sorted[i % sorted.length];
        const orig = settlements.find(s => s.member_id === m.member_id);
        orig.final_total         = this._r(orig.final_total         + step);
        orig.rounding_adjustment = this._r(orig.rounding_adjustment + step);
        notes.push(`₹0.01 ${step > 0 ? 'added to' : 'from'} ${orig.member_name} (largest share)`);
      }
    } else {
      notes.push('Sum matches exactly — no rounding adjustment needed.');
    }

    const recon = this._r(settlements.reduce((s, m) => s + m.final_total, 0));
    return {
      bill_id: b.id, target_total: this._r(targetTotal),
      total_base_subtotal:  this._r(totalBase),
      total_taxes:          this._r(b.taxes.total_tax || 0),
      total_service_charge: this._r(b.service_charge  || 0),
      total_discount:       this._r(b.discount         || 0),
      total_tip:            this._r(b.tip              || 0),
      members: settlements,
      reconciled_sum:       recon,
      is_zero_loss_exact:   Math.abs(recon - targetTotal) < 0.001,
      rounding_reconciliation_details: notes
    };
  }

  // ─── STEP 3 render ───────────────────────────────────
  _renderStep3() {
    const rep  = this.report;
    if (!rep) return;
    const curr = this.bill.currency || '₹';
    const fmt  = n => curr + Math.abs(n).toFixed(2);

    // Totals strip
    const stripItems = [
      ['Items',    fmt(rep.total_base_subtotal)],
      ['Tax',      fmt(rep.total_taxes)],
      ['Service',  fmt(rep.total_service_charge)],
    ];
    if (rep.total_discount > 0) stripItems.push(['Discount', '−' + fmt(rep.total_discount)]);
    if (rep.total_tip      > 0) stripItems.push(['Tip',       fmt(rep.total_tip)]);
    stripItems.push(['Total', fmt(rep.target_total)]);

    document.getElementById('totalsStrip').innerHTML = stripItems
      .map(([l, v]) => `<div class="strip-item"><div class="strip-label">${l}</div><div class="strip-val">${v}</div></div>`)
      .join('');

    // Zero-loss badge
    document.getElementById('zeroLossText').textContent =
      `All shares sum to ${fmt(rep.reconciled_sum)} — exact to the paisa.`;

    // Per-person cards — color swatch + name, no avatar circle
    const grid = document.getElementById('memberCards');
    grid.innerHTML = '';
    rep.members.forEach(m => {
      const wPct = (m.consumption_weight * 100).toFixed(1);
      const card = document.createElement('div');
      card.className = 'member-card';
      card.style.borderLeftColor = m.avatar_color;

      const itemRows = (m.assigned_items || []).map(it => {
        const label = it.share_fraction < 0.99
          ? `${this._esc(it.item_name)} <span style="font-size:11px;color:var(--ink-3)">(${Math.round(it.share_fraction * 100)}%)</span>`
          : this._esc(it.item_name);
        return `<div class="mc-item-row">
          <span class="name">${label}</span>
          <span class="amt">${curr}${it.share_amount.toFixed(2)}</span>
        </div>`;
      }).join('') || `<div class="mc-item-row"><span class="name" style="color:var(--ink-4);font-style:italic">No items assigned</span></div>`;

      // Breakdown chips
      const bdItems = [
        `<span class="bd-item"><span class="bd-label">Tax</span> <span class="bd-val">${curr}${m.tax_share.toFixed(2)}</span></span>`,
        `<span class="bd-item"><span class="bd-label">Service</span> <span class="bd-val">${curr}${m.service_charge_share.toFixed(2)}</span></span>`,
      ];
      if (m.discount_share > 0)
        bdItems.push(`<span class="bd-item"><span class="bd-label">Discount</span> <span class="bd-val neg">−${curr}${m.discount_share.toFixed(2)}</span></span>`);
      if ((m.tip_share || 0) > 0)
        bdItems.push(`<span class="bd-item"><span class="bd-label">Tip</span> <span class="bd-val">${curr}${m.tip_share.toFixed(2)}</span></span>`);

      const adjNote = m.rounding_adjustment !== 0
        ? `<div class="mc-rounding-note">Rounding: ${m.rounding_adjustment > 0 ? '+' : ''}${curr}${Math.abs(m.rounding_adjustment).toFixed(2)}</div>` : '';

      card.innerHTML = `
        <div class="mc-header">
          <div class="mc-name">
            <span class="mc-swatch" style="background:${m.avatar_color}"></span>
            ${this._esc(m.member_name)}
            <span class="mc-pct">${wPct}% of bill</span>
          </div>
          <div class="mc-total">${curr}${m.final_total.toFixed(2)}</div>
        </div>
        <div class="mc-body">
          ${itemRows}
          <div class="mc-breakdown">${bdItems.join('')}</div>
          ${adjNote}
        </div>
      `;
      grid.appendChild(card);
    });
  }

  // ─── WhatsApp export ─────────────────────────────────
  copyWhatsApp() {
    const rep  = this.report;
    if (!rep) return;
    const curr = this.bill.currency || '₹';
    let txt = `*${this.bill.restaurant_name || 'Dinner'} — Who pays what*\n\n`;
    rep.members.forEach(m => {
      txt += `*${m.member_name}: ${curr}${m.final_total.toFixed(2)}*\n`;
      (m.assigned_items || []).forEach(it => {
        const pct = it.share_fraction < 0.99 ? ` (${Math.round(it.share_fraction * 100)}%)` : '';
        txt += `  • ${it.item_name}${pct}: ${curr}${it.share_amount.toFixed(2)}\n`;
      });
      txt += `  + Tax ${curr}${m.tax_share.toFixed(2)}, Service ${curr}${m.service_charge_share.toFixed(2)}\n\n`;
    });
    txt += `Total: ${curr}${rep.target_total.toFixed(2)} — split exact to the paisa.`;
    navigator.clipboard.writeText(txt).then(() => {
      const t = document.getElementById('toast');
      t.style.display = 'flex';
      setTimeout(() => { t.style.display = 'none'; }, 2500);
    });
  }
}

window.app = new FairShareApp();
