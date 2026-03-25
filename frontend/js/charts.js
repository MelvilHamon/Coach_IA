/**
 * charts.js — Wrapper Plotly.js avec le design system CoachAgent.
 */

const COLORS = {
  bg:       '#F7F4F0',
  card:     '#FFFFFF',
  dark:     '#141414',
  ink:      '#141414',
  inkMid:   '#787470',
  inkLight: '#A09B96',
  accent:   '#D4380D',
  success:  '#2D6A4F',
  warning:  '#B45309',
  danger:   '#991B1B',
  border:   '#E8E4DF',
  grid:     '#F0EDE8',
};

const FONT = "'JetBrains Mono', monospace";

const BASE_LAYOUT = {
  paper_bgcolor: COLORS.card,
  plot_bgcolor:  COLORS.card,
  font: { family: FONT, color: COLORS.inkMid, size: 10 },
  margin: { l: 48, r: 24, t: 24, b: 40 },
  showlegend: false,
  hovermode: 'x unified',
  hoverlabel: {
    bgcolor:     COLORS.dark,
    font: { color: COLORS.bg, family: FONT, size: 11 },
    bordercolor: '#2A2A2A',
  },
};

const AX = {
  gridcolor: COLORS.grid,
  gridwidth: 1,
  showline:  false,
  showgrid:  true,
  zeroline:  false,
  tickfont: { family: FONT, size: 10, color: COLORS.inkLight },
};

const PLOTLY_CONFIG = { displayModeBar: false, responsive: true };

/**
 * Safe wrapper around Plotly.newPlot — shows a message if Plotly isn't loaded.
 */
