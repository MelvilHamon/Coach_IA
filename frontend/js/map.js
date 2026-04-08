/**
 * map.js — Carte GPS Leaflet avec trace colorée par allure/dénivelé.
 *
 * Tile layers :
 *   - Clair (défaut) : CartoDB Positron
 *   - Sombre         : CartoDB DarkMatter
 *
 * Gradient overlay :
 *   - Allure : vert (lent) → jaune → rouge (rapide)
 *   - Dénivelé : bleu (descente) → blanc (plat) → orange (montée)
 */

let _currentMap = null;

const TILES = {
  light: {
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    label: 'Clair',
  },
  dark: {
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    label: 'Sombre',
  },
};

const TILE_OPTS = {
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
  subdomains: 'abcd',
  maxZoom: 19,
};

const GRADIENT_MODES = {
  none:     'Trace unie',
  speed:    'Allure',
  altitude: 'Dénivelé',
};


// ── Color interpolation helpers ─────────────────────────────────────────────

function _lerp(a, b, t) {
  return a + (b - a) * t;
}

function _rgbToHex(r, g, b) {
  return '#' + [r, g, b].map(v => Math.round(v).toString(16).padStart(2, '0')).join('');
}

// ── Multi-stop gradient interpolation ────────────────────────────────────────

function _gradientColor(t, stops) {
  // t in [0,1], stops = [[r,g,b], ...] evenly spaced
  t = Math.max(0, Math.min(1, t));
  const n = stops.length - 1;
  const i = Math.min(Math.floor(t * n), n - 1);
  const u = t * n - i;
  return _rgbToHex(
    _lerp(stops[i][0], stops[i + 1][0], u),
    _lerp(stops[i][1], stops[i + 1][1], u),
    _lerp(stops[i][2], stops[i + 1][2], u),
  );
}

// Allure : slow (red) → orange → yellow → green-teal → dark green (fast)
const _SPEED_STOPS = [
  [180, 30, 30],    // #B41E1E  lent
  [212, 120, 20],   // #D47814
  [200, 180, 30],   // #C8B41E
  [60, 160, 90],    // #3CA05A
  [30, 100, 70],    // #1E6446  rapide
];

// Dénivelé : bleu foncé (descente forte) → bleu clair → vert-jaune (plat) → orange → rouge (montée forte)
const _ALT_STOPS = [
  [30, 64, 175],    // #1E40AF  descente forte
  [70, 140, 200],   // #468CC8  descente douce
  [140, 180, 80],   // #8CB450  plat / faux plat
  [220, 150, 30],   // #DC961E  montée douce
  [190, 50, 30],    // #BE321E  montée forte
];

function _percentile(arr, p) {
  const sorted = [...arr].sort((a, b) => a - b);
  const i = (p / 100) * (sorted.length - 1);
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return lo === hi ? sorted[lo] : _lerp(sorted[lo], sorted[hi], i - lo);
}

function _speedColor(speed_kmh, p10, p90) {
  if (p90 <= p10) return '#2563EB';
  const t = (speed_kmh - p10) / (p90 - p10);
  return _gradientColor(t, _SPEED_STOPS);
}

function _altColor(gradient_pct, clipNeg, clipPos) {
  // Map [-clipNeg, +clipPos] to [0, 1] with 0.5 = flat
  const g = Math.max(-clipNeg, Math.min(clipPos, gradient_pct));
  let t;
  if (g < 0) {
    t = 0.5 - (Math.abs(g) / clipNeg) * 0.5; // 0 = max descent, 0.5 = flat
  } else {
    t = 0.5 + (g / clipPos) * 0.5;             // 0.5 = flat, 1 = max ascent
  }
  return _gradientColor(t, _ALT_STOPS);
}


// ── Compute per-segment data ────────────────────────────────────────────────

