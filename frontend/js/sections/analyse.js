/**
 * analyse.js — Analyse de séance détaillée
 *
 * Sélecteur activité → métriques + zones FC + carte GPS + vitesse/altitude + review
 */

import { api } from '../api.js';
import {
  el, sectionTitle, badge, detailRow, metricCard, fmt, fmtDate, loading, empty,
  acwrColor, riskColor, reviewBox, flagPill, collapsible,
} from '../components.js';
import { plotZones, plotSpeed, plotAltitude, plotGap } from '../charts.js';
import { renderMap } from '../map.js';

let _actSelect = null;

export async function renderAnalyse(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  try {
    const activitiesRes = await api.activities({ limit: 500 });
    container.innerHTML = '';

    const activities = activitiesRes.activities;
    if (!activities.length) {
      container.appendChild(empty('Aucune activité.'));
      return;
    }

    // ── Selector ──
    _actSelect = el('select', { className: 'ca-select' });
    for (const a of activities) {
      _actSelect.appendChild(el('option', { value: a.id },
        `${fmtDate(a.date)} — ${(a.nom || '').slice(0, 30)} [${a.session_type || ''}]`,
      ));
    }

    const controlSection = el('div', { className: 'ca-section' },
      el('div', { className: 'ca-select-wrap' }, _actSelect),
    );
    container.appendChild(controlSection);

    // ── Content area ──
    const contentArea = el('div');
    container.appendChild(contentArea);

    _actSelect.addEventListener('change', () => loadActivity(Number(_actSelect.value), contentArea));
    loadActivity(activities[0].id, contentArea);

  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}

async function loadActivity(actId, target) {
  target.innerHTML = '';
  target.appendChild(loading());

  try {
    // Fetch all data in parallel
    const [detail, gpsRes, speedRes, altRes, gapRes, reviewRes] = await Promise.all([
      api.activity(actId),
      api.gps(actId).catch(() => null),
      api.gpsSpeed(actId).catch(() => null),
      api.gpsAltitude(actId).catch(() => null),
      api.gpsGap(actId).catch(() => null),
      api.review(actId).catch(() => null),
    ]);

    target.innerHTML = '';

    if (detail.error) {
      target.appendChild(empty('Activité introuvable.'));
      return;
    }

    // ── Two-column: Metrics + Zones ──
    const leftCol = el('div');
    const rightCol = el('div');

    // Metrics
    leftCol.appendChild(sectionTitle('Métriques'));

    const acwr_v = detail.acwr_km;
    const risk = detail.injury_risk_label || '—';

    const rows = el('div', { className: 'ca-detail-rows' },
      detailRow('Type', badge(detail.session_type)),
      detailRow('Distance', detail['Distance (km)'] != null ? fmt(detail['Distance (km)'], 1) + ' km' : '—'),
      detailRow('Durée', detail['Temps (min)'] != null ? fmt(detail['Temps (min)'], 0) + ' min' : '—'),
      detailRow('Allure', detail.pace_display ? detail.pace_display + ' min/km' : '—'),
      detailRow('FC moy.', detail['Fréquence cardiaque (bpm)'] != null ? fmt(detail['Fréquence cardiaque (bpm)'], 0) + ' bpm' : '—'),
      detailRow('Dénivelé', detail['Dénivelé (m)'] != null ? fmt(detail['Dénivelé (m)'], 0) + ' m' : '—'),
      detailRow('TRIMP', fmt(detail.trimp, 0)),
      detailRow('hrTSS', fmt(detail.hrtss, 0)),
      detailRow('EF', fmt(detail.efficiency_factor, 4)),
      detailRow('Découplage', detail.decoupling_pct != null ? fmt(detail.decoupling_pct, 1) + '%' : '—'),
      detailRow('VO2max est.', detail.vo2max_estimate != null ? fmt(detail.vo2max_estimate, 1) + ' mL/kg/min' : '—'),
      detailRow('ACWR', fmt(acwr_v, 2), { color: acwrColor(acwr_v) }),
      detailRow('Risque', `${risk} (${fmt(detail.injury_risk_score, 0)}/100)`, { color: riskColor(risk) }),
      detailRow('Form TSB', fmt(detail.tsb, 0)),
    );
    leftCol.appendChild(rows);

    // Zones FC
    rightCol.appendChild(sectionTitle('Zones FC'));
    const zonesEl = el('div', { id: 'chart-zones' });
    rightCol.appendChild(zonesEl);

    const twoCol = el('div', { className: 'ca-two-col ca-section' }, leftCol, rightCol);
    target.appendChild(twoCol);

    // Render zones
    const zones = detail.zones || {};
    plotZones(document.getElementById('chart-zones'), zones);

    // ── GPS Map ──
    if (gpsRes && gpsRes.points?.length > 1) {
      const mapSection = el('div', { className: 'ca-section' },
        sectionTitle('Parcours'),
      );
      const mapEl = el('div', { className: 'ca-map-container', id: 'gps-map' });
      mapSection.appendChild(mapEl);

      // GPS metrics if available
      if (gpsRes.metrics) {
        const gm = gpsRes.metrics;
        const gpsMetrics = el('div', { style: { display: 'flex', gap: '24px', flexWrap: 'wrap', marginTop: '12px', fontSize: '10px', color: 'var(--ink-mid)' } },
          el('span', {}, `Distance GPS : ${fmt(gm.distance_m / 1000, 2)} km`),
          el('span', {}, `D+ : ${fmt(gm.elevation_gain_m, 0)} m`),
          el('span', {}, `D− : ${fmt(gm.elevation_loss_m, 0)} m`),
          el('span', {}, `Vitesse moy. : ${fmt(gm.avg_speed_kmh, 1)} km/h`),
        );
        mapSection.appendChild(gpsMetrics);
      }

      target.appendChild(mapSection);

      // Render map after DOM insertion
      requestAnimationFrame(() => {
        const mapContainer = document.getElementById('gps-map');
        if (mapContainer) renderMap(mapContainer, gpsRes.points);
      });
    }

    // ── Speed + Altitude profiles ──
    const hasSpeed = speedRes && speedRes.speed_kmh?.length;
    const hasAlt = altRes && altRes.altitude_m?.length;

    if (hasSpeed || hasAlt) {
      const profileSection = el('div', { className: 'ca-section' },
        sectionTitle('Profils vitesse & altitude'),
        el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          'Vitesse lissée par filtre de Savitzky-Golay (fenêtre 11 points). L\'altitude provient des données barométriques Garmin.',
        ),
      );

      if (hasSpeed) {
        const speedEl = el('div', { className: 'ca-chart-card', style: { marginBottom: '16px' } },
          el('div', { id: 'chart-speed' }),
        );
        profileSection.appendChild(speedEl);
      }

      if (hasAlt) {
        const altEl = el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-altitude' }),
        );
        profileSection.appendChild(altEl);
      }

      target.appendChild(profileSection);

      if (hasSpeed) plotSpeed(document.getElementById('chart-speed'), speedRes);
      if (hasAlt) plotAltitude(document.getElementById('chart-altitude'), altRes);
    }

    // ── GAP (Gradient Adjusted Pace) ──
    const hasGap = gapRes && gapRes.gap_speed_array?.length;
    if (hasGap) {
      const gapSection = el('div', { className: 'ca-section' },
        sectionTitle('Gradient Adjusted Pace'),
        el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          'Allure corrigée de la pente. Permet de comparer l\'effort sur terrain vallonné à un équivalent plat.',
        ),
        el('div', { className: 'ca-metrics-row', style: { marginBottom: '16px' } },
          metricCard('GAP moyen', gapRes.gap_avg_pace, 'min/km', {
            explain: 'Allure ajustée moyenne sur l\'ensemble du parcours.',
          }),
          metricCard('GAP vitesse', fmt(gapRes.gap_avg_kmh, 1), 'km/h', {
            explain: 'Vitesse ajustée correspondante.',
          }),
        ),
        el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-gap' }),
        ),
      );

      const refText = gapRes.reference
        || 'Modèle empirique Strava Engineering (Robb D., 2017).';
      gapSection.appendChild(collapsible('Méthode de calcul — GAP', () =>
        el('div', {},
          el('p', {}, 'Le Gradient Adjusted Pace corrige la vitesse en fonction de la pente du terrain '
            + 'via une lookup table empirique ajustée sur ~6 millions de runs.'),
          el('p', { style: { fontStyle: 'italic' } },
            'GAP_speed = speed / facteur(gradient%)'),
          el('p', {}, 'Le facteur est interpolé depuis une table couvrant -50% à +50% de pente. '
            + 'En montée, le GAP est plus rapide que l\'allure réelle. '
            + 'En descente douce (-5% à -15%), le bénéfice est faible contrairement au modèle linéaire.'),
          el('p', {}, refText),
        ),
      ));

      target.appendChild(gapSection);
      plotGap(document.getElementById('chart-gap'), gapRes);
    }

    // ── Review ──
    const reviewSection = el('div', { className: 'ca-section' },
      sectionTitle('Review coach'),
    );

    const reviewContent = el('div');
    const genBtn = el('button', { className: 'ca-btn accent', onClick: async () => {
      genBtn.textContent = 'Génération…';
      genBtn.disabled = true;
      try {
        const res = await api.generateReview(actId);
        reviewContent.innerHTML = '';
        if (res.review) reviewContent.appendChild(reviewBox(res.review));
        else if (res.error) reviewContent.appendChild(el('div', { className: 'ca-error' }, res.error));
      } catch (e) {
        reviewContent.appendChild(el('div', { className: 'ca-error' }, e.message));
      } finally {
        genBtn.textContent = 'Générer / Régénérer';
        genBtn.disabled = false;
      }
    } }, 'Générer / Régénérer');

    reviewSection.appendChild(genBtn);

    if (reviewRes?.review) {
      reviewContent.appendChild(reviewBox(reviewRes.review));
    } else {
      reviewContent.appendChild(el('div', { className: 'ca-empty' }, 'Pas de review — cliquer pour en générer une.'));
    }
    reviewSection.appendChild(reviewContent);
    target.appendChild(reviewSection);

  } catch (err) {
    target.innerHTML = '';
    target.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}
