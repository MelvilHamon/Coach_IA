/**
 * map.js — Carte GPS Leaflet avec trace et marqueurs.
 */

let _currentMap = null;

export function renderMap(container, points) {
  if (_currentMap) {
    _currentMap.remove();
    _currentMap = null;
  }

  if (!points || points.length < 2) {
    container.innerHTML = '<div class="ca-empty">GPS non disponible</div>';
    return;
  }

  const lats = points.map(p => p.lat);
  const lons = points.map(p => p.lon);
  const centerLat = lats.reduce((a, b) => a + b, 0) / lats.length;
  const centerLon = lons.reduce((a, b) => a + b, 0) / lons.length;

  const map = L.map(container, {
    center: [centerLat, centerLon],
    zoom: 13,
    zoomControl: true,
    attributionControl: true,
  });

  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 19,
  }).addTo(map);

  // Trace
  const coords = points.map(p => [p.lat, p.lon]);
  L.polyline(coords, {
    color: '#D4380D',
    weight: 3,
    opacity: 0.9,
    smoothFactor: 1,
  }).addTo(map);

  // Départ
  L.circleMarker(coords[0], {
    radius: 6,
    color: '#2D6A4F',
    fillColor: '#2D6A4F',
    fillOpacity: 1,
    weight: 0,
  }).bindTooltip('Départ', { permanent: false, direction: 'top' }).addTo(map);

  // Arrivée
  L.circleMarker(coords[coords.length - 1], {
    radius: 6,
    color: '#991B1B',
    fillColor: '#991B1B',
    fillOpacity: 1,
    weight: 0,
  }).bindTooltip('Arrivée', { permanent: false, direction: 'top' }).addTo(map);

  // Fit bounds
  map.fitBounds(L.latLngBounds(coords), { padding: [30, 30] });

  _currentMap = map;
}
