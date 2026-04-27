/**
 * state.js — État global partagé entre les sections.
 */

let _currentSport = 'run';

export function getCurrentSport() {
  return _currentSport;
}

export function setCurrentSport(sport) {
  _currentSport = sport;
}

let _pendingActivityId = null;

export function setPendingActivityId(id) {
  _pendingActivityId = id != null ? Number(id) : null;
}

export function consumePendingActivityId() {
  const id = _pendingActivityId;
  _pendingActivityId = null;
  return id;
}
