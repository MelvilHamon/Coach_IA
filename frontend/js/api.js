/**
 * api.js — Wrapper fetch vers /api/*
 */

const BASE = '';

async function _fetch(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, opts);
  if (res.status === 401) {
    // Session expired — reload to show login
    window.dispatchEvent(new Event('ca:logout'));
    throw new Error('Session expirée');
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function _post(path, body) {
  return _fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

export const api = {
  // Auth (OTP)
  sendOtp:     (email)               => _post('/api/auth/send-otp', { email }),
  verifyOtp:   (email, code, display_name = '') => _post('/api/auth/verify-otp', { email, code, display_name }),
  logout:      ()                    => _post('/api/auth/logout', {}),
  me:          ()                    => _fetch('/api/auth/me'),
  getProfile:  ()                    => _fetch('/api/auth/profile'),
  saveProfile: (profile)             => _post('/api/auth/profile', profile),
  saveGarmin:        (email, password) => _post('/api/auth/garmin-credentials', { email, password }),
  stravaDisconnect:  ()               => _post('/api/auth/strava/disconnect', {}),

  // Activities
  activities:     (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return _fetch(`/api/activities${qs ? '?' + qs : ''}`);
  },
  activityTypes:  ()            => _fetch('/api/activities/types'),
  activity:       (id)          => _fetch(`/api/activities/${id}`),
  activityStream: (id)          => _fetch(`/api/activities/${id}/stream`),

  // Charts (all accept optional sport parameter)
  chartVolume:       (sport) => _fetch(`/api/charts/volume${sport ? '?sport=' + sport : ''}`),
  chartAcwr:         (sport) => _fetch(`/api/charts/acwr${sport ? '?sport=' + sport : ''}`),
  chartPace:         (sport) => _fetch(`/api/charts/pace${sport ? '?sport=' + sport : ''}`),
  chartSpeed:        (sport) => _fetch(`/api/charts/speed${sport ? '?sport=' + sport : ''}`),
  chartEf:           (sport) => _fetch(`/api/charts/ef${sport ? '?sport=' + sport : ''}`),
  chartVo2:          (sport) => _fetch(`/api/charts/vo2${sport ? '?sport=' + sport : ''}`),
  chartDistribution: (sport) => _fetch(`/api/charts/distribution${sport ? '?sport=' + sport : ''}`),
  chartFitness:      (sport) => _fetch(`/api/charts/fitness${sport ? '?sport=' + sport : ''}`),
  chartMonotony:     (sport) => _fetch(`/api/charts/monotony${sport ? '?sport=' + sport : ''}`),

  // GPS
  gps:         (id) => _fetch(`/api/gps/${id}`),
  gpsSpeed:    (id) => _fetch(`/api/gps/${id}/speed`),
  gpsAltitude: (id) => _fetch(`/api/gps/${id}/altitude`),
  gpsGap:      (id) => _fetch(`/api/gps/${id}/gap`),
  gpsBpm:      (id) => _fetch(`/api/gps/${id}/bpm`),
  gpsSplits:   (id) => _fetch(`/api/gps/${id}/splits`),
  sessionAnalysis: (id) => _fetch(`/api/gps/${id}/session-analysis`),

  // Records
  records: () => _fetch('/api/records'),

  // Reviews
  review:         (id) => _fetch(`/api/reviews/${id}`),
  generateReview: (id) => _fetch(`/api/reviews/${id}`, { method: 'POST' }),

  // Config & Status
  config: () => _fetch('/api/config'),
  status: () => _fetch('/api/status'),

  // Planning
  plannedWorkouts:  ()           => _fetch('/api/planning'),
  createPlanned:    (data)       => _post('/api/planning', data),
  updatePlanned:    (id, data)   => _fetch(`/api/planning/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  deletePlanned:    (id)         => _fetch(`/api/planning/${id}`, { method: 'DELETE' }),

  // Gear
  gear:            ()              => _fetch('/api/gear'),
  createGear:      (data)          => _post('/api/gear', data),
  updateGear:      (id, data)      => _fetch(`/api/gear/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
  deleteGear:      (id)            => _fetch(`/api/gear/${id}`, { method: 'DELETE' }),
  gearAssignments: ()              => _fetch('/api/gear/assignments'),
  assignGear:      (actId, slot, gearId) => _fetch(`/api/gear/assign/${actId}/${slot}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ gear_id: gearId }) }),

  // Feedback (ressentis)
  feedback:     (id) => _fetch(`/api/feedback/${id}`),
  saveFeedback: (id, data) => _fetch(`/api/feedback/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),

  // Blocs manuels (effort/récup)
  blocks:      (id) => _fetch(`/api/blocks/${id}`),
  saveBlocks:  (id, blocks) => _fetch(`/api/blocks/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ blocks }) }),
  deleteBlocks:(id) => _fetch(`/api/blocks/${id}`, { method: 'DELETE' }),

  // Workouts (.FIT generation)
  generateFit:     (workoutId) => _post(`/api/workouts/generate-fit/${workoutId}`, {}),
  textToFit:       (text, name) => _post('/api/workouts/text-to-fit', { text, workout_name: name }),
  describeWorkout: (data)      => _post('/api/workouts/describe', data),
  downloadFit:     (filename)  => `${BASE}/api/workouts/download/${filename}`,

  // Sync
  syncStart:  () => _fetch('/api/sync', { method: 'POST' }),
  syncStatus: () => _fetch('/api/sync/status'),
};
