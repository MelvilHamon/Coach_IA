/**
 * stadiums.js — Mes stades : vue d'ensemble, carte interactive, détail par stade.
 */

import { api } from '../api.js';
import { el, sectionTitle, loading, empty, fmt, fmtDate } from '../components.js';
import { setPendingActivityId } from '../state.js';
import { t } from '../i18n.js';

const SAT_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const SAT_ATTR = 'Tiles &copy; Esri';
const LABEL_TILES = 'https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png';

let _bigMap = null;
const _miniMaps = new Map();

export async function renderStadiums(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  try {
    const res = await api.stadiums();
    const stadiums = res.stadiums || [];
    const glob = res.global || {};

    container.innerHTML = '';
    _bigMap = null;
    _miniMaps.clear();

    if (!stadiums.length) {
      const section = el('div', { className: 'ca-section' },
        sectionTitle(t('nav.stadiums')),
        empty('Aucun stade détecté pour l\'instant.'),
      );
      container.appendChild(section);
      return;
    }

    container.appendChild(_renderHero(stadiums, glob));
    container.appendChild(_renderMap(stadiums));
    container.appendChild(_renderGrid(stadiums));

    // Defer Leaflet init until DOM is mounted
    requestAnimationFrame(() => {
      _initBigMap(stadiums);
      stadiums.forEach(s => _initMiniMap(s));
    });
  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}

// ── Hero overview ──────────────────────────────────────────────────────────

function _renderHero(stadiums, glob) {
  const hero = el('div', {
    className: 'ca-section',
    style: {
      background: 'linear-gradient(135deg, #1a1a1a 0%, #2d2d2d 50%, #1a1a1a 100%)',
      color: '#f4f1ea',
      padding: '32px 28px',
      borderRadius: '4px',
      marginBottom: '24px',
      position: 'relative',
      overflow: 'hidden',
    },
  });

  // Decorative track-lane background
  hero.appendChild(el('div', {
    style: {
      position: 'absolute', inset: 0, opacity: '0.06',
      background: 'repeating-linear-gradient(90deg, transparent 0 60px, #fff 60px 62px)',
      pointerEvents: 'none',
    },
  }));

  const title = el('div', {
    style: { position: 'relative', zIndex: 2 },
  },
    el('div', {
      style: {
        fontFamily: 'Barlow Condensed, sans-serif',
        fontSize: '11px',
        letterSpacing: '0.3em',
        textTransform: 'uppercase',
        opacity: 0.6,
        marginBottom: '6px',
      },
    }, 'Athlétisme · Pistes'),
    el('div', {
      style: {
        fontFamily: 'Cormorant Garamond, serif',
        fontSize: '34px',
        fontWeight: 400,
        fontStyle: 'italic',
        marginBottom: '4px',
      },
    }, 'Mes stades'),
    el('div', {
      style: { fontSize: '13px', opacity: 0.65, marginBottom: '24px' },
    }, `${glob.n_stadiums} stade${glob.n_stadiums > 1 ? 's' : ''} fréquenté${glob.n_stadiums > 1 ? 's' : ''} · ${glob.n_sessions} séance${glob.n_sessions > 1 ? 's' : ''} sur piste`),
  );
  hero.appendChild(title);

  hero.appendChild(el('div', {
    style: {
      position: 'relative', zIndex: 2,
      fontFamily: 'Barlow Condensed, sans-serif',
      fontSize: '10px', letterSpacing: '0.25em', textTransform: 'uppercase',
      opacity: 0.55, marginBottom: '10px',
    },
  }, `Records personnels — pistes 400 m (${glob.n_stadiums_400m ?? 0} stade${(glob.n_stadiums_400m ?? 0) > 1 ? 's' : ''})`));

  const prGrid = el('div', {
    style: {
      position: 'relative', zIndex: 2,
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
      gap: '20px',
      paddingTop: '14px',
      borderTop: '1px solid rgba(255,255,255,0.12)',
    },
  });

  prGrid.appendChild(_heroPR('1 tour', _formatLap(glob.pr_lap_s)));
  for (const n of ['2', '3', '5', '10']) {
    const v = glob.pr_multi?.[n];
    prGrid.appendChild(_heroPR(`${n} tours`, _formatLap(v)));
  }

  hero.appendChild(prGrid);
  return hero;
}

function _heroPR(label, value) {
  return el('div', {},
    el('div', {
      style: {
        fontFamily: 'Barlow Condensed, sans-serif',
        fontSize: '10px',
        letterSpacing: '0.25em',
        textTransform: 'uppercase',
        opacity: 0.55,
        marginBottom: '6px',
      },
    }, label),
    el('div', {
      style: {
        fontFamily: 'JetBrains Mono, monospace',
        fontSize: '22px',
        fontWeight: 300,
        color: '#f4f1ea',
      },
    }, value),
  );
}

// ── Big map ────────────────────────────────────────────────────────────────

function _renderMap(stadiums) {
  const wrap = el('div', {
    className: 'ca-section',
    style: { marginBottom: '24px' },
  });
  wrap.appendChild(el('div', {
    style: {
      fontFamily: 'Barlow Condensed, sans-serif',
      fontSize: '11px',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: 'var(--ink-mid)',
      marginBottom: '10px',
    },
  }, 'Carte des stades'));

  const mapEl = el('div', {
    id: 'stadiums-bigmap',
    style: {
      height: '380px',
      width: '100%',
      borderRadius: '4px',
      border: '1px solid var(--border)',
      overflow: 'hidden',
    },
  });
  wrap.appendChild(mapEl);
  return wrap;
}

function _initBigMap(stadiums) {
  if (typeof L === 'undefined') return;
  const mapEl = document.getElementById('stadiums-bigmap');
  if (!mapEl) return;

  const withCoords = stadiums.filter(s => s.lat != null && s.lon != null);
  if (!withCoords.length) {
    mapEl.innerHTML = '<div style="padding:20px;color:var(--ink-mid);text-align:center">Aucune coordonnée disponible.</div>';
    return;
  }

  const map = L.map(mapEl, { zoomControl: true, scrollWheelZoom: false });
  L.tileLayer(SAT_TILES, { attribution: SAT_ATTR, maxZoom: 19 }).addTo(map);
  L.tileLayer(LABEL_TILES, { subdomains: 'abcd', maxZoom: 19, opacity: 0.85 }).addTo(map);

  const bounds = [];
  for (const s of withCoords) {
    const icon = L.divIcon({
      className: 'ca-stadium-marker',
      html: `<div style="
        background:#e74c3c;color:#fff;border:2px solid #fff;
        border-radius:50%;width:30px;height:30px;
        display:flex;align-items:center;justify-content:center;
        font-family:JetBrains Mono,monospace;font-size:11px;font-weight:600;
        box-shadow:0 2px 6px rgba(0,0,0,0.4)">${s.n_sessions ?? ''}</div>`,
      iconSize: [30, 30],
      iconAnchor: [15, 15],
    });
    const m = L.marker([s.lat, s.lon], { icon }).addTo(map);
    m.bindPopup(`
      <div style="font-family:Cormorant Garamond,serif;font-size:15px;font-weight:600;margin-bottom:4px">${_titleCase(s.nom || s.id)}</div>
      <div style="color:#666;font-size:11px;margin-bottom:6px">${s.commune || ''} · ${s.track_length_m ? fmt(s.track_length_m, 0) + ' m' : ''}</div>
      <div style="font-family:JetBrains Mono,monospace;font-size:12px">
        ${s.n_sessions} séances · PR ${_formatLap(s.pr_lap_s)}
      </div>
      <a href="#" data-stadium-id="${s.id}" class="ca-stadium-popup-link"
         style="display:inline-block;margin-top:8px;color:#e74c3c;font-size:11px;text-transform:uppercase;letter-spacing:0.1em">
        Voir le détail →
      </a>
    `);
    bounds.push([s.lat, s.lon]);
  }

  if (bounds.length === 1) map.setView(bounds[0], 14);
  else map.fitBounds(bounds, { padding: [40, 40] });

  // Wire popup link clicks
  map.on('popupopen', (e) => {
    const link = e.popup.getElement().querySelector('.ca-stadium-popup-link');
    if (link) {
      link.addEventListener('click', (ev) => {
        ev.preventDefault();
        const sid = link.dataset.stadiumId;
        const stadium = stadiums.find(x => x.id === sid);
        if (stadium) _openStadiumDetail(stadium);
      });
    }
  });

  _bigMap = map;
}

// ── Grid of stadium cards ──────────────────────────────────────────────────

function _renderGrid(stadiums) {
  const wrap = el('div', { className: 'ca-section' });
  wrap.appendChild(el('div', {
    style: {
      fontFamily: 'Barlow Condensed, sans-serif',
      fontSize: '11px',
      letterSpacing: '0.25em',
      textTransform: 'uppercase',
      color: 'var(--ink-mid)',
      marginBottom: '14px',
    },
  }, `Stades fréquentés (${stadiums.length})`));

  const grid = el('div', {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
      gap: '20px',
    },
  });

  for (const s of stadiums) {
    grid.appendChild(_stadiumCard(s));
  }
  wrap.appendChild(grid);
  return wrap;
}

