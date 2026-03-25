/**
 * app.js — Routeur et point d'entrée.
 */

import { api } from './api.js';
import { fmtDateShort } from './components.js';
import { renderOverview } from './sections/overview.js';
import { renderHistory } from './sections/history.js';
import { renderProfil } from './sections/profil.js';
import { renderProgression } from './sections/progression.js';
import { renderCharge } from './sections/charge.js';
import { renderAnalyse } from './sections/analyse.js';

// ── Sections ────────────────────────────────────────────────────────────────

const SECTIONS = {
  overview:    renderOverview,
  history:     renderHistory,
  profil:      renderProfil,
  progression: renderProgression,
  charge:      renderCharge,
  analyse:     renderAnalyse,
};

let _currentSection = 'overview';
let _syncPolling = null;

// ── Navigation ──────────────────────────────────────────────────────────────

function navigate(section) {
  if (!SECTIONS[section]) section = 'overview';
  _currentSection = section;

  // Update tabs
  document.querySelectorAll('.ca-nav-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.section === section);
  });

  // Update hash
  window.location.hash = section;

  // Render
  const container = document.getElementById('page-content');
  try {
    SECTIONS[section](container);
  } catch (err) {
    container.innerHTML = `<div class="ca-error">Erreur de rendu : ${err.message}</div>`;
  }
}

// ── Sync UI ─────────────────────────────────────────────────────────────────

function _fmtAgo(minutes) {
  if (minutes == null) return '—';
  if (minutes < 1)   return 'à l\'instant';
  if (minutes < 60)  return `il y a ${Math.round(minutes)} min`;
  const h = Math.floor(minutes / 60);
  if (h < 24) return `il y a ${h}h`;
  const d = Math.floor(h / 24);
  return `il y a ${d}j`;
}

function _updateSyncUI(syncData) {
  const el = document.getElementById('header-sync');
  const btn = document.getElementById('sync-btn');
  if (!el || !btn) return;

  if (syncData.sync_in_progress) {
    el.textContent = 'Synchronisation…';
    el.classList.add('syncing');
    btn.classList.add('spinning');
  } else {
    el.classList.remove('syncing');
    btn.classList.remove('spinning');

    if (syncData.last_error) {
      el.textContent = `Dernière tentative : ${_fmtAgo(syncData.last_sync_ago_minutes)}`;
    } else {
      el.textContent = `Mis à jour ${_fmtAgo(syncData.last_sync_ago_minutes)}`;
    }
  }
}

function _onSyncComplete(syncData) {
  const result = syncData.last_result || {};
  const stepsRun = result.steps_run || [];

  if (stepsRun.includes('strava') || stepsRun.includes('analysis')) {
    // Nouvelles activités ou analyse → rafraîchir la section active + header
    navigate(_currentSection);
    initHeader();
  } else if (stepsRun.includes('strava_gps') || stepsRun.includes('garmin') || stepsRun.includes('gps_analysis')) {
    // Nouvelles données GPS → rafraîchir seulement si on est dans Analyse
    if (_currentSection === 'analyse') {
      navigate('analyse');
    }
    initHeader();
  } else {
    // Rien de significatif → juste mettre à jour le timestamp
    initHeader();
  }
}

function _startSyncPolling() {
  if (_syncPolling) return;
  _syncPolling = setInterval(async () => {
    try {
      const st = await api.syncStatus();
      _updateSyncUI(st);
      if (!st.sync_in_progress) {
        _stopSyncPolling();
        _onSyncComplete(st);
      }
    } catch {
      // polling non-critical
    }
  }, 3000);
}

function _stopSyncPolling() {
  if (_syncPolling) {
    clearInterval(_syncPolling);
    _syncPolling = null;
  }
}

async function triggerSync() {
  const btn = document.getElementById('sync-btn');
  const el = document.getElementById('header-sync');
  if (btn) btn.classList.add('spinning');
  if (el) { el.textContent = 'Synchronisation…'; el.classList.add('syncing'); }

  try {
    await api.syncStart();
    _startSyncPolling();
  } catch {
    if (btn) btn.classList.remove('spinning');
    if (el) { el.textContent = 'Échec sync'; el.classList.remove('syncing'); }
  }
}

// ── Header ──────────────────────────────────────────────────────────────────

async function initHeader() {
  try {
    const status = await api.status();
    const dateEl = document.getElementById('header-date');
    const countEl = document.getElementById('header-count');

    if (status.last_activity) {
      dateEl.textContent = fmtDateShort(status.last_activity);
    }
    countEl.textContent = `${status.n_activities} activités`;
  } catch {
    // Header non-critical
  }
}

// ── Init sync check ─────────────────────────────────────────────────────────

async function initSync() {
  try {
    const st = await api.syncStatus();
    _updateSyncUI(st);

    if (st.sync_in_progress) {
      // Un sync est déjà en cours (lancé au startup du serveur)
      _startSyncPolling();
    } else if (st.last_sync_ago_minutes == null || st.last_sync_ago_minutes > 30) {
      // Données périmées → lancer le sync en background
      triggerSync();
    }
  } catch {
    // Sync check non-critical
  }
}

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // Nav clicks
  document.querySelectorAll('.ca-nav-tab').forEach(tab => {
    tab.addEventListener('click', () => navigate(tab.dataset.section));
  });

  // Sync button
  const syncBtn = document.getElementById('sync-btn');
  if (syncBtn) {
    syncBtn.addEventListener('click', () => triggerSync());
  }

  // Hash routing
  const hash = window.location.hash.slice(1);
  const initial = SECTIONS[hash] ? hash : 'overview';

  initHeader();
  initSync();
  navigate(initial);
});

window.addEventListener('hashchange', () => {
  const hash = window.location.hash.slice(1);
  if (SECTIONS[hash] && hash !== _currentSection) {
    navigate(hash);
  }
});
