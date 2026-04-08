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