function _stadiumCard(s) {
  const card = el('div', {
    style: {
      background: 'var(--bg)',
      border: '1px solid var(--border)',
      borderRadius: '4px',
      overflow: 'hidden',
      cursor: 'pointer',
      transition: 'transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease',
      display: 'flex',
      flexDirection: 'column',
    },
    onMouseEnter: (e) => {
      e.currentTarget.style.transform = 'translateY(-2px)';
      e.currentTarget.style.boxShadow = '0 6px 20px rgba(0,0,0,0.08)';
      e.currentTarget.style.borderColor = '#999';
    },
    onMouseLeave: (e) => {
      e.currentTarget.style.transform = '';
      e.currentTarget.style.boxShadow = '';
      e.currentTarget.style.borderColor = 'var(--border)';
    },
    onClick: () => _openStadiumDetail(s),
  });

  // Satellite mini-map header
  const mapId = `stadium-mini-${s.id}`;
  const header = el('div', {
    style: {
      height: '160px',
      position: 'relative',
      background: '#2d2d2d',
    },
  });
  header.appendChild(el('div', {
    id: mapId,
    style: { height: '100%', width: '100%', pointerEvents: 'none' },
  }));
  // Gradient overlay for legibility
  header.appendChild(el('div', {
    style: {
      position: 'absolute', inset: 0,
      background: 'linear-gradient(to bottom, rgba(0,0,0,0) 50%, rgba(0,0,0,0.75) 100%)',
      pointerEvents: 'none',
    },
  }));
  // Stadium name overlay
  header.appendChild(el('div', {
    style: {
      position: 'absolute', bottom: '10px', left: '14px', right: '14px',
      color: '#fff',
      fontFamily: 'Cormorant Garamond, serif',
      fontSize: '18px',
      fontWeight: 500,
      lineHeight: 1.2,
      textShadow: '0 1px 3px rgba(0,0,0,0.6)',
      pointerEvents: 'none',
    },
  }, _titleCase(s.nom || s.id)));

  // Badges (surface/lights)
  const badges = el('div', {
    style: {
      position: 'absolute', top: '10px', right: '10px',
      display: 'flex', gap: '6px',
      pointerEvents: 'none',
    },
  });
  if (s.track_length_m) badges.appendChild(_pillBadge(`Piste ${fmt(s.track_length_m, 0)} m`));
  if (s.eclairage) badges.appendChild(_pillBadge('Éclairé', '#f1c40f'));
  header.appendChild(badges);

  card.appendChild(header);

  // Body
  const body = el('div', { style: { padding: '14px 16px 16px' } });
  body.appendChild(el('div', {
    style: { color: 'var(--ink-mid)', fontSize: '11px', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: '12px' },
  }, [s.commune, s.surface].filter(Boolean).join(' · ')));

  const stats = el('div', {
    style: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px', marginBottom: '12px' },
  });
  stats.appendChild(_stat('Taille', s.track_length_m ? `${fmt(s.track_length_m, 0)} m` : '—'));
  stats.appendChild(_stat('Séances', s.n_sessions ?? '—'));
  stats.appendChild(_stat('PR tour', _formatLap(s.pr_lap_s)));
  body.appendChild(stats);

  // Multi-lap PR strip
  if (s.pr_multi && Object.keys(s.pr_multi).length) {
    const strip = el('div', {
      style: {
        display: 'flex', gap: '10px', flexWrap: 'wrap',
        padding: '10px 0 0', borderTop: '1px solid var(--border)',
      },
    });
    for (const n of ['2', '3', '5', '10']) {
      const pr = s.pr_multi[n];
      if (!pr) continue;
      strip.appendChild(el('div', {
        style: { fontSize: '11px', fontFamily: 'JetBrains Mono, monospace', color: 'var(--ink-mid)' },
      }, `${n}t · `,
        el('span', { style: { color: 'var(--ink)' } }, _formatLap(pr.time_s)),
      ));
    }
    body.appendChild(strip);
  }

  body.appendChild(el('div', {
    style: {
      marginTop: '12px', fontSize: '11px', color: '#e74c3c',
      textTransform: 'uppercase', letterSpacing: '0.12em',
    },
  }, 'Voir les séances →'));

  card.appendChild(body);
  return card;
}

