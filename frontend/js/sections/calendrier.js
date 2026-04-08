/**
 * calendrier.js — Calendrier Semaine / Mois / Année style Garmin Connect.
 *
 * Planification avec backend API : créer, modifier, supprimer des séances.
 */

import { api } from '../api.js';
import { el, fmt, loading } from '../components.js';

// ── Constants ───────────────────────────────────────────────────────────────

const DAY_NAMES = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const MONTH_NAMES = [
  'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
  'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
];
const MONTH_SHORT = [
  'Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Juin',
  'Juil', 'Août', 'Sep', 'Oct', 'Nov', 'Déc',
];

const PLAN_TYPES = [
  'Endurance fondamentale', 'Seuil', 'Fractionné court',
  'Fractionné moyen', 'Fractionné long', 'Trail', 'Récupération active',
  'Sortie longue', 'Compétition', 'Renforcement musculaire',
];
const RECOVERY_OPTIONS = ['1min', '90s', '2min', '3min'];

// ── In-memory planned workouts (loaded from API) ────────────────────────────

let _planned = [];

async function _loadPlannedFromApi() {
  try {
    const res = await api.plannedWorkouts();
    _planned = res.workouts || [];
  } catch { _planned = []; }
}

// ── Migrate localStorage to API (one-time) ──────────────────────────────────

async function _migrateLocalStorage() {
  const STORAGE_KEY = 'ca_planned_workouts';
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const arr = JSON.parse(raw);
    if (!Array.isArray(arr) || arr.length === 0) return;
    for (const p of arr) {
      await api.createPlanned({
        date: p.date, type: p.type,
        target: p.distance_km ? 'distance' : 'duration',
        distance_km: p.distance_km, duration_min: p.duration_min || null,
        allure: p.allure, reps: p.reps,
        allure_effort: p.allure_effort, recovery: p.recovery, notes: p.notes,
      });
    }
    localStorage.removeItem(STORAGE_KEY);
  } catch { /* ignore migration errors */ }
}

// ── Color by session_type ───────────────────────────────────────────────────

function _typeColor(sessionType) {
  const s = (sessionType || '').toLowerCase();
  if (s.includes('récup') || s.includes('recup'))              return '#2D6A4F';
  if (s.includes('endurance') || s.includes('base') || s.includes('sortie longue')) return '#2D6A4F';
  if (s.includes('seuil') || s.includes('tempo'))              return '#2563EB';
  if (s.includes('fractionné') || s.includes('sprint') || s.includes('vo2') || s.includes('anaéro')) return '#991B1B';
  if (s.includes('trail'))                                      return '#6B5B4F';
  if (s.includes('compétition'))                                return '#B45309';
  if (s.includes('renforcement') || s.includes('muscul'))      return '#7C3AED';
  if (s.includes('run') || s.includes('course'))               return '#2563EB';
  return '#A09B96';
}

// ── Date helpers ────────────────────────────────────────────────────────────

function _dk(d) {
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}
function _todayKey() { return _dk(new Date()); }

function _mondayOf(d) {
  const r = new Date(d);
  const dow = r.getDay();
  r.setDate(r.getDate() - (dow === 0 ? 6 : dow - 1));
  r.setHours(0,0,0,0);
  return r;
}

// ── Format helpers ──────────────────────────────────────────────────────────

