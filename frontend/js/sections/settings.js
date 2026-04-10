/**
 * settings.js — Page Paramètres : profil, identifiants Garmin & Strava.
 */

import { api } from '../api.js';
import { el, sectionTitle, loading } from '../components.js';

export async function renderSettings(container) {
  container.innerHTML = '';
  container.appendChild(loading());

  let userInfo;
  try {
    userInfo = await api.me();
  } catch (err) {
    container.innerHTML = '';
    container.appendChild(el('div', { className: 'ca-error' }, err.message));
    return;
  }

  const profile = userInfo.profile || {};

  container.innerHTML = '';
  container.appendChild(sectionTitle('Paramètres'));

  // ── User info ──
  const userSection = el('div', { className: 'ca-section' },
    el('div', { className: 'ca-detail-rows' },
      el('div', { className: 'ca-detail-row' },
        el('span', { className: 'ca-detail-label' }, 'Utilisateur'),
        el('span', { className: 'ca-detail-value' }, userInfo.user.display_name || userInfo.user.email),
      ),
      el('div', { className: 'ca-detail-row' },
        el('span', { className: 'ca-detail-label' }, 'Email'),
        el('span', { className: 'ca-detail-value' }, userInfo.user.email),
      ),
    ),
  );
  container.appendChild(userSection);

  // ── Profil physiologique ──
  const genderSelect = el('select', { className: 'ca-input', style: { width: '160px' } },
    el('option', { value: 'male' }, 'Homme'),
    el('option', { value: 'female' }, 'Femme'),
  );
  genderSelect.value = profile.gender === 'female' ? 'female' : 'male';

  const hrInput = (placeholder, key) => {
    const inp = el('input', {
      type: 'number', className: 'ca-input', placeholder,
      style: { width: '120px' }, min: '30', max: '230',
    });
    if (profile[key]) inp.value = profile[key];
    return inp;
  };

  const hrMax = hrInput('FC max', 'hr_max');
  const hrRest = hrInput('FC repos', 'hr_rest');
  const hrThreshold = hrInput('FC seuil', 'hr_threshold');

  const weightInput = el('input', {
    type: 'number', className: 'ca-input', placeholder: 'Poids (kg)',
    style: { width: '120px' }, min: '30', max: '200', step: '0.1',
  });
  if (profile.weight_kg) weightInput.value = profile.weight_kg;

  const zoneInput = (label, key) => {
    const inp = el('input', {
      type: 'number', className: 'ca-input', placeholder: label,
      style: { width: '90px' }, min: '30', max: '230',
    });
    if (profile[key]) inp.value = profile[key];
    return inp;
  };

  const z1 = zoneInput('Z1 max', 'hr_z1_max');
  const z2 = zoneInput('Z2 max', 'hr_z2_max');
  const z3 = zoneInput('Z3 max', 'hr_z3_max');
  const z4 = zoneInput('Z4 max', 'hr_z4_max');
  const z5 = zoneInput('Z5 max', 'hr_z5_max');

  const profileMsg = el('div', { className: 'ca-auth-error', style: { display: 'none', marginTop: '8px' } });

  const profileBtn = el('button', {
    className: 'ca-btn accent',
    onClick: async () => {
      profileMsg.style.display = 'none';
      const data = {
        gender: genderSelect.value,
        hr_max: hrMax.value ? parseInt(hrMax.value) : null,
        hr_rest: hrRest.value ? parseInt(hrRest.value) : null,
        hr_threshold: hrThreshold.value ? parseInt(hrThreshold.value) : null,
        hr_z1_max: z1.value ? parseInt(z1.value) : null,
        hr_z2_max: z2.value ? parseInt(z2.value) : null,
        hr_z3_max: z3.value ? parseInt(z3.value) : null,
        hr_z4_max: z4.value ? parseInt(z4.value) : null,
        hr_z5_max: z5.value ? parseInt(z5.value) : null,
        weight_kg: weightInput.value ? parseFloat(weightInput.value) : null,
      };
      profileBtn.textContent = 'Enregistrement…';
      profileBtn.disabled = true;
      try {
        const res = await api.saveProfile(data);
        if (res.ok) {
          profileMsg.textContent = 'Profil enregistré.';
          profileMsg.style.color = 'var(--success)';
        } else {
          profileMsg.textContent = res.error || 'Erreur';
          profileMsg.style.color = 'var(--danger)';
        }
        profileMsg.style.display = '';
      } catch (e) {
        profileMsg.textContent = e.message;
        profileMsg.style.color = 'var(--danger)';
        profileMsg.style.display = '';
      } finally {
        profileBtn.textContent = 'Enregistrer';
        profileBtn.disabled = false;
      }
    },
  }, 'Enregistrer');

  const profileSection = el('div', { className: 'ca-section' },
    sectionTitle('Profil physiologique'),
    el('div', { className: 'ca-settings-explain' },
      'Ces informations permettent de calculer tes zones FC, TRIMP et hrTSS avec précision.',
    ),
    el('div', { style: { display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', marginTop: '12px' } },
      el('label', { style: { fontSize: '12px' } }, 'Genre : '), genderSelect,
      el('label', { style: { fontSize: '12px' } }, 'FC max : '), hrMax,
      el('label', { style: { fontSize: '12px' } }, 'FC repos : '), hrRest,
      el('label', { style: { fontSize: '12px' } }, 'FC seuil : '), hrThreshold,
      el('label', { style: { fontSize: '12px' } }, 'Poids : '), weightInput,
    ),
    el('div', { style: { marginTop: '12px' } },
      el('div', { className: 'ca-settings-explain', style: { marginBottom: '8px' } },
        'Zones BPM personnalisées (limite haute de chaque zone) :',
      ),
      el('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' } },
        el('label', { style: { fontSize: '11px' } }, 'Z1'), z1,
        el('label', { style: { fontSize: '11px' } }, 'Z2'), z2,
        el('label', { style: { fontSize: '11px' } }, 'Z3'), z3,
        el('label', { style: { fontSize: '11px' } }, 'Z4'), z4,
        el('label', { style: { fontSize: '11px' } }, 'Z5'), z5,
      ),
    ),
    el('div', { style: { marginTop: '12px' } }, profileBtn),
    profileMsg,
  );
  container.appendChild(profileSection);

  // ── Matériel (chaussures & montres) ──
  const gearContainer = el('div', { className: 'ca-section' });
  container.appendChild(gearContainer);
  await renderGearSection(gearContainer);

  // ── Garmin credentials ──
  const garminStatus = userInfo.has_garmin
    ? el('span', { style: { color: 'var(--success)', fontWeight: 500 } }, 'Configuré')
    : el('span', { style: { color: 'var(--danger)' } }, 'Non configuré');

  const garminEmail = el('input', { type: 'email', className: 'ca-input', placeholder: 'Email Garmin', style: { width: '260px' } });
  const garminPw = el('input', { type: 'password', className: 'ca-input', placeholder: 'Mot de passe Garmin', style: { width: '260px' } });
  const garminMsg = el('div', { className: 'ca-auth-error', style: { display: 'none', marginTop: '8px' } });

  const garminBtn = el('button', {
    className: 'ca-btn accent',
    onClick: async () => {
      garminMsg.style.display = 'none';
      if (!garminEmail.value || !garminPw.value) {
        garminMsg.textContent = 'Email et mot de passe requis.';
        garminMsg.style.display = '';
        return;
      }
      garminBtn.textContent = 'Enregistrement…';
      garminBtn.disabled = true;
      try {
        const res = await api.saveGarmin(garminEmail.value, garminPw.value);
        if (res.ok) {
          garminMsg.textContent = 'Identifiants Garmin enregistrés.';
          garminMsg.style.color = 'var(--success)';
          garminMsg.style.display = '';
          garminEmail.value = '';
          garminPw.value = '';
        } else {
          garminMsg.textContent = res.error || 'Erreur';
          garminMsg.style.color = 'var(--danger)';
          garminMsg.style.display = '';
        }
      } catch (e) {
        garminMsg.textContent = e.message;
        garminMsg.style.color = 'var(--danger)';
        garminMsg.style.display = '';
      } finally {
        garminBtn.textContent = 'Enregistrer';
        garminBtn.disabled = false;
      }
    },
  }, 'Enregistrer');

  const garminSection = el('div', { className: 'ca-section' },
    sectionTitle('Garmin Connect'),
    el('div', { style: { marginBottom: '12px' } }, el('span', {}, 'Statut : '), garminStatus),
    el('div', { className: 'ca-settings-explain' },
      'Tes identifiants Garmin sont chiffrés et stockés localement. Ils servent à synchroniser tes activités et données GPS.',
    ),
    el('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center', marginTop: '12px' } },
      garminEmail, garminPw, garminBtn,
    ),
    garminMsg,
  );
  container.appendChild(garminSection);

  // ── Strava OAuth ──
  const stravaConnected = userInfo.has_strava;
  const stravaMsg = el('div', { className: 'ca-auth-error', style: { display: 'none', marginTop: '8px' } });

  // Check URL params for OAuth callback result
  const urlParams = new URLSearchParams(window.location.hash.split('?')[1] || '');
  if (urlParams.get('strava') === 'connected') {
    stravaMsg.textContent = 'Compte Strava connecté avec succès !';
    stravaMsg.style.color = 'var(--success)';
    stravaMsg.style.display = '';
  } else if (urlParams.get('error') === 'strava_denied') {
    stravaMsg.textContent = 'Autorisation Strava refusée.';
    stravaMsg.style.color = 'var(--danger)';
    stravaMsg.style.display = '';
  } else if (urlParams.get('error') === 'strava_exchange_failed') {
    stravaMsg.textContent = 'Erreur lors de la connexion Strava. Réessayez.';
    stravaMsg.style.color = 'var(--danger)';
    stravaMsg.style.display = '';
  } else if (urlParams.get('error') === 'not_authenticated') {
    stravaMsg.textContent = 'Session expirée. Reconnecte-toi et réessaye.';
    stravaMsg.style.color = 'var(--danger)';
    stravaMsg.style.display = '';
  } else if (urlParams.get('error') === 'strava_not_configured') {
    stravaMsg.textContent = 'Strava non configuré côté serveur (STRAVA_CLIENT_ID manquant).';
    stravaMsg.style.color = 'var(--danger)';
    stravaMsg.style.display = '';
  }

  let stravaBody;
  if (stravaConnected) {
    const athleteId = userInfo.strava_athlete_id;
    const disconnectBtn = el('button', {
      className: 'ca-btn danger',
      onClick: async () => {
        if (!confirm('Déconnecter ton compte Strava ?')) return;
        disconnectBtn.textContent = 'Déconnexion…';
        disconnectBtn.disabled = true;
        try {
          await api.stravaDisconnect();
          window.location.reload();
        } catch (e) {
          stravaMsg.textContent = e.message;
          stravaMsg.style.color = 'var(--danger)';
          stravaMsg.style.display = '';
          disconnectBtn.textContent = 'Déconnecter';
          disconnectBtn.disabled = false;
        }
      },
    }, 'Déconnecter');

    stravaBody = el('div', {},
      el('div', { style: { marginBottom: '12px' } },
        el('span', { style: { color: 'var(--success)', fontWeight: 500 } }, 'Connecté'),
        athleteId ? el('span', { style: { marginLeft: '8px', opacity: 0.7, fontSize: '12px' } }, `(athlete #${athleteId})`) : '',
      ),
      disconnectBtn,
    );
  } else {
    const connectBtn = el('img', {
      src: '/img/btn_strava_connect.png',
      alt: 'Connect with Strava',
      style: { height: '48px', cursor: 'pointer' },
      onClick: () => {
        window.location.href = '/api/auth/strava/login';
      },
    });

    stravaBody = el('div', {},
      el('div', { style: { marginBottom: '12px' } },
        el('span', { style: { color: 'var(--danger)' } }, 'Non connecté'),
      ),
      el('div', { className: 'ca-settings-explain' },
        'Connecte ton compte Strava pour synchroniser automatiquement tes activités.',
      ),
      el('div', { style: { marginTop: '12px' } }, connectBtn),
    );
  }

  const stravaSection = el('div', { className: 'ca-section' },
    sectionTitle('Strava'),
    stravaBody,
    stravaMsg,
  );
  container.appendChild(stravaSection);
}