function _pillBadge(text, color) {
  return el('div', {
    style: {
      background: 'rgba(0,0,0,0.65)',
      color: color || '#fff',
      fontSize: '10px',
      fontFamily: 'JetBrains Mono, monospace',
      padding: '3px 8px',
      borderRadius: '10px',
      letterSpacing: '0.04em',
      backdropFilter: 'blur(4px)',
    },
  }, text);
}

function _initMiniMap(s) {
  if (typeof L === 'undefined') return;
  if (s.lat == null || s.lon == null) return;
  const target = document.getElementById(`stadium-mini-${s.id}`);
  if (!target) return;

  const m = L.map(target, {
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    boxZoom: false,
    keyboard: false,
    touchZoom: false,
  });
  L.tileLayer(SAT_TILES, { maxZoom: 19 }).addTo(m);
  m.setView([s.lat, s.lon], 17);
  _miniMaps.set(s.id, m);
}

// ── Detail modal ───────────────────────────────────────────────────────────

async function _openStadiumDetail(s) {
  const overlay = el('div', {
    style: {
      position: 'fixed', inset: 0, zIndex: 10000,
      background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: '20px',
    },
    onClick: (e) => { if (e.target === e.currentTarget) overlay.remove(); },
  });

  const modal = el('div', {
    style: {
      background: 'var(--bg)',
      maxWidth: '900px', width: '100%',
      maxHeight: '92vh',
      borderRadius: '6px',
      overflow: 'hidden',
      display: 'flex', flexDirection: 'column',
      boxShadow: '0 20px 60px rgba(0,0,0,0.4)',
    },
  });

  // Header with satellite hero
  const heroId = `stadium-detail-hero-${s.id}`;
  const hero = el('div', { style: { position: 'relative', height: '200px', background: '#2d2d2d', flex: 'none' } });
  hero.appendChild(el('div', { id: heroId, style: { height: '100%', width: '100%', pointerEvents: 'none' } }));
  hero.appendChild(el('div', {
    style: {
      position: 'absolute', inset: 0,
      background: 'linear-gradient(to bottom, rgba(0,0,0,0.1) 0%, rgba(0,0,0,0.8) 100%)',
      pointerEvents: 'none',
    },
  }));

  const close = el('button', {
    style: {
      position: 'absolute', top: '12px', right: '12px',
      background: 'rgba(0,0,0,0.6)', color: '#fff',
      border: 'none', borderRadius: '50%',
      width: '32px', height: '32px',
      cursor: 'pointer', fontSize: '16px', lineHeight: '1',
    },
    onClick: () => overlay.remove(),
  }, '✕');
  hero.appendChild(close);

  hero.appendChild(el('div', {
    style: {
      position: 'absolute', bottom: '16px', left: '24px', right: '24px',
      color: '#fff',
    },
  },
    el('div', {
      style: { fontFamily: 'Barlow Condensed, sans-serif', fontSize: '10px', letterSpacing: '0.3em', textTransform: 'uppercase', opacity: 0.7, marginBottom: '4px' },
    }, s.commune || ''),
    el('div', {
      style: { fontFamily: 'Cormorant Garamond, serif', fontSize: '28px', fontWeight: 500, lineHeight: 1.1 },
    }, _titleCase(s.nom || s.id)),
    el('div', {
      style: { marginTop: '8px', fontSize: '12px', opacity: 0.85, display: 'flex', gap: '14px' },
    },
      s.track_length_m ? el('span', {}, `${fmt(s.track_length_m, 0)} m`) : null,
      s.surface ? el('span', {}, s.surface) : null,
      s.eclairage ? el('span', {}, 'Éclairé') : null,
    ),
  ));

  modal.appendChild(hero);

  // Scrollable body
  const body = el('div', { style: { padding: '24px', overflowY: 'auto', flex: '1 1 auto' } });

  // PR table
  body.appendChild(el('div', {
    style: { fontFamily: 'Barlow Condensed, sans-serif', fontSize: '11px', letterSpacing: '0.25em', textTransform: 'uppercase', color: 'var(--ink-mid)', marginBottom: '10px' },
  }, 'Records personnels'));

  const prTable = el('div', {
    style: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))', gap: '12px', marginBottom: '24px' },
  });
  prTable.appendChild(_prBlock('1 tour', _formatLap(s.pr_lap_s)));
  for (const n of ['2', '3', '5', '10']) {
    const v = s.pr_multi?.[n]?.time_s;
    prTable.appendChild(_prBlock(`${n} tours`, _formatLap(v)));
  }
  body.appendChild(prTable);

  // Progression chart
  body.appendChild(el('div', {
    style: { fontFamily: 'Barlow Condensed, sans-serif', fontSize: '11px', letterSpacing: '0.25em', textTransform: 'uppercase', color: 'var(--ink-mid)', marginBottom: '10px' },
  }, 'Progression'));
  const chartEl = el('div', { id: `stadium-chart-${s.id}`, style: { height: '260px', marginBottom: '24px' } });
  body.appendChild(chartEl);

  // Sessions list
  body.appendChild(el('div', {
    style: { fontFamily: 'Barlow Condensed, sans-serif', fontSize: '11px', letterSpacing: '0.25em', textTransform: 'uppercase', color: 'var(--ink-mid)', marginBottom: '10px' },
  }, 'Séances réalisées'));
  const sessList = el('div', { style: { marginBottom: '8px' } }, loading());
  body.appendChild(sessList);

  modal.appendChild(body);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);

  // ESC to close
  const onKey = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', onKey); } };
  document.addEventListener('keydown', onKey);

  // Initialize satellite hero map
  requestAnimationFrame(() => {
    if (typeof L !== 'undefined' && s.lat != null) {
      const m = L.map(heroId, {
        zoomControl: false, attributionControl: false,
        dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
        boxZoom: false, keyboard: false, touchZoom: false,
      });
      L.tileLayer(SAT_TILES, { maxZoom: 19 }).addTo(m);
      m.setView([s.lat, s.lon], 17);
    }
    _plotProgression(s, `stadium-chart-${s.id}`);
  });

  // Fetch session list
  try {
    const res = await api.stadiumSessions(s.id);
    sessList.innerHTML = '';
    if (!res.sessions?.length) {
      sessList.appendChild(empty('Aucune séance enregistrée.'));
    } else {
      sessList.appendChild(_renderSessionsTable(res.sessions, overlay));
    }
  } catch (err) {
    sessList.innerHTML = '';
    sessList.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}