function _fmtDuration(totalMin) {
  if (!totalMin || totalMin <= 0) return '0:00:00';
  const h = Math.floor(totalMin / 60);
  const m = Math.floor(totalMin % 60);
  const s = Math.round((totalMin % 1) * 60);
  return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function _fmtDurationShort(totalMin) {
  if (!totalMin || totalMin <= 0) return '';
  const h = Math.floor(totalMin / 60);
  const m = Math.floor(totalMin % 60);
  const s = Math.round((totalMin % 1) * 60);
  if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  return `${m}:${String(s).padStart(2,'0')}`;
}

// ── Index helpers ───────────────────────────────────────────────────────────

function _indexByDate(activities) {
  const map = {};
  for (const a of activities) {
    const key = _dk(new Date(a.date));
    (map[key] ??= []).push(a);
  }
  return map;
}

function _indexPlannedByDate() {
  const map = {};
  for (const p of _planned) (map[p.date] ??= []).push(p);
  return map;
}

// ── Week rows for month view ────────────────────────────────────────────────

function _weekRows(year, month) {
  const first = new Date(year, month, 1);
  const last  = new Date(year, month + 1, 0);
  let startDow = first.getDay();
  startDow = startDow === 0 ? 6 : startDow - 1;

  const rows = [];
  let row = [];

  const prevLast = new Date(year, month, 0);
  for (let i = startDow - 1; i >= 0; i--) {
    const d = new Date(prevLast);
    d.setDate(prevLast.getDate() - i);
    row.push({ date: d, outside: true });
  }

  for (let day = 1; day <= last.getDate(); day++) {
    row.push({ date: new Date(year, month, day), outside: false });
    if (row.length === 7) { rows.push(row); row = []; }
  }

  if (row.length > 0) {
    let nextDay = 1;
    while (row.length < 7) {
      row.push({ date: new Date(year, month + 1, nextDay++), outside: true });
    }
    rows.push(row);
  }
  return rows;
}

// ── Totals helpers ──────────────────────────────────────────────────────────

function _weekTotals(weekDays, actsByDate) {
  let dist = 0, dur = 0, count = 0;
  for (const wd of weekDays) {
    for (const a of (actsByDate[_dk(wd.date || wd)] || [])) {
      count++; dist += a.distance_km || 0; dur += a.temps_min || 0;
    }
  }
  return { count, dist, dur };
}

function _periodTotals(activities, startDate, endDate, typeFilter) {
  let filtered = activities.filter(a => {
    const d = new Date(a.date);
    return d >= startDate && d <= endDate;
  });
  if (typeFilter && typeFilter !== 'all') {
    filtered = filtered.filter(a =>
      (a.session_type || '').toLowerCase().includes(typeFilter.toLowerCase())
    );
  }
  let dist = 0, dur = 0;
  for (const a of filtered) { dist += a.distance_km || 0; dur += a.temps_min || 0; }
  return { count: filtered.length, dist, dur };
}

// ── Activity line (no emoji) ────────────────────────────────────────────────

function _activityLine(a) {
  const color = _typeColor(a.session_type);
  const dist = a.distance_km != null ? `${fmt(a.distance_km, 1)} km` : '';
  const dur  = _fmtDurationShort(a.temps_min);
  const name = a.nom || a.session_type || 'Activité';
  const label = dist ? `${name} - ${dist}` : name;

  return el('div', { className: 'cg-act-line', style: { borderLeftColor: color } },
    el('span', { className: 'cg-act-label' }, label),
    dur ? el('span', { className: 'cg-act-dur' }, dur) : null,
  );
}

function _activityCardWeek(a) {
  const color = _typeColor(a.session_type);
  const name = a.nom || a.session_type || 'Activité';

  const rows = [];
  if (a.distance_km != null) rows.push(['Distance', `${fmt(a.distance_km, 1)} km`]);
  if (a.temps_min != null) rows.push(['Durée', _fmtDurationShort(a.temps_min)]);
  if (a.pace_display) rows.push(['Allure', `${a.pace_display} /km`]);
  if (a.fc_bpm || a['Fréquence cardiaque (bpm)']) rows.push(['FC moy.', `${fmt(a.fc_bpm || a['Fréquence cardiaque (bpm)'], 0)} bpm`]);
  if (a.denivele_m || a['Dénivelé (m)']) rows.push(['D+', `${fmt(a.denivele_m || a['Dénivelé (m)'], 0)} m`]);
  if (a.trimp) rows.push(['TRIMP', fmt(a.trimp, 0)]);
  if (a.efficiency_factor) rows.push(['EF', fmt(a.efficiency_factor, 3)]);

  const metricsEl = el('div', { className: 'cg-week-act-metrics' });
  for (const [label, val] of rows) {
    metricsEl.appendChild(el('div', { className: 'cg-week-act-row' },
      el('span', {}, label),
      el('strong', {}, String(val)),
    ));
  }

  return el('div', { className: 'cg-week-act', style: { borderLeftColor: color } },
    el('div', { className: 'cg-week-act-name' }, name),
    metricsEl,
  );
}

// ── Planned workout display ──────────────────────────────────────────────────

function _plannedLabel(p) {
  const parts = [p.type];
  if (p.type === 'Renforcement musculaire') {
    const exCount = p.exercises?.length || 0;
    if (exCount) parts.push(`${exCount} exo`);
    if (p.duration_min) parts.push(`~${p.duration_min} min`);
  } else {
    if (p.target === 'duration' && p.duration_min) parts.push(`${p.duration_min} min`);
    else if (p.distance_km) parts.push(`${p.distance_km} km`);
    if (p.allure) parts.push(`@ ${p.allure}/km`);
  }
  return parts.join(' - ');
}

function _plannedLine(p, dayKey, hasActs, onEdit, onDelete) {
  const isOverdue = dayKey < _todayKey() && !hasActs;
  const color = isOverdue ? 'var(--danger)' : _typeColor(p.type);

  return el('div', {
    className: 'cg-act-line cg-act-planned',
    style: { borderLeftColor: color, borderLeftStyle: 'dashed' },
  },
    el('span', {
      className: 'cg-act-label',
      style: { fontStyle: 'italic', color: 'var(--ink-mid)', cursor: 'pointer' },
      onClick: (e) => { e.stopPropagation(); onEdit(); },
    }, _plannedLabel(p)),
    el('span', {
      className: 'cg-act-del',
      onClick: (e) => { e.stopPropagation(); onDelete(); },
    }, '\u00D7'),
  );
}

// ── Modal overlay ────────────────────────────────────────────────────────────

function _showModal(content, onClose) {
  const overlay = el('div', { className: 'cg-modal-overlay', onClick: onClose });
  const modal = el('div', { className: 'cg-modal', onClick: (e) => e.stopPropagation() });
  modal.appendChild(content);
  overlay.appendChild(modal);
  document.body.appendChild(overlay);
  return overlay;
}

// ── Plan form (create + edit) ────────────────────────────────────────────────

function _buildWorkoutForm(existing, onSave, onCancel, defaultDate) {
  const isEdit = !!existing;
  const data = existing || { date: defaultDate || _todayKey(), type: PLAN_TYPES[0], target: 'distance' };

  const dateInput = el('input', { type: 'date', className: 'ca-input', value: data.date });

  const typeSelect = el('select', { className: 'ca-select' });
  for (const t of PLAN_TYPES) {
    const opt = el('option', { value: t }, t);
    if (t === data.type) opt.selected = true;
    typeSelect.appendChild(opt);
  }

  // Target toggle: distance or duration
  const targetDistance = el('button', {
    className: `ca-radio-btn${data.target !== 'duration' ? ' active' : ''}`,
    onClick: () => { setTarget('distance'); },
  }, 'Distance (km)');
  const targetDuration = el('button', {
    className: `ca-radio-btn${data.target === 'duration' ? ' active' : ''}`,
    onClick: () => { setTarget('duration'); },
  }, 'Durée (min)');
  const targetGroup = el('div', { className: 'ca-radio-group' }, targetDistance, targetDuration);

  let currentTarget = data.target || 'distance';

  const distInput = el('input', {
    type: 'number', className: 'ca-input', placeholder: 'km',
    step: '0.1', min: '0', style: { width: '90px' },
  });
  if (data.distance_km) distInput.value = data.distance_km;

  const durInput = el('input', {
    type: 'number', className: 'ca-input', placeholder: 'min',
    step: '1', min: '0', style: { width: '90px' },
  });
  if (data.duration_min) durInput.value = data.duration_min;

  const distRow = el('div', { className: 'ca-plan-row', style: { marginTop: '8px' } },
    el('label', { className: 'ca-plan-label' }, 'Distance'), distInput,
  );
  const durRow = el('div', { className: 'ca-plan-row', style: { marginTop: '8px' } },
    el('label', { className: 'ca-plan-label' }, 'Durée'), durInput,
  );

  function setTarget(t) {
    currentTarget = t;
    targetDistance.className = `ca-radio-btn${t === 'distance' ? ' active' : ''}`;
    targetDuration.className = `ca-radio-btn${t === 'duration' ? ' active' : ''}`;
    distRow.style.display = t === 'distance' ? 'flex' : 'none';
    durRow.style.display = t === 'duration' ? 'flex' : 'none';
  }
  setTarget(currentTarget);

  const allureInput = el('input', {
    type: 'text', className: 'ca-input', placeholder: '5:30',
    style: { width: '80px' },
  });
  if (data.allure) allureInput.value = data.allure;

  // Fractionné fields
  const repsInput = el('input', {
    type: 'text', className: 'ca-input', placeholder: '8x400m',
    style: { width: '120px' },
  });
  if (data.reps) repsInput.value = data.reps;

  const allureEffort = el('input', {
    type: 'text', className: 'ca-input', placeholder: 'Effort',
    style: { width: '80px' },
  });
  if (data.allure_effort) allureEffort.value = data.allure_effort;

  const recovSelect = el('select', { className: 'ca-select', style: { minWidth: '70px' } });
  for (const r of RECOVERY_OPTIONS) {
    const opt = el('option', { value: r }, r);
    if (r === data.recovery) opt.selected = true;
    recovSelect.appendChild(opt);
  }

  const fracFields = el('div', {
    style: { display: (data.type || '').toLowerCase().includes('fractionné') ? 'block' : 'none' },
  },
    el('div', { className: 'ca-plan-row', style: { marginTop: '8px' } },
      el('label', { className: 'ca-plan-label' }, 'Répét.'), repsInput,
      el('label', { className: 'ca-plan-label', style: { marginLeft: '8px' } }, 'Allure'), allureEffort,
      el('label', { className: 'ca-plan-label', style: { marginLeft: '8px' } }, 'Récup'), recovSelect,
    ),
  );

  // ── Renforcement musculaire: exercises builder ──
  const exercisesList = [];
  const exercisesContainer = el('div', { className: 'ca-exercises-list' });

  function _addExerciseRow(ex = {}) {
    const idx = exercisesList.length;
    const nameIn = el('input', { type: 'text', className: 'ca-input', placeholder: 'Exercice', style: { flex: '1', minWidth: '120px' } });
    if (ex.name) nameIn.value = ex.name;
    const setsIn = el('input', { type: 'number', className: 'ca-input', placeholder: 'Séries', min: '1', style: { width: '55px' } });
    if (ex.sets) setsIn.value = ex.sets;
    const repsIn = el('input', { type: 'text', className: 'ca-input', placeholder: 'Reps/durée', style: { width: '75px' } });
    if (ex.reps) repsIn.value = ex.reps;
    const weightIn = el('input', { type: 'text', className: 'ca-input', placeholder: 'Charge', style: { width: '70px' } });
    if (ex.weight) weightIn.value = ex.weight;
    const restIn = el('input', { type: 'text', className: 'ca-input', placeholder: 'Repos', style: { width: '60px' } });
    if (ex.rest) restIn.value = ex.rest;

    const removeBtn = el('button', {
      className: 'cg-popup-del',
      style: { fontSize: '14px', cursor: 'pointer', padding: '2px 6px' },
      onClick: () => { row.remove(); exercisesList.splice(exercisesList.indexOf(entry), 1); },
    }, '\u00D7');

    const row = el('div', { className: 'ca-plan-row', style: { marginTop: '4px', flexWrap: 'wrap', gap: '4px', alignItems: 'center' } },
      nameIn, setsIn, repsIn, weightIn, restIn, removeBtn,
    );

    const entry = { nameIn, setsIn, repsIn, weightIn, restIn, row };
    exercisesList.push(entry);
    exercisesContainer.appendChild(row);
  }

  const addExBtn = el('button', {
    className: 'ca-btn',
    style: { fontSize: '11px', marginTop: '6px' },
    onClick: () => _addExerciseRow(),
  }, '+ Ajouter un exercice');

  // Header row for exercises
  const exHeader = el('div', { className: 'ca-plan-row', style: { gap: '4px', fontSize: '10px', color: 'var(--ink-mid)', fontWeight: '600' } },
    el('span', { style: { flex: '1', minWidth: '120px' } }, 'Exercice'),
    el('span', { style: { width: '55px' } }, 'Séries'),
    el('span', { style: { width: '75px' } }, 'Reps'),
    el('span', { style: { width: '70px' } }, 'Charge'),
    el('span', { style: { width: '60px' } }, 'Repos'),
    el('span', { style: { width: '26px' } }),
  );

  const strengthDurInput = el('input', {
    type: 'number', className: 'ca-input', placeholder: 'min',
    step: '1', min: '0', style: { width: '90px' },
  });
  if (data.type === 'Renforcement musculaire' && data.duration_min) strengthDurInput.value = data.duration_min;

  const strengthFields = el('div', {
    style: { display: (data.type === 'Renforcement musculaire') ? 'block' : 'none' },
  },
    el('div', { className: 'ca-plan-row', style: { marginTop: '8px' } },
      el('label', { className: 'ca-plan-label' }, 'Durée estimée (min)'), strengthDurInput,
    ),
    el('div', { style: { marginTop: '10px' } },
      el('label', { className: 'ca-plan-label', style: { display: 'block', marginBottom: '4px' } }, 'Exercices'),
      exHeader,
      exercisesContainer,
      addExBtn,
    ),
  );

  // Pre-populate exercises from existing data
  if (data.exercises?.length) {
    for (const ex of data.exercises) _addExerciseRow(ex);
  }

  // Cardio fields wrapper (to hide when renfo)
  const cardioFields = el('div', {},
    el('div', { style: { marginTop: '12px' } },
      el('label', { className: 'ca-plan-label', style: { marginBottom: '4px', display: 'block' } }, 'Objectif'),
      targetGroup,
    ),
    distRow,
    durRow,
    el('div', { className: 'ca-plan-row', style: { marginTop: '8px' } },
      el('label', { className: 'ca-plan-label' }, 'Allure'), allureInput,
    ),
    fracFields,
  );

  function _isRenfo(type) { return type === 'Renforcement musculaire'; }
  function _isFrac(type) { return type.toLowerCase().includes('fractionné'); }

  function _updateFieldVisibility() {
    const t = typeSelect.value;
    if (_isRenfo(t)) {
      cardioFields.style.display = 'none';
      strengthFields.style.display = 'block';
    } else {
      cardioFields.style.display = 'block';
      strengthFields.style.display = 'none';
      fracFields.style.display = _isFrac(t) ? 'block' : 'none';
    }
  }

  typeSelect.addEventListener('change', _updateFieldVisibility);
  _updateFieldVisibility();

  const notesInput = el('textarea', {
    className: 'ca-input', placeholder: 'Notes...', rows: '2',
    style: { width: '100%', resize: 'vertical' },
  });
  if (data.notes) notesInput.value = data.notes;

  const msgEl = el('div', { className: 'ca-auth-error', style: { display: 'none', marginTop: '8px' } });

  const saveBtn = el('button', {
    className: 'ca-btn accent',
    onClick: async () => {
      if (!dateInput.value) return;
      msgEl.style.display = 'none';
      saveBtn.disabled = true;
      saveBtn.textContent = 'Enregistrement...';
      try {
        const isRenfo = _isRenfo(typeSelect.value);
        const payload = {
          date: dateInput.value,
          type: typeSelect.value,
          target: isRenfo ? 'duration' : currentTarget,
          distance_km: !isRenfo && currentTarget === 'distance' && distInput.value ? parseFloat(distInput.value) : null,
          duration_min: isRenfo
            ? (strengthDurInput.value ? parseFloat(strengthDurInput.value) : null)
            : (currentTarget === 'duration' && durInput.value ? parseFloat(durInput.value) : null),
          allure: !isRenfo && allureInput.value ? allureInput.value : null,
          reps: !isRenfo && repsInput.value ? repsInput.value : null,
          allure_effort: !isRenfo && allureEffort.value ? allureEffort.value : null,
          recovery: !isRenfo ? recovSelect.value : null,
          exercises: isRenfo ? exercisesList.map(e => ({
            name: e.nameIn.value || 'Exercice',
            sets: e.setsIn.value ? parseInt(e.setsIn.value) : null,
            reps: e.repsIn.value || null,
            weight: e.weightIn.value || null,
            rest: e.restIn.value || null,
          })).filter(e => e.name) : null,
          notes: notesInput.value || null,
        };
        if (isEdit) {
          await api.updatePlanned(existing.id, payload);
        } else {
          await api.createPlanned(payload);
        }
        await _loadPlannedFromApi();
        onSave();
      } catch (e) {
        msgEl.textContent = e.message;
        msgEl.style.color = 'var(--danger)';
        msgEl.style.display = '';
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = isEdit ? 'Modifier' : 'Enregistrer';
      }
    },
  }, isEdit ? 'Modifier' : 'Enregistrer');

  const cancelBtn = el('button', { className: 'ca-btn', onClick: onCancel }, 'Annuler');

  const form = el('div', { className: 'ca-plan-form' },
    el('div', { className: 'cg-modal-title' }, isEdit ? 'Modifier la séance' : 'Planifier une séance'),
    el('div', { className: 'ca-plan-row' },
      el('label', { className: 'ca-plan-label' }, 'Date'), dateInput,
      el('label', { className: 'ca-plan-label', style: { marginLeft: '8px' } }, 'Type'), typeSelect,
    ),
    cardioFields,
    strengthFields,
    el('div', { style: { marginTop: '8px' } }, notesInput),
    msgEl,
    el('div', { style: { marginTop: '12px', display: 'flex', gap: '8px' } }, saveBtn, cancelBtn),
  );

  return form;
}

// ── Feedback in popup ───────────────────────────────────────────────────────

async function _loadFeedbackInPopup(actId, container) {
  try {
    const res = await api.feedback(actId);
    const fb = res?.feedback;
    _renderFeedbackInPopup(actId, fb, container);
  } catch {
    _renderFeedbackInPopup(actId, null, container);
  }
}

function _renderFeedbackInPopup(actId, fb, container) {
  container.innerHTML = '';

  if (fb) {
    // Display existing feedback with edit option
    const diffDots = '●'.repeat(fb.difficulty) + '○'.repeat(10 - fb.difficulty);
    container.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--ink-mid)', marginBottom: '2px' } },
      `Difficulté : ${diffDots} ${fb.difficulty}/10`,
    ));
    if (fb.sensations) {
      container.appendChild(el('div', { style: { fontSize: '11px', color: 'var(--ink-mid)', fontStyle: 'italic' } },
        fb.sensations,
      ));
    }
    const editBtn = el('button', {
      className: 'cg-popup-edit',
      style: { marginTop: '4px', fontSize: '10px' },
      onClick: (e) => { e.stopPropagation(); _showFeedbackForm(actId, fb, container); },
    }, 'Modifier ressentis');
    container.appendChild(editBtn);
  } else {
    const addBtn = el('button', {
      className: 'cg-popup-edit',
      style: { fontSize: '10px' },
      onClick: (e) => { e.stopPropagation(); _showFeedbackForm(actId, null, container); },
    }, '+ Ajouter ressentis');
    container.appendChild(addBtn);
  }
}

