/**
 * app.js — Routeur et point d'entrée avec auth.
 */

import { api } from './api.js';
import { fmtDateShort } from './components.js';
import { getCurrentSport, setCurrentSport } from './state.js';
import { renderOverview } from './sections/overview.js';
import { renderHistory } from './sections/history.js';
import { renderProfil } from './sections/profil.js';
import { renderProgression } from './sections/progression.js';
import { renderCharge } from './sections/charge.js';
import { renderAnalyse } from './sections/analyse.js';
import { renderCalendrier } from './sections/calendrier.js';
import { renderSettings } from './sections/settings.js';

// ── Sections ────────────────────────────────────────────────────────────────

const SECTIONS = {
  overview:    renderOverview,
  history:     renderHistory,
  profil:      renderProfil,
  progression: renderProgression,
  charge:      renderCharge,
  calendrier:  renderCalendrier,
  analyse:     renderAnalyse,
  settings:    renderSettings,
};

let _currentSection = 'overview';
let _syncPolling = null;
let _currentUser = null;

// ── Auth ─────────────────────────────────────────────────────────────────────

function showAuth() {
  document.getElementById('auth-page').style.display = '';
  document.getElementById('app-shell').style.display = 'none';
}

function showApp(user) {
  _currentUser = user;
  document.getElementById('auth-page').style.display = 'none';
  document.getElementById('app-shell').style.display = '';
  const userEl = document.getElementById('header-user');
  if (userEl) userEl.textContent = user.display_name || user.email;
}

function initAuthForms() {
  const emailForm = document.getElementById('otp-email-form');
  const codeForm = document.getElementById('otp-code-form');
  let _otpEmail = '';

  function showEmailStep() {
    emailForm.style.display = '';
    codeForm.style.display = 'none';
  }

  function showCodeStep(email) {
    _otpEmail = email;
    emailForm.style.display = 'none';
    codeForm.style.display = '';
    document.getElementById('otp-email-display').textContent = email;
    document.getElementById('otp-code').value = '';
    document.getElementById('otp-code').focus();
  }

  // Step 1: Send OTP
  emailForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = document.getElementById('otp-email-error');
    errEl.style.display = 'none';
    const email = document.getElementById('otp-email').value.trim();
    try {
      const res = await api.sendOtp(email);
      if (res.error) { errEl.textContent = res.error; errEl.style.display = ''; return; }
      showCodeStep(email);
    } catch (err) {
      errEl.textContent = err.message; errEl.style.display = '';
    }
  });

  // Step 2: Verify OTP
  codeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = document.getElementById('otp-code-error');
    errEl.style.display = 'none';
    const code = document.getElementById('otp-code').value.trim();
    try {
      const res = await api.verifyOtp(_otpEmail, code);
      if (res.error) { errEl.textContent = res.error; errEl.style.display = ''; return; }
      showApp(res.user);
      initHeader();
      initSync();
      navigate('overview');
      maybeShowStravaOnboarding();
    } catch (err) {
      errEl.textContent = err.message; errEl.style.display = '';
    }
  });

  // Back to email step
  document.getElementById('otp-back').addEventListener('click', showEmailStep);

  // Resend OTP
  document.getElementById('otp-resend').addEventListener('click', async () => {
    const errEl = document.getElementById('otp-code-error');
    errEl.style.display = 'none';
    try {
      await api.sendOtp(_otpEmail);
      errEl.textContent = 'Nouveau code envoyé !';
      errEl.style.display = '';
      errEl.classList.add('ca-auth-success');
      setTimeout(() => { errEl.style.display = 'none'; errEl.classList.remove('ca-auth-success'); }, 3000);
    } catch (err) {
      errEl.textContent = err.message; errEl.style.display = '';
    }
  });
}

async function checkSession() {
  try {
    const res = await api.me();
    if (res.user) {
      showApp(res.user);
      return true;
    }
  } catch {
    // not authenticated
  }
  showAuth();
  return false;
}

// ── Navigation ──────────────────────────────────────────────────────────────

function navigate(section) {
  if (!SECTIONS[section]) section = 'overview';
  _currentSection = section;

  document.querySelectorAll('.ca-nav-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.section === section);
  });

  window.location.hash = section;

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

  // Avertir l'utilisateur si le token Strava a expiré
  if (result.strava_auth_error) {
    _showStravaBanner(result.strava_auth_error);
  }

  if (stepsRun.includes('strava') || stepsRun.includes('analysis')) {
    navigate(_currentSection);
    initHeader();
  } else if (stepsRun.includes('strava_gps') || stepsRun.includes('garmin') || stepsRun.includes('gps_analysis')) {
    if (_currentSection === 'analyse') navigate('analyse');
    initHeader();
  } else {
    initHeader();
  }
}

