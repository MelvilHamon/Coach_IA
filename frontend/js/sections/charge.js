/**
 * charge.js — Charge d'entraînement : ACWR, flags, risque, répartition 80/20
 */

import { api } from '../api.js';
import {
  el, sectionTitle, metricCard, flagPill, fmt, fmtDate, loading, empty,
  acwrStatus, riskStatus, badge, collapsible,
} from '../components.js';
import { plotAcwr, plotPolarizedBar } from '../charts.js';
import { getCurrentSport } from '../state.js';


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
  return `${monday.toLocaleDateString('fr-FR', opts)} → ${sun.toLocaleDateString('fr-FR', opts)}`;
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
      'Aucune activité avec données FC cette semaine.',
    );
  }

  // ── KPI cards ──
  const kpiRow = el('div', { className: 'ca-metrics-row', style: { marginBottom: '24px' } },
    metricCard('Endurance fond.', fmt(pctEF, 0), '%', {
      status: _polarizedStatus(pctEF),
      explain: `Cible : 80%. Z1+Z2+Z3 = ${fmt(grandEF, 0)} min sur ${fmt(grandTotal, 0)} min totales.`,
    }),
    metricCard('Seuil et +', fmt(pctSeuil, 0), '%', {
      status: _polarizedStatus(pctEF),
      explain: `Cible : 20%. Z4+Z5 = ${fmt(grandSeuil, 0)} min sur ${fmt(grandTotal, 0)} min totales.`,
    }),
    metricCard('Activités', String(actsWithZones), '', {
      status: 'neutral',
      explain: `${weekActs.length} activités cette semaine, dont ${actsWithZones} avec données FC.`,
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
      'Endurance fondamentale = Z1+Z2+Z3 (FC < 80% max)',
    ),
    el('span', {},
      el('span', { style: { display: 'inline-block', width: '10px', height: '10px', background: 'var(--danger)', marginRight: '6px', borderRadius: '1px' } }),
      'Seuil et + = Z4+Z5 (FC \u2265 80% max)',
    ),
  );

  // ── Table ──
  const fmtMin = (v) => `${Math.round(v)}`;
  const fmtPct = (v) => `${v.toFixed(0)}%`;

  const thead = el('thead', {},
    el('tr', {},
      el('th', {}, 'Activité'),
      el('th', {}, 'Date'),
      el('th', {}, 'Type'),
      el('th', { style: { textAlign: 'right' } }, 'Total'),
      el('th', { style: { textAlign: 'right' } }, 'EF'),
      el('th', { style: { textAlign: 'right' } }, 'Seuil+'),
      el('th', { style: { textAlign: 'right' } }, '% EF'),
      el('th', { style: { textAlign: 'right' } }, '% Seuil'),
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
    el('td', { style: { textTransform: 'uppercase', letterSpacing: '0.1em', fontSize: '9px' } }, 'Total semaine'),
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
      container.appendChild(empty('Pas de données ACWR.'));
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
      metricCard('ACWR actuel', fmt(last?.acwr_km, 2), '', {
        status: acwrStatus(last?.acwr_km),
        explain: 'Ratio charge aiguë / chronique. Entre 0.8 et 1.3 = zone optimale. Au-dessus de 1.5 = surcharge.',
      }),
      metricCard('Score de risque', fmt(last?.injury_risk_score, 0), '/100', {
        status: riskStatus(last?.injury_risk_label),
        explain: 'Score composite 0-100 basé sur 4 facteurs : ACWR, monotonie, pic de charge, jours consécutifs.',
      }),
      metricCard('Monotony', fmt(monoV, 2), '', {
        status: monoStatus,
        explain: 'Régularité de la charge 7j (mean/std). > 2.0 = entraînement trop uniforme.',
      }),
      metricCard('Strain', fmt(last?.strain, 0), '', {
        status: 'neutral',
        explain: 'Charge globale = Monotony × somme TRIMP 7j. Combine uniformité et volume.',
      }),
    );
    container.appendChild(cards);

    // ── ACWR chart ──
    const chartSection = el('div', { className: 'ca-section' },
      sectionTitle('ACWR — 90 derniers jours'),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        'L\'ACWR (Acute:Chronic Workload Ratio) compare votre charge des 7 derniers jours à celle des 28 derniers jours. '
        + 'La zone verte (0.8–1.3) est optimale pour progresser en limitant le risque. '
        + 'Au-dessus de 1.5, le risque de blessure augmente significativement.',
      ),
      el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-acwr', className: 'ca-chart-container' }),
      ),
    );
    chartSection.appendChild(collapsible('Méthode de calcul — ACWR', () =>
      el('div', {},
        el('p', {}, 'L\'ACWR est calculé via EWMA (Exponential Weighted Moving Average) selon Hulin et al. (2016) et Williams et al. (2017).'),
        el('p', { style: { fontStyle: 'italic' } }, 'Charge aiguë : EWMA 7j, λ = 2/(7+1) = 0.250'),
        el('p', { style: { fontStyle: 'italic' } }, 'Charge chronique : EWMA 28j, λ = 2/(28+1) ≈ 0.069'),
        el('p', { style: { fontStyle: 'italic' } }, 'ACWR = charge aiguë / charge chronique'),
        el('p', {}, 'La série est construite sur un calendrier quotidien (jours sans activité = 0) '
          + 'pour que les jours de repos décroissent correctement la charge.'),
        el('p', {}, 'Référence : Hulin BT et al. (2016). The acute:chronic workload ratio predicts injury. Br J Sports Med 50(4):231-236.'),
      ),
    ));

    container.appendChild(chartSection);
    plotAcwr(document.getElementById('chart-acwr'), acwrRes);

    // ── Flags ──
    if (last) {
      const flagSection = el('div', { className: 'ca-section' },
        sectionTitle('Alertes actives'),
        el('div', { className: 'ca-metric-explain', style: { marginBottom: '12px' } },
          'Facteurs de risque détectés sur la dernière activité.',
        ),
        el('div', { className: 'ca-flags' },
          flagPill('acwr',        last.flags?.acwr),
          flagPill('monotony',    last.flags?.monotony),
          flagPill('load_spike',  last.flags?.load_spike),
          flagPill('consecutive', last.flags?.consecutive),
        ),
      );
      flagSection.appendChild(collapsible('Méthode — Score de risque blessure', () =>
        el('div', {},
          el('p', {}, 'Score composite 0-100 basé sur 4 facteurs indépendants :'),
          el('p', {}, 'ACWR > 1.5 → +40 pts, ACWR 1.3-1.5 → +20 pts'),
          el('p', {}, 'Variation charge > 50% → +35 pts, > 30% → +20 pts'),
          el('p', {}, 'Monotonie (Foster 1998) > 2.0 → +20 pts'),
          el('p', {}, '≥ 6 jours consécutifs → +25 pts, ≥ 4 jours → +15 pts'),
          el('p', {}, 'Labels : faible (0-24), modéré (25-49), élevé (50-74), critique (75-100).'),
        ),
      ));

      container.appendChild(flagSection);
    }

    // ── 80/20 Polarized Training ──────────────────────────────────────────────
    const now = new Date();
    const thisMonday = _mondayOf(now);
    const lastMonday = new Date(thisMonday);
    lastMonday.setDate(lastMonday.getDate() - 7);

    let selectedMonday = thisMonday;

    const polarizedSection = el('div', { className: 'ca-section' },
      sectionTitle('Répartition 80/20 de la semaine'),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        'L\'entraînement polarisé vise 80% du volume en endurance fondamentale (FC < 80% max) '
        + 'et 20% en intensité seuil ou supérieure (FC ≥ 80% max). '
        + 'Méthode validée par Seiler (2010) et Stöggl & Sperlich (2014).',
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
    } }, '\u25C0 Semaine précédente');

    const nextBtn = el('button', { className: 'ca-btn', onClick: () => {
      const next = new Date(selectedMonday);
      next.setDate(next.getDate() + 7);
      if (next <= thisMonday) {
        selectedMonday = next;
        weekLabel.textContent = _fmtWeekRange(selectedMonday);
        contentArea.innerHTML = '';
        contentArea.appendChild(_buildPolarizedBlock(allActivities, selectedMonday));
      }
    } }, 'Semaine suivante \u25B6');

    const weekSelector = el('div', {
      style: { display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '20px', flexWrap: 'wrap' },
    }, prevBtn, weekLabel, nextBtn);

    polarizedSection.appendChild(weekSelector);

    const contentArea = el('div');
    contentArea.appendChild(_buildPolarizedBlock(allActivities, selectedMonday));
    polarizedSection.appendChild(contentArea);

    // Collapsible explanation
    polarizedSection.appendChild(collapsible('Méthode de calcul — Zones FC et répartition 80/20', () =>
      el('div', {},
        el('p', {}, 'Les zones de fréquence cardiaque sont calculées en pourcentage de la FC maximale (FC_max), '
          + 'configurée dans le profil athlète. La répartition utilise les minutes par zone déjà calculées '
          + 'pour chaque activité à partir des streams Strava (échantillonnage seconde par seconde).'),
        el('p', { style: { fontWeight: '500' } }, 'Définition des 5 zones :'),
        el('p', {}, 'Z1 (Récupération) : < 60% FC_max — effort très léger, échauffement, récupération.'),
        el('p', {}, 'Z2 (Endurance) : 60-70% FC_max — endurance de base, conversation possible.'),
        el('p', {}, 'Z3 (Tempo) : 70-80% FC_max — effort modéré, limite haute de l\'endurance fondamentale.'),
        el('p', {}, 'Z4 (Seuil) : 80-90% FC_max — effort soutenu, seuil lactique, tempo rapide.'),
        el('p', {}, 'Z5 (VO2max) : > 90% FC_max — effort maximal, intervalles courts.'),
        el('p', { style: { fontWeight: '500', marginTop: '12px' } }, 'Règle 80/20 :'),
        el('p', {}, 'Endurance fondamentale = Z1 + Z2 + Z3 (toute minute passée sous 80% FC_max).'),
        el('p', {}, 'Seuil et au-dessus = Z4 + Z5 (toute minute passée au-dessus de 80% FC_max).'),
        el('p', {}, 'L\'objectif est d\'avoir ~80% du temps total d\'entraînement hebdomadaire en endurance '
          + 'fondamentale et ~20% en intensité. Une marge de 75-85% est considérée comme acceptable.'),
        el('p', { style: { marginTop: '8px' } },
          'Références : Seiler S. (2010). What is Best Practice for Training Intensity and Duration Distribution in Endurance Athletes? '
          + 'Int J Sports Physiol Perform. Stöggl T, Sperlich B. (2014). Polarized training has greater impact on key endurance variables. '
          + 'Front Physiol 5:33.'),
      ),
    ));

    container.appendChild(polarizedSection);

  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}