function _showFeedbackForm(actId, existing, container) {
  container.innerHTML = '';

  const diffVal = existing?.difficulty || 5;
  const range = el('input', {
    type: 'range', min: '1', max: '10', value: diffVal,
    style: { width: '100%' },
  });
  const label = el('span', { style: { fontSize: '11px', fontWeight: '600' } }, `${diffVal}/10`);
  range.addEventListener('input', () => { label.textContent = `${range.value}/10`; });

  const textarea = el('textarea', {
    placeholder: 'Sensations...',
    rows: '2',
    style: { width: '100%', fontSize: '11px', resize: 'vertical', marginTop: '4px', padding: '4px', borderRadius: '4px', border: '1px solid var(--border)' },
  });
  if (existing?.sensations) textarea.value = existing.sensations;

  const msg = el('span', { style: { fontSize: '10px', display: 'none' } });

  const saveBtn = el('button', {
    className: 'ca-btn accent',
    style: { fontSize: '11px', padding: '3px 10px', marginTop: '4px' },
    onClick: async (e) => {
      e.stopPropagation();
      saveBtn.disabled = true;
      try {
        await api.saveFeedback(actId, {
          sensations: textarea.value || null,
          difficulty: parseInt(range.value),
        });
        const res = await api.feedback(actId);
        _renderFeedbackInPopup(actId, res?.feedback, container);
      } catch (err) {
        msg.textContent = err.message;
        msg.style.color = 'var(--danger)';
        msg.style.display = '';
        saveBtn.disabled = false;
      }
    },
  }, 'Enregistrer');

  container.appendChild(el('div', { style: { display: 'flex', alignItems: 'center', gap: '6px' } },
    el('span', { style: { fontSize: '11px', whiteSpace: 'nowrap' } }, 'Difficulté'),
    range,
    label,
  ));
  container.appendChild(textarea);
  container.appendChild(el('div', { style: { display: 'flex', alignItems: 'center', gap: '6px' } }, saveBtn, msg));
}

