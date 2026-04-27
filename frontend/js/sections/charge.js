/**
 * charge.js — Charge d'entraînement : ACWR, flags, risque, répartition 80/20
 */

import { api } from '../api.js';
import {
  el, sectionTitle, metricCard, flagPill, fmt, fmtDate, loading, empty,
  acwrStatus, riskStatus, badge, collapsible, methodBody,
} from '../components.js';
import { plotAcwr, plotPolarizedBar } from '../charts.js';
import { getCurrentSport } from '../state.js';
import { t, getLang } from '../i18n.js';


// ── Week helpers ────────────────────────────────────────────────────────────

function _mondayOf(date) {
  const d = new Date(date);
  const day = d.getDay(); // 0=Sun
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


// ── 80/20 block builder ─────────────────────────────────────────────────────

function _buildPolarizedBlock(activities, weekMonday) {
  const weekStart = weekMonday;
  const weekEnd = _sundayOf(weekMonday);

  // Filter to the selected week
  const weekActs = activities.filter(a => {
    const d = new Date(a.date);
    return d >= weekStart && d <= weekEnd;
  });

  // Aggregate zones
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
        nom: a.nom || '—',
        date: a.date,
        type: a.session_type || '',
        total: total,
        ef: ef,
        seuil: seuil,
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
    return el('div', { className: 'ca-empty' },
      t('charge.noFcWeek'),
    );
  }

  // ── KPI cards ──
  const kpiRow = el('div', { className: 'ca-metrics-row', style: { marginBottom: '24px' } },
    metricCard(t('charge.enduranceFond'), fmt(pctEF, 0), '%', {
      status: _polarizedStatus(pctEF),
      explain: t('charge.target80', { ef: fmt(grandEF, 0), tot: fmt(grandTotal, 0) }),
    }),
    metricCard(t('charge.threshold'), fmt(pctSeuil, 0), '%', {
      status: _polarizedStatus(pctEF),
      explain: t('charge.target20', { seuil: fmt(grandSeuil, 0), tot: fmt(grandTotal, 0) }),
    }),
    metricCard(t('common.activities').charAt(0).toUpperCase() + t('common.activities').slice(1), String(actsWithZones), '', {
      status: 'neutral',
      explain: t('charge.activitiesExplain', { week: weekActs.length, fc: actsWithZones }),
    }),
  );

  // ── Progress bar ──
  const barEl = el('div', { id: 'chart-polarized', style: { marginBottom: '16px' } });

  // ── Legend ──
  const legend = el('div', {
    className: 'ca-metric-explain',
    style: { marginBottom: '20px', display: 'flex', gap: '24px', flexWrap: 'wrap' },
  },
    el('span', {},
      el('span', { style: { display: 'inline-block', width: '10px', height: '10px', background: 'var(--success)', marginRight: '6px', borderRadius: '1px' } }),
      t('charge.legendEf'),
    ),
    el('span', {},
      el('span', { style: { display: 'inline-block', width: '10px', height: '10px', background: 'var(--danger)', marginRight: '6px', borderRadius: '1px' } }),
      t('charge.legendSeuil'),
    ),
  );

  // ── Table ──
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
    tbody.appendChild(el('tr', {},
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

  // Total row
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

  const table = el('div', { className: 'ca-table-wrap' },
    el('table', { className: 'ca-table' }, thead, tbody),
  );

  // ── Assemble ──
  const wrapper = el('div', {},
    kpiRow,
    barEl,
    legend,
    table,
  );

  // Render chart after DOM insertion
  requestAnimationFrame(() => {
    const chartEl = document.getElementById('chart-polarized');
    if (chartEl) plotPolarizedBar(chartEl, pctEF, pctSeuil);
  });

  return wrapper;
}


// ── Main render ─────────────────────────────────────────────────────────────

export async function renderCharge(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  const sport = getCurrentSport();

  try {
    const [acwrRes, activitiesRes] = await Promise.all([
      api.chartAcwr(sport),
      api.activities({ limit: 500, sport }),
    ]);

    container.innerHTML = '';

    if (!acwrRes.points?.length) {
      container.appendChild(empty(t('charge.noAcwr')));
      return;
    }

    const allActivities = activitiesRes.activities;
    const last = allActivities[0];

    // Monotony/Strain status helpers
    const monoV = last?.monotony;
    let monoStatus = 'ok';
    if (monoV != null) {
      monoStatus = monoV > 2.5 ? 'alert' : monoV > 2.0 ? 'warn' : 'ok';
    }

    // ── KPI row ──
    const cards = el('div', { className: 'ca-metrics-row ca-section' },
      metricCard(t('charge.acwrCurrent'), fmt(last?.acwr_km, 2), '', {
        status: acwrStatus(last?.acwr_km),
        explain: t('charge.acwrCurrentExplain'),
      }),
      metricCard(t('charge.riskScore'), fmt(last?.injury_risk_score, 0), '/100', {
        status: riskStatus(last?.injury_risk_label),
        explain: t('charge.riskExplain'),
      }),
      metricCard('Monotony', fmt(monoV, 2), '', {
        status: monoStatus,
        explain: t('charge.monotonyExplain'),
      }),
      metricCard('Strain', fmt(last?.strain, 0), '', {
        status: 'neutral',
        explain: t('charge.strainExplain'),
      }),
    );
    container.appendChild(cards);

    // ── ACWR chart ──
    const chartSection = el('div', { className: 'ca-section' },
      sectionTitle(t('charge.acwrTitle')),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        t('charge.acwrChartExplain'),
      ),
      el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-acwr', className: 'ca-chart-container' }),
      ),
    );
    chartSection.appendChild(collapsible(t('charge.methodAcwr'), () => methodBody('charge.methodAcwrBody')));

    container.appendChild(chartSection);
    plotAcwr(document.getElementById('chart-acwr'), acwrRes);

    // ── Flags ──
    if (last) {
      const flagSection = el('div', { className: 'ca-section' },
        sectionTitle(t('charge.flagsTitle')),
        el('div', { className: 'ca-metric-explain', style: { marginBottom: '12px' } },
          t('charge.flagsExplain'),
        ),
        el('div', { className: 'ca-flags' },
          flagPill('acwr',        last.flags?.acwr),
          flagPill('monotony',    last.flags?.monotony),
          flagPill('load_spike',  last.flags?.load_spike),
          flagPill('consecutive', last.flags?.consecutive),
        ),
      );
      flagSection.appendChild(collapsible(t('charge.methodRisk'), () => methodBody('charge.methodRiskBody')));

      container.appendChild(flagSection);
    }

    // ── 80/20 Polarized Training ──────────────────────────────────────────────
    const now = new Date();
    const thisMonday = _mondayOf(now);
    const lastMonday = new Date(thisMonday);
    lastMonday.setDate(lastMonday.getDate() - 7);

    let selectedMonday = thisMonday;

    const polarizedSection = el('div', { className: 'ca-section' },
      sectionTitle(t('charge.polarizedTitle')),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        t('charge.polarizedExplain'),
      ),
    );

    // Week selector
    const weekLabel = el('span', {
      style: { fontFamily: 'var(--font-mono)', fontSize: '11px' },
    }, _fmtWeekRange(selectedMonday));

    const prevBtn = el('button', { className: 'ca-btn', onClick: () => {
      selectedMonday = new Date(selectedMonday);
      selectedMonday.setDate(selectedMonday.getDate() - 7);
      weekLabel.textContent = _fmtWeekRange(selectedMonday);
      contentArea.innerHTML = '';
      contentArea.appendChild(_buildPolarizedBlock(allActivities, selectedMonday));
    } }, t('charge.prevWeek'));

    const nextBtn = el('button', { className: 'ca-btn', onClick: () => {
      const next = new Date(selectedMonday);
      next.setDate(next.getDate() + 7);
      if (next <= thisMonday) {
        selectedMonday = next;
        weekLabel.textContent = _fmtWeekRange(selectedMonday);
        contentArea.innerHTML = '';
        contentArea.appendChild(_buildPolarizedBlock(allActivities, selectedMonday));
      }
    } }, t('charge.nextWeek'));

    const weekSelector = el('div', {
      style: { display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '20px', flexWrap: 'wrap' },
    }, prevBtn, weekLabel, nextBtn);

    polarizedSection.appendChild(weekSelector);

    const contentArea = el('div');
    contentArea.appendChild(_buildPolarizedBlock(allActivities, selectedMonday));
    polarizedSection.appendChild(contentArea);

    // Collapsible explanation
    polarizedSection.appendChild(collapsible(t('charge.methodZones'), () => methodBody('charge.methodZonesBody')));

    container.appendChild(polarizedSection);

  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}
