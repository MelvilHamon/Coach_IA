/**
 * overview.js — Vue d'ensemble
 */

import { api } from '../api.js';
import { el, metricCard, sectionTitle, distBar, fmt, loading, empty, acwrStatus, riskStatus } from '../components.js';
import { plotVolume } from '../charts.js';

export async function renderOverview(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  try {
    const [activitiesRes, volumeRes, distRes] = await Promise.all([
      api.activities({ limit: 1 }),
      api.chartVolume(),
      api.chartDistribution(),
    ]);

    container.innerHTML = '';

    const acts = activitiesRes.activities;
    if (!acts.length) {
      container.appendChild(empty('Aucune activité trouvée. Lancer d\'abord le pipeline d\'analyse.'));
      return;
    }

    const last = acts[0];

    // ── KPI Cards ──
    const formV = last.tsb;
    let formStatus = 'neutral';
    if (formV != null) {
      formStatus = formV > 10 ? 'ok' : formV > -10 ? 'warn' : 'alert';
    }

    const cards = el('div', { className: 'ca-metrics-row ca-section' },
      metricCard('Volume semaine', fmt(last.weekly_km, 1), 'km', {
        explain: 'Kilométrage cumulé sur la semaine en cours.',
      }),
      metricCard('ACWR', fmt(last.acwr_km, 2), '', {
        status: acwrStatus(last.acwr_km),
        explain: 'Ratio charge aiguë (7j) / chronique (28j). Zone optimale : 0.8 – 1.3.',
      }),
      metricCard('Risque blessure', fmt(last.injury_risk_score, 0), '/100', {
        status: riskStatus(last.injury_risk_label),
        explain: 'Score composite basé sur l\'ACWR, la monotonie, les pics de charge et les jours consécutifs.',
      }),
      metricCard('Form (TSB)', fmt(formV, 0), '', {
        status: formStatus,
        explain: 'Training Stress Balance = fitness − fatigue. Positif = frais. Négatif = fatigué.',
      }),
    );
    container.appendChild(cards);

    // ── Volume chart ──
    const chartSection = el('div', { className: 'ca-section' },
      sectionTitle('Volume hebdomadaire — 16 semaines'),
      el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-volume', className: 'ca-chart-container' }),
      ),
    );
    container.appendChild(chartSection);

    if (volumeRes.weeks.length) {
      plotVolume(document.getElementById('chart-volume'), volumeRes);
    }

    // ── Distribution ──
    const distTypes = distRes.types || [];
    if (distTypes.length) {
      const distSection = el('div', { className: 'ca-section' },
        sectionTitle('Répartition des séances'),
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
    container.appendChild(el('div', { className: 'ca-error' }, `Erreur : ${err.message}`));
  }
}