// ── Exercises display in popup ──────────────────────────────────────────────

function _buildExercisesPopup(exercises) {
  if (!exercises?.length) return [];
  const rows = exercises.map(ex => {
    const parts = [];
    if (ex.sets) parts.push(`${ex.sets}x`);
    if (ex.reps) parts.push(ex.reps);
    if (ex.weight) parts.push(`@ ${ex.weight}`);
    if (ex.rest) parts.push(`repos ${ex.rest}`);
    return el('div', { style: { fontSize: '11px', color: 'var(--ink-mid)', padding: '1px 0', display: 'flex', gap: '6px' } },
      el('span', { style: { fontWeight: '600', minWidth: '100px' } }, ex.name || '—'),
      el('span', {}, parts.join(' · ')),
    );
  });
  return [el('div', { style: { marginTop: '4px', borderTop: '1px solid var(--border)', paddingTop: '4px' } }, ...rows)];
}

// ── FIT generation zone ─────────────────────────────────────────────────────

function _buildFitZone(planned, container) {
  const descBtn = el('button', {
    className: 'ca-btn',
    style: { fontSize: '11px', padding: '3px 10px' },
    onClick: async (e) => {
      e.stopPropagation();
      descBtn.disabled = true;
      descBtn.textContent = 'Chargement...';
      try {
        const res = await api.describeWorkout({ workout_id: planned.id });
        _showDescriptionInZone(res.description, container, descBtn);
      } catch (err) {
        descBtn.textContent = 'Description';
        descBtn.disabled = false;
        alert('Erreur : ' + err.message);
      }
    },
  }, 'Description');

  const fitBtn = el('button', {
    className: 'ca-btn accent',
    style: { fontSize: '11px', padding: '3px 10px' },
    onClick: async (e) => {
      e.stopPropagation();
      fitBtn.disabled = true;
      fitBtn.textContent = 'Génération...';
      try {
        const res = await api.generateFit(planned.id);
        if (res.ok && res.download_url) {
          // Téléchargement direct
          const a = document.createElement('a');
          a.href = api.downloadFit(res.filename);
          a.download = res.filename;
          document.body.appendChild(a);
          a.click();
          a.remove();
          fitBtn.textContent = 'Téléchargé !';
          fitBtn.style.background = 'var(--success)';
          setTimeout(() => {
            fitBtn.textContent = 'Fichier .FIT';
            fitBtn.style.background = '';
            fitBtn.disabled = false;
          }, 2000);
        }
      } catch (err) {
        fitBtn.textContent = 'Fichier .FIT';
        fitBtn.disabled = false;
        alert('Erreur : ' + err.message);
      }
    },
  }, 'Fichier .FIT');

  container.innerHTML = '';
  container.appendChild(
    el('div', { style: { display: 'flex', gap: '6px', flexWrap: 'wrap' } },
      descBtn, fitBtn,
    )
  );
}

