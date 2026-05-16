/**
 * progression.js — Allure, EF, VO2max
 */

import { api } from '../api.js';
import { el, sectionTitle, loading, empty, collapsible, methodBody } from '../components.js';
import { plotEf, plotVo2, plotSpeedTrend } from '../charts.js';
import { getCurrentSport } from '../state.js';
import { t } from '../i18n.js';

let _activeTab = 'ef';

export async function renderProgression(container) {
  container.innerHTML = '';

  const sport = getCurrentSport();

  // ── Sub-tabs (adapt per sport) ──
  const tabs = sport === 'velo'
    ? [
        { id: 'speed', label: t('progression.speed') },
        { id: 'ef',    label: t('progression.ef') },
      ]
    : [
        { id: 'ef',   label: t('progression.ef') },
        { id: 'vo2',  label: t('progression.vo2') },
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
      if (tabId === 'speed') {
        const data = await api.chartSpeed(sport);
        content.innerHTML = '';
        if (!data.series?.length) {
          content.appendChild(empty(t('progression.noSpeed')));
          return;
        }
        const note = el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          t('progression.speedExplain'),
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
          content.appendChild(empty(t('progression.noEf')));
          return;
        }
        const note = el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          t('progression.efExplain'),
        );
        content.appendChild(note);
        const chartEl = el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-ef', className: 'ca-chart-container' }),
        );
        content.appendChild(chartEl);
        plotEf(document.getElementById('chart-ef'), data);

        content.appendChild(collapsible(t('progression.methodEf'), () => methodBody('progression.methodEfBody')));

      } else if (tabId === 'vo2') {
        const data = await api.chartVo2(sport);
        content.innerHTML = '';
        if (!data.points?.length) {
          content.appendChild(empty(t('progression.noVo2')));
          return;
        }
        const note = el('div', { className: 'ca-metric-explain', style: { marginBottom: '16px' } },
          t('progression.vo2Explain'),
        );
        content.appendChild(note);
        const chartEl = el('div', { className: 'ca-chart-card' },
          el('div', { id: 'chart-vo2', className: 'ca-chart-container' }),
        );
        content.appendChild(chartEl);
        plotVo2(document.getElementById('chart-vo2'), data);

        content.appendChild(collapsible(t('progression.methodVo2'), () => methodBody('progression.methodVo2Body')));
      }
    } catch (err) {
      content.innerHTML = '';
      content.appendChild(el('div', { className: 'ca-error' }, err.message));
    }
  }

  loadTab(_activeTab);
}
