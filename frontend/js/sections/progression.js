/**
 * progression.js — Allure, EF, VO2max
 */

import { api } from '../api.js';
import { el, sectionTitle, loading, empty, collapsible } from '../components.js';
import { plotPace, plotEf, plotVo2, plotSpeedTrend } from '../charts.js';
import { getCurrentSport } from '../state.js';

let _activeTab = 'pace';

export async function renderProgression(container) {
  container.innerHTML = '';

  const sport = getCurrentSport();

  // ── Sub-tabs (adapt per sport) ──
  const tabs = sport === 'velo'
    ? [
        { id: 'speed', label: 'Vitesse' },
        { id: 'ef',    label: 'Efficiency Factor' },
      ]
    : [
        { id: 'pace', label: 'Allure' },
        { id: 'ef',   label: 'Efficiency Factor' },
        { id: 'vo2',  label: 'VO2max' },
      ];

  // Reset active tab if not available for this sport
  if (!tabs.find(t => t.id === _activeTab)) {
    _activeTab = tabs[0].id;
  }

  const tabBtns = tabs.map(t => {
    const btn = el('button', {
      className: `ca-subtab ${t.id === _activeTab ? 'active' : ''}`,
      onClick: () => {
        _activeTab = t.id;
        document.querySelectorAll('.ca-subtab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        loadTab(t.id);
      },
    }, t.label);
    return btn;
  });

  const tabBar = el('div', { className: 'ca-subtabs' }, ...tabBtns);
  container.appendChild(tabBar);

  const content = el('div', { className: 'ca-section' });
  container.appendChild(content);

  async function loadTab(tabId) {
    content.innerHTML = '';
    content.appendChild(loading());

    try {
      if (tabId === 'pace') {
        const data = await api.chartPace(sport);
        content.innerHTML = '';
        if (!data.series?.length) {
          content.appendChild(empty('Pas de données d\'allure.'));
          return;
        }
        const note = el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          'Évolution de l\'allure par type de séance. Une tendance descendante indique une amélioration de la vitesse.',
        );
        content.appendChild(note);
        const chartEl = el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-pace', className: 'ca-chart-container' }),
        );
        content.appendChild(chartEl);
        plotPace(document.getElementById('chart-pace'), data);

        content.appendChild(collapsible('Méthode — Allure par type de séance', () =>
          el('div', {},
            el('p', {}, 'L\'allure (min/km) est calculée depuis la distance et la durée de chaque activité. '
              + 'Les séances sont regroupées par type (endurance, tempo, fractionné, etc.) détecté automatiquement.'),
            el('p', {}, 'Une tendance descendante sur un type donné indique une amélioration de la vitesse pour ce type d\'effort.'),
          ),
        ));

      } else if (tabId === 'speed') {
        const data = await api.chartSpeed(sport);
        content.innerHTML = '';
        if (!data.series?.length) {
          content.appendChild(empty('Pas de données de vitesse.'));
          return;
        }
        const note = el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          'Évolution de la vitesse moyenne (km/h) par type de séance. Une tendance ascendante indique une amélioration.',
        );
        content.appendChild(note);
        const chartEl = el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-speed-trend', className: 'ca-chart-container' }),
        );
        content.appendChild(chartEl);
        plotSpeedTrend(document.getElementById('chart-speed-trend'), data);

      } else if (tabId === 'ef') {
        const data = await api.chartEf(sport);
        content.innerHTML = '';
        if (!data.points?.length) {
          content.appendChild(empty('FC requise pour calculer l\'Efficiency Factor.'));
          return;
        }
        const note = el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          'Vitesse ÷ FC. Un EF qui augmente signifie que vous courez plus vite pour le même effort cardiaque — signe de progression aérobie.',
        );
        content.appendChild(note);
        const chartEl = el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-ef', className: 'ca-chart-container' }),
        );
        content.appendChild(chartEl);
        plotEf(document.getElementById('chart-ef'), data);

        content.appendChild(collapsible('Méthode — Efficiency Factor', () =>
          el('div', {},
            el('p', {}, 'L\'Efficiency Factor (Friel 2009) mesure l\'efficacité aérobie :'),
            el('p', { style: { fontStyle: 'italic' } }, 'EF = vitesse (km/h) / FC moyenne (bpm)'),
            el('p', {}, 'Un EF qui augmente au fil du temps signifie que le système cardiovasculaire '
              + 'devient plus efficace : même fréquence cardiaque, vitesse supérieure.'),
            el('p', {}, 'La moyenne glissante sur 10 séances filtre la variabilité quotidienne (météo, fatigue, terrain). '
              + 'Nécessite un cardiofréquencemètre.'),
          ),
        ));

      } else if (tabId === 'vo2') {
        const data = await api.chartVo2(sport);
        content.innerHTML = '';
        if (!data.points?.length) {
          content.appendChild(empty('VO2max non calculable — nécessite FC et type de séance.'));
          return;
        }
        const note = el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          'Estimation du VO2max via la formule de Daniels. Reflète la capacité aérobie maximale. La tendance lissée filtre la variabilité jour à jour.',
        );
        content.appendChild(note);
        const chartEl = el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-vo2', className: 'ca-chart-container' }),
        );
        content.appendChild(chartEl);
        plotVo2(document.getElementById('chart-vo2'), data);

        content.appendChild(collapsible('Méthode de calcul — VO2max (Daniels & Gilbert)', () =>
          el('div', {},
            el('p', {},
              'L\'estimation utilise l\'équation de Daniels & Gilbert (1979) qui relie la vitesse de course et la VO2 via une régression exponentielle empirique :',
            ),
            el('p', { style: { fontStyle: 'italic' } },
              'VO2 = -4.60 + 0.182258 \u00d7 v + 0.000104 \u00d7 v\u00b2',
            ),
            el('p', {},
              'o\u00f9 v est la vitesse en m/min. Le VO2max est ensuite d\u00e9riv\u00e9 en ajustant le co\u00fbt m\u00e9tabolique par la dur\u00e9e de l\'effort via un facteur de fatigue :',
            ),
            el('p', { style: { fontStyle: 'italic' } },
              '%VO2max = 0.8 + 0.1894393 \u00d7 e^{-0.012778\u00d7t} + 0.2989558 \u00d7 e^{-0.1932605\u00d7t}',
            ),
            el('p', {},
              'Variables d\'entr\u00e9e : vitesse moyenne (km/h), dur\u00e9e de la s\u00e9ance (min). Seules les s\u00e9ances d\'endurance, tempo et seuil sont utilis\u00e9es \u2014 les fractionnés et récupérations sont exclues car le modèle suppose un effort continu.',
            ),
            el('p', {},
              'Limites : cette estimation ne tient pas compte de l\'altitude, de la température, du vent, du dénivelé ni de la surface. Elle tend \u00e0 sous-estimer le VO2max r\u00e9el chez les coureurs de trail et \u00e0 le surestimer sur terrain plat assist\u00e9.',
            ),
            el('p', {},
              'R\u00e9f\u00e9rence : Daniels, J. & Gilbert, J. (1979). ',
              el('em', {}, 'Oxygen Power: Performance Tables for Distance Runners'),
              '. Tempe, AZ.',
            ),
          ),
        ));
      }
    } catch (err) {
      content.innerHTML = '';
      content.appendChild(el('div', { className: 'ca-error' }, err.message));
    }
  }

  loadTab(_activeTab);
}