function _showDescriptionInZone(description, container, descBtn) {
  // Afficher la description dans la zone
  const descDiv = el('div', {
    style: {
      marginTop: '6px', fontSize: '11px', color: 'var(--ink)',
      background: 'var(--bg-alt, var(--bg))', padding: '8px',
      borderRadius: '6px', lineHeight: '1.5', whiteSpace: 'pre-wrap',
      maxHeight: '200px', overflowY: 'auto',
    },
  }, description);

  const closeBtn = el('button', {
    className: 'ca-btn',
    style: { fontSize: '10px', padding: '2px 8px', marginTop: '4px' },
    onClick: (e) => {
      e.stopPropagation();
      descDiv.remove();
      closeBtn.remove();
      descBtn.textContent = 'Description';
      descBtn.disabled = false;
    },
  }, 'Fermer');

  container.appendChild(descDiv);
  container.appendChild(closeBtn);
  descBtn.textContent = 'Description';
}

// ── Text-to-FIT modal ──────────────────────────────────────────────────────

function _openTextToFitModal() {
  const textarea = el('textarea', {
    className: 'ca-input',
    placeholder: 'Décrivez votre séance...\nEx: 10x400m en 1:30 avec 1min de récup\nEx: Sortie longue 20km à 5:30/km\nEx: 45min en endurance fondamentale',
    rows: '5',
    style: { width: '100%', resize: 'vertical', fontFamily: 'inherit' },
  });

  const msgEl = el('div', { style: { display: 'none', fontSize: '12px', marginTop: '8px' } });
  const resultZone = el('div', { style: { marginTop: '8px' } });

  const generateBtn = el('button', {
    className: 'ca-btn accent',
    onClick: async () => {
      const text = textarea.value.trim();
      if (!text) return;
      generateBtn.disabled = true;
      generateBtn.textContent = 'Génération en cours...';
      msgEl.style.display = 'none';
      resultZone.innerHTML = '';

      try {
        const res = await api.textToFit(text);
        if (res.ok) {
          // Afficher la structure générée
          const structured = res.structured;
          if (structured?.description) {
            resultZone.appendChild(el('div', {
              style: {
                fontSize: '12px', background: 'var(--bg-alt, var(--bg))',
                padding: '8px', borderRadius: '6px', marginBottom: '8px',
                lineHeight: '1.5', whiteSpace: 'pre-wrap',
              },
            }, structured.description));
          }

          // Afficher les steps
          if (structured?.steps) {
            const stepsText = structured.steps.map((s, i) => {
              const parts = [`${i + 1}. ${s.type}`];
              if (s.km) parts.push(`${s.km}km`);
              if (s.seconds) parts.push(`${Math.round(s.seconds / 60)}min`);
              if (s.pace_fast) parts.push(`${s.pace_fast}-${s.pace_slow}/km`);
              if (s.hr_low) parts.push(`${s.hr_low}-${s.hr_high}bpm`);
              if (s.count) parts.push(`x${s.count}`);
              parts.push(`[${s.intensity || 'active'}]`);
              return parts.join(' ');
            }).join('\n');
            resultZone.appendChild(el('pre', {
              style: { fontSize: '11px', color: 'var(--ink-mid)', margin: '0 0 8px 0', whiteSpace: 'pre-wrap' },
            }, stepsText));
          }

          // Bouton téléchargement
          const dlBtn = el('button', {
            className: 'ca-btn accent',
            style: { fontSize: '12px' },
            onClick: () => {
              const a = document.createElement('a');
              a.href = api.downloadFit(res.filename);
              a.download = res.filename;
              document.body.appendChild(a);
              a.click();
              a.remove();
            },
          }, `Télécharger ${res.filename}`);
          resultZone.appendChild(dlBtn);

          msgEl.textContent = 'Fichier .FIT généré avec succès !';
          msgEl.style.color = 'var(--success)';
          msgEl.style.display = '';
        }
      } catch (err) {
        msgEl.textContent = 'Erreur : ' + err.message;
        msgEl.style.color = 'var(--danger)';
        msgEl.style.display = '';
      } finally {
        generateBtn.disabled = false;
        generateBtn.textContent = 'Générer le fichier .FIT';
      }
    },
  }, 'Générer le fichier .FIT');

  let overlay;
  const cancelBtn = el('button', { className: 'ca-btn', onClick: () => overlay.remove() }, 'Fermer');

  const content = el('div', { className: 'ca-plan-form' },
    el('div', { className: 'cg-modal-title' }, 'Créer un workout Garmin'),
    el('div', { style: { fontSize: '12px', color: 'var(--ink-mid)', marginBottom: '8px' } },
      'Décrivez votre séance en texte libre. Un LLM la convertira en fichier .FIT pour votre montre Garmin.',
    ),
    textarea,
    msgEl,
    resultZone,
    el('div', { style: { marginTop: '12px', display: 'flex', gap: '8px' } }, generateBtn, cancelBtn),
  );

  overlay = _showModal(content, () => overlay.remove());
}

// ── Activity popup ──────────────────────────────────────────────────────────

