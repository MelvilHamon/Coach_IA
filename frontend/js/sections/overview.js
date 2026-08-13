/**
 * overview.js — Vue d'ensemble
 */

import { api } from '../api.js';
import {
  el, metricCard, sectionTitle, distBar, fmt, fmtDate, loading, empty,
  acwrStatus, badge, weeklyReviewBox, tableWrap,
} from '../components.js';
import { plotVolume, plotPolarizedBar } from '../charts.js';
import { getCurrentSport, setPendingActivityId } from '../state.js';
import { t, getLang } from '../i18n.js';


// ── Week helpers ────────────────────────────────────────────────────────────

function _mondayOf(date) {
  const d = new Date(date);
  const day = d.getDay();
  const diff = day === 0 ? 6 : day - 1;
  d.setDate(d.getDate() - diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function _sundayOf(monday) {
  const d = new Date(monday);
  d.setDate(d.getDate() + 6);
  d.setHours(23, 59, 59, 999);
  return d;
}

function _fmtWeekRange(monday) {
  const sun = _sundayOf(monday);
  const opts = { day: '2-digit', month: 'short' };
  const loc = getLang() === 'en' ? 'en-US' : 'fr-FR';
  return `${monday.toLocaleDateString(loc, opts)} → ${sun.toLocaleDateString(loc, opts)}`;
}


// ── 80/20 status ────────────────────────────────────────────────────────────

function _polarizedStatus(pctEF) {
  if (pctEF >= 75 && pctEF <= 85) return 'ok';
  if ((pctEF >= 70 && pctEF < 75) || (pctEF > 85 && pctEF <= 90)) return 'warn';
  return 'alert';
}


// ── 80/20 block builder (récupéré de charge.js) ─────────────────────────────

function _buildPolarizedBlock(activities, weekMonday) {
  const weekStart = weekMonday;
  const weekEnd = _sundayOf(weekMonday);

  const weekActs = activities.filter(a => {
    const d = new Date(a.date);
    return d >= weekStart && d <= weekEnd;
  });

  let totalZ1 = 0, totalZ2 = 0, totalZ3 = 0, totalZ4 = 0, totalZ5 = 0;
  let actsWithZones = 0;
  const rows = [];

  for (const a of weekActs) {
    const z1 = a.z1_min || 0;
    const z2 = a.z2_min || 0;
    const z3 = a.z3_min || 0;
    const z4 = a.z4_min || 0;
    const z5 = a.z5_min || 0;
    const total = z1 + z2 + z3 + z4 + z5;

    if (total > 0) {
      actsWithZones++;
      totalZ1 += z1; totalZ2 += z2; totalZ3 += z3;
      totalZ4 += z4; totalZ5 += z5;

      const ef = z1 + z2 + z3;
      const seuil = z4 + z5;
      rows.push({
        id: a.id,
        nom: a.nom || '—',
        date: a.date,
        type: a.session_type || '',
        total, ef, seuil,
        pctEF: (ef / total * 100),
        pctSeuil: (seuil / total * 100),
      });
    }
  }

  const grandTotal = totalZ1 + totalZ2 + totalZ3 + totalZ4 + totalZ5;
  const grandEF = totalZ1 + totalZ2 + totalZ3;
  const grandSeuil = totalZ4 + totalZ5;
  const pctEF = grandTotal > 0 ? grandEF / grandTotal * 100 : 0;
  const pctSeuil = grandTotal > 0 ? grandSeuil / grandTotal * 100 : 0;

  if (grandTotal === 0) {
    return el('div', { className: 'ca-empty' }, t('charge.noFcWeek'));
  }

  const barEl = el('div', { id: 'chart-polarized', className: 'ca-chart-container', style: { minHeight: '76px' } });
  const barCard = el('div', { className: 'ca-polarized-bar-card' }, barEl);

  const fmtMin = (v) => `${Math.round(v)}`;
  const fmtPct = (v) => `${v.toFixed(0)}%`;

  const thead = el('thead', {},
    el('tr', {},
      el('th', {}, t('common.activity')),
      el('th', {}, t('common.date')),
      el('th', {}, t('common.type')),
      el('th', { style: { textAlign: 'right' } }, t('common.total')),
      el('th', { style: { textAlign: 'right' } }, t('charge.colEf')),
      el('th', { style: { textAlign: 'right' } }, t('charge.colSeuil')),
      el('th', { style: { textAlign: 'right' } }, t('charge.colPctEf')),
      el('th', { style: { textAlign: 'right' } }, t('charge.colPctSeuil')),
    ),
  );

  const tbody = el('tbody');
  for (const r of rows) {
    tbody.appendChild(el('tr', {
      style: { cursor: 'pointer' },
      title: t('history.seeAnalyse'),
      onClick: () => {
        setPendingActivityId(r.id);
        window.location.hash = 'analyse';
      },
    },
      el('td', {}, (r.nom || '').slice(0, 28)),
      el('td', { className: 'dim' }, fmtDate(r.date)),
      el('td', {}, badge(r.type)),
      el('td', { style: { textAlign: 'right' } }, `${fmtMin(r.total)} min`),
      el('td', { style: { textAlign: 'right', color: 'var(--success)' } }, `${fmtMin(r.ef)}`),
      el('td', { style: { textAlign: 'right', color: 'var(--danger)' } }, `${fmtMin(r.seuil)}`),
      el('td', { style: { textAlign: 'right' } }, fmtPct(r.pctEF)),
      el('td', { style: { textAlign: 'right' } }, fmtPct(r.pctSeuil)),
    ));
  }
  tbody.appendChild(el('tr', { style: { fontWeight: '600', borderTop: '2px solid var(--ink)' } },
    el('td', { style: { textTransform: 'uppercase', letterSpacing: '0.1em', fontSize: '9px' } }, t('charge.weekTotal')),
    el('td', {}),
    el('td', {}),
    el('td', { style: { textAlign: 'right' } }, `${fmtMin(grandTotal)} min`),
    el('td', { style: { textAlign: 'right', color: 'var(--success)' } }, `${fmtMin(grandEF)}`),
    el('td', { style: { textAlign: 'right', color: 'var(--danger)' } }, `${fmtMin(grandSeuil)}`),
    el('td', { style: { textAlign: 'right' } }, fmtPct(pctEF)),
    el('td', { style: { textAlign: 'right' } }, fmtPct(pctSeuil)),
  ));

  // primary: 0 → le nom de la séance sert de titre de carte sur mobile.
  const table = tableWrap(thead, tbody, { primary: 0 });
  table.style.marginTop = '24px';

  const wrapper = el('div', {}, barCard, table);

  requestAnimationFrame(() => {
    const chartEl = document.getElementById('chart-polarized');
    if (chartEl) plotPolarizedBar(chartEl, pctEF, pctSeuil);
  });

  return wrapper;
}


// ── Main render ─────────────────────────────────────────────────────────────

export async function renderOverview(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  const sport = getCurrentSport();

  try {
    const [activitiesRes, volumeRes, distRes] = await Promise.all([
      api.activities({ limit: 500, sport }),
      api.chartVolume(sport),
      api.chartDistribution(sport),
    ]);

    container.innerHTML = '';

    const acts = activitiesRes.activities;
    if (!acts.length) {
      container.appendChild(empty(t('common.noActivitiesFound')));
      return;
    }

    const last = acts[0];

    // ── KPI cards : km/semaine + Indice de surcharge ──
    const cards = el('div', { className: 'ca-metrics-row ca-section' },
      metricCard(t('overview.weekVolume'), fmt(last.weekly_km, 1), 'km', {
        explain: t('overview.weekVolumeExplain'),
      }),
      metricCard(t('overview.acwrLabel'), fmt(last.acwr_km, 2), '', {
        status: acwrStatus(last.acwr_km),
        explain: t('overview.acwrExplain'),
      }),
    );
    container.appendChild(cards);

    // ── Volume + Indice de surcharge chart ──
    const chartSection = el('div', { className: 'ca-section' },
      sectionTitle(t('overview.weeklyVolumeTitle')),
      el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-volume', className: 'ca-chart-container' }),
      ),
    );
    container.appendChild(chartSection);

    // ── 80/20 section (avec sélecteur de semaine + table) ──
    const thisMonday = _mondayOf(new Date());
    let selectedMonday = thisMonday;

    const polarizedSection = el('div', { id: 'polarized-section', className: 'ca-section' },
      sectionTitle(t('charge.polarizedTitle')),
    );

    const renderWeek = (monday) => {
      selectedMonday = monday;
      contentArea.innerHTML = '';
      contentArea.appendChild(_buildPolarizedBlock(acts, selectedMonday));
    };

    const contentArea = el('div');
    contentArea.appendChild(_buildPolarizedBlock(acts, selectedMonday));
    polarizedSection.appendChild(contentArea);

    // Volume chart : clic → scroll vers la semaine cliquée dans 80/20
    if (volumeRes.weeks.length) {
      plotVolume(document.getElementById('chart-volume'), volumeRes, {
        onWeekClick: (isoWeek) => {
          const m = _mondayOf(new Date(isoWeek));
          renderWeek(m);
          polarizedSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        },
      });
    }

    container.appendChild(polarizedSection);

    // ── Bilan hebdomadaire ──
    const weeklyOffset = new Date().getDay() === 0 ? 0 : 1;

    const weeklySection = el('div', { className: 'ca-section' },
      sectionTitle(weeklyOffset === 0 ? t('overview.weeklyReview') : t('overview.lastWeeklyReview')),
    );
    const weeklyContent = el('div');
    const weeklyGenBtn = el('button', { className: 'ca-btn accent', style: { marginBottom: '12px' } }, t('overview.generateBilan'));

    weeklyGenBtn.addEventListener('click', async () => {
      weeklyGenBtn.textContent = t('common.generating');
      weeklyGenBtn.disabled = true;
      try {
        const res = await api.generateWeeklyReview(weeklyOffset);
        weeklyContent.innerHTML = '';
        if (res.error) weeklyContent.appendChild(el('div', { className: 'ca-empty' }, res.error));
        else if (res.review) weeklyContent.appendChild(weeklyReviewBox(res.review));
        else weeklyContent.appendChild(el('div', { className: 'ca-empty' }, t('common.noBilan')));
      } catch (e) {
        weeklyContent.innerHTML = '';
        weeklyContent.appendChild(el('div', { className: 'ca-error' }, e.message));
      } finally {
        weeklyGenBtn.textContent = t('overview.regenerateBilan');
        weeklyGenBtn.disabled = false;
      }
    });

    weeklySection.appendChild(weeklyGenBtn);

    try {
      const cachedWeekly = await api.weeklyReview(weeklyOffset);
      if (cachedWeekly?.review) {
        weeklyContent.appendChild(weeklyReviewBox(cachedWeekly.review));
        weeklyGenBtn.textContent = t('overview.regenerateBilan');
      } else {
        weeklyContent.appendChild(el('div', { className: 'ca-empty' }, t('common.copyClick')));
      }
    } catch (_) { /* ignore */ }

    weeklySection.appendChild(weeklyContent);
    container.appendChild(weeklySection);

    // ── Distribution ──
    const distTypes = distRes.types || [];
    if (distTypes.length) {
      const distSection = el('div', { className: 'ca-section' },
        sectionTitle(t('overview.distribution')),
      );
      const barsWrap = el('div', { style: { maxWidth: '560px' } });
      for (const t of distTypes) {
        barsWrap.appendChild(distBar(t.type, t.count, t.pct));
      }
      distSection.appendChild(barsWrap);
      container.appendChild(distSection);
    }

  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, t('common.errorPrefix', { msg: err.message })));
  }
}
