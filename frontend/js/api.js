/**
 * api.js — Wrapper fetch vers /api/*
 */

const BASE = '';

async function _fetch(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  // Activities
  activities:     (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return _fetch(`/api/activities${qs ? '?' + qs : ''}`);
  },
  activityTypes:  ()            => _fetch('/api/activities/types'),
  activity:       (id)          => _fetch(`/api/activities/${id}`),
  activityStream: (id)          => _fetch(`/api/activities/${id}/stream`),

  // Charts
  chartVolume:       () => _fetch('/api/charts/volume'),
  chartAcwr:         () => _fetch('/api/charts/acwr'),
  chartPace:         () => _fetch('/api/charts/pace'),
  chartEf:           () => _fetch('/api/charts/ef'),
  chartVo2:          () => _fetch('/api/charts/vo2'),
  chartDistribution: () => _fetch('/api/charts/distribution'),
  chartFitness:      () => _fetch('/api/charts/fitness'),
  chartMonotony:     () => _fetch('/api/charts/monotony'),

  // GPS
  gps:         (id) => _fetch(`/api/gps/${id}`),
  gpsSpeed:    (id) => _fetch(`/api/gps/${id}/speed`),
  gpsAltitude: (id) => _fetch(`/api/gps/${id}/altitude`),
  gpsGap:      (id) => _fetch(`/api/gps/${id}/gap`),

  // Records
  records: () => _fetch('/api/records'),

  // Reviews
  review:         (id) => _fetch(`/api/reviews/${id}`),
  generateReview: (id) => _fetch(`/api/reviews/${id}`, { method: 'POST' }),

  // Config & Status
  config: () => _fetch('/api/config'),
  status: () => _fetch('/api/status'),

  // Sync
  syncStart:  () => _fetch('/api/sync', { method: 'POST' }),
  syncStatus: () => _fetch('/api/sync/status'),
};