function _showPopup(cell, acts, planned, dayKey, onChanged) {
  document.querySelectorAll('.cg-popup').forEach(p => p.remove());

  const popup = el('div', { className: 'cg-popup', onClick: (e) => e.stopPropagation() });

  for (const a of acts) {
    const actBlock = el('div', { className: 'cg-popup-act' },
      el('div', { className: 'cg-popup-name' }, a.nom || 'Activité'),
      el('div', { className: 'cg-popup-meta' },
        [a.session_type, a.distance_km != null ? `${fmt(a.distance_km, 1)} km` : null,
         a.pace_display ? `${a.pace_display} /km` : null,
         a.fc_bpm ? `${fmt(a.fc_bpm, 0)} bpm` : null,
         a.trimp ? `TRIMP ${fmt(a.trimp, 0)}` : null,
        ].filter(Boolean).join(' · '),
      ),
    );

    // Feedback inline zone
    const fbZone = el('div', { className: 'cg-feedback-zone', style: { marginTop: '6px' } });
    _loadFeedbackInPopup(a.id, fbZone);
    actBlock.appendChild(fbZone);

    popup.appendChild(actBlock);
  }

  for (const p of planned) {
    const isOverdue = dayKey < _todayKey() && !acts.length;
    const plannedBlock = el('div', { className: 'cg-popup-act' },
      el('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
        el('span', { className: 'cg-popup-name', style: { fontStyle: 'italic' } }, `[Planifié] ${p.type}`),
        el('div', { style: { display: 'flex', gap: '4px' } },
          el('button', {
            className: 'cg-popup-edit',
            onClick: (e) => { e.stopPropagation(); _openEditModal(p, onChanged); },
          }, 'Modifier'),
          el('button', {
            className: 'cg-popup-del',
            onClick: async (e) => {
              e.stopPropagation();
              await api.deletePlanned(p.id);
              await _loadPlannedFromApi();
              onChanged();
            },
          }, '\u00D7'),
        ),
      ),
      el('div', { className: 'cg-popup-meta', style: isOverdue ? { color: 'var(--danger)' } : {} },
        [
          p.target === 'duration' && p.duration_min ? `${p.duration_min} min` : null,
          p.distance_km ? `${p.distance_km} km` : null,
          p.allure ? `${p.allure} /km` : null,
          p.reps || null,
          isOverdue ? 'Non réalisé' : null,
        ].filter(Boolean).join(' · '),
      ),
      ..._buildExercisesPopup(p.exercises),
      p.notes ? el('div', { className: 'cg-popup-notes' }, p.notes) : null,
    );

    // ── Description + FIT generation zone ──
    const fitZone = el('div', { className: 'cg-fit-zone', style: { marginTop: '8px', borderTop: '1px solid var(--border)', paddingTop: '8px' } });
    _buildFitZone(p, fitZone);
    plannedBlock.appendChild(fitZone);

    popup.appendChild(plannedBlock);
  }

  cell.style.position = 'relative';
  cell.appendChild(popup);

  requestAnimationFrame(() => {
    const rect = popup.getBoundingClientRect();
    if (rect.right > window.innerWidth - 8) { popup.style.left = 'auto'; popup.style.right = '0'; }
    if (rect.bottom > window.innerHeight - 8) { popup.style.top = 'auto'; popup.style.bottom = '100%'; }
  });

  const close = () => { popup.remove(); document.removeEventListener('click', close); };
  setTimeout(() => document.addEventListener('click', close), 0);
}

// ── Edit modal ───────────────────────────────────────────────────────────────

function _openEditModal(workout, onChanged) {
  let overlay;
  const form = _buildWorkoutForm(workout, () => {
    overlay.remove();
    onChanged();
  }, () => overlay.remove());
  overlay = _showModal(form, () => overlay.remove());
}

function _openCreateModal(defaultDate, onChanged) {
  let overlay;
  const form = _buildWorkoutForm(null, () => {
    overlay.remove();
    onChanged();
  }, () => overlay.remove(), defaultDate);
  overlay = _showModal(form, () => overlay.remove());
}

// ── Day cell builder (shared by month + week views) ─────────────────────────

function _buildDayCell(wd, actsByDate, plannedByDate, today, rerender, outside) {
  const key = _dk(wd);
  const dow = wd.getDay();
  const isWeekend = dow === 0 || dow === 6;
  const isToday = key === today;
  const dayActs = actsByDate[key] || [];
  const dayPlanned = plannedByDate[key] || [];

  const classes = ['cg-cell'];
  if (outside) classes.push('cg-cell-outside');
  if (isWeekend) classes.push('cg-cell-weekend');

  const cell = el('div', { className: classes.join(' ') });

  const dayHeader = el('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
    el('div', { className: `cg-day-num${isToday ? ' cg-day-today' : ''}` }, String(wd.getDate())),
    el('button', {
      className: 'cg-add-btn',
      title: 'Planifier',
      onClick: (e) => { e.stopPropagation(); _openCreateModal(key, rerender); },
    }, '+'),
  );
  cell.appendChild(dayHeader);

  const maxShow = 3;
  const items = [];
  for (const a of dayActs) items.push(_activityLine(a));
  for (const p of dayPlanned) items.push(_plannedLine(p, key, dayActs.length > 0,
    () => _openEditModal(p, rerender),
    async () => { await api.deletePlanned(p.id); await _loadPlannedFromApi(); rerender(); },
  ));

  for (let j = 0; j < Math.min(items.length, maxShow); j++) cell.appendChild(items[j]);
  if (items.length > maxShow) cell.appendChild(el('div', { className: 'cg-act-overflow' }, `+${items.length - maxShow} autres`));

  if (dayActs.length || dayPlanned.length) {
    cell.style.cursor = 'pointer';
    cell.addEventListener('click', (e) => { e.stopPropagation(); _showPopup(cell, dayActs, dayPlanned, key, rerender); });
  }
  return cell;
}

// ══════════════════════════════════════════════════════════════════════════════
// VIEW: MONTH
// ══════════════════════════════════════════════════════════════════════════════

function _renderMonth(calArea, activities, viewYear, viewMonth, rerender) {
  calArea.innerHTML = '';
  const actsByDate = _indexByDate(activities);
  const plannedByDate = _indexPlannedByDate();
  const rows = _weekRows(viewYear, viewMonth);
  const today = _todayKey();

  const grid = el('div', { className: 'cg-grid' });

  for (const name of DAY_NAMES) grid.appendChild(el('div', { className: 'cg-col-header' }, name));
  grid.appendChild(el('div', { className: 'cg-col-header cg-col-totals-header' }, 'Totaux hebdo'));

  for (const week of rows) {
    for (let i = 0; i < 7; i++) {
      grid.appendChild(_buildDayCell(week[i].date, actsByDate, plannedByDate, today, rerender, week[i].outside));
    }
    const wt = _weekTotals(week.map(w => w.date), actsByDate);
    const totCell = el('div', { className: 'cg-cell cg-cell-totals' });
    if (wt.count > 0) {
      totCell.appendChild(el('div', { className: 'cg-tot-row' },
        el('span', { className: 'cg-tot-label' }, 'DISTANCE'),
        el('span', { className: 'cg-tot-value' }, `${fmt(wt.dist, 2)} km`),
      ));
      totCell.appendChild(el('div', { className: 'cg-tot-row' },
        el('span', { className: 'cg-tot-label' }, 'DURÉE'),
        el('span', { className: 'cg-tot-value' }, _fmtDuration(wt.dur)),
      ));
    }
    grid.appendChild(totCell);
  }
  calArea.appendChild(grid);
}