function _renderSessionsTable(sessions, overlay) {
  const table = el('table', { className: 'ca-records-table', style: { width: '100%', fontSize: '12px' } },
    el('thead', {},
      el('tr', {},
        el('th', {}, 'Date'),
        el('th', {}, 'Tours'),
        el('th', {}, 'Best'),
        el('th', {}, 'Moyenne'),
        el('th', {}, 'CV'),
        el('th', {}, 'Distance'),
      ),
    ),
  );
  const tbody = el('tbody');
  for (const p of sessions) {
    const row = el('tr', {
      style: { cursor: 'pointer' },
      title: 'Voir l\'analyse de cette séance',
      onClick: () => {
        setPendingActivityId(p.strava_id);
        overlay.remove();
        window.location.hash = 'analyse';
      },
    },
      el('td', { className: 'dim' }, p.date ? fmtDate(p.date) : '—'),
      el('td', {}, p.n_laps ?? '—'),
      el('td', { className: 'pr-time' }, _formatLap(p.best_lap_s)),
      el('td', {}, _formatLap(p.mean_lap_s)),
      el('td', {}, p.cv != null ? fmt(p.cv, 2) : '—'),
      el('td', {}, p.total_distance_m ? fmt(p.total_distance_m / 1000, 2) + ' km' : '—'),
    );
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

function _prBlock(label, value) {
  return el('div', {
    style: {
      background: '#f7f5ef',
      border: '1px solid var(--border)',
      padding: '12px',
      borderRadius: '4px',
      textAlign: 'center',
    },
  },
    el('div', { style: { fontSize: '10px', color: 'var(--ink-mid)', letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '4px' } }, label),
    el('div', { style: { fontFamily: 'JetBrains Mono, monospace', fontSize: '18px' } }, value),
  );
}

function _plotProgression(s, elemId) {
  if (typeof Plotly === 'undefined') return;
  const target = document.getElementById(elemId);
  if (!target) return;
  const prog = (s.progression || []).slice().sort((a, b) => (a.date || '').localeCompare(b.date || ''));
  if (!prog.length) {
    target.innerHTML = '<div style="padding:20px;color:var(--ink-mid);text-align:center;font-size:12px">Pas assez de données</div>';
    return;
  }

  const x = prog.map(p => (p.date || '').slice(0, 10));
  const best = prog.map(p => p.best_lap_s);
  const mean = prog.map(p => p.mean_lap_s);

  Plotly.newPlot(target, [
    {
      x, y: best,
      type: 'scatter', mode: 'lines+markers',
      name: 'Meilleur tour',
      line: { color: '#e74c3c', width: 2 },
      marker: { size: 7, color: '#e74c3c' },
    },
    {
      x, y: mean,
      type: 'scatter', mode: 'lines+markers',
      name: 'Tour moyen',
      line: { color: '#999', width: 1.5, dash: 'dot' },
      marker: { size: 5, color: '#999' },
    },
  ], {
    margin: { l: 50, r: 20, t: 10, b: 40 },
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    xaxis: { gridcolor: '#eee', tickfont: { size: 10 } },
    yaxis: { title: 'Secondes', gridcolor: '#eee', tickfont: { size: 10 }, titlefont: { size: 11 } },
    legend: { orientation: 'h', y: -0.25, font: { size: 11 } },
    hovermode: 'x unified',
  }, { displayModeBar: false, responsive: true });
}

// ── Helpers ────────────────────────────────────────────────────────────────

function _stat(label, value) {
  return el('div', {},
    el('div', { style: { fontSize: '10px', color: 'var(--ink-mid)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '2px' } }, label),
    el('div', { style: { fontFamily: 'JetBrains Mono, monospace', fontSize: '15px' } }, String(value)),
  );
}

function _formatLap(seconds) {
  if (seconds == null) return '—';
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function _formatPace(minPerKm) {
  if (minPerKm == null) return '—';
  const m = Math.floor(minPerKm);
  const s = Math.round((minPerKm - m) * 60);
  return `${m}:${String(s).padStart(2, '0')}/km`;
}

function _titleCase(str) {
  return String(str).toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}
