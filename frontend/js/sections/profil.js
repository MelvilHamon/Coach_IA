/**
 * profil.js — Profil athlète : Records, Fitness/Fatigue/Form, Monotony/Strain
 */

import { api } from '../api.js';
import { el, sectionTitle, loading, empty, collapsible, fmt, fmtDate, methodBody } from '../components.js';
import { plotFitness, plotMonotony } from '../charts.js';
import { getCurrentSport } from '../state.js';
import { t } from '../i18n.js';

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
      sectionTitle(isVelo ? t('profil.prBikeTitle') : t('profil.prRunTitle')),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        isVelo ? t('profil.prBikeExplain') : t('profil.prRunExplain'),
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
            el('th', {}, t('common.distance')),
            el('th', {}, t('common.time')),
            el('th', {}, isVelo ? t('common.speed') : t('common.pace')),
            el('th', {}, t('common.date')),
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
            paceOrSpeed = '—';
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
      // .ca-table-wrap : filet de sécurité, la table de records déborde d'un
      // écran de 375px dès qu'une valeur s'allonge.
      prSection.appendChild(el('div', { className: 'ca-table-wrap' }, table));
    } else {
      prSection.appendChild(empty(t('profil.noRecords')));
    }

    prSection.appendChild(collapsible(t('profil.methodPR'), () => methodBody('profil.methodPRBody')));
    container.appendChild(prSection);

    // ── Records de puissance (vélo uniquement) ──
    if (isVelo) {
      const powerRecords = allDist.velo_power || {};
      const powerKeys = Object.keys(powerRecords);
      const powerSection = el('div', { className: 'ca-section' },
        sectionTitle(t('profil.prBikePowerTitle') || 'Records de puissance'),
        el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          t('profil.prBikePowerExplain') || 'Meilleure puissance moyenne soutenue sur des fenêtres de durée fixes (sliding window sur les streams de puissance).',
        ),
      );

      if (powerKeys.length) {
        const powerOrder = ['5s', '1min', '5min', '10min', '20min', '30min', '60min'];
        const sortedKeys = powerOrder.filter(k => powerRecords[k]);
        const table = el('table', { className: 'ca-records-table' },
          el('thead', {},
            el('tr', {},
              el('th', {}, t('common.duration') || 'Durée'),
              el('th', {}, t('common.power') || 'Puissance'),
              el('th', {}, t('common.date')),
            ),
          ),
        );
        const tbody = el('tbody');
        for (const k of sortedKeys) {
          const r = powerRecords[k];
          tbody.appendChild(el('tr', {},
            el('td', {}, k),
            el('td', { className: 'pr-time' }, fmt(r.power_w, 0) + ' W'),
            el('td', {}, r.date ? fmtDate(r.date) : '—'),
          ));
        }
        table.appendChild(tbody);
        powerSection.appendChild(el('div', { className: 'ca-table-wrap' }, table));
      } else {
        powerSection.appendChild(empty(t('profil.noPowerRecords') || 'Aucun record de puissance — connectez un capteur de puissance.'));
      }

      container.appendChild(powerSection);
    }

    // ── Fitness / Fatigue / Form ──
    const ffSection = el('div', { className: 'ca-section' },
      sectionTitle(t('profil.ffTitle')),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        t('profil.ffExplain'),
      ),
    );

    if (fitnessRes.points?.length) {
      const chartEl = el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-fitness', className: 'ca-chart-container' }),
      );
      ffSection.appendChild(chartEl);
    } else {
      ffSection.appendChild(empty(t('profil.ffNoData')));
    }

    ffSection.appendChild(collapsible(t('profil.methodBanister'), () => methodBody('profil.methodBanisterBody')));
    container.appendChild(ffSection);

    if (fitnessRes.points?.length) {
      plotFitness(document.getElementById('chart-fitness'), fitnessRes);
    }

    // ── Monotony & Strain ──
    const msSection = el('div', { className: 'ca-section' },
      sectionTitle(t('profil.msTitle')),
      el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
        t('profil.msExplain'),
      ),
    );

    if (monotonyRes.points?.length) {
      const chartEl = el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-monotony', className: 'ca-chart-container' }),
      );
      msSection.appendChild(chartEl);
    } else {
      msSection.appendChild(empty(t('profil.msNoData')));
    }

    msSection.appendChild(collapsible(t('profil.methodFoster'), () => methodBody('profil.methodFosterBody')));
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