// ══════════════════════════════════════════════════════════════════════════════
// VIEW: WEEK
// ══════════════════════════════════════════════════════════════════════════════

function _renderWeek(calArea, activities, monday, rerender) {
  calArea.innerHTML = '';
  const actsByDate = _indexByDate(activities);
  const plannedByDate = _indexPlannedByDate();
  const today = _todayKey();

  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    days.push(d);
  }

  const grid = el('div', { className: 'cg-grid cg-grid-week' });

  for (let i = 0; i < 7; i++) {
    const d = days[i];
    const label = `${DAY_NAMES[i]} ${d.getDate()} ${MONTH_SHORT[d.getMonth()]}`;
    grid.appendChild(el('div', { className: 'cg-col-header' }, label));
  }
  grid.appendChild(el('div', { className: 'cg-col-header cg-col-totals-header' }, 'Totaux'));

  for (let i = 0; i < 7; i++) {
    const d = days[i];
    const key = _dk(d);
    const dow = d.getDay();
    const isWeekend = dow === 0 || dow === 6;
    const isToday = key === today;
    const dayActs = actsByDate[key] || [];
    const dayPlanned = plannedByDate[key] || [];

    const classes = ['cg-cell', 'cg-cell-week'];
    if (isWeekend) classes.push('cg-cell-weekend');

    const cell = el('div', { className: classes.join(' ') });

    const dayHeader = el('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
      el('div', { className: `cg-day-num${isToday ? ' cg-day-today' : ''}` }, String(d.getDate())),
      el('button', {
        className: 'cg-add-btn',
        title: 'Planifier',
        onClick: (e) => { e.stopPropagation(); _openCreateModal(key, rerender); },
      }, '+'),
    );
    cell.appendChild(dayHeader);

    for (const a of dayActs) cell.appendChild(_activityCardWeek(a));
    for (const p of dayPlanned) cell.appendChild(_plannedLine(p, key, dayActs.length > 0,
      () => _openEditModal(p, rerender),
      async () => { await api.deletePlanned(p.id); await _loadPlannedFromApi(); rerender(); },
    ));

    if (dayActs.length || dayPlanned.length) {
      cell.style.cursor = 'pointer';
      cell.addEventListener('click', (e) => { e.stopPropagation(); _showPopup(cell, dayActs, dayPlanned, key, rerender); });
    }
    grid.appendChild(cell);
  }

  const wt = _weekTotals(days, actsByDate);
  const totCell = el('div', { className: 'cg-cell cg-cell-totals' });
  if (wt.count > 0) {
    totCell.appendChild(el('div', { className: 'cg-tot-row' },
      el('span', { className: 'cg-tot-label' }, 'ACTIVITÉS'), el('span', { className: 'cg-tot-value' }, `${wt.count}`),
    ));
    totCell.appendChild(el('div', { className: 'cg-tot-row' },
      el('span', { className: 'cg-tot-label' }, 'DISTANCE'), el('span', { className: 'cg-tot-value' }, `${fmt(wt.dist, 2)} km`),
    ));
    totCell.appendChild(el('div', { className: 'cg-tot-row' },
      el('span', { className: 'cg-tot-label' }, 'DURÉE'), el('span', { className: 'cg-tot-value' }, _fmtDuration(wt.dur)),
    ));
  }
  grid.appendChild(totCell);

  calArea.appendChild(grid);
}

// ══════════════════════════════════════════════════════════════════════════════
// VIEW: YEAR
// ══════════════════════════════════════════════════════════════════════════════

function _renderYear(calArea, activities, viewYear) {
  calArea.innerHTML = '';
  const actsByDate = _indexByDate(activities);
  const today = _todayKey();

  const yearGrid = el('div', { className: 'cg-year-grid' });

  for (let month = 0; month < 12; month++) {
    const monthEl = el('div', { className: 'cg-year-month' });
    monthEl.appendChild(el('div', { className: 'cg-year-month-title' }, MONTH_NAMES[month]));

    const hdr = el('div', { className: 'cg-mini-grid' });
    for (const n of ['L','M','M','J','V','S','D']) {
      hdr.appendChild(el('div', { className: 'cg-mini-hdr' }, n));
    }

    const first = new Date(viewYear, month, 1);
    const last  = new Date(viewYear, month + 1, 0);
    let startDow = first.getDay();
    startDow = startDow === 0 ? 6 : startDow - 1;

    for (let i = 0; i < startDow; i++) {
      hdr.appendChild(el('div', { className: 'cg-mini-cell cg-mini-empty' }));
    }

    for (let day = 1; day <= last.getDate(); day++) {
      const d = new Date(viewYear, month, day);
      const key = _dk(d);
      const acts = actsByDate[key] || [];
      const isToday = key === today;

      const classes = ['cg-mini-cell'];
      if (isToday) classes.push('cg-mini-today');

      const dayEl = el('div', { className: classes.join(' ') });

      if (acts.length > 0) {
        const color = _typeColor(acts[0].session_type);
        dayEl.appendChild(el('div', { className: 'cg-mini-dot', style: { background: color } }));
        dayEl.title = acts.map(a => `${a.nom || a.session_type} – ${fmt(a.distance_km, 1)} km`).join('\n');
      }
      dayEl.appendChild(el('span', { className: 'cg-mini-num' }, String(day)));

      hdr.appendChild(dayEl);
    }

    monthEl.appendChild(hdr);

    const mt = _periodTotals(activities, new Date(viewYear, month, 1), new Date(viewYear, month + 1, 0), 'all');
    if (mt.count > 0) {
      monthEl.appendChild(el('div', { className: 'cg-year-month-summary' },
        `${mt.count} act. · ${fmt(mt.dist, 1)} km · ${_fmtDuration(mt.dur)}`,
      ));
    }

    yearGrid.appendChild(monthEl);
  }

  calArea.appendChild(yearGrid);
}

// ══════════════════════════════════════════════════════════════════════════════
// MAIN RENDER
// ══════════════════════════════════════════════════════════════════════════════

