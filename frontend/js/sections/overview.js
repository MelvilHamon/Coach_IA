/**
 * overview.js — Vue d'ensemble
 */

import { api } from '../api.js';
import { el, metricCard, sectionTitle, distBar, fmt, loading, empty, acwrStatus, riskStatus, weeklyReviewBox } from '../components.js';
import { plotVolume } from '../charts.js';
import { getCurrentSport } from '../state.js';
import { t } from '../i18n.js';

export async function renderOverview(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  const sport = getCurrentSport();

  try {
    const [activitiesRes, volumeRes, distRes] = await Promise.all([
      api.activities({ limit: 1, sport }),
      api.chartVolume(sport),
      api.chartDistribution(sport),
    ]);

    container.innerHTML = '';

    const acts = activitiesRes.activities;
    if (!acts.length) {
      container.appendChild(empty(t('common.noActivitiesFound')));
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
      metricCard(t('overview.weekVolume'), fmt(last.weekly_km, 1), 'km', {
        explain: t('overview.weekVolumeExplain'),
      }),
      metricCard('ACWR', fmt(last.acwr_km, 2), '', {
        status: acwrStatus(last.acwr_km),
        explain: t('overview.acwrExplain'),
      }),
      metricCard(t('overview.injuryRisk'), fmt(last.injury_risk_score, 0), '/100', {
        status: riskStatus(last.injury_risk_label),
        explain: t('overview.injuryExplain'),
      }),
      metricCard(t('overview.formTSB'), fmt(formV, 0), '', {
        status: formStatus,
        explain: t('overview.tsbExplain'),
      }),
    );
    container.appendChild(cards);

    // ── Volume chart ──
    const chartSection = el('div', { className: 'ca-section' },
      sectionTitle(t('overview.weeklyVolumeTitle')),
      el('div', { className: 'ca-chart-card' },
        el('div', { id: 'chart-volume', className: 'ca-chart-container' }),
      ),
    );
    container.appendChild(chartSection);

    if (volumeRes.weeks.length) {
      plotVolume(document.getElementById('chart-volume'), volumeRes);
    }

    // ── Bilan hebdomadaire ──
    // Dimanche → semaine en cours (complète), sinon → semaine précédente
    const weeklyOffset = new Date().getDay() === 0 ? 0 : 1;

    const weeklySection = el('div', { className: 'ca-section' },
      sectionTitle(weeklyOffset === 0 ? t('overview.weeklyReview') : t('overview.lastWeeklyReview')),
    );
    const weeklyContent = el('div');
    const weeklyGenBtn = el('button', { className: 'ca-btn accent', style: { marginBottom: '12px' } }, t('overview.generateBilan'));

    weeklyGenBtn.addEventListener('click', async () => {
      weeklyGenBtn.textContent = t('common.generating');
      weeklyGenBtn.disabled = true;
      try {
        const res = await api.generateWeeklyReview(weeklyOffset);
        weeklyContent.innerHTML = '';
        if (res.error) weeklyContent.appendChild(el('div', { className: 'ca-empty' }, res.error));
        else if (res.review) weeklyContent.appendChild(weeklyReviewBox(res.review));
        else weeklyContent.appendChild(el('div', { className: 'ca-empty' }, t('common.noBilan')));
      } catch (e) {
        weeklyContent.innerHTML = '';
        weeklyContent.appendChild(el('div', { className: 'ca-error' }, e.message));
      } finally {
        weeklyGenBtn.textContent = t('overview.regenerateBilan');
        weeklyGenBtn.disabled = false;
      }
    });

    weeklySection.appendChild(weeklyGenBtn);

    // Load cached weekly review
    try {
      const cachedWeekly = await api.weeklyReview(weeklyOffset);
      if (cachedWeekly?.review) {
        weeklyContent.appendChild(weeklyReviewBox(cachedWeekly.review));
        weeklyGenBtn.textContent = t('overview.regenerateBilan');
      } else {
        weeklyContent.appendChild(el('div', { className: 'ca-empty' }, t('common.copyClick')));
      }
    } catch (_) { /* ignore */ }

    weeklySection.appendChild(weeklyContent);
    container.appendChild(weeklySection);

    // ── Distribution ──
    const distTypes = distRes.types || [];
    if (distTypes.length) {
      const distSection = el('div', { className: 'ca-section' },
        sectionTitle(t('overview.distribution')),
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
    container.appendChild(el('div', { className: 'ca-error' }, t('common.errorPrefix', { msg: err.message })));
  }
}
