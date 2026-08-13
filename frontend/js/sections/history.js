/**
 * history.js — Historique des activités + reviews
 */

import { api } from '../api.js';
import {
  el, sectionTitle, badge, fmt, fmtDate, loading, empty,
  acwrColor, riskColor, reviewBox, tableWrap,
} from '../components.js';
import { getCurrentSport, setPendingActivityId } from '../state.js';
import { t } from '../i18n.js';

let _currentPeriod = 'all';
let _currentType = null;
let _reviewSelect = null;

export async function renderHistory(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  const sport = getCurrentSport();

  try {
    const [activitiesRes, typesRes] = await Promise.all([
      api.activities({ limit: 500, sport }),
      api.activityTypes(),
    ]);

    container.innerHTML = '';

    const allActivities = activitiesRes.activities;
    if (!allActivities.length) {
      container.appendChild(empty());
      return;
    }

    // ── Controls ──
    const typeSelect = el('select', { className: 'ca-select', onChange: () => { _currentType = typeSelect.value || null; refresh(); } },
      el('option', { value: '' }, t('history.allTypes')),
    );
    for (const t of typesRes.types) {
      typeSelect.appendChild(el('option', { value: t }, t));
    }

    const periodBtns = ['30j', '90j', 'all'].map(p => {
      const btn = el('button', {
        className: `ca-radio-btn ${p === _currentPeriod ? 'active' : ''}`,
        onClick: () => {
          _currentPeriod = p;
          document.querySelectorAll('.ca-radio-btn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          refresh();
        },
      }, p === 'all' ? t('history.all') : p);
      return btn;
    });

    const controls = el('div', { className: 'ca-section', style: { display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap' } },
      el('div', { className: 'ca-select-wrap' }, typeSelect),
      el('div', { className: 'ca-radio-group' }, ...periodBtns),
    );
    container.appendChild(controls);

    // ── Table container ──
    const tableContainer = el('div', { className: 'ca-section' });
    container.appendChild(tableContainer);

    // ── Review section ──
    const reviewSection = el('div', { className: 'ca-section' },
      sectionTitle(t('common.reviewCoach')),
    );
    _reviewSelect = el('select', { className: 'ca-select', style: { marginBottom: '12px' } });
    const reviewContent = el('div');
    const genBtn = el('button', { className: 'ca-btn accent', onClick: generateReview }, t('common.generateOrRegenerate'));

    reviewSection.appendChild(el('div', { style: { display: 'flex', gap: '12px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '16px' } },
      el('div', { className: 'ca-select-wrap' }, _reviewSelect),
      genBtn,
    ));
    reviewSection.appendChild(reviewContent);
    container.appendChild(reviewSection);

    // ── Render ──
    function refresh() {
      let filtered = [...allActivities];
      if (_currentType) filtered = filtered.filter(a => a.session_type === _currentType);
      if (_currentPeriod !== 'all') {
        const days = parseInt(_currentPeriod);
        const cutoff = new Date(Date.now() - days * 86400000);
        filtered = filtered.filter(a => new Date(a.date) >= cutoff);
      }
      renderTable(tableContainer, filtered);
      populateReviewSelect(filtered);
    }

    async function generateReview() {
      const id = _reviewSelect?.value;
      if (!id) return;
      genBtn.textContent = t('common.generating');
      genBtn.disabled = true;
      try {
        const res = await api.generateReview(Number(id));
        reviewContent.innerHTML = '';
        if (res.review) {
          reviewContent.appendChild(reviewBox(res.review));
        } else if (res.error) {
          reviewContent.appendChild(el('div', { className: 'ca-error' }, res.error));
        }
      } catch (e) {
        reviewContent.appendChild(el('div', { className: 'ca-error' }, e.message));
      } finally {
        genBtn.textContent = t('common.generateOrRegenerate');
        genBtn.disabled = false;
      }
    }

    function populateReviewSelect(acts) {
      _reviewSelect.innerHTML = '';
      for (const a of acts.slice(0, 200)) {
        _reviewSelect.appendChild(el('option', { value: a.id },
          `${fmtDate(a.date)} — ${(a.nom || '').slice(0, 28)} [${a.session_type || ''}]`,
        ));
      }
      // Load cached review for first
      if (acts.length) loadReview(acts[0].id, reviewContent);
    }

    async function loadReview(id, target) {
      try {
        const res = await api.review(id);
        target.innerHTML = '';
        if (res.review) {
          target.appendChild(reviewBox(res.review));
        } else {
          target.appendChild(el('div', { className: 'ca-empty' }, t('common.noReview')));
        }
      } catch {
        target.innerHTML = '';
      }
    }

    _reviewSelect.addEventListener('change', () => {
      loadReview(Number(_reviewSelect.value), reviewContent);
    });

    refresh();

  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, t('common.errorPrefix', { msg: err.message })));
  }
}

function renderTable(container, activities) {
  container.innerHTML = '';

  if (!activities.length) {
    container.appendChild(empty(t('history.noActSelection')));
    return;
  }

  const sport = getCurrentSport();
  const speedCol = sport === 'velo' ? t('common.speed') : t('common.pace');

  const thead = el('thead', {},
    el('tr', {},
      ...[t('common.date'), 'Nom', t('common.type'), t('common.distance'), speedCol, 'TRIMP', 'ACWR', t('history.cols.risk')].map(h =>
        el('th', {}, h),
      ),
    ),
  );

  const tbody = el('tbody');
  for (const a of activities) {
    const acwr_v = a.acwr_km;
    const risk = a.injury_risk_label || '—';

    let speedDisplay = a.pace_display || '—';
    if (sport === 'velo' && a.distance_km && a.temps_min && a.temps_min > 0) {
      speedDisplay = fmt(a.distance_km / (a.temps_min / 60), 1) + ' km/h';
    }

    const row = el('tr', {
      style: { cursor: 'pointer' },
      title: t('history.seeAnalyse'),
      onClick: () => {
        setPendingActivityId(a.id);
        window.location.hash = 'analyse';
      },
    },
      el('td', { className: 'dim' }, fmtDate(a.date)),
      el('td', { className: 'dim' }, (a.nom || '').slice(0, 30)),
      el('td', {}, badge(a.session_type)),
      el('td', {}, a.distance_km != null ? fmt(a.distance_km, 1) + ' km' : '—'),
      el('td', {}, speedDisplay),
      el('td', {}, fmt(a.trimp, 0)),
      el('td', { style: { color: acwrColor(acwr_v) } }, fmt(acwr_v, 2)),
      el('td', { style: { color: riskColor(risk), fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.1em' } }, risk),
    );
    tbody.appendChild(row);
  }

  // primary: 1 → la colonne « Nom » sert de titre de carte sur mobile.
  container.appendChild(tableWrap(thead, tbody, { primary: 1 }));
}