// ── Gear section ───────────────────────────────────────────────────────────

const GEAR_TYPES = [
  { value: 'shoes', label: 'Chaussures' },
  { value: 'watch', label: 'Montre' },
];

async function renderGearSection(container) {
  container.innerHTML = '';
  container.appendChild(el('div', { className: 'ca-loading' }, 'Chargement matériel…'));

  let gearList = [];
  try {
    const res = await api.gear();
    gearList = res.gear || [];
  } catch { /* empty */ }

  container.innerHTML = '';
  container.appendChild(sectionTitle('Matériel'));
  container.appendChild(el('div', { className: 'ca-settings-explain' },
    'Enregistre tes chaussures et montres pour suivre les kilomètres cumulés.',
  ));

  // ── Add form ──
  const nameInput = el('input', { type: 'text', className: 'ca-input', placeholder: 'Nom (ex: Nike Vaporfly)', style: { width: '200px' } });
  const brandInput = el('input', { type: 'text', className: 'ca-input', placeholder: 'Marque', style: { width: '140px' } });
  const typeSelect = el('select', { className: 'ca-input', style: { width: '130px' } });
  for (const t of GEAR_TYPES) {
    typeSelect.appendChild(el('option', { value: t.value }, t.label));
  }
  const dateInput = el('input', { type: 'date', className: 'ca-input', style: { width: '150px' } });
  const addMsg = el('div', { className: 'ca-auth-error', style: { display: 'none', marginTop: '8px' } });

  const addBtn = el('button', {
    className: 'ca-btn accent',
    onClick: async () => {
      if (!nameInput.value.trim()) {
        addMsg.textContent = 'Nom requis.';
        addMsg.style.color = 'var(--danger)';
        addMsg.style.display = '';
        return;
      }
      addBtn.disabled = true;
      addBtn.textContent = 'Ajout…';
      addMsg.style.display = 'none';
      try {
        await api.createGear({
          name: nameInput.value.trim(),
          type: typeSelect.value,
          brand: brandInput.value.trim() || null,
          acquired_date: dateInput.value || null,
          retired: false,
        });
        nameInput.value = '';
        brandInput.value = '';
        dateInput.value = '';
        renderGearSection(container);
      } catch (e) {
        addMsg.textContent = e.message;
        addMsg.style.color = 'var(--danger)';
        addMsg.style.display = '';
      } finally {
        addBtn.disabled = false;
        addBtn.textContent = 'Ajouter';
      }
    },
  }, 'Ajouter');

  const addForm = el('div', { style: { marginTop: '12px', display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' } },
    typeSelect, nameInput, brandInput,
    el('label', { style: { fontSize: '11px' } }, 'Acquis le'), dateInput,
    addBtn,
  );
  container.appendChild(addForm);
  container.appendChild(addMsg);

  // ── Gear list ──
  if (!gearList.length) {
    container.appendChild(el('div', { className: 'ca-empty', style: { marginTop: '16px' } }, 'Aucun matériel enregistré.'));
    return;
  }

  const table = el('div', { style: { marginTop: '16px' } });

  for (const g of gearList) {
    const typeLabel = GEAR_TYPES.find(t => t.value === g.type)?.label || g.type;
    const dateStr = g.acquired_date || '—';
    const km = g.total_km != null ? `${g.total_km} km` : '0 km';
    const retiredBadge = g.retired
      ? el('span', { style: { fontSize: '10px', color: 'var(--ink-light)', marginLeft: '6px' } }, '(retiré)')
      : null;

    const retireBtn = el('button', {
      className: 'ca-btn',
      style: { fontSize: '11px', padding: '2px 8px' },
      onClick: async () => {
        await api.updateGear(g.id, {
          name: g.name, type: g.type, brand: g.brand,
          acquired_date: g.acquired_date, retired: !g.retired,
        });
        renderGearSection(container);
      },
    }, g.retired ? 'Réactiver' : 'Retirer');

    const deleteBtn = el('button', {
      className: 'ca-btn',
      style: { fontSize: '11px', padding: '2px 8px', color: 'var(--danger)' },
      onClick: async () => {
        if (!confirm(`Supprimer "${g.name}" ?`)) return;
        await api.deleteGear(g.id);
        renderGearSection(container);
      },
    }, 'Supprimer');

    const row = el('div', {
      className: 'ca-detail-row',
      style: { padding: '8px 0', borderBottom: '1px solid var(--border)', alignItems: 'center', opacity: g.retired ? '0.5' : '1' },
    },
      el('div', { style: { flex: '1', minWidth: '0' } },
        el('div', { style: { fontWeight: 500 } },
          el('span', {}, `${typeLabel === 'Chaussures' ? '\u{1F45F}' : '\u{231A}'} `),
          el('span', {}, g.name),
          retiredBadge,
        ),
        el('div', { style: { fontSize: '12px', color: 'var(--ink-mid)' } },
          [g.brand, `depuis ${dateStr}`, km].filter(Boolean).join(' · '),
        ),
      ),
      el('div', { style: { display: 'flex', gap: '4px', flexShrink: '0' } }, retireBtn, deleteBtn),
    );
    table.appendChild(row);
  }

  container.appendChild(table);
}