function safePlot(container, traces, layout, config) {
  if (typeof Plotly === 'undefined') {
    console.error('Plotly is not loaded — charts cannot render.');
    if (typeof container === 'string') container = document.getElementById(container);
    if (container) container.innerHTML = '<div class="ca-empty">Plotly non chargé — vérifier la connexion.</div>';
    return;
  }
  // Check for empty data — handle both cartesian (y) and pie (values) traces
  const hasData = traces.some(t =>
    (t.y && t.y.length > 0) || (t.values && t.values.length > 0)
  );
  if (!traces.length || !hasData) {
    if (typeof container === 'string') container = document.getElementById(container);
    if (container) container.innerHTML = '<div class="ca-empty">Données insuffisantes</div>';
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

export function plotVolume(container, data) {
  const weeks = data.weeks || [];
  if (!weeks.length) return;

  const x    = weeks.map(w => w.week);
  const km   = weeks.map(w => w.total_km);
  const acwr = weeks.map(w => w.acwr);

  const traces = [
    {
      x, y: km,
      type: 'bar',
      name: 'km / semaine',
      marker: { color: COLORS.dark, opacity: 0.12, line: { color: COLORS.dark, width: 1 } },
      yaxis: 'y',
    },
    {
      x, y: acwr,
      type: 'scatter', mode: 'lines+markers',
      name: 'ACWR',
      line:   { color: COLORS.accent, width: 2 },
      marker: { size: 4, color: COLORS.accent },
      yaxis: 'y2',
    },
  ];

  const layout = {
    ...BASE_LAYOUT,
    height: 280,
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 9, color: COLORS.inkLight },
      x: 0, y: 1.08, orientation: 'h',
    },
    xaxis: { ...AX },
    yaxis: {
      ...AX,
      title: { text: 'km', font: { family: FONT, size: 10, color: COLORS.inkLight } },
    },
    yaxis2: {
      ...AX,
      title: { text: 'ACWR', font: { family: FONT, size: 10, color: COLORS.inkLight } },
      overlaying: 'y', side: 'right', range: [0, 2.5],
    },
    shapes: [
      { type: 'line', yref: 'y2', y0: 1.3, y1: 1.3, xref: 'paper', x0: 0, x1: 1, line: { dash: 'dot', color: COLORS.warning, width: 1 }, opacity: 0.5 },
      { type: 'line', yref: 'y2', y0: 1.5, y1: 1.5, xref: 'paper', x0: 0, x1: 1, line: { dash: 'dot', color: COLORS.danger, width: 1 }, opacity: 0.5 },
    ],
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
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
    height: 260,
    xaxis: { ...AX },
    yaxis: {
      ...AX, range: [0, yMax],
      title: { text: 'ACWR', font: { family: FONT, size: 10, color: COLORS.inkLight } },
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
      { x: 1, xref: 'paper', y: 1.3, yref: 'y', text: '1.3', showarrow: false, font: { family: FONT, size: 9, color: COLORS.warning }, xanchor: 'left', xshift: 4 },
      { x: 1, xref: 'paper', y: 1.5, yref: 'y', text: '1.5', showarrow: false, font: { family: FONT, size: 9, color: COLORS.danger }, xanchor: 'left', xshift: 4 },
    ],
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
    height: 340,
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 9, color: COLORS.inkLight },
      x: 0, y: -0.18, orientation: 'h',
    },
    xaxis: { ...AX },
    yaxis: {
      ...AX, autorange: 'reversed',
      title: { text: 'min/km', font: { family: FONT, size: 10, color: COLORS.inkLight } },
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
      type: 'scatter', mode: 'lines', name: 'Moy. 10 séances',
      line: { color: COLORS.ink, width: 2 },
      fill: 'tozeroy', fillcolor: 'rgba(20,20,20,0.04)',
    },
  ];

  const layout = {
    ...BASE_LAYOUT, height: 320,
    xaxis: { ...AX },
    yaxis: { ...AX, title: { text: 'EF (vitesse / FC)', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
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
      type: 'scatter', mode: 'lines', name: 'Tendance',
      line: { color: COLORS.ink, width: 2 },
      fill: 'tozeroy', fillcolor: 'rgba(20,20,20,0.04)',
    },
  ];

  const layout = {
    ...BASE_LAYOUT, height: 320,
    xaxis: { ...AX },
    yaxis: { ...AX, title: { text: 'mL/kg/min', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
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
      type: 'scatter', mode: 'lines', name: 'CTL (Fitness)',
      line: { color: COLORS.success, width: 2 },
    },
    {
      x, y: pts.map(p => p.atl),
      type: 'scatter', mode: 'lines', name: 'ATL (Fatigue)',
      line: { color: COLORS.accent, width: 2 },
    },
    {
      x, y: pts.map(p => p.tsb),
      type: 'scatter', mode: 'lines', name: 'TSB (Form)',
      line: { color: COLORS.ink, width: 1.5, dash: 'dot' },
      fill: 'tozeroy',
      fillcolor: 'rgba(20,20,20,0.04)',
    },
  ];

  const layout = {
    ...BASE_LAYOUT, height: 320,
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 9, color: COLORS.inkLight },
      x: 0, y: -0.18, orientation: 'h',
    },
    xaxis: { ...AX },
    yaxis: { ...AX, title: { text: 'TRIMP', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
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
    ...BASE_LAYOUT, height: 280,
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 9, color: COLORS.inkLight },
      x: 0, y: 1.08, orientation: 'h',
    },
    xaxis: { ...AX },
    yaxis: {
      ...AX, range: [0, yMax],
      title: { text: 'Monotony', font: { family: FONT, size: 10, color: COLORS.inkLight } },
    },
    yaxis2: {
      ...AX,
      title: { text: 'Strain', font: { family: FONT, size: 10, color: COLORS.inkLight } },
      overlaying: 'y', side: 'right',
    },
    shapes: [
      { type: 'line', yref: 'y', y0: 2.0, y1: 2.0, xref: 'paper', x0: 0, x1: 1, line: { dash: 'dot', color: COLORS.warning, width: 1 }, opacity: 0.6 },
    ],
    annotations: [
      { x: 1, xref: 'paper', y: 2.0, yref: 'y', text: '2.0', showarrow: false, font: { family: FONT, size: 9, color: COLORS.warning }, xanchor: 'left', xshift: 4 },
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
    ...BASE_LAYOUT, height: 200,
    margin: { l: 48, r: 16, t: 8, b: 32 },
    showlegend: true,
    legend: {
      bgcolor: 'rgba(0,0,0,0)', borderwidth: 0,
      font: { family: FONT, size: 9, color: COLORS.inkLight },
      x: 0, y: 1.08, orientation: 'h',
    },
    xaxis: { ...AX, title: { text: 'km', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
    yaxis: { ...AX, title: { text: 'km/h (GAP)', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── Zones FC (donut) ────────────────────────────────────────────────────────

export function plotZones(container, zones) {
  if (!zones || !Object.keys(zones).length) {
    container.innerHTML = '<div class="ca-empty">FC non disponible</div>';
    return;
  }

  const labels = Object.keys(zones).map(z => z.toUpperCase());
  const values = Object.values(zones).map(z => z.pct);
  const colors = ['#E8E4DF', '#C4C0BB', '#787470', '#141414', COLORS.accent];

  const traces = [{
    labels, values,
    type: 'pie', hole: 0.6,
    marker: { colors: colors.slice(0, labels.length), line: { color: COLORS.card, width: 2 } },
    textfont: { family: FONT, size: 9, color: COLORS.ink },
  }];

  const layout = {
    ...BASE_LAYOUT,
    height: 200,
    margin: { l: 0, r: 0, t: 10, b: 10 },
    showlegend: true,
    legend: { font: { family: FONT, size: 9, color: COLORS.inkMid }, bgcolor: 'rgba(0,0,0,0)' },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}

// ── Speed profile (analyse) ─────────────────────────────────────────────────

export function plotSpeed(container, data) {
  if (!data.speed_kmh || !data.speed_kmh.length) return;

  const dist = data.distance_m.map(d => d / 1000);
  const traces = [{
    x: dist, y: data.speed_kmh,
    type: 'scatter', mode: 'lines',
    line: { color: COLORS.accent, width: 1.5 },
    fill: 'tozeroy', fillcolor: 'rgba(212, 56, 13, 0.06)',
    showlegend: false,
  }];

  const layout = {
    ...BASE_LAYOUT, height: 200,
    margin: { l: 48, r: 16, t: 8, b: 32 },
    xaxis: { ...AX, title: { text: 'km', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
    yaxis: { ...AX, title: { text: 'km/h', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
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
    showlegend: false,
  }];

  const layout = {
    ...BASE_LAYOUT, height: 180,
    margin: { l: 48, r: 16, t: 8, b: 32 },
    xaxis: { ...AX, title: { text: 'km', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
    yaxis: { ...AX, title: { text: 'm', font: { family: FONT, size: 10, color: COLORS.inkLight } } },
  };

  safePlot(container, traces, layout, PLOTLY_CONFIG);
}
