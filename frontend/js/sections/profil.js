/**
 * profil.js — Profil athlète : Records, Fitness/Fatigue/Form, Monotony/Strain
 */

import { api } from '../api.js';
import { el, sectionTitle, loading, empty, collapsible, fmt, fmtDate } from '../components.js';
import { plotFitness, plotMonotony } from '../charts.js';
import { getCurrentSport } from '../state.js';

export async function renderProfil(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  const sport = getCurrentSport();

  try {
    const [recordsRes, fitnessRes, monotonyRes] = await Promise.all([
      api.records().catch(() => ({ distances: {} })),
      api.chartFitness(sport).catch(() => ({ points: [] })),
      api.chartMonotony(sport).catch(() => ({ points: [] })),
    ]);

    container.innerHTML = '';

    // ── Personal Records (filtered by current sport) ──
    const isVelo = sport === 'velo';
    const prSection = el('div', { className: 'ca-section' },
      sectionTitle(isVelo ? 'Records personnels — Vélo' : 'Records personnels — Course'),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        isVelo
          ? 'Meilleurs temps détectés par sliding window sur les traces GPS. Distances de 1 km à 100 km.'
          : 'Meilleurs temps détectés par sliding window sur les traces GPS. Distances standards de 400m au marathon.',
      ),
    );

    // New format: { run: {...}, velo: {...} } — fallback for old format (flat dict)
    const allDist = recordsRes.distances || {};
    const distances = allDist[sport] || (allDist.run ? {} : allDist);
    const distKeys = Object.keys(distances);

    if (distKeys.length) {
      const table = el('table', { className: 'ca-records-table' },
        el('thead', {},
          el('tr', {},
            el('th', {}, 'Distance'),
            el('th', {}, 'Temps'),
            el('th', {}, isVelo ? 'Vitesse' : 'Allure'),
            el('th', {}, 'Date'),
          ),
        ),
      );

      const tbody = el('tbody');
      for (const dist of distKeys) {
        const r = distances[dist];
        const timeStr = _formatTime(r.time_s);

        // For cycling: show speed (km/h) instead of pace
        let paceOrSpeed;
        if (isVelo) {
          const distM = _parseDistMeters(dist);
          if (distM && r.time_s > 0) {
            const speedKmh = (distM / 1000) / (r.time_s / 3600);
            paceOrSpeed = fmt(speedKmh, 1) + ' km/h';
          } else {
            paceOrSpeed = r.pace + '/km';
          }
        } else {
          paceOrSpeed = r.pace + '/km';
        }

        tbody.appendChild(el('tr', {},
          el('td', {}, dist),
          el('td', { className: 'pr-time' }, timeStr),
          el('td', { className: 'pr-pace' }, paceOrSpeed),
          el('td', {}, r.date ? fmtDate(r.date) : '—'),
        ));
      }
      table.appendChild(tbody);
      prSection.appendChild(table);
    } else {
      prSection.appendChild(empty('Aucun record — données GPS insuffisantes.'));
    }

    prSection.appendChild(collapsible('Méthode de calcul — Records personnels', () =>
      el('div', {},
        el('p', {}, 'Pour chaque distance cible, '
          + 'on parcourt la trace GPS avec une fenêtre glissante sur la distance cumulée (haversine).'),
        el('p', {}, 'Pour chaque point i, on cherche le premier point j tel que '
          + 'dist_cum[j] − dist_cum[i] ≥ distance_cible. Le temps écoulé time_s[j] − time_s[i] est le temps du segment.'),
        el('p', {}, 'Le record est le minimum global sur toutes les traces GPS disponibles (Strava + Garmin).'),
      ),
    ));
    container.appendChild(prSection);

    // ── Fitness / Fatigue / Form ──
    const ffSection = el('div', { className: 'ca-section' },
      sectionTitle('Fitness / Fatigue / Form — 90 jours'),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        'Modèle de Banister (EWMA). CTL = forme chronique (42j), ATL = fatigue aiguë (7j), TSB = CTL − ATL. '
        + 'TSB positif = frais et en forme. TSB négatif = fatigue accumulée.',
      ),
    );

    if (fitnessRes.points?.length) {
      const chartEl = el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-fitness', className: 'ca-chart-container' }),
      );
      ffSection.appendChild(chartEl);
    } else {
      ffSection.appendChild(empty('Données Fitness/Fatigue non disponibles — nécessite FC.'));
    }

    ffSection.appendChild(collapsible('Méthode de calcul — Banister EWMA', () =>
      el('div', {},
        el('p', {}, 'Le modèle impulse-response de Banister (1991) modélise la performance comme '
          + 'la différence entre un effet positif (fitness) et négatif (fatigue) de l\'entraînement.'),
        el('p', { style: { fontStyle: 'italic' } },
          'CTL[n] = CTL[n-1] + (TRIMP[n] − CTL[n-1]) / 42'),
        el('p', { style: { fontStyle: 'italic' } },
          'ATL[n] = ATL[n-1] + (TRIMP[n] − ATL[n-1]) / 7'),
        el('p', { style: { fontStyle: 'italic' } },
          'TSB = CTL − ATL'),
        el('p', {}, 'Le TRIMP (Training Impulse) est calculé via la formule de Banister : '
          + 'TRIMP = durée × ΔHR × C × exp(k × ΔHR), où ΔHR est la fraction de réserve cardiaque.'),
        el('p', {}, 'Référence : Banister EW (1991). Modeling elite athletic performance. '
          + 'In: Physiological Testing of the High Performance Athlete. Human Kinetics.'),
      ),
    ));
    container.appendChild(ffSection);

    if (fitnessRes.points?.length) {
      plotFitness(document.getElementById('chart-fitness'), fitnessRes);
    }

    // ── Monotony & Strain ──
    const msSection = el('div', { className: 'ca-section' },
      sectionTitle('Monotony & Strain — 90 jours'),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        'Monotony = régularité de la charge (mean/std TRIMP 7j). Strain = charge globale (Monotony × sum TRIMP 7j). '
        + 'Monotony > 2.0 signale un entraînement trop uniforme, facteur de surmenage.',
      ),
    );

    if (monotonyRes.points?.length) {
      const chartEl = el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-monotony', className: 'ca-chart-container' }),
      );
      msSection.appendChild(chartEl);
    } else {
      msSection.appendChild(empty('Données Monotony/Strain non disponibles — nécessite FC.'));
    }

    msSection.appendChild(collapsible('Méthode de calcul — Foster 1998', () =>
      el('div', {},
        el('p', {}, 'Training Monotony et Strain sont des indicateurs proposés par Foster (1998) '
          + 'pour détecter le risque de surmenage.'),
        el('p', { style: { fontStyle: 'italic' } },
          'Monotony = mean(TRIMP quotidien 7j) / std(TRIMP quotidien 7j)'),
        el('p', { style: { fontStyle: 'italic' } },
          'Strain = Monotony × sum(TRIMP quotidien 7j)'),
        el('p', {}, 'Une Monotony > 2.0 indique un entraînement trop homogène en intensité. '
          + 'Un Strain élevé couplé à une Monotony haute multiplie le risque d\'infection et de blessure.'),
        el('p', {}, 'Référence : Foster C (1998). Monitoring training in athletes with reference to overtraining syndrome. '
          + 'Medicine & Science in Sports & Exercise, 30(7), 1164-1168.'),
      ),
    ));
    container.appendChild(msSection);

    if (monotonyRes.points?.length) {
      plotMonotony(document.getElementById('chart-monotony'), monotonyRes);
    }

  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}

function _formatTime(seconds) {
  if (!seconds) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.round(seconds % 60);
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}'${String(s).padStart(2, '0')}"`;
  return `${m}'${String(s).padStart(2, '0')}"`;
}

function _parseDistMeters(label) {
  const m = label.match(/^(\d+)km$/);
  if (m) return parseInt(m[1]) * 1000;
  const m2 = label.match(/^(\d+)m$/);
  if (m2) return parseInt(m2[1]);
  if (label === '1mi') return 1609;
  if (label === 'semi') return 21097;
  if (label === 'marathon') return 42195;
  return null;
}
