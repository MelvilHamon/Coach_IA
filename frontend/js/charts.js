/**
 * charts.js — Wrapper Plotly.js avec le design system CoachAgent.
 */

import { t } from './i18n.js';

const COLORS = {
  bg:       '#F7F4F0',
  card:     '#FFFFFF',
  dark:     '#141414',
  ink:      '#141414',
  inkMid:   '#787470',
  inkLight: '#A09B96',
  accent:   '#2563EB',
  success:  '#2D6A4F',
  warning:  '#B45309',
  danger:   '#991B1B',
  border:   '#E8E4DF',
  grid:     '#F0EDE8',
};

const FONT = "'JetBrains Mono', monospace";

const BASE_LAYOUT = {
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor:  'rgba(0,0,0,0)',
  font: { family: FONT, color: COLORS.inkMid, size: 12 },
  margin: { l: 48, r: 16, t: 16, b: 36 },
  showlegend: false,
  hovermode: 'x unified',
  hoverlabel: {
    bgcolor:     COLORS.dark,
    font: { color: COLORS.bg, family: FONT, size: 13 },
    bordercolor: '#2A2A2A',
  },
};

const AX = {
  showline:  true,
  linecolor: COLORS.inkLight,
  linewidth: 1,
  showgrid:  false,
  zeroline:  false,
  tickfont: { family: FONT, size: 11, color: COLORS.inkLight },
};

const PLOTLY_CONFIG = { displayModeBar: false, responsive: true };

/**
 * Safe wrapper around Plotly.newPlot — shows a message if Plotly isn't loaded.
 */
function safePlot(container, traces, layout, config) {
  if (typeof Plotly === 'undefined') {
    console.error('Plotly is not loaded — charts cannot render.');
    if (typeof container === 'string') container = document.getElementById(container);
    if (container) container.innerHTML = `<div class="ca-empty">${t('charts.noPlotly')}</div>`;
    return;
  }
  // Check for empty data — handle both cartesian (y) and pie (values) traces
  const hasData = traces.some(tr =>
    (tr.y && tr.y.length > 0) || (tr.values && tr.values.length > 0)
  );
  if (!traces.length || !hasData) {
    if (typeof container === 'string') container = document.getElementById(container);
    if (container) container.innerHTML = `<div class="ca-empty">${t('charts.notEnough')}</div>`;
    return;
  }
  Plotly.newPlot(container, traces, layout, config);
}

// ── Type palette ────────────────────────────────────────────────────────────

const STYPE_PALETTE = [
  COLORS.accent, COLORS.success, COLORS.warning,
  COLORS.inkMid, COLORS.inkLight, '#6B5B4F', '#8B7355',
];

// ── Volume + ACWR (overview) ────────────────────────────────────────────────

function _fmtStravaWeek(iso) {
  const d = new Date(iso);
  const months = ['janv', 'févr', 'mars', 'avr', 'mai', 'juin', 'juil', 'août', 'sept', 'oct', 'nov', 'déc'];
  return `${d.getDate()} ${months[d.getMonth()]}`;
}

export function plotVolume(container, data, opts = {}) {
  const weeks = data.weeks || [];
  if (!weeks.length) return;

  const x       = weeks.map(w => w.week);
  const xLabels = weeks.map(w => _fmtStravaWeek(w.week));
  const km      = weeks.map(w => w.total_km);
  const acwr    = weeks.map(w => w.acwr);

  const traces = [
    {
      x: xLabels, y: km,
      type: 'bar',
      name: t('charts.kmPerWeek'),
      marker: { color: '#4A4744', opacity: 0.9, line: { width: 0 } },
      width: 0.55,
      yaxis: 'y',
      hovertemplate: '<b>%{y:.1f} km</b><extra></extra>',
    },
    {
      x: xLabels, y: acwr,
      type: 'scatter', mode: 'lines+markers',
      name: 'Indice de surcharge',
      line:   { color: COLORS.accent, width: 2 },
      marker: { size: 6, color: COLORS.accent },
      yaxis: 'y2',
      hovertemplate: '<b>%{y:.2f}</b><extra></extra>',
    },
  ];

  const layout = {
    ...BASE_LAYOUT,
    height: 300,
    margin: { l: 40, r: 40, t: 24, b: 40 },
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 11, color: COLORS.inkMid },
      x: 0, y: 1.12, orientation: 'h',
    },
    xaxis: {
      ...AX,
      type: 'category',
      tickangle: 0,
      tickfont: { family: FONT, size: 10, color: COLORS.inkLight },
    },
    yaxis: {
      ...AX,
      ticksuffix: ' km',
      tickfont: { family: FONT, size: 10, color: COLORS.inkLight },
    },
    yaxis2: {
      ...AX,
      overlaying: 'y', side: 'right', range: [0, 2.5],
      tickfont: { family: FONT, size: 10, color: COLORS.inkLight },
    },
    shapes: [
      { type: 'line', yref: 'y2', y0: 1.3, y1: 1.3, xref: 'paper', x0: 0, x1: 1, line: { dash: 'dot', color: COLORS.warning, width: 1 }, opacity: 0.4 },
      { type: 'line', yref: 'y2', y0: 1.5, y1: 1.5, xref: 'paper', x0: 0, x1: 1, line: { dash: 'dot', color: COLORS.danger, width: 1 }, opacity: 0.4 },
    ],
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);

  if (opts.onWeekClick && typeof container.on === 'function') {
    container.on('plotly_click', (ev) => {
      const p = ev?.points?.[0];
      if (!p) return;
      const iso = weeks[p.pointIndex]?.week;
      if (iso) opts.onWeekClick(iso);
    });
    container.style.cursor = 'pointer';
  }
}

