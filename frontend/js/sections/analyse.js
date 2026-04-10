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
import { plotZones, plotSpeed, plotAltitude, plotGap, plotBpm, plotPower, plotSplits, enableBlockSelect, computeBlockMetrics, updateBlockShapes } from '../charts.js';
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
    const [detail, gpsRes, speedRes, altRes, gapRes, bpmRes, powerRes, splitsRes, reviewRes, gearRes, assignRes, feedbackRes, sessionAnalysisRes, blocksRes] = await Promise.all([
      api.activity(actId),
      api.gps(actId).catch(() => null),
      api.gpsSpeed(actId).catch(() => null),
      api.gpsAltitude(actId).catch(() => null),
      api.gpsGap(actId).catch(() => null),
      api.gpsBpm(actId).catch(() => null),
      api.gpsPower(actId).catch(() => null),
      api.gpsSplits(actId).catch(() => null),
      api.review(actId).catch(() => null),
      api.gear().catch(() => null),
      api.gearAssignments().catch(() => null),
      api.feedback(actId).catch(() => null),
      api.sessionAnalysis(actId).catch(() => null),
      api.blocks(actId).catch(() => null),
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
    const isVelo = detail.sport === 'velo';

    const distKm = detail['Distance (km)'] || 0;
    const durMin = detail['Temps (min)'] || 0;
    const elevM  = detail['Dénivelé (m)'] || 0;

    // Computed vélo metrics
    const speedKmh = (distKm > 0 && durMin > 0) ? distKm / (durMin / 60) : null;
    const elevPerKm = (distKm > 0 && elevM > 0) ? elevM / distKm : null;

    let rows;
    if (isVelo) {
      rows = el('div', { className: 'ca-detail-rows' },
        detailRow('Type', badge(detail.session_type)),
        detailRow('Distance', distKm ? fmt(distKm, 1) + ' km' : '—'),
        detailRow('Durée', durMin ? fmt(durMin, 0) + ' min' : '—'),
        detailRow('Vitesse moy.', speedKmh != null ? fmt(speedKmh, 1) + ' km/h' : '—'),
        detailRow('Dénivelé', elevM ? fmt(elevM, 0) + ' m' : '—'),
        detailRow('D+/km', elevPerKm != null ? fmt(elevPerKm, 1) + ' m/km' : '—'),
        detailRow('FC moy.', detail['Fréquence cardiaque (bpm)'] != null ? fmt(detail['Fréquence cardiaque (bpm)'], 0) + ' bpm' : '—'),
        detailRow('TRIMP', fmt(detail.trimp, 0)),
        detailRow('hrTSS', fmt(detail.hrtss, 0)),
        detailRow('EF', detail.efficiency_factor != null ? fmt(detail.efficiency_factor, 4) : '—', {},
          detail.efficiency_factor != null ? undefined : undefined),
        detailRow('Découplage', detail.decoupling_pct != null ? fmt(detail.decoupling_pct, 1) + '%' : '—'),
        detailRow('ACWR', fmt(acwr_v, 2), { color: acwrColor(acwr_v) }),
        detailRow('Risque', `${risk} (${fmt(detail.injury_risk_score, 0)}/100)`, { color: riskColor(risk) }),
        detailRow('Form TSB', fmt(detail.tsb, 0)),
      );
    } else {
      rows = el('div', { className: 'ca-detail-rows' },
        detailRow('Type', badge(detail.session_type)),
        detailRow('Distance', distKm ? fmt(distKm, 1) + ' km' : '—'),
        detailRow('Durée', durMin ? fmt(durMin, 0) + ' min' : '—'),
        detailRow('Allure', detail.pace_display ? detail.pace_display + ' min/km' : '—'),
        detailRow('FC moy.', detail['Fréquence cardiaque (bpm)'] != null ? fmt(detail['Fréquence cardiaque (bpm)'], 0) + ' bpm' : '—'),
        detailRow('Dénivelé', elevM ? fmt(elevM, 0) + ' m' : '—'),
        detailRow('TRIMP', fmt(detail.trimp, 0)),
        detailRow('hrTSS', fmt(detail.hrtss, 0)),
        detailRow('EF', fmt(detail.efficiency_factor, 4)),
        detailRow('Découplage', detail.decoupling_pct != null ? fmt(detail.decoupling_pct, 1) + '%' : '—'),
        detailRow('VO2max est.', detail.vo2max_estimate != null ? fmt(detail.vo2max_estimate, 1) + ' mL/kg/min' : '—'),
        detailRow('ACWR', fmt(acwr_v, 2), { color: acwrColor(acwr_v) }),
        detailRow('Risque', `${risk} (${fmt(detail.injury_risk_score, 0)}/100)`, { color: riskColor(risk) }),
        detailRow('Form TSB', fmt(detail.tsb, 0)),
      );
    }
    leftCol.appendChild(rows);

    // ── Session analysis summary (fractionné / tempo) ──
    // Manual blocks take priority over auto detection
    const hasManualBlocks = blocksRes?.blocks?.length > 0;
    const sType = detail.session_type || '';
    const isFractOrTempo = sType.includes('fractionné') || sType.includes('tempo') || sType.includes('mixte') || sType.includes('pyramide');

    if (!hasManualBlocks && isFractOrTempo && sessionAnalysisRes && sessionAnalysisRes.patterns?.length) {
      const analysisBox = el('div', {
        style: {
          marginTop: '12px', padding: '12px 14px',
          background: 'var(--bg, #F7F4F0)', borderRadius: '8px',
          border: '1px solid var(--border, #E8E4DF)',
          fontSize: '13px', lineHeight: '1.6',
        },
      });

      analysisBox.appendChild(el('div', {
        style: { fontWeight: '700', marginBottom: '6px', fontSize: '13px' },
      }, `Analyse auto : ${sType}`));

      for (const p of sessionAnalysisRes.patterns) {
        analysisBox.appendChild(el('div', {
          style: { fontFamily: "'JetBrains Mono', monospace", fontSize: '12px' },
        }, p.description));
      }

      analysisBox.appendChild(el('div', {
        style: { marginTop: '6px', fontSize: '11px', color: 'var(--ink-mid, #787470)', fontStyle: 'italic' },
      }, 'Détection automatique — sélectionner des blocs manuels sur le graphe d\'allure pour un résultat plus précis.'));

      leftCol.appendChild(analysisBox);
    }

    // Gear assignment
    const allGear = gearRes?.gear || [];
    const assignments = assignRes?.assignments || {};
    const actAssign = assignments[String(actId)] || {};

    if (allGear.length) {
      const gearRow = el('div', { style: { marginTop: '12px', display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' } });

      for (const slot of ['shoes', 'watch']) {
        const slotGear = allGear.filter(g => g.type === slot && !g.retired);
        if (!slotGear.length) continue;
        const label = slot === 'shoes' ? 'Chaussures' : 'Montre';
        const select = el('select', { className: 'ca-select', style: { fontSize: '11px', minWidth: '120px' } });
        select.appendChild(el('option', { value: '' }, `— ${label} —`));
        for (const g of slotGear) {
          const opt = el('option', { value: g.id }, g.name);
          if (actAssign[slot] === g.id) opt.selected = true;
          select.appendChild(opt);
        }
        select.addEventListener('change', async () => {
          await api.assignGear(actId, slot, select.value || null);
        });
        gearRow.appendChild(select);
      }

      leftCol.appendChild(gearRow);
    }

    // Zones FC
    rightCol.appendChild(sectionTitle('Zones FC'));
    const zonesEl = el('div', { id: 'chart-zones' });
    rightCol.appendChild(zonesEl);

    // Splits under zones FC (same right column) — running only
    const hasSplits = !isVelo && splitsRes && splitsRes.splits?.length;
    if (hasSplits) {
      rightCol.appendChild(sectionTitle('Allure par kilomètre'));
      rightCol.appendChild(el('div', { id: 'chart-splits' }));
    }

    const twoCol = el('div', { className: 'ca-two-col ca-section' }, leftCol, rightCol);
    target.appendChild(twoCol);

    // Render zones
    const zones = detail.zones || {};
    plotZones(document.getElementById('chart-zones'), zones);

    // Render splits
    if (hasSplits) {
      plotSplits(document.getElementById('chart-splits'), splitsRes);
    }

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

    // ── Speed + BPM + Altitude profiles with manual block selection ──
    const hasSpeed = speedRes && speedRes.speed_kmh?.length;
    const hasAlt = altRes && altRes.altitude_m?.length;
    const hasBpm = bpmRes && bpmRes.bpm?.length;

    // Mutable blocks state for this activity
    let manualBlocks = (blocksRes?.blocks || []).slice();
    let _disableSelect = null;  // cleanup for block selection mode

    if (hasSpeed || hasAlt || hasBpm) {
      const profileSection = el('div', { className: 'ca-section' },
        sectionTitle('Profils allure & altitude'),
        el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          'Allure lissée par filtre de Savitzky-Golay (fenêtre 11 points). Le dénivelé (gris, axe droit) est affiché en fond pour contextualiser les variations d\'allure.',
        ),
      );

      // ── Block toolbar (only if speed data available) ──
      let blockListEl, blockSummaryEl;
      if (hasSpeed) {
        const addEffortBtn = el('button', { className: 'ca-btn accent', style: { fontSize: '11px', padding: '4px 10px' } }, '+ Bloc effort');
        const stopBtn = el('button', { className: 'ca-btn', style: { fontSize: '11px', padding: '4px 10px', display: 'none' } }, 'Terminer');
        const clearBtn = el('button', { className: 'ca-btn', style: { fontSize: '11px', padding: '4px 10px' } }, 'Tout effacer');
        const modeLabel = el('span', { style: { fontSize: '11px', color: 'var(--ink-mid)', fontStyle: 'italic' } });

        const toolbar = el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' } },
          addEffortBtn, stopBtn, clearBtn, modeLabel,
        );
        profileSection.appendChild(toolbar);

        // Speed chart
        const speedEl = el('div', { className: 'ca-chart-card', style: { marginBottom: '8px' } },
          el('div', { id: 'chart-speed' }),
        );
        profileSection.appendChild(speedEl);

        // Block list + summary container
        blockListEl = el('div', { style: { marginBottom: '12px' } });
        blockSummaryEl = el('div', { style: { marginBottom: '16px' } });
        profileSection.appendChild(blockListEl);
        profileSection.appendChild(blockSummaryEl);

        // ── Block selection handlers ──
        const distKm = speedRes.distance_m.map(d => d / 1000);
        const bpmArr = hasBpm ? bpmRes.bpm : null;

        function renderBlockList() {
          blockListEl.innerHTML = '';
          if (!manualBlocks.length) return;

          const effortBlocks = manualBlocks.filter(b => b.type === 'effort');
          for (let i = 0; i < manualBlocks.length; i++) {
            const b = manualBlocks[i];
            const m = computeBlockMetrics(b, distKm, speedRes.speed_kmh, bpmArr);
            const color = b.type === 'effort' ? 'var(--accent, #2563EB)' : 'var(--success, #2D6A4F)';
            const label = b.type === 'effort' ? 'Effort' : 'Récup';
            const idx = b.type === 'effort' ? effortBlocks.indexOf(b) + 1 : '';

            const removeBtn = el('button', {
              style: { background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)', fontSize: '13px', padding: '0 4px' },
              title: 'Supprimer',
              onClick: () => { manualBlocks.splice(i, 1); onBlocksChanged(); },
            }, '\u00d7');

            blockListEl.appendChild(el('div', {
              style: { display: 'flex', alignItems: 'center', gap: '8px', padding: '3px 0', fontSize: '12px', fontFamily: "'JetBrains Mono', monospace" },
            },
              el('span', { style: { color, fontWeight: '600', minWidth: '55px' } }, `${label}${idx ? ' ' + idx : ''}`),
              el('span', {}, `${b.start_km.toFixed(2)} → ${b.end_km.toFixed(2)} km`),
              el('span', { style: { color: 'var(--ink-mid)' } }, `${m.distance_m}m`),
              el('span', { style: { fontWeight: '600' } }, `${m.pace_display} /km`),
              el('span', { style: { color: 'var(--ink-mid)' } }, `${m.duration_display}`),
              m.avg_bpm ? el('span', { style: { color: 'var(--ink-mid)' } }, `${m.avg_bpm} bpm`) : null,
              removeBtn,
            ));
          }
        }

        function renderBlockSummary() {
          blockSummaryEl.innerHTML = '';
          const efforts = manualBlocks.filter(b => b.type === 'effort');
          if (!efforts.length) return;

          const metrics = efforts.map(b => computeBlockMetrics(b, distKm, speedRes.speed_kmh, bpmArr));
          const n = efforts.length;
          const avgDist = Math.round(metrics.reduce((s, m) => s + m.distance_m, 0) / n);
          const avgPaceS = metrics.reduce((s, m) => s + m.avg_pace_s, 0) / n;
          const pm = Math.floor(avgPaceS / 60);
          const ps = Math.round(avgPaceS % 60);
          const avgPace = `${pm}:${String(ps).padStart(2, '0')}`;
          const avgBpm = metrics.filter(m => m.avg_bpm).length
            ? Math.round(metrics.reduce((s, m) => s + (m.avg_bpm || 0), 0) / metrics.filter(m => m.avg_bpm).length)
            : null;

          // Recovery between effort blocks
          let recovStr = '';
          if (n > 1) {
            const sortedEfforts = efforts.slice().sort((a, b) => a.start_km - b.start_km);
            const recovDists = [];
            for (let i = 0; i < sortedEfforts.length - 1; i++) {
              recovDists.push(Math.round((sortedEfforts[i + 1].start_km - sortedEfforts[i].end_km) * 1000));
            }
            const avgRecov = Math.round(recovDists.reduce((a, b) => a + b, 0) / recovDists.length);
            // Compute recovery pace
            const recovBlocks = [];
            for (let i = 0; i < sortedEfforts.length - 1; i++) {
              recovBlocks.push({ start_km: sortedEfforts[i].end_km, end_km: sortedEfforts[i + 1].start_km, type: 'recovery' });
            }
            const recovMetrics = recovBlocks.map(b => computeBlockMetrics(b, distKm, speedRes.speed_kmh, bpmArr));
            const avgRecovPaceS = recovMetrics.reduce((s, m) => s + m.avg_pace_s, 0) / recovMetrics.length;
            const rpm = Math.floor(avgRecovPaceS / 60);
            const rps = Math.round(avgRecovPaceS % 60);
            recovStr = `, récup ~${avgRecov}m @ ${rpm}:${String(rps).padStart(2, '0')} /km`;
          }

          const bpmStr = avgBpm ? ` (FC ${avgBpm})` : '';
          const summary = `${n} \u00d7 ~${avgDist}m @ ${avgPace} /km${bpmStr}${recovStr}`;

          blockSummaryEl.appendChild(el('div', {
            style: {
              padding: '10px 14px', background: 'var(--bg, #F7F4F0)', borderRadius: '8px',
              border: '1px solid var(--border, #E8E4DF)', fontSize: '13px', fontWeight: '600',
              fontFamily: "'JetBrains Mono', monospace",
            },
          }, summary));
        }

        function onBlocksChanged() {
          // Sort blocks by start_km
          manualBlocks.sort((a, b) => a.start_km - b.start_km);

          // Update chart shapes (pace blocks only on speed chart)
          const speedChart = document.getElementById('chart-speed');
          const paceBlocks = manualBlocks.filter(b => b.type === 'effort');
          if (speedChart) updateBlockShapes(speedChart, paceBlocks);

          renderBlockList();
          renderBlockSummary();

          // Auto-save
          api.saveBlocks(actId, manualBlocks).catch(() => {});
        }

        function enterSelectMode(blockType) {
          if (_disableSelect) _disableSelect();
          modeLabel.textContent = blockType === 'effort' ? 'Cliquer-glisser pour sélectionner un bloc effort' : 'Sélection récup';
          addEffortBtn.style.display = 'none';
          stopBtn.style.display = '';

          const speedChart = document.getElementById('chart-speed');
          _disableSelect = enableBlockSelect(speedChart, (block) => {
            manualBlocks.push(block);
            onBlocksChanged();
          }, blockType);
        }

        function exitSelectMode() {
          if (_disableSelect) { _disableSelect(); _disableSelect = null; }
          modeLabel.textContent = '';
          addEffortBtn.style.display = '';
          stopBtn.style.display = 'none';
        }

        addEffortBtn.addEventListener('click', () => enterSelectMode('effort'));
        stopBtn.addEventListener('click', exitSelectMode);
        clearBtn.addEventListener('click', () => {
          manualBlocks = manualBlocks.filter(b => b.type === 'power_effort');
          onBlocksChanged();
          if (!manualBlocks.length) api.deleteBlocks(actId).catch(() => {});
          else api.saveBlocks(actId, manualBlocks).catch(() => {});
        });

        // Initial render of saved pace blocks
        if (manualBlocks.filter(b => b.type === 'effort').length) {
          renderBlockList();
          renderBlockSummary();
        }
      } else {
        // No speed data — just the chart cards
        if (hasSpeed) {
          profileSection.appendChild(el('div', { className: 'ca-chart-card', style: { marginBottom: '16px' } },
            el('div', { id: 'chart-speed' }),
          ));
        }
      }

      if (hasBpm) {
        const bpmEl = el('div', { className: 'ca-chart-card', style: { marginBottom: '16px' } },
          el('div', { id: 'chart-bpm' }),
        );
        profileSection.appendChild(bpmEl);
      }

      const hasPower = powerRes && powerRes.power_w?.length;
      let powerBlockListEl, powerBlockSummaryEl;
      if (hasPower) {
        profileSection.appendChild(el('h4', { style: { margin: '16px 0 8px', fontSize: '13px', color: 'var(--ink-light)' } }, 'Puissance'));

        // Power block toolbar
        const addPowerEffortBtn = el('button', { className: 'ca-btn accent', style: { fontSize: '11px', padding: '4px 10px' } }, '+ Bloc effort');
        const stopPowerBtn = el('button', { className: 'ca-btn', style: { fontSize: '11px', padding: '4px 10px', display: 'none' } }, 'Terminer');
        const clearPowerBtn = el('button', { className: 'ca-btn', style: { fontSize: '11px', padding: '4px 10px' } }, 'Tout effacer');
        const powerModeLabel = el('span', { style: { fontSize: '11px', color: 'var(--ink-mid)', fontStyle: 'italic' } });

        const powerToolbar = el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' } },
          addPowerEffortBtn, stopPowerBtn, clearPowerBtn, powerModeLabel,
        );
        profileSection.appendChild(powerToolbar);

        const powerEl = el('div', { className: 'ca-chart-card', style: { marginBottom: '8px' } },
          el('div', { id: 'chart-power' }),
        );
        profileSection.appendChild(powerEl);

        // Power block list + summary
        powerBlockListEl = el('div', { style: { marginBottom: '12px' } });
        powerBlockSummaryEl = el('div', { style: { marginBottom: '16px' } });
        profileSection.appendChild(powerBlockListEl);
        profileSection.appendChild(powerBlockSummaryEl);

        const powerDistKm = powerRes.distance_m.map(d => d / 1000);
        const powerBpmArr = hasBpm ? bpmRes.bpm : null;
        const powerSpeedKmh = hasSpeed ? speedRes.speed_kmh : null;

        function renderPowerBlockList() {
          powerBlockListEl.innerHTML = '';
          const powerBlocks = manualBlocks.filter(b => b.type === 'power_effort');
          if (!powerBlocks.length) return;

          for (let i = 0; i < manualBlocks.length; i++) {
            const b = manualBlocks[i];
            if (b.type !== 'power_effort') continue;
            const m = computeBlockMetrics(b, powerDistKm, powerSpeedKmh || powerDistKm.map(() => 0), powerBpmArr, powerRes.power_w);
            const idx = powerBlocks.indexOf(b) + 1;

            const removeBtn = el('button', {
              style: { background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)', fontSize: '13px', padding: '0 4px' },
              title: 'Supprimer',
              onClick: () => { manualBlocks.splice(i, 1); onPowerBlocksChanged(); },
            }, '\u00d7');

            powerBlockListEl.appendChild(el('div', {
              style: { display: 'flex', alignItems: 'center', gap: '8px', padding: '3px 0', fontSize: '12px', fontFamily: "'JetBrains Mono', monospace" },
            },
              el('span', { style: { color: '#EA580C', fontWeight: '600', minWidth: '55px' } }, `Effort ${idx}`),
              el('span', {}, `${b.start_km.toFixed(2)} → ${b.end_km.toFixed(2)} km`),
              el('span', { style: { color: 'var(--ink-mid)' } }, `${m.distance_m}m`),
              el('span', { style: { fontWeight: '600' } }, `${m.avg_power_w != null ? m.avg_power_w + ' W' : '—'}`),
              m.pace_display !== '—' ? el('span', { style: { color: 'var(--ink-mid)' } }, `${m.pace_display} /km`) : null,
              el('span', { style: { color: 'var(--ink-mid)' } }, `${m.duration_display}`),
              m.avg_bpm ? el('span', { style: { color: 'var(--ink-mid)' } }, `${m.avg_bpm} bpm`) : null,
              removeBtn,
            ));
          }
        }

        function renderPowerBlockSummary() {
          powerBlockSummaryEl.innerHTML = '';
          const efforts = manualBlocks.filter(b => b.type === 'power_effort');
          if (!efforts.length) return;

          const metrics = efforts.map(b => computeBlockMetrics(b, powerDistKm, powerSpeedKmh || powerDistKm.map(() => 0), powerBpmArr, powerRes.power_w));
          const n = efforts.length;
          const avgDist = Math.round(metrics.reduce((s, m) => s + m.distance_m, 0) / n);
          const avgPower = metrics.filter(m => m.avg_power_w).length
            ? Math.round(metrics.reduce((s, m) => s + (m.avg_power_w || 0), 0) / metrics.filter(m => m.avg_power_w).length)
            : null;
          const avgBpm = metrics.filter(m => m.avg_bpm).length
            ? Math.round(metrics.reduce((s, m) => s + (m.avg_bpm || 0), 0) / metrics.filter(m => m.avg_bpm).length)
            : null;

          // Recovery between power effort blocks
          let recovStr = '';
          if (n > 1) {
            const sortedEfforts = efforts.slice().sort((a, b) => a.start_km - b.start_km);
            const recovDists = [];
            for (let i = 0; i < sortedEfforts.length - 1; i++) {
              recovDists.push(Math.round((sortedEfforts[i + 1].start_km - sortedEfforts[i].end_km) * 1000));
            }
            const avgRecov = Math.round(recovDists.reduce((a, b) => a + b, 0) / recovDists.length);
            const recovBlocks = [];
            for (let i = 0; i < sortedEfforts.length - 1; i++) {
              recovBlocks.push({ start_km: sortedEfforts[i].end_km, end_km: sortedEfforts[i + 1].start_km, type: 'recovery' });
            }
            const recovMetrics = recovBlocks.map(b => computeBlockMetrics(b, powerDistKm, powerSpeedKmh || powerDistKm.map(() => 0), powerBpmArr, powerRes.power_w));
            const avgRecovPower = recovMetrics.filter(m => m.avg_power_w).length
              ? Math.round(recovMetrics.reduce((s, m) => s + (m.avg_power_w || 0), 0) / recovMetrics.filter(m => m.avg_power_w).length)
              : null;
            recovStr = avgRecovPower != null ? `, récup ~${avgRecov}m @ ${avgRecovPower} W` : `, récup ~${avgRecov}m`;
          }

          const bpmStr = avgBpm ? ` (FC ${avgBpm})` : '';
          const powerStr = avgPower != null ? `${avgPower} W` : '—';
          const summary = `${n} \u00d7 ~${avgDist}m @ ${powerStr}${bpmStr}${recovStr}`;

          powerBlockSummaryEl.appendChild(el('div', {
            style: {
              padding: '10px 14px', background: 'var(--bg, #F7F4F0)', borderRadius: '8px',
              border: '1px solid var(--border, #E8E4DF)', fontSize: '13px', fontWeight: '600',
              fontFamily: "'JetBrains Mono', monospace",
            },
          }, summary));
        }

        function onPowerBlocksChanged() {
          manualBlocks.sort((a, b) => a.start_km - b.start_km);
          const powerChart = document.getElementById('chart-power');
          const powerBlocks = manualBlocks.filter(b => b.type === 'power_effort');
          if (powerChart) updateBlockShapes(powerChart, powerBlocks);
          renderPowerBlockList();
          renderPowerBlockSummary();
          api.saveBlocks(actId, manualBlocks).catch(() => {});
        }

        let _disablePowerSelect = null;

        function enterPowerSelectMode() {
          if (_disablePowerSelect) _disablePowerSelect();
          powerModeLabel.textContent = 'Cliquer-glisser pour sélectionner un bloc effort';
          addPowerEffortBtn.style.display = 'none';
          stopPowerBtn.style.display = '';

          const powerChart = document.getElementById('chart-power');
          _disablePowerSelect = enableBlockSelect(powerChart, (block) => {
            block.type = 'power_effort';
            manualBlocks.push(block);
            onPowerBlocksChanged();
          }, 'effort');
        }

        function exitPowerSelectMode() {
          if (_disablePowerSelect) { _disablePowerSelect(); _disablePowerSelect = null; }
          powerModeLabel.textContent = '';
          addPowerEffortBtn.style.display = '';
          stopPowerBtn.style.display = 'none';
        }

        addPowerEffortBtn.addEventListener('click', enterPowerSelectMode);
        stopPowerBtn.addEventListener('click', exitPowerSelectMode);
        clearPowerBtn.addEventListener('click', () => {
          manualBlocks = manualBlocks.filter(b => b.type !== 'power_effort');
          onPowerBlocksChanged();
          api.saveBlocks(actId, manualBlocks).catch(() => {});
        });

        // Initial render of saved power blocks
        const savedPowerBlocks = manualBlocks.filter(b => b.type === 'power_effort');
        if (savedPowerBlocks.length) {
          renderPowerBlockList();
          renderPowerBlockSummary();
        }
      }

      if (hasAlt) {
        const altEl = el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-altitude' }),
        );
        profileSection.appendChild(altEl);
      }

      target.appendChild(profileSection);

      if (hasSpeed) plotSpeed(document.getElementById('chart-speed'), speedRes, hasAlt ? altRes : null, { blocks: manualBlocks });
      if (hasBpm) plotBpm(document.getElementById('chart-bpm'), bpmRes, hasAlt ? altRes : null);
      if (hasPower) plotPower(document.getElementById('chart-power'), powerRes, hasAlt ? altRes : null, { blocks: manualBlocks.filter(b => b.type === 'power_effort') });
      if (hasAlt) plotAltitude(document.getElementById('chart-altitude'), altRes);
    }

    // ── GAP (Gradient Adjusted Pace) — running only ──
    const hasGap = !isVelo && gapRes && gapRes.gap_speed_array?.length;
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

    // ── Ressentis (feedback) ──
    const feedbackSection = el('div', { className: 'ca-section' },
      sectionTitle('Ressentis'),
    );

    const existingFb = feedbackRes?.feedback || null;

    const difficultyInput = el('input', {
      type: 'range', min: '1', max: '10', value: existingFb?.difficulty || 5,
      className: 'ca-range',
      style: { width: '100%' },
    });
    const difficultyLabel = el('span', {
      className: 'ca-difficulty-value',
    }, `${existingFb?.difficulty || 5}/10`);

    difficultyInput.addEventListener('input', () => {
      difficultyLabel.textContent = `${difficultyInput.value}/10`;
    });

    const sensationsInput = el('textarea', {
      className: 'ca-input',
      placeholder: 'Comment te sentais-tu pendant cette séance ? (jambes lourdes, bonne forme, douleur...)',
      rows: '3',
      style: { width: '100%', resize: 'vertical' },
    });
    if (existingFb?.sensations) sensationsInput.value = existingFb.sensations;

    const fbMsg = el('div', { style: { display: 'none', marginTop: '6px', fontSize: '12px' } });

    const fbSaveBtn = el('button', { className: 'ca-btn accent', onClick: async () => {
      fbSaveBtn.disabled = true;
      fbSaveBtn.textContent = 'Enregistrement...';
      fbMsg.style.display = 'none';
      try {
        await api.saveFeedback(actId, {
          sensations: sensationsInput.value || null,
          difficulty: parseInt(difficultyInput.value),
        });
        fbMsg.textContent = 'Ressentis enregistrés';
        fbMsg.style.color = 'var(--success, #2D6A4F)';
        fbMsg.style.display = '';
      } catch (e) {
        fbMsg.textContent = e.message;
        fbMsg.style.color = 'var(--danger)';
        fbMsg.style.display = '';
      } finally {
        fbSaveBtn.disabled = false;
        fbSaveBtn.textContent = 'Enregistrer';
      }
    } }, 'Enregistrer');

    feedbackSection.appendChild(
      el('div', { style: { display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' } },
        el('label', { style: { fontWeight: '600', fontSize: '13px', whiteSpace: 'nowrap' } }, 'Difficulté ressentie'),
        difficultyInput,
        difficultyLabel,
      ),
    );
    feedbackSection.appendChild(sensationsInput);
    feedbackSection.appendChild(el('div', { style: { marginTop: '8px', display: 'flex', alignItems: 'center', gap: '12px' } }, fbSaveBtn, fbMsg));
    target.appendChild(feedbackSection);

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
