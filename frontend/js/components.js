/**
 * components.js — Composants HTML réutilisables.
 */

import { t, getLang } from './i18n.js';

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

function _locale() { return getLang() === 'en' ? 'en-US' : 'fr-FR'; }

export function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString(_locale(), { day: '2-digit', month: '2-digit', year: 'numeric' });
}

export function fmtDateShort(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString(_locale(), { day: '2-digit', month: 'short', year: 'numeric' }).toUpperCase();
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
  return el('div', { className: 'ca-loading' }, t('common.loading'));
}

export function empty(text) {
  return el('div', { className: 'ca-empty' }, text != null ? text : t('common.empty'));
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

// ── Method body (paragraphs from i18n key) ──────────────────────────────────

export function methodBody(key) {
  const paragraphs = t(key);
  const div = el('div', {});
  if (Array.isArray(paragraphs)) {
    for (const p of paragraphs) {
      div.appendChild(el('p', p.italic ? { style: { fontStyle: 'italic' } } : {}, p.text));
    }
  }
  return div;
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

const FLAG_KEYS = {
  acwr:         'components.flagAcwr',
  monotony:     'components.flagMonotony',
  load_spike:   'components.flagSpike',
  consecutive:  'components.flagConsec',
};

export function flagPill(key, active) {
  return el('span', { className: `ca-flag ${active ? 'active' : 'off'}` },
    FLAG_KEYS[key] ? t(FLAG_KEYS[key]) : key,
  );
}

// ── Review box ──────────────────────────────────────────────────────────────

export function reviewBox(review) {
  if (!review) return null;
  const box = el('div', { className: 'ca-review-box' });

  // Structured output (new format with sections)
  const sections = review.sections;
  if (sections && (sections.execution || sections.charge)) {
    // Score badge
    const score = review.score;
    if (score != null) {
      const scoreColor = score >= 7 ? 'var(--success, #2D6A4F)' : score >= 4 ? 'var(--warning, #B8860B)' : 'var(--danger, #D32F2F)';
      box.appendChild(el('div', { style: { display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' } },
        el('span', { style: {
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
          width: '36px', height: '36px', borderRadius: '50%',
          background: scoreColor, color: '#fff', fontWeight: '700', fontSize: '15px',
        } }, String(score)),
        el('span', { style: { fontSize: '14px', fontWeight: '500' } }, sections.resume || ''),
      ));
    } else if (sections.resume) {
      box.appendChild(el('p', { style: { fontWeight: '500', marginBottom: '10px' } }, sections.resume));
    }

    // Tags
    const tags = review.tags;
    if (tags && tags.length) {
      const tagContainer = el('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '12px' } });
      for (const t of tags) {
        const tagColor = ['surcharge', 'fatigue', 'pic_charge', 'monotonie', 'decouplage_eleve'].includes(t)
          ? 'var(--danger, #D32F2F)' : ['bonne_seance', 'progression', 'seance_cle', 'endurance_solide'].includes(t)
          ? 'var(--success, #2D6A4F)' : 'var(--ink-mid, #787470)';
        tagContainer.appendChild(el('span', { style: {
          fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
          background: tagColor + '18', color: tagColor, fontWeight: '500',
        } }, t.replace(/_/g, ' ')));
      }
      box.appendChild(tagContainer);
    }

    // Section blocks
    const sectionDefs = [
      { key: 'execution', label: t('components.sectionExecution') },
      { key: 'charge', label: t('components.sectionCharge') },
      { key: 'fatigue', label: t('components.sectionFatigue') },
      { key: 'conseil', label: t('components.sectionConseil') },
    ];
    for (const { key, label } of sectionDefs) {
      const text = sections[key];
      if (!text) continue;
      const isConseil = key === 'conseil';
      box.appendChild(el('div', { style: { marginBottom: '10px' } },
        el('div', { style: { fontWeight: '600', fontSize: '12px', color: 'var(--ink-mid)', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.5px' } }, label),
        el('div', { style: {
          fontSize: '13px', lineHeight: '1.6',
          ...(isConseil ? { background: 'var(--accent-light, #EBF5FF)', color: 'var(--bg-dark, #141414)', padding: '8px 12px', borderRadius: '6px', borderLeft: '3px solid var(--accent, #2563EB)' } : {}),
        } }, text),
      ));
    }
  } else {
    // Legacy fallback: plain text
    const text = review.review_text || review.review || '';
    box.innerHTML = simpleMarkdown(text);
  }

  const meta = [review.model, (review.generated_at || '').slice(0, 10)].filter(Boolean).join('  ·  ');
  if (meta) {
    box.appendChild(el('div', { className: 'ca-review-meta' }, meta));
  }
  return box;
}

export function weeklyReviewBox(review) {
  if (!review) return null;
  const box = el('div', { className: 'ca-review-box' });
  const sections = review.sections;

  if (sections) {
    // Header with score and stats
    const score = review.score;
    const headerParts = [];
    if (review.activities_count != null) headerParts.push(t('components.sessionsCount', { n: review.activities_count }));
    if (review.total_km != null) headerParts.push(t('components.kmTotal', { km: review.total_km }));
    if (review.total_elevation != null) headerParts.push(t('components.elevTotal', { m: review.total_elevation }));

    const headerRow = el('div', { style: { display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' } });
    if (score != null) {
      const scoreColor = score >= 7 ? 'var(--success, #2D6A4F)' : score >= 4 ? 'var(--warning, #B8860B)' : 'var(--danger, #D32F2F)';
      headerRow.appendChild(el('span', { style: {
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        width: '36px', height: '36px', borderRadius: '50%',
        background: scoreColor, color: '#fff', fontWeight: '700', fontSize: '15px',
      } }, String(score)));
    }
    headerRow.appendChild(el('span', { style: { fontSize: '13px', color: 'var(--ink-mid)' } }, headerParts.join('  ·  ')));
    box.appendChild(headerRow);

    if (sections.resume) {
      box.appendChild(el('p', { style: { fontWeight: '500', marginBottom: '10px', fontSize: '14px' } }, sections.resume));
    }

    // Tags
    const tags = review.tags;
    if (tags && tags.length) {
      const tagContainer = el('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '12px' } });
      for (const t of tags) {
        const tagColor = ['surcharge', 'trop_monotone', 'recuperation_necessaire', 'semaine_lourde'].includes(t)
          ? 'var(--danger, #D32F2F)' : ['bonne_progression', 'equilibree', 'pic_forme'].includes(t)
          ? 'var(--success, #2D6A4F)' : 'var(--ink-mid, #787470)';
        tagContainer.appendChild(el('span', { style: {
          fontSize: '11px', padding: '2px 8px', borderRadius: '10px',
          background: tagColor + '18', color: tagColor, fontWeight: '500',
        } }, t.replace(/_/g, ' ')));
      }
      box.appendChild(tagContainer);
    }

    // Section blocks
    const sectionDefs = [
      { key: 'volume', label: t('components.sectionVolume') },
      { key: 'intensite', label: t('components.sectionIntensity') },
      { key: 'recuperation', label: t('components.sectionRecovery') },
      { key: 'prochaine_semaine', label: t('components.sectionNextWeek') },
    ];
    for (const { key, label } of sectionDefs) {
      const text = sections[key];
      if (!text) continue;
      const isAdvice = key === 'prochaine_semaine';
      box.appendChild(el('div', { style: { marginBottom: '10px' } },
        el('div', { style: { fontWeight: '600', fontSize: '12px', color: 'var(--ink-mid)', marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.5px' } }, label),
        el('div', { style: {
          fontSize: '13px', lineHeight: '1.6',
          ...(isAdvice ? { background: 'var(--accent-light, #EBF5FF)', color: 'var(--bg-dark, #141414)', padding: '8px 12px', borderRadius: '6px', borderLeft: '3px solid var(--accent, #2563EB)' } : {}),
        } }, text),
      ));
    }
  }

  const meta = [review.model, (review.generated_at || '').slice(0, 10)].filter(Boolean).join('  ·  ');
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