export async function renderCalendrier(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  try {
    // Load activities + planned workouts in parallel
    const [activitiesRes, typesRes] = await Promise.all([
      api.activities({ limit: 1000 }),
      api.activityTypes().catch(() => ({ types: [] })),
    ]);
    await _migrateLocalStorage();
    await _loadPlannedFromApi();

    const activities = activitiesRes.activities || [];
    const types = typesRes.types || [];

    container.innerHTML = '';

    const now = new Date();
    let viewYear  = now.getFullYear();
    let viewMonth = now.getMonth();
    let viewMonday = _mondayOf(now);
    let currentView = 'month';
    let typeFilter = 'all';

    // ── Navigation label ─────────────────────────────────────────────────
    const monthLabel = el('span', { className: 'cg-month-label' });

    function _updateLabel() {
      if (currentView === 'month') {
        monthLabel.textContent = `${MONTH_NAMES[viewMonth]} ${viewYear}`;
      } else if (currentView === 'week') {
        const sun = new Date(viewMonday);
        sun.setDate(sun.getDate() + 6);
        const ml = viewMonday.getDate();
        const sl = sun.getDate();
        const sameMonth = viewMonday.getMonth() === sun.getMonth();
        if (sameMonth) {
          monthLabel.textContent = `${ml} - ${sl} ${MONTH_NAMES[viewMonday.getMonth()]} ${viewMonday.getFullYear()}`;
        } else {
          monthLabel.textContent = `${ml} ${MONTH_SHORT[viewMonday.getMonth()]} - ${sl} ${MONTH_SHORT[sun.getMonth()]} ${sun.getFullYear()}`;
        }
      } else {
        monthLabel.textContent = `${viewYear}`;
      }
    }

    function _goPrev() {
      if (currentView === 'month') {
        viewMonth--; if (viewMonth < 0) { viewMonth = 11; viewYear--; }
      } else if (currentView === 'week') {
        viewMonday = new Date(viewMonday);
        viewMonday.setDate(viewMonday.getDate() - 7);
      } else {
        viewYear--;
      }
      _updateLabel(); rerender();
    }
    function _goNext() {
      if (currentView === 'month') {
        viewMonth++; if (viewMonth > 11) { viewMonth = 0; viewYear++; }
      } else if (currentView === 'week') {
        viewMonday = new Date(viewMonday);
        viewMonday.setDate(viewMonday.getDate() + 7);
      } else {
        viewYear++;
      }
      _updateLabel(); rerender();
    }
    function _goToday() {
      viewYear = now.getFullYear(); viewMonth = now.getMonth();
      viewMonday = _mondayOf(now);
      _updateLabel(); rerender();
    }

    // ── Control bar ──────────────────────────────────────────────────────
    const todayBtn = el('button', { className: 'ca-btn', onClick: _goToday }, "Aujourd'hui");
    const prevBtn  = el('button', { className: 'ca-btn', onClick: _goPrev }, '\u25C0');
    const nextBtn  = el('button', { className: 'ca-btn', onClick: _goNext }, '\u25B6');

    const viewGroup = el('div', { className: 'ca-radio-group' });
    const viewBtns = {};
    for (const [key, label] of [['week','Semaine'],['month','Mois'],['year','Année']]) {
      const btn = el('button', {
        className: `ca-radio-btn${key === currentView ? ' active' : ''}`,
        onClick: () => {
          currentView = key;
          for (const [k, b] of Object.entries(viewBtns)) b.className = `ca-radio-btn${k === key ? ' active' : ''}`;
          if (key === 'week') viewMonday = _mondayOf(new Date());
          if (key === 'month') { viewYear = viewMonday.getFullYear(); viewMonth = viewMonday.getMonth(); }
          _updateLabel(); rerender();
        },
      }, label);
      viewBtns[key] = btn;
      viewGroup.appendChild(btn);
    }

    const planBtn = el('button', {
      className: 'ca-btn accent',
      onClick: () => _openCreateModal(_todayKey(), rerender),
    }, '+ Planifier');

    const fitWorkoutBtn = el('button', {
      className: 'ca-btn',
      style: { borderColor: 'var(--accent)', color: 'var(--accent)' },
      onClick: () => _openTextToFitModal(),
    }, 'Workout Garmin');

    const controlBar = el('div', { className: 'cg-control-bar' },
      el('div', { className: 'cg-control-left' }, todayBtn, prevBtn, monthLabel, nextBtn),
      el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } }, fitWorkoutBtn, planBtn, viewGroup),
    );

    // ── Calendar area ────────────────────────────────────────────────────
    const calArea = el('div', { className: 'cg-cal-area' });

    // ── Footer ───────────────────────────────────────────────────────────
    const footerStats = el('span', { className: 'cg-footer-stats' });
    const footerLabel = el('span', { className: 'cg-footer-label' }, 'Totaux');
    const footerSelect = el('select', { className: 'ca-select', style: { minWidth: '160px' } });
    footerSelect.appendChild(el('option', { value: 'all' }, 'Toutes activités'));
    for (const t of types) footerSelect.appendChild(el('option', { value: t }, t));
    footerSelect.addEventListener('change', () => { typeFilter = footerSelect.value; updateFooter(); });

    function updateFooter() {
      let start, end, label;
      if (currentView === 'month') {
        start = new Date(viewYear, viewMonth, 1);
        end   = new Date(viewYear, viewMonth + 1, 0);
        label = 'Totaux mensuels';
      } else if (currentView === 'week') {
        start = new Date(viewMonday);
        end   = new Date(viewMonday); end.setDate(end.getDate() + 6);
        label = 'Totaux semaine';
      } else {
        start = new Date(viewYear, 0, 1);
        end   = new Date(viewYear, 11, 31);
        label = 'Totaux annuels';
      }
      footerLabel.textContent = label;
      const t = _periodTotals(activities, start, end, typeFilter);
      footerStats.innerHTML = '';
      footerStats.appendChild(el('span', {}, 'Activités: '));
      footerStats.appendChild(el('strong', {}, `${t.count}`));
      footerStats.appendChild(el('span', { style: { margin: '0 12px' } }, 'Distance: '));
      footerStats.appendChild(el('strong', {}, `${fmt(t.dist, 2)} km`));
      footerStats.appendChild(el('span', { style: { margin: '0 12px' } }, 'Durée: '));
      footerStats.appendChild(el('strong', {}, _fmtDuration(t.dur)));
    }

    const footer = el('div', { className: 'cg-footer' },
      el('div', { className: 'cg-footer-left' }, footerLabel, footerSelect),
      footerStats,
    );

    // ── Rerender ─────────────────────────────────────────────────────────
    function rerender() {
      if (currentView === 'month') {
        _renderMonth(calArea, activities, viewYear, viewMonth, rerender);
      } else if (currentView === 'week') {
        _renderWeek(calArea, activities, viewMonday, rerender);
      } else {
        _renderYear(calArea, activities, viewYear);
      }
      updateFooter();
    }

    // ── Assemble ─────────────────────────────────────────────────────────
    const wrapper = el('div', { className: 'cg-fullpage' });
    wrapper.appendChild(el('div', { className: 'cg-topbar' }, controlBar));
    wrapper.appendChild(calArea);
    wrapper.appendChild(footer);
    container.appendChild(wrapper);

    _updateLabel();
    rerender();

  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, err.message));
  }
}
