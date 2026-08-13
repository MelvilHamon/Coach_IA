/**
 * app.js — Routeur et point d'entrée avec auth.
 */

import { api } from './api.js';
import { fmtDateShort } from './components.js';
import { getCurrentSport, setCurrentSport } from './state.js';
import { t, getLang, setLang, onLangChange } from './i18n.js';
import { renderOverview } from './sections/overview.js';
import { renderHistory } from './sections/history.js';
import { renderProfil } from './sections/profil.js';
import { renderProgression } from './sections/progression.js';
import { renderExplication } from './sections/explication.js';
import { renderAnalyse } from './sections/analyse.js';
import { renderCalendrier } from './sections/calendrier.js';
import { renderSettings } from './sections/settings.js';
import { renderStadiums } from './sections/stadiums.js';

// ── Sections ────────────────────────────────────────────────────────────────

const SECTIONS = {
  overview:    renderOverview,
  history:     renderHistory,
  profil:      renderProfil,
  progression: renderProgression,
  explication: renderExplication,
  calendrier:  renderCalendrier,
  analyse:     renderAnalyse,
  stadiums:    renderStadiums,
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
  // La coquille était masquée jusqu'ici : ses hauteurs n'étaient pas mesurables.
  measureChrome();
  placeSharedControls();
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

// Sections accessibles depuis la feuille « Plus » plutôt que depuis la barre
// basse. Doit rester aligné avec le markup de #more-sheet dans index.html.
const SHEET_SECTIONS = new Set(['history', 'profil', 'progression', 'explication', 'settings']);

const MOBILE_QUERY = window.matchMedia('(max-width: 768px)');

function isMobile() {
  return MOBILE_QUERY.matches;
}

function openSheet() {
  const sheet = document.getElementById('more-sheet');
  const backdrop = document.getElementById('more-sheet-backdrop');
  const btn = document.getElementById('more-btn');
  if (!sheet || !backdrop) return;
  sheet.hidden = false;
  backdrop.hidden = false;
  if (btn) btn.setAttribute('aria-expanded', 'true');
}

function closeSheet() {
  const sheet = document.getElementById('more-sheet');
  const backdrop = document.getElementById('more-sheet-backdrop');
  const btn = document.getElementById('more-btn');
  if (!sheet || !backdrop) return;
  sheet.hidden = true;
  backdrop.hidden = true;
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

/**
 * Déplace le sélecteur Run/Vélo et le switch de langue entre le header (desktop)
 * et la feuille « Plus » (mobile). On déplace les nœuds existants au lieu de les
 * dupliquer : les écouteurs suivent, et il n'y a jamais deux éléments portant le
 * même identifiant.
 */
function placeSharedControls() {
  const sheetSlot = document.getElementById('sheet-controls');
  const metaSlot = document.getElementById('sheet-meta');
  const nav = document.querySelector('.ca-nav');
  const headerMeta = document.querySelector('.ca-header-meta');
  const sport = document.querySelector('.ca-sport-selector');
  const lang = document.querySelector('.ca-lang-switch');
  if (!sheetSlot || !metaSlot || !nav || !headerMeta) return;

  // Les textes d'état du header : lisibles au calme dans la feuille, ils se
  // marchaient dessus à côté des boutons sur un écran de 390 px.
  const info = ['header-user', 'header-date', 'header-count', 'header-sync']
    .map(id => document.getElementById(id))
    .filter(Boolean);
  const syncBtn = document.getElementById('sync-btn');

  if (isMobile()) {
    info.forEach(n => { if (n.parentElement !== metaSlot) metaSlot.appendChild(n); });
    if (sport && sport.parentElement !== sheetSlot) sheetSlot.appendChild(sport);
    if (lang && lang.parentElement !== sheetSlot) sheetSlot.appendChild(lang);
  } else {
    // Ordre d'origine du header : user, date, count, sync, puis les boutons.
    info.forEach(n => { if (n.parentElement !== headerMeta) headerMeta.insertBefore(n, syncBtn); });
    if (sport && sport.parentElement !== nav) nav.appendChild(sport);
    if (lang && lang.parentElement !== headerMeta) headerMeta.appendChild(lang);
  }
}

/**
 * Expose au CSS deux mesures que les media queries ne peuvent pas calculer :
 * la largeur de la barre de défilement (sans quoi .cg-fullpage en 100vw déborde)
 * et la hauteur réelle du header + nav.
 */
function measureChrome() {
  const root = document.documentElement;
  root.style.setProperty('--sbw', `${window.innerWidth - root.clientWidth}px`);
  const header = document.querySelector('.ca-header');
  const nav = document.querySelector('.ca-nav');
  const h = (header ? header.offsetHeight : 0) + (nav && nav.offsetHeight ? nav.offsetHeight : 0);
  if (h) root.style.setProperty('--chrome-h', `${h}px`);
}

function navigate(section) {
  if (!SECTIONS[section]) section = 'overview';
  _currentSection = section;

  // Les deux barres (haut desktop, basse mobile) et les liens de la feuille
  // portent tous data-section : un seul balayage les maintient en phase.
  document.querySelectorAll('.ca-nav-tab, .ca-bnav-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.section === section);
  });
  // « Plus » s'allume quand la section courante vit dans la feuille.
  const moreBtn = document.getElementById('more-btn');
  if (moreBtn) moreBtn.classList.toggle('active', SHEET_SECTIONS.has(section));
  closeSheet();

  window.location.hash = section;

  const container = document.getElementById('page-content');
  try {
    SECTIONS[section](container);
  } catch (err) {
    container.innerHTML = `<div class="ca-error">${t('common.errorPrefix', { msg: err.message })}</div>`;
  }
}

// ── Sync UI ─────────────────────────────────────────────────────────────────

function _fmtAgo(minutes) {
  if (minutes == null) return '—';
  if (minutes < 1)   return t('common.atInstant');
  if (minutes < 60)  return t('common.minAgo', { n: Math.round(minutes) });
  const h = Math.floor(minutes / 60);
  if (h < 24) return t('common.hoursAgo', { n: h });
  const d = Math.floor(h / 24);
  return t('common.daysAgo', { n: d });
}

function _updateSyncUI(syncData) {
  const el = document.getElementById('header-sync');
  const btn = document.getElementById('sync-btn');
  if (!el || !btn) return;

  if (syncData.sync_in_progress) {
    el.textContent = t('header.syncing');
    el.classList.add('syncing');
    btn.classList.add('spinning');
  } else {
    el.classList.remove('syncing');
    btn.classList.remove('spinning');

    if (syncData.last_error) {
      el.textContent = t('header.lastAttempt', { ago: _fmtAgo(syncData.last_sync_ago_minutes) });
    } else {
      el.textContent = t('header.lastUpdate', { ago: _fmtAgo(syncData.last_sync_ago_minutes) });
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
  reconnect.textContent = t('header.reconnectStrava');
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
  if (el) { el.textContent = t('header.syncing'); el.classList.add('syncing'); }

  try {
    await api.syncStart();
    _startSyncPolling();
  } catch {
    if (btn) btn.classList.remove('spinning');
    if (el) { el.textContent = t('header.syncFailed'); el.classList.remove('syncing'); }
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
    countEl.textContent = `${status.n_activities} ${t('common.activities')}`;
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

function applyI18nToDom() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (key) el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (key) el.setAttribute('placeholder', t(key));
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (key) el.setAttribute('title', t(key));
  });
  // Update active language button
  document.querySelectorAll('.ca-lang-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.lang === getLang());
  });
}

function initLangSwitch() {
  document.querySelectorAll('.ca-lang-btn').forEach(b => {
    b.addEventListener('click', () => setLang(b.dataset.lang));
  });
  onLangChange(() => {
    applyI18nToDom();
    initHeader();
    if (_currentSection) navigate(_currentSection);
  });
  applyI18nToDom();
}

/** Écouteurs de la coquille applicative : navigation, sport, sync, mobile. */
function initShell() {
  // Barre du haut, barre basse et liens de la feuille partagent data-section.
  document.querySelectorAll('.ca-nav-tab, .ca-bnav-tab[data-section]').forEach(tab => {
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

  const syncBtn = document.getElementById('sync-btn');
  if (syncBtn) syncBtn.addEventListener('click', () => triggerSync());

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) logoutBtn.addEventListener('click', () => logout());

  // Feuille « Plus »
  const moreBtn = document.getElementById('more-btn');
  const backdrop = document.getElementById('more-sheet-backdrop');
  if (moreBtn) {
    moreBtn.addEventListener('click', () => {
      const sheet = document.getElementById('more-sheet');
      if (sheet && sheet.hidden) openSheet(); else closeSheet();
    });
  }
  if (backdrop) backdrop.addEventListener('click', () => closeSheet());
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeSheet();
  });

  placeSharedControls();
  measureChrome();

  // Un seul écouteur de redimensionnement pour toute l'application : les cartes
  // Leaflet et les graphes Plotly ne se recalculent pas tout seuls, et rien
  // n'écoutait la rotation de l'écran jusqu'ici.
  let resizeTimer = null;
  const onResize = () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      placeSharedControls();
      measureChrome();
      window.dispatchEvent(new CustomEvent('ca:resize'));
    }, 150);
  };
  window.addEventListener('resize', onResize);
  window.addEventListener('orientationchange', onResize);
}

document.addEventListener('DOMContentLoaded', async () => {
  initAuthForms();
  applyI18nToDom();
  initLangSwitch();

  // Listen for 401 forced logouts
  window.addEventListener('ca:logout', () => {
    _currentUser = null;
    showAuth();
  });

  // Check existing session
  const authenticated = await checkSession();

  // Les écouteurs de la coquille sont posés une seule fois, quel que soit le
  // chemin d'authentification : le markup existe déjà dans les deux cas.
  initShell();

  if (authenticated) {
    // Hash routing (strip query params: #settings?strava=connected → settings)
    const hash = window.location.hash.slice(1).split('?')[0];
    const initial = SECTIONS[hash] ? hash : 'overview';

    initHeader();
    initSync();
    navigate(initial);
    maybeShowStravaOnboarding();
  }
});

window.addEventListener('hashchange', () => {
  const hash = window.location.hash.slice(1).split('?')[0];
  if (SECTIONS[hash] && hash !== _currentSection) {
    navigate(hash);
  }
});