function _haversine(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
    * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function _computeSegments(points) {
  const segments = [];
  for (let i = 0; i < points.length - 1; i++) {
    const p1 = points[i], p2 = points[i + 1];
    const dist = _haversine(p1.lat, p1.lon, p2.lat, p2.lon);
    const dt = (p2.time_s ?? 0) - (p1.time_s ?? 0);
    const speed_kmh = dt > 0 ? (dist / dt) * 3.6 : 0;
    const alt1 = p1.altitude_m ?? 0;
    const alt2 = p2.altitude_m ?? 0;
    const gradient_pct = dist > 1 ? ((alt2 - alt1) / dist) * 100 : 0;

    segments.push({
      from: [p1.lat, p1.lon],
      to: [p2.lat, p2.lon],
      speed_kmh,
      gradient_pct,
    });
  }
  return segments;
}


// ── Render map ──────────────────────────────────────────────────────────────

export function renderMap(container, points) {
  if (_currentMap) {
    _currentMap.remove();
    _currentMap = null;
  }

  if (!points || points.length < 2) {
    container.innerHTML = '<div class="ca-empty">GPS non disponible</div>';
    return;
  }

  // ── Controls container (toggle buttons above map) ──
  const parent = container.parentElement;
  let controlsEl = parent?.querySelector('.ca-map-controls');
  if (controlsEl) controlsEl.remove();

  controlsEl = document.createElement('div');
  controlsEl.className = 'ca-map-controls';

  // State
  let currentTile = 'light';
  let currentGradient = 'none';
  let tileLayer = null;
  let traceLayer = null;

  const map = L.map(container, {
    center: [0, 0],
    zoom: 13,
    zoomControl: true,
    attributionControl: true,
  });

  function setTile(key) {
    if (tileLayer) map.removeLayer(tileLayer);
    tileLayer = L.tileLayer(TILES[key].url, TILE_OPTS).addTo(map);
    currentTile = key;
  }

  setTile('light');

  // Precompute segments
  const segments = _computeSegments(points);
  const speeds = segments.map(s => s.speed_kmh).filter(s => s > 1);
  // Percentile-based range: ignore outliers (stops, sprints)
  const speedP10 = speeds.length ? _percentile(speeds, 10) : 0;
  const speedP90 = speeds.length ? _percentile(speeds, 90) : 20;
  // Gradient clips: use P95 of absolute gradients to scale per-activity
  const grads = segments.map(s => s.gradient_pct);
  const absGrads = grads.map(g => Math.abs(g)).filter(g => g > 0.5);
  const gradClip = absGrads.length ? Math.max(5, _percentile(absGrads, 95)) : 12;

  function drawTrace(mode) {
    if (traceLayer) {
      map.removeLayer(traceLayer);
      traceLayer = null;
    }

    if (mode === 'none') {
      // Single polyline
      const coords = points.map(p => [p.lat, p.lon]);
      traceLayer = L.polyline(coords, {
        color: '#2563EB',
        weight: 3.5,
        opacity: 0.9,
        smoothFactor: 1,
      }).addTo(map);
    } else {
      // Multi-segment colored polyline
      const group = L.layerGroup();
      // Downsample for performance: merge every N segments
      const step = segments.length > 2000 ? Math.ceil(segments.length / 1000) : 1;

      for (let i = 0; i < segments.length; i += step) {
        const seg = segments[i];
        let color;
        if (mode === 'speed') {
          color = _speedColor(seg.speed_kmh, speedP10, speedP90);
        } else {
          color = _altColor(seg.gradient_pct, gradClip, gradClip);
        }
        const end = Math.min(i + step, segments.length - 1);
        const endSeg = segments[end] || seg;
        L.polyline([seg.from, endSeg.to], {
          color,
          weight: 3.5,
          opacity: 0.9,
          smoothFactor: 0,
        }).addTo(group);
      }
      traceLayer = group;
      group.addTo(map);
    }
    currentGradient = mode;
  }

  drawTrace('none');

  // ── Markers ──
  const coords = points.map(p => [p.lat, p.lon]);

  // Départ
  L.circleMarker(coords[0], {
    radius: 7,
    color: '#fff',
    fillColor: '#2D6A4F',
    fillOpacity: 1,
    weight: 2,
  }).bindTooltip('Départ', { permanent: false, direction: 'top' }).addTo(map);

  // Arrivée — red/white checkered style
  L.circleMarker(coords[coords.length - 1], {
    radius: 7,
    color: '#991B1B',
    fillColor: '#fff',
    fillOpacity: 1,
    weight: 2.5,
  }).bindTooltip('Arrivée', { permanent: false, direction: 'top' }).addTo(map);

  // Fit bounds
  map.fitBounds(L.latLngBounds(coords), { padding: [30, 30] });

  // ── Build controls ──
  // Tile toggle
  const tileGroup = document.createElement('div');
  tileGroup.className = 'ca-radio-group';
  for (const [key, tile] of Object.entries(TILES)) {
    const btn = document.createElement('button');
    btn.className = `ca-radio-btn${key === currentTile ? ' active' : ''}`;
    btn.textContent = tile.label;
    btn.addEventListener('click', () => {
      setTile(key);
      tileGroup.querySelectorAll('.ca-radio-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
    tileGroup.appendChild(btn);
  }

  // Gradient toggle
  const gradGroup = document.createElement('div');
  gradGroup.className = 'ca-radio-group';
  for (const [key, label] of Object.entries(GRADIENT_MODES)) {
    const btn = document.createElement('button');
    btn.className = `ca-radio-btn${key === currentGradient ? ' active' : ''}`;
    btn.textContent = label;
    btn.addEventListener('click', () => {
      drawTrace(key);
      gradGroup.querySelectorAll('.ca-radio-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
    gradGroup.appendChild(btn);
  }

  controlsEl.appendChild(tileGroup);
  controlsEl.appendChild(gradGroup);

  // Legend (hidden by default, shown when gradient active)
  const legendEl = document.createElement('div');
  legendEl.className = 'ca-map-legend';
  legendEl.style.display = 'none';
  controlsEl.appendChild(legendEl);

  function _cssGradient(stops) {
    const colors = stops.map((s, i) => {
      const pct = (i / (stops.length - 1)) * 100;
      return `${_rgbToHex(s[0], s[1], s[2])} ${pct.toFixed(0)}%`;
    });
    return `linear-gradient(to right, ${colors.join(', ')})`;
  }

  function _fmtPace(kmh) {
    if (!kmh || kmh < 0.5) return '—';
    const minPerKm = 60 / kmh;
    const m = Math.floor(minPerKm);
    const s = Math.round((minPerKm - m) * 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  function updateLegend() {
    if (currentGradient === 'none') {
      legendEl.style.display = 'none';
      return;
    }
    legendEl.style.display = 'flex';
    if (currentGradient === 'speed') {
      legendEl.innerHTML = `
        <span class="ca-legend-label">${_fmtPace(speedP10)}/km</span>
        <span class="ca-legend-bar" style="background:${_cssGradient(_SPEED_STOPS)}"></span>
        <span class="ca-legend-label">${_fmtPace(speedP90)}/km</span>
      `;
    } else {
      legendEl.innerHTML = `
        <span class="ca-legend-label">-${Math.round(gradClip)}%</span>
        <span class="ca-legend-bar" style="background:${_cssGradient(_ALT_STOPS)}"></span>
        <span class="ca-legend-label">+${Math.round(gradClip)}%</span>
      `;
    }
  }

  // Hook legend update to gradient changes
  const origDrawTrace = drawTrace;
  const drawTraceWrapped = (mode) => { origDrawTrace(mode); updateLegend(); };
  // Re-bind gradient buttons
  gradGroup.querySelectorAll('.ca-radio-btn').forEach((btn, i) => {
    const key = Object.keys(GRADIENT_MODES)[i];
    btn.replaceWith(btn.cloneNode(true));
  });
  gradGroup.innerHTML = '';
  for (const [key, label] of Object.entries(GRADIENT_MODES)) {
    const btn = document.createElement('button');
    btn.className = `ca-radio-btn${key === currentGradient ? ' active' : ''}`;
    btn.textContent = label;
    btn.addEventListener('click', () => {
      drawTraceWrapped(key);
      gradGroup.querySelectorAll('.ca-radio-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
    gradGroup.appendChild(btn);
  }

  // Insert controls before the map container
  if (parent) parent.insertBefore(controlsEl, container);

  _currentMap = map;
}