function _showStravaBanner(message) {
  // Éviter les doublons
  const existing = document.getElementById('strava-auth-banner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.id = 'strava-auth-banner';
  banner.style.cssText =
    'position:fixed;top:0;left:0;right:0;z-index:9999;' +
    'background:#e74c3c;color:#fff;padding:12px 20px;' +
    'display:flex;align-items:center;justify-content:space-between;' +
    'font-size:14px;box-shadow:0 2px 8px rgba(0,0,0,.2)';

  const text = document.createElement('span');
  text.textContent = message;

  const btnWrap = document.createElement('div');
  btnWrap.style.cssText = 'display:flex;gap:10px;align-items:center';

  const reconnect = document.createElement('a');
  reconnect.textContent = 'Reconnecter Strava';
  reconnect.href = '#settings';
  reconnect.style.cssText =
    'background:#fff;color:#e74c3c;padding:6px 14px;border-radius:4px;' +
    'text-decoration:none;font-weight:600;white-space:nowrap';
  reconnect.addEventListener('click', () => banner.remove());

  const close = document.createElement('button');
  close.textContent = '✕';
  close.style.cssText =
    'background:none;border:none;color:#fff;font-size:18px;cursor:pointer;padding:0 4px';
  close.addEventListener('click', () => banner.remove());

  btnWrap.appendChild(reconnect);
  btnWrap.appendChild(close);
  banner.appendChild(text);
  banner.appendChild(btnWrap);
  document.body.appendChild(banner);
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

// ── Strava onboarding modal ────────────────────────────────────────────────

async function maybeShowStravaOnboarding() {
  try {
    const [userInfo, status] = await Promise.all([api.me(), api.status()]);
    if (userInfo.has_strava) return;           // already connected
    if (status.n_activities > 0) return;       // not a first-timer
  } catch {
    return; // non-critical
  }

  const modal = document.getElementById('strava-onboarding-modal');
  if (!modal) return;
  modal.style.display = '';

  document.getElementById('strava-onboarding-connect').addEventListener('click', () => {
    window.location.href = '/api/auth/strava/login';
  });

  document.getElementById('strava-onboarding-skip').addEventListener('click', () => {
    modal.style.display = 'none';
  });
}

// ── Init sync check ─────────────────────────────────────────────────────────

async function initSync() {
  try {
    const st = await api.syncStatus();
    _updateSyncUI(st);

    if (st.sync_in_progress) {
      _startSyncPolling();
    } else if (st.last_sync_ago_minutes == null || st.last_sync_ago_minutes > 30) {
      triggerSync();
    }
  } catch {
    // Sync check non-critical
  }
}

// ── Logout ──────────────────────────────────────────────────────────────────

async function logout() {
  try { await api.logout(); } catch { /* ok */ }
  _currentUser = null;
  _stopSyncPolling();
  showAuth();
}

// ── Init ────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  initAuthForms();

  // Listen for 401 forced logouts
  window.addEventListener('ca:logout', () => {
    _currentUser = null;
    showAuth();
  });

  // Check existing session
  const authenticated = await checkSession();

  if (authenticated) {
    // Nav clicks
    document.querySelectorAll('.ca-nav-tab').forEach(tab => {
      tab.addEventListener('click', () => navigate(tab.dataset.section));
    });

    // Sport selector
    document.querySelectorAll('.ca-sport-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        setCurrentSport(btn.dataset.sport);
        document.querySelectorAll('.ca-sport-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        navigate(_currentSection); // re-render current section with new sport
      });
    });

    // Sync button
    const syncBtn = document.getElementById('sync-btn');
    if (syncBtn) syncBtn.addEventListener('click', () => triggerSync());

    // Logout button
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) logoutBtn.addEventListener('click', () => logout());

    // Hash routing (strip query params: #settings?strava=connected → settings)
    const hash = window.location.hash.slice(1).split('?')[0];
    const initial = SECTIONS[hash] ? hash : 'overview';

    initHeader();
    initSync();
    navigate(initial);
    maybeShowStravaOnboarding();
  } else {
    // Still wire nav for after login
    document.querySelectorAll('.ca-nav-tab').forEach(tab => {
      tab.addEventListener('click', () => navigate(tab.dataset.section));
    });
    const syncBtn = document.getElementById('sync-btn');
    if (syncBtn) syncBtn.addEventListener('click', () => triggerSync());
    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) logoutBtn.addEventListener('click', () => logout());
  }
});

window.addEventListener('hashchange', () => {
  const hash = window.location.hash.slice(1).split('?')[0];
  if (SECTIONS[hash] && hash !== _currentSection) {
    navigate(hash);
  }
});
