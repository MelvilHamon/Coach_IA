/**
 * charge.js — Charge d'entraînement : ACWR, flags, risque
 */

import { api } from '../api.js';
import {
  el, sectionTitle, metricCard, flagPill, fmt, loading, empty,
  acwrStatus, riskStatus, collapsible,
} from '../components.js';
import { plotAcwr } from '../charts.js';

export async function renderCharge(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  try {
    const [acwrRes, activitiesRes] = await Promise.all([
      api.chartAcwr(),
      api.activities({ limit: 1 }),
    ]);

    container.innerHTML = '';

    if (!acwrRes.points?.length) {
      container.appendChild(empty('Pas de données ACWR.'));
      return;
    }

    const last = activitiesRes.activities[0];

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

  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}