// ── ACWR 90 jours (charge) ──────────────────────────────────────────────────

export function plotAcwr(container, data) {
  const pts = data.points || [];
  if (!pts.length) return;

  const x = pts.map(p => p.date);
  const y = pts.map(p => p.acwr);
  const yMax = Math.max(2.0, Math.max(...y) + 0.2);

  const traces = [{
    x, y,
    type: 'scatter', mode: 'lines+markers',
    line:   { color: COLORS.accent, width: 2 },
    marker: { size: 4, color: COLORS.accent },
    showlegend: false,
  }];

  const layout = {
    ...BASE_LAYOUT,
    height: 320,
    xaxis: { ...AX },
    yaxis: {
      ...AX, range: [0, yMax],
      title: { text: 'ACWR', font: { family: FONT, size: 12, color: COLORS.inkLight } },
    },
    shapes: [
      { type: 'rect', yref: 'y', y0: 0, y1: 0.8, xref: 'paper', x0: 0, x1: 1, fillcolor: COLORS.danger, opacity: 0.04, line: { width: 0 } },
      { type: 'rect', yref: 'y', y0: 0.8, y1: 1.3, xref: 'paper', x0: 0, x1: 1, fillcolor: COLORS.success, opacity: 0.04, line: { width: 0 } },
      { type: 'rect', yref: 'y', y0: 1.3, y1: 1.5, xref: 'paper', x0: 0, x1: 1, fillcolor: COLORS.warning, opacity: 0.06, line: { width: 0 } },
      { type: 'rect', yref: 'y', y0: 1.5, y1: yMax, xref: 'paper', x0: 0, x1: 1, fillcolor: COLORS.danger, opacity: 0.06, line: { width: 0 } },
      { type: 'line', yref: 'y', y0: 1.3, y1: 1.3, xref: 'paper', x0: 0, x1: 1, line: { dash: 'dot', color: COLORS.warning, width: 1 }, opacity: 0.6 },
      { type: 'line', yref: 'y', y0: 1.5, y1: 1.5, xref: 'paper', x0: 0, x1: 1, line: { dash: 'dot', color: COLORS.danger, width: 1 }, opacity: 0.6 },
    ],
    annotations: [
      { x: 1, xref: 'paper', y: 1.3, yref: 'y', text: '1.3', showarrow: false, font: { family: FONT, size: 11, color: COLORS.warning }, xanchor: 'left', xshift: 4 },
      { x: 1, xref: 'paper', y: 1.5, yref: 'y', text: '1.5', showarrow: false, font: { family: FONT, size: 11, color: COLORS.danger }, xanchor: 'left', xshift: 4 },
    ],
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── Speed trend by type (progression — vélo) ──────────────────────────────

export function plotSpeedTrend(container, data) {
  const series = data.series || [];
  if (!series.length) return;

  const traces = series.map((s, i) => ({
    x: s.points.map(p => p.date),
    y: s.points.map(p => p.speed),
    type: 'scatter', mode: 'lines+markers',
    name: s.type,
    line:   { color: STYPE_PALETTE[i % STYPE_PALETTE.length], width: 1.5 },
    marker: { size: 4, color: STYPE_PALETTE[i % STYPE_PALETTE.length] },
    opacity: 0.85,
  }));

  const layout = {
    ...BASE_LAYOUT,
    height: 400,
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 11, color: COLORS.inkLight },
      x: 0, y: -0.18, orientation: 'h',
    },
    xaxis: { ...AX },
    yaxis: {
      ...AX,
      title: { text: 'km/h', font: { family: FONT, size: 12, color: COLORS.inkLight } },
    },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── Pace by type (progression) ──────────────────────────────────────────────

export function plotPace(container, data) {
  const series = data.series || [];
  if (!series.length) return;

  const traces = series.map((s, i) => ({
    x: s.points.map(p => p.date),
    y: s.points.map(p => p.pace),
    type: 'scatter', mode: 'lines+markers',
    name: s.type,
    line:   { color: STYPE_PALETTE[i % STYPE_PALETTE.length], width: 1.5 },
    marker: { size: 4, color: STYPE_PALETTE[i % STYPE_PALETTE.length] },
    opacity: 0.85,
  }));

  const layout = {
    ...BASE_LAYOUT,
    height: 400,
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 11, color: COLORS.inkLight },
      x: 0, y: -0.18, orientation: 'h',
    },
    xaxis: { ...AX },
    yaxis: {
      ...AX, autorange: 'reversed',
      title: { text: 'min/km', font: { family: FONT, size: 12, color: COLORS.inkLight } },
    },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── EF (progression) ────────────────────────────────────────────────────────

export function plotEf(container, data) {
  const pts = data.points || [];
  if (!pts.length) return;

  const traces = [
    {
      x: pts.map(p => p.date), y: pts.map(p => p.ef),
      type: 'scatter', mode: 'markers', name: 'EF',
      marker: { size: 3, color: COLORS.inkLight }, opacity: 0.6,
    },
    {
      x: pts.map(p => p.date), y: pts.map(p => p.ef_roll),
      type: 'scatter', mode: 'lines', name: t('charts.avg10'),
      line: { color: COLORS.ink, width: 2 },
      fill: 'tozeroy', fillcolor: 'rgba(20,20,20,0.04)',
    },
  ];

  const layout = {
    ...BASE_LAYOUT, height: 380,
    xaxis: { ...AX },
    yaxis: { ...AX, title: { text: 'EF (vitesse / FC)', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── VO2max (progression) ────────────────────────────────────────────────────

export function plotVo2(container, data) {
  const pts = data.points || [];
  if (!pts.length) return;

  const traces = [
    {
      x: pts.map(p => p.date), y: pts.map(p => p.vo2),
      type: 'scatter', mode: 'markers', name: 'VO2max',
      marker: { size: 4, color: COLORS.inkLight }, opacity: 0.5,
    },
    {
      x: pts.map(p => p.date), y: pts.map(p => p.vo2_roll),
      type: 'scatter', mode: 'lines', name: t('charts.trend'),
      line: { color: COLORS.ink, width: 2 },
      fill: 'tozeroy', fillcolor: 'rgba(20,20,20,0.04)',
    },
  ];

  const layout = {
    ...BASE_LAYOUT, height: 380,
    xaxis: { ...AX },
    yaxis: { ...AX, title: { text: 'mL/kg/min', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── Fitness / Fatigue / Form (Banister) ─────────────────────────────────────

export function plotFitness(container, data) {
  const pts = data.points || [];
  if (!pts.length) return;

  const x = pts.map(p => p.date);

  const traces = [
    {
      x, y: pts.map(p => p.ctl),
      type: 'scatter', mode: 'lines', name: t('charts.ctlFitness'),
      line: { color: COLORS.success, width: 2 },
    },
    {
      x, y: pts.map(p => p.atl),
      type: 'scatter', mode: 'lines', name: t('charts.atlFatigue'),
      line: { color: COLORS.accent, width: 2 },
    },
    {
      x, y: pts.map(p => p.tsb),
      type: 'scatter', mode: 'lines', name: t('charts.tsbForm'),
      line: { color: COLORS.ink, width: 1.5, dash: 'dot' },
      fill: 'tozeroy',
      fillcolor: 'rgba(20,20,20,0.04)',
    },
  ];

  const layout = {
    ...BASE_LAYOUT, height: 380,
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 11, color: COLORS.inkLight },
      x: 0, y: -0.18, orientation: 'h',
    },
    xaxis: { ...AX },
    yaxis: { ...AX, title: { text: 'TRIMP', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
    shapes: [
      { type: 'line', yref: 'y', y0: 0, y1: 0, xref: 'paper', x0: 0, x1: 1, line: { color: COLORS.inkLight, width: 1, dash: 'dot' }, opacity: 0.5 },
    ],
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── Monotony & Strain ──────────────────────────────────────────────────────

export function plotMonotony(container, data) {
  const pts = data.points || [];
  if (!pts.length) return;

  const x = pts.map(p => p.date);

  const traces = [
    {
      x, y: pts.map(p => p.strain),
      type: 'bar', name: 'Strain',
      marker: { color: COLORS.dark, opacity: 0.12, line: { color: COLORS.dark, width: 1 } },
      yaxis: 'y2',
    },
    {
      x, y: pts.map(p => p.monotony),
      type: 'scatter', mode: 'lines+markers', name: 'Monotony',
      line: { color: COLORS.accent, width: 2 },
      marker: { size: 4, color: COLORS.accent },
      yaxis: 'y',
    },
  ];

  const yMax = Math.max(3, Math.max(...pts.map(p => p.monotony || 0)) + 0.5);

  const layout = {
    ...BASE_LAYOUT, height: 340,
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 11, color: COLORS.inkLight },
      x: 0, y: 1.08, orientation: 'h',
    },
    xaxis: { ...AX },
    yaxis: {
      ...AX, range: [0, yMax],
      title: { text: 'Monotony', font: { family: FONT, size: 12, color: COLORS.inkLight } },
    },
    yaxis2: {
      ...AX,
      title: { text: 'Strain', font: { family: FONT, size: 12, color: COLORS.inkLight } },
      overlaying: 'y', side: 'right',
    },
    shapes: [
      { type: 'line', yref: 'y', y0: 2.0, y1: 2.0, xref: 'paper', x0: 0, x1: 1, line: { dash: 'dot', color: COLORS.warning, width: 1 }, opacity: 0.6 },
    ],
    annotations: [
      { x: 1, xref: 'paper', y: 2.0, yref: 'y', text: '2.0', showarrow: false, font: { family: FONT, size: 11, color: COLORS.warning }, xanchor: 'left', xshift: 4 },
    ],
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── GAP vs Pace (analyse) ──────────────────────────────────────────────────

export function plotGap(container, data) {
  if (!data.gap_speed_array || !data.gap_speed_array.length) return;

  const dist = data.distance_m.map(d => d / 1000);

  // Fetch real speed for comparison — we overlay GAP
  const traces = [
    {
      x: dist, y: data.gap_speed_array,
      type: 'scatter', mode: 'lines', name: 'GAP',
      line: { color: COLORS.accent, width: 1.5 },
      showlegend: true,
    },
  ];

  const layout = {
    ...BASE_LAYOUT, height: 260,
    margin: { l: 52, r: 20, t: 12, b: 36 },
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 11, color: COLORS.inkLight },
      x: 0, y: 1.08, orientation: 'h',
    },
    xaxis: { ...AX, title: { text: 'km', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
    yaxis: { ...AX, title: { text: 'km/h (GAP)', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── Zones FC (donut) ────────────────────────────────────────────────────────

export function plotZones(container, zones) {
  if (!zones || !Object.keys(zones).length) {
    container.innerHTML = `<div class="ca-empty">${t('charts.noHr')}</div>`;
    return;
  }

  const labels = Object.keys(zones).map(z => z.toUpperCase());
  const values = Object.values(zones).map(z => z.pct);
  const colors = ['#9CA3AF', '#22D3EE', '#22C55E', '#F97316', '#EF4444'];
  const text = values.map(v => v > 0 ? `${Math.round(v)}%` : '');

  const traces = [{
    labels, values, text,
    type: 'pie', hole: 0.6,
    textinfo: 'text',
    hovertemplate: '%{label}: %{value:.1f}%<extra></extra>',
    marker: { colors: colors.slice(0, labels.length), line: { color: COLORS.card, width: 2 } },
    textfont: { family: FONT, size: 11, color: COLORS.ink },
  }];

  const layout = {
    ...BASE_LAYOUT,
    height: 220,
    margin: { l: 24, r: 24, t: 16, b: 16 },
    showlegend: true,
    legend: { font: { family: FONT, size: 11, color: COLORS.inkMid }, bgcolor: 'rgba(0,0,0,0)' },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── Speed profile (analyse) — with manual block selection ───────────────────

/**
 * Convert pixel X on the plot area to data-space km.
 */
function _pxToKm(plotEl, pxX) {
  const layout = plotEl._fullLayout;
  const xa = layout.xaxis;
  return xa.p2d(pxX - layout._size.l);
}

/**
 * Build Plotly shapes array from blocks list.
 */
function _blockShapes(blocks, yRange) {
  return blocks.map(b => ({
    type: 'rect',
    xref: 'x', yref: 'y',
    x0: b.start_km, x1: b.end_km,
    y0: yRange[0], y1: yRange[1],
    fillcolor: b.type === 'effort'
      ? 'rgba(249, 115, 22, 0.18)'
      : 'rgba(168, 85, 247, 0.12)',
    line: {
      color: b.type === 'effort' ? '#F97316' : '#A855F7',
      width: 1.5,
      dash: b.type === 'effort' ? 'solid' : 'dot',
    },
  }));
}

export function plotSpeed(container, data, altData, opts = {}) {
  if (!data.speed_kmh || !data.speed_kmh.length) return;

  const dist = data.distance_m.map(d => d / 1000);
  const unit = opts.unit === 'kmh' ? 'kmh' : 'pace';

  let yArr, yRange, yTitle, hoverTpl;
  if (unit === 'kmh') {
    // Speed in km/h directly. Null out very slow points (stops < 1 km/h).
    yArr = data.speed_kmh.map(v => v > 1.0 ? v : null);
    const sorted = yArr.filter(v => v !== null).slice().sort((a, b) => a - b);
    const pctl = (arr, pct) => arr[Math.floor(arr.length * pct)] || arr[0];
    const p2  = sorted.length ? pctl(sorted, 0.02) : 5;
    const p98 = sorted.length ? pctl(sorted, 0.98) : 50;
    const lo = Math.floor(Math.max(0, p2 - 2));
    const hi = Math.ceil(p98 + 2);
    yRange = [lo, hi];
    yTitle = 'km/h';
    hoverTpl = '%{y:.1f} km/h<extra></extra>';
  } else {
    // Convert km/h to min/km. Null out very slow points (stops, walking < 3 km/h).
    const rawPace = data.speed_kmh.map(v => v > 3.0 ? 60 / v : null);
    const sorted = rawPace.filter(p => p !== null).slice().sort((a, b) => a - b);
    const pctl = (arr, pct) => arr[Math.floor(arr.length * pct)] || arr[0];
    const p2  = sorted.length ? pctl(sorted, 0.02) : 3;
    const p98 = sorted.length ? pctl(sorted, 0.98) : 10;
    const clipMax = p98 + 1.0;
    yArr = rawPace.map(v => v !== null && v <= clipMax ? v : null);
    const paceMin = Math.floor(p2 * 2) / 2;
    const paceMax = Math.ceil(Math.min(p98 + 0.5, clipMax) * 2) / 2;
    yRange = [paceMax, paceMin];  // reversed axis: [slow, fast]
    yTitle = 'min/km';
    hoverTpl = '%{y:.1f} min/km<extra></extra>';
  }

  const blocks = opts.blocks || [];

  const traces = [];

  // Altitude background trace (yaxis2)
  if (altData && altData.altitude_m?.length) {
    const altDist = altData.distance_m.map(d => d / 1000);
    traces.push({
      x: altDist, y: altData.altitude_m,
      type: 'scatter', mode: 'lines', fill: 'tozeroy',
      fillcolor: 'rgba(120, 116, 112, 0.08)',
      line: { color: 'rgba(120, 116, 112, 0.20)', width: 1 },
      yaxis: 'y2', showlegend: false, hoverinfo: 'skip',
    });
  }

  traces.push({
    x: dist, y: yArr,
    type: 'scatter', mode: 'lines',
    line: { color: COLORS.accent, width: 1.5 },
    fill: 'tozeroy', fillcolor: 'rgba(37, 99, 235, 0.06)',
    showlegend: false,
    connectgaps: true,
    hovertemplate: hoverTpl,
  });

  const yaxis = {
    ...AX,
    title: { text: yTitle, font: { family: FONT, size: 12, color: COLORS.inkLight } },
    range: yRange,
  };
  if (unit === 'pace') yaxis.autorange = 'reversed';

  const layout = {
    ...BASE_LAYOUT, height: 260,
    margin: { l: 52, r: 28, t: 12, b: 36 },
    xaxis: { ...AX, title: { text: 'km', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
    yaxis,
    shapes: _blockShapes(blocks, yRange),
    dragmode: false,
  };

  if (altData && altData.altitude_m?.length) {
    layout.yaxis2 = {
      overlaying: 'y', side: 'right',
      showgrid: false, showticklabels: false, zeroline: false,
    };
  }

  safePlot(container, traces, layout, PLOTLY_CONFIG);

  container._caData = { dist, pace: yArr, speedKmh: data.speed_kmh, yRange, unit };
}

/**
 * Enable drag-to-select block mode on a plotSpeed container.
 *
 * @param {HTMLElement} plotEl  — the div passed to plotSpeed (must already be plotted)
 * @param {Function} onBlock   — callback(block) when a block is created: { start_km, end_km, type }
 * @param {string} blockType   — "effort" (default)
 * @returns {Function} cleanup — call to disable the mode
 */
export function enableBlockSelect(plotEl, onBlock, blockType = 'effort') {
  let dragging = false;
  let startKm = 0;
  let previewLine = null;

  // We overlay an invisible div on top of the plot area to capture mouse events
  // without interfering with Plotly's internal structure.
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:absolute;top:0;left:0;width:100%;height:100%;z-index:10;cursor:crosshair;';
  plotEl.style.position = 'relative';
  plotEl.appendChild(overlay);

  // Vertical guide line element
  const guideLine = document.createElement('div');
  guideLine.style.cssText = `
    position:absolute; top:0; width:2px; height:100%;
    background:${blockType === 'effort' ? COLORS.accent : COLORS.success};
    opacity:0.7; pointer-events:none; display:none; z-index:11;
  `;
  plotEl.appendChild(guideLine);

  // Preview rectangle
  const previewRect = document.createElement('div');
  previewRect.style.cssText = `
    position:absolute; top:0; height:100%; pointer-events:none; display:none; z-index:11;
    background:${blockType === 'effort' ? 'rgba(37,99,235,0.12)' : 'rgba(45,106,79,0.08)'};
    border-left:2px solid ${blockType === 'effort' ? COLORS.accent : COLORS.success};
    border-right:2px solid ${blockType === 'effort' ? COLORS.accent : COLORS.success};
  `;
  plotEl.appendChild(previewRect);

  function kmToPx(km) {
    const layout = plotEl._fullLayout;
    if (!layout) return 0;
    const xa = layout.xaxis;
    return xa.d2p(km) + layout._size.l;
  }

  function onMouseDown(e) {
    if (!plotEl._fullLayout) return;
    const rect = plotEl.getBoundingClientRect();
    const px = e.clientX - rect.left;
    startKm = _pxToKm(plotEl, px);
    if (startKm < 0) startKm = 0;
    dragging = true;

    // Show guide line at start
    guideLine.style.left = px + 'px';
    guideLine.style.display = '';
    previewRect.style.display = '';
    previewRect.style.left = px + 'px';
    previewRect.style.width = '0px';

    e.preventDefault();
  }

  function onMouseMove(e) {
    const rect = plotEl.getBoundingClientRect();
    const px = e.clientX - rect.left;

    if (!dragging) {
      // Just show the guide line following the cursor
      guideLine.style.left = px + 'px';
      guideLine.style.display = '';
      return;
    }

    // Update preview rect
    const startPx = kmToPx(startKm);
    const left = Math.min(startPx, px);
    const width = Math.abs(px - startPx);
    previewRect.style.left = left + 'px';
    previewRect.style.width = width + 'px';
  }

  function onMouseUp(e) {
    if (!dragging) return;
    dragging = false;
    previewRect.style.display = 'none';

    const rect = plotEl.getBoundingClientRect();
    const px = e.clientX - rect.left;
    let endKm = _pxToKm(plotEl, px);

    // Ensure start < end
    let s = Math.min(startKm, endKm);
    let en = Math.max(startKm, endKm);

    // Ignore tiny drags (< 0.05 km = 50m)
    if (en - s < 0.05) return;

    // Clamp
    const maxKm = plotEl._caData?.dist?.slice(-1)[0] || en;
    s = Math.max(0, s);
    en = Math.min(maxKm, en);

    onBlock({ start_km: Math.round(s * 100) / 100, end_km: Math.round(en * 100) / 100, type: blockType });
  }

  function onMouseLeave() {
    guideLine.style.display = 'none';
    if (dragging) {
      dragging = false;
      previewRect.style.display = 'none';
    }
  }

  overlay.addEventListener('mousedown', onMouseDown);
  overlay.addEventListener('mousemove', onMouseMove);
  overlay.addEventListener('mouseup', onMouseUp);
  overlay.addEventListener('mouseleave', onMouseLeave);

  // Cleanup function
  return function disable() {
    overlay.remove();
    guideLine.remove();
    previewRect.remove();
  };
}

/**
 * Compute metrics for a block from the raw speed/bpm arrays.
 *
 * @param {{ start_km, end_km }} block
 * @param {number[]} distKm   — distance array in km
 * @param {number[]} speedKmh — speed array in km/h
 * @param {number[]|null} bpm — bpm array (same length), optional
 * @returns {{ distance_m, avg_pace_s, pace_display, avg_speed_kmh, avg_bpm }}
 */
export function computeBlockMetrics(block, distKm, speedKmh, bpm, powerW) {
  const mask = distKm.map((d, i) => d >= block.start_km && d <= block.end_km);
  const speeds = speedKmh.filter((_, i) => mask[i] && speedKmh[i] > 0.5);
  const bpms = bpm ? bpm.filter((_, i) => mask[i] && bpm[i] > 0) : [];
  const powers = powerW ? powerW.filter((_, i) => mask[i] && powerW[i] != null && powerW[i] > 0) : [];

  const distance_m = Math.round((block.end_km - block.start_km) * 1000);
  const avg_speed = speeds.length ? speeds.reduce((a, b) => a + b, 0) / speeds.length : 0;
  const avg_pace_s = avg_speed > 0 ? 3600 / avg_speed : 0;
  const pm = Math.floor(avg_pace_s / 60);
  const ps = Math.round(avg_pace_s % 60);
  const pace_display = avg_speed > 0 ? `${pm}:${String(ps).padStart(2, '0')}` : '—';
  const speed_display = avg_speed > 0 ? `${(Math.round(avg_speed * 10) / 10).toFixed(1)} km/h` : '—';
  const avg_bpm = bpms.length ? Math.round(bpms.reduce((a, b) => a + b, 0) / bpms.length) : null;
  const avg_power_w = powers.length ? Math.round(powers.reduce((a, b) => a + b, 0) / powers.length) : null;

  // Estimate duration from distance / avg speed
  const duration_s = avg_speed > 0 ? (distance_m / 1000) / avg_speed * 3600 : 0;
  const durMin = Math.floor(duration_s / 60);
  const durSec = Math.round(duration_s % 60);
  const duration_display = `${durMin}:${String(durSec).padStart(2, '0')}`;

  return { distance_m, avg_pace_s, pace_display, speed_display, avg_speed_kmh: Math.round(avg_speed * 10) / 10, avg_bpm, avg_power_w, duration_s, duration_display };
}

/**
 * Redraw block shapes on an existing plotSpeed or plotPower chart.
 */
export function updateBlockShapes(plotEl, blocks) {
  if (!plotEl._caData) return;
  const shapes = _blockShapes(blocks, plotEl._caData.yRange);
  Plotly.relayout(plotEl, { shapes });
}

// ── Altitude profile (analyse) ──────────────────────────────────────────────

export function plotAltitude(container, data) {
  if (!data.altitude_m || !data.altitude_m.length) return;

  const dist = data.distance_m.map(d => d / 1000);
  const alt  = data.altitude_m;

  const traces = [{
    x: dist, y: alt,
    type: 'scatter', mode: 'lines',
    line: { color: COLORS.ink, width: 1 },
    fill: 'tozeroy', fillcolor: 'rgba(20, 20, 20, 0.06)',
    opacity: 0.7,
    showlegend: false,
  }];

  const layout = {
    ...BASE_LAYOUT, height: 240,
    margin: { l: 52, r: 20, t: 12, b: 36 },
    xaxis: { ...AX, title: { text: 'km', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
    yaxis: { ...AX, title: { text: 'm', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── BPM profile with altitude background (analyse) ─────────────────────────

export function plotBpm(container, bpmData, altData) {
  if (!bpmData.bpm || !bpmData.bpm.length) return;

  const dist = bpmData.distance_m.map(d => d / 1000);
  const traces = [];

  // Altitude background trace (yaxis2)
  if (altData && altData.altitude_m?.length) {
    const altDist = altData.distance_m.map(d => d / 1000);
    traces.push({
      x: altDist, y: altData.altitude_m,
      type: 'scatter', mode: 'lines', fill: 'tozeroy',
      fillcolor: 'rgba(120, 116, 112, 0.08)',
      line: { color: 'rgba(120, 116, 112, 0.20)', width: 1 },
      yaxis: 'y2', showlegend: false, hoverinfo: 'skip',
    });
  }

  // Compute BPM Y-axis range for better readability
  const validBpm = bpmData.bpm.filter(b => b != null && b > 30);
  const bpmMin = validBpm.length ? Math.min(...validBpm) : 80;
  const bpmMax = validBpm.length ? Math.max(...validBpm) : 200;
  const bpmPad = 5;

  // BPM main trace — blue color scheme
  traces.push({
    x: dist, y: bpmData.bpm,
    type: 'scatter', mode: 'lines',
    line: { color: '#2563EB', width: 1.5 },
    fill: 'tozeroy', fillcolor: 'rgba(37, 99, 235, 0.08)',
    showlegend: false,
  });

  const layout = {
    ...BASE_LAYOUT, height: 260,
    margin: { l: 64, r: 48, t: 16, b: 40 },
    xaxis: { ...AX, title: { text: 'km', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
    yaxis: {
      ...AX,
      title: { text: 'bpm', font: { family: FONT, size: 12, color: COLORS.inkLight } },
      range: [Math.max(40, bpmMin - bpmPad), bpmMax + bpmPad],
    },
  };

  if (altData && altData.altitude_m?.length) {
    layout.yaxis2 = {
      overlaying: 'y', side: 'right',
      showgrid: false, showticklabels: false, zeroline: false,
    };
  }

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}


// ── Power chart ─────────────────────────────────────────────────────────────

export function plotPower(container, powerData, altData, opts = {}) {
  if (!powerData.power_w || !powerData.power_w.length) return;

  const dist = powerData.distance_m.map(d => d / 1000);
  const traces = [];

  // Altitude background trace (yaxis2)
  if (altData && altData.altitude_m?.length) {
    const altDist = altData.distance_m.map(d => d / 1000);
    traces.push({
      x: altDist, y: altData.altitude_m,
      type: 'scatter', mode: 'lines', fill: 'tozeroy',
      fillcolor: 'rgba(120, 116, 112, 0.08)',
      line: { color: 'rgba(120, 116, 112, 0.20)', width: 1 },
      yaxis: 'y2', showlegend: false, hoverinfo: 'skip',
    });
  }

  const validPow = powerData.power_w.filter(p => p != null && p > 0);
  const powMax = validPow.length ? Math.max(...validPow) : 400;
  const powPad = 20;
  const yRange = [0, powMax + powPad];

  const blocks = opts.blocks || [];

  // Power main trace — orange color scheme
  traces.push({
    x: dist, y: powerData.power_w,
    type: 'scatter', mode: 'lines',
    line: { color: '#EA580C', width: 1.5 },
    fill: 'tozeroy', fillcolor: 'rgba(234, 88, 12, 0.08)',
    showlegend: false,
  });

  const layout = {
    ...BASE_LAYOUT, height: 260,
    margin: { l: 52, r: 28, t: 12, b: 36 },
    xaxis: { ...AX, title: { text: 'km', font: { family: FONT, size: 12, color: COLORS.inkLight } } },
    yaxis: {
      ...AX,
      title: { text: 'watts', font: { family: FONT, size: 12, color: COLORS.inkLight } },
      range: yRange,
    },
    shapes: _blockShapes(blocks, yRange),
    dragmode: false,
  };

  if (altData && altData.altitude_m?.length) {
    layout.yaxis2 = {
      overlaying: 'y', side: 'right',
      showgrid: false, showticklabels: false, zeroline: false,
    };
  }

  safePlot(container, traces, layout, PLOTLY_CONFIG);

  // Store data refs for drag interaction
  container._caData = { dist, powerW: powerData.power_w, yRange };
}


// ── Splits (pace per km, horizontal bars) ───────────────────────────────────

export function plotSplits(container, splitsData) {
  if (!splitsData || !splitsData.splits || !splitsData.splits.length) {
    container.innerHTML = `<div class="ca-empty">${t('charts.noSplits')}</div>`;
    return;
  }

  const splits = splitsData.splits;
  const paces = splits.map(s => s.pace_s_per_km);
  const labels = splits.map(s => `km ${s.km}`);
  const displays = splits.map(s => s.pace_display);

  // Color gradient: fastest = green, slowest = accent blue
  const minP = Math.min(...paces);
  const maxP = Math.max(...paces);
  const range = maxP - minP || 1;
  const barColors = paces.map(p => {
    const t = (p - minP) / range;          // 0 = fastest, 1 = slowest
    const r = Math.round(45 + t * (37 - 45));
    const g = Math.round(106 + t * (99 - 106));
    const b = Math.round(79 + t * (235 - 79));
    return `rgb(${r},${g},${b})`;
  });

  // Zoom on useful range: base slightly below min pace so differences pop
  const spread = maxP - minP || 10;
  const xBase = minP - spread * 0.6;   // left edge well below fastest

  // Subtract base so bars show only the interesting part
  const xValues = paces.map(p => p - xBase);

  const traces = [{
    y: labels,
    x: xValues,
    type: 'bar',
    orientation: 'h',
    marker: { color: barColors },
    text: displays,
    textposition: 'inside',
    insidetextanchor: 'end',
    textfont: { family: FONT, size: 10, color: '#fff' },
    hovertemplate: '%{y}: <b>%{text}</b> min/km<extra></extra>',
  }];

  const height = Math.max(90, splits.length * 14 + 24);

  const layout = {
    ...BASE_LAYOUT,
    height,
    margin: { l: 36, r: 8, t: 4, b: 4 },
    xaxis: {
      ...AX,
      showticklabels: false,
      zeroline: false,
      showgrid: false,
    },
    yaxis: {
      ...AX,
      autorange: 'reversed',
      tickfont: { family: FONT, size: 10, color: COLORS.inkMid },
    },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

export function plotPolarizedBar(container, pctEF, pctSeuil) {
  const traces = [
    {
      x: [pctEF], y: [''],
      type: 'bar', orientation: 'h',
      marker: { color: COLORS.success },
      name: t('charts.enduranceFond'),
      text: [`${pctEF.toFixed(0)}%`], textposition: 'inside',
      textfont: { color: '#fff', family: FONT, size: 14 },
      hovertemplate: t('charts.hoverEndurance'),
    },
    {
      x: [pctSeuil], y: [''],
      type: 'bar', orientation: 'h',
      marker: { color: COLORS.danger },
      name: t('charts.thresholdPlus'),
      text: [`${pctSeuil.toFixed(0)}%`], textposition: 'inside',
      textfont: { color: '#fff', family: FONT, size: 14 },
      hovertemplate: t('charts.hoverThreshold'),
    },
  ];

  const layout = {
    ...BASE_LAYOUT, height: 110,
    barmode: 'stack',
    showlegend: false,
    margin: { l: 0, r: 0, t: 0, b: 28 },
    xaxis: { ...AX, range: [0, 100], showgrid: false, showticklabels: false, zeroline: false },
    yaxis: { ...AX, showgrid: false, showticklabels: false },
    shapes: [{
      type: 'line',
      x0: 80, x1: 80, y0: -0.5, y1: 0.5,
      line: { color: COLORS.ink, width: 2, dash: 'dot' },
    }],
    annotations: [
      {
        x: 80, y: 0.5, yref: 'paper', yanchor: 'bottom',
        text: '80%', showarrow: false,
        font: { family: FONT, size: 11, color: COLORS.inkMid },
      },
      {
        x: pctEF / 2, y: -0.6, xanchor: 'center', yanchor: 'top',
        text: 'Z1 + Z2 + Z3', showarrow: false,
        font: { family: FONT, size: 12, color: COLORS.success },
      },
      {
        x: pctEF + pctSeuil / 2, y: -0.6, xanchor: 'center', yanchor: 'top',
        text: 'Z4 + Z5', showarrow: false,
        font: { family: FONT, size: 12, color: COLORS.danger },
      },
    ],
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}
