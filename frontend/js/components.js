/**
 * components.js — Composants HTML réutilisables.
 */

// ── Helpers ─────────────────────────────────────────────────────────────────

export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'className') e.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
    else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    if (typeof c === 'string' || typeof c === 'number') e.appendChild(document.createTextNode(c));
    else e.appendChild(c);
  }
  return e;
}

export function fmt(v, decimals = 1) {
  if (v == null || v === '' || (typeof v === 'number' && !isFinite(v))) return '—';
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return n.toFixed(decimals);
}

export function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function fmtDateShort(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase();
}

// ── Metric Card ─────────────────────────────────────────────────────────────

const STATUS_COLORS = {
  ok:      'var(--success)',
  warn:    'var(--warning)',
  alert:   'var(--danger)',
  neutral: 'var(--border)',
};

export function metricCard(label, value, unit = '', { status = 'neutral', explain = '' } = {}) {
  const card = el('div', { className: `ca-metric-card ${status}` },
    el('div', { className: 'ca-metric-label' }, label),
    el('div', { className: 'ca-metric-value-row' },
      el('span', { className: 'ca-metric-value' }, value),
      unit ? el('span', { className: 'ca-metric-unit' }, unit) : null,
    ),
    explain ? el('div', { className: 'ca-metric-explain' }, explain) : null,
  );
  return card;
}

// ── Badge ───────────────────────────────────────────────────────────────────

const BADGE_CLASSES = {
  'fractionné court':  'fractionne',
  'fractionné moyen':  'fractionne',
  'fractionné long':   'fractionne',
  'mixte':             'fractionne',
  'trail':             'trail',
  'tempo / seuil':     'tempo',
  'tempo / allure':    'tempo',
  'endurance fondamentale': 'endurance',
  'sortie longue':     'endurance',
  'récupération active': '',
};

export function badge(sessionType) {
  const cls = BADGE_CLASSES[sessionType] || '';
  return el('span', { className: `ca-badge ${cls}` }, sessionType || '—');
}

// ── ACWR helpers ────────────────────────────────────────────────────────────

export function acwrStatus(v) {
  if (v == null || isNaN(v)) return 'neutral';
  if (v > 1.5) return 'alert';
  if (v > 1.3) return 'warn';
  return 'ok';
}

export function acwrColor(v) {
  if (v == null || isNaN(v)) return 'var(--ink-light)';
  if (v > 1.5) return 'var(--danger)';
  if (v > 1.3) return 'var(--warning)';
  if (v > 0.8) return 'var(--success)';
  return 'var(--ink-mid)';
}

export function riskStatus(label) {
  const l = (label || '').toLowerCase();
  if (l === 'faible') return 'ok';
  if (l === 'modéré') return 'warn';
  if (l === 'élevé' || l === 'critique') return 'alert';
  return 'neutral';
}

export function riskColor(label) {
  const l = (label || '').toLowerCase();
  if (l === 'faible') return 'var(--success)';
  if (l === 'modéré') return 'var(--warning)';
  if (l === 'élevé' || l === 'critique') return 'var(--danger)';
  return 'var(--ink-light)';
}

// ── Detail row (Analyse) ────────────────────────────────────────────────────

export function detailRow(label, value, { color } = {}) {
  const valStyle = color ? { color } : {};
  return el('div', { className: 'ca-detail-row' },
    el('span', { className: 'ca-detail-label' }, label),
    el('span', { className: 'ca-detail-value', style: valStyle },
      typeof value === 'string' || typeof value === 'number' ? String(value) : value,
    ),
  );
}

// ── Section title ───────────────────────────────────────────────────────────

export function sectionTitle(text) {
  return el('div', { className: 'ca-section-title' }, text);
}

// ── Loading / Empty ─────────────────────────────────────────────────────────

export function loading() {
  return el('div', { className: 'ca-loading' }, 'Chargement…');
}

export function empty(text = 'Pas de données.') {
  return el('div', { className: 'ca-empty' }, text);
}

// ── Collapsible explanation block ────────────────────────────────────────────

export function collapsible(title, contentFn) {
  const body = el('div', { className: 'ca-collapsible-body' });
  let rendered = false;

  const toggle = el('button', {
    className: 'ca-collapsible-toggle',
    onClick: () => {
      const open = body.classList.toggle('open');
      toggle.classList.toggle('open', open);
      if (open && !rendered) {
        const content = contentFn();
        if (typeof content === 'string') body.innerHTML = content;
        else body.appendChild(content);
        rendered = true;
      }
    },
  }, title);

  return el('div', { className: 'ca-collapsible' }, toggle, body);
}

// ── Distribution bar ────────────────────────────────────────────────────────

const TYPE_COLORS = {
  'fractionné':   'var(--accent)',
  'trail':        'var(--success)',
  'tempo':        'var(--warning)',
  'endurance':    'var(--ink-mid)',
  'récupération': 'var(--ink-light)',
  'sortie':       'var(--ink-mid)',
};

function typeColor(stype) {
  const lower = (stype || '').toLowerCase();
  for (const [key, color] of Object.entries(TYPE_COLORS)) {
    if (lower.includes(key)) return color;
  }
  return 'var(--ink-light)';
}

export function distBar(label, count, pct) {
  const bar = el('div', { className: 'ca-dist-bar', style: { width: '0%', background: typeColor(label) } });
  requestAnimationFrame(() => { bar.style.width = `${pct}%`; });

  return el('div', { className: 'ca-dist-row' },
    el('span', { className: 'ca-dist-label' }, label),
    el('div', { className: 'ca-dist-track' }, bar),
    el('span', { className: 'ca-dist-count' }, String(count)),
  );
}

// ── Flag pill ───────────────────────────────────────────────────────────────

const FLAG_LABELS = {
  acwr:         'ACWR élevé',
  monotony:     'Monotonie',
  load_spike:   'Pic de charge',
  consecutive:  'Jours consécutifs',
};

export function flagPill(key, active) {
  return el('span', { className: `ca-flag ${active ? 'active' : 'off'}` },
    FLAG_LABELS[key] || key,
  );
}

// ── Review box ──────────────────────────────────────────────────────────────

export function reviewBox(review) {
  if (!review) return null;
  const text = review.review_text || '';
  const meta = [review.model, (review.generated_at || '').slice(0, 10)].filter(Boolean).join('  ·  ');

  const box = el('div', { className: 'ca-review-box' });
  box.innerHTML = simpleMarkdown(text);
  if (meta) {
    box.appendChild(el('div', { className: 'ca-review-meta' }, meta));
  }
  return box;
}

function simpleMarkdown(text) {
  return text
    .replace(/### (.+)/g, '<h4>$1</h4>')
    .replace(/## (.+)/g, '<h3>$1</h3>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n- /g, '\n<li>')
    .replace(/(<li>.*(?:\n|$))+/g, '<ul>$&</ul>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/^/, '<p>')
    .replace(/$/, '</p>');
}
