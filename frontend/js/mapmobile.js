/**
 * mapmobile.js — Comportement tactile et redimensionnement des cartes Leaflet.
 *
 * Deux problèmes que Leaflet ne règle pas seul sur téléphone :
 *
 *  1. Une carte pleine largeur capture le glissement vertical du doigt. On ne
 *     peut plus faire défiler la page dès qu'on la touche. Même parade que
 *     Google Maps embarqué : un voile transparent laisse passer le défilement,
 *     et un appui le retire pour rendre la carte manipulable.
 *  2. Une carte instanciée dans un conteneur qui change de taille (rotation de
 *     l'écran) garde ses anciennes dimensions tant qu'on ne la prévient pas.
 */

const MOBILE_QUERY = window.matchMedia('(max-width: 768px)');

/**
 * Branche voile tactile et recalcul de taille sur une carte.
 * @param {L.Map} map
 * @param {HTMLElement} container  l'élément qui porte la carte
 * @param {string} hint  texte affiché sur le voile
 */
export function attachMapMobile(map, container, hint = 'Appuyez pour explorer la carte') {
  let guard = null;

  function removeGuard() {
    if (guard) { guard.remove(); guard = null; }
    map.dragging.enable();
  }

  function addGuard() {
    if (guard || !container.isConnected) return;
    map.dragging.disable();
    guard = document.createElement('div');
    guard.className = 'ca-map-guard';
    guard.textContent = hint;
    // Un simple clic suffit : le voile capte l'appui, pas le glissement.
    guard.addEventListener('click', removeGuard, { once: true });
    container.appendChild(guard);
  }

  function sync() {
    if (MOBILE_QUERY.matches) addGuard(); else removeGuard();
  }

  sync();

  const onResize = () => {
    if (!container.isConnected) {
      window.removeEventListener('ca:resize', onResize);
      return;
    }
    map.invalidateSize();
    sync();
  };
  window.addEventListener('ca:resize', onResize);
}
