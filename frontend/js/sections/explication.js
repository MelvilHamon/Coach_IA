/**
 * explication.js — Glossaire des métriques affichées dans PacePilot.
 */

import { el, sectionTitle } from '../components.js';
import { t } from '../i18n.js';

const METRICS = [
  {
    name: 'Charge d\'entraînement',
    alias: 'TRIMP',
    short: 'Combien d\'effort tu as fourni sur une séance.',
    long: 'Quantité d\'effort accumulée, calculée à partir de la durée et de la fréquence cardiaque. Une grosse séance dure longtemps et fait monter le cœur — elle compte beaucoup. Une sortie facile en compte peu. C\'est l\'unité de base pour comparer tes journées entre elles.',
  },
  {
    name: 'Indice de surcharge',
    alias: 'ACWR',
    short: 'Est-ce que tu en fais trop d\'un coup ?',
    long: 'Compare ta charge des 7 derniers jours à celle des 4 dernières semaines. Au-dessus de 1.3, ta charge récente dépasse nettement ton habitude — c\'est là que les blessures arrivent. Entre 0.8 et 1.3 : tu progresses sans casser. Sous 0.8 : tu décharges (utile, mais pas en continu).',
  },
  {
    name: 'Stress cardiaque',
    alias: 'hrTSS',
    short: 'À quel point une séance a sollicité ton cœur.',
    long: 'Score normalisé entre 0 et ~150 par séance, basé sur le temps passé dans chaque zone de fréquence cardiaque et ton seuil. 100 = une heure pile à intensité seuil. C\'est plus précis que la simple durée pour comparer une sortie courte intense à une sortie longue tranquille.',
  },
  {
    name: 'Efficacité cardio',
    alias: 'EF',
    short: 'Est-ce que tu cours plus vite pour le même cœur ?',
    long: 'Rapport vitesse / fréquence cardiaque. Si à FC égale tu vas plus vite qu\'il y a un mois, ton EF monte : ton système aéro­bie s\'améliore. C\'est l\'indicateur de progression aérobie le plus stable, à condition de comparer des sorties similaires (même type, même chaleur).',
  },
  {
    name: 'Forme',
    alias: 'TSB',
    short: 'Es-tu frais ou cramé là, maintenant ?',
    long: 'Différence entre ta condition chronique (fitness sur 6 semaines) et ta fatigue aiguë (sur 1 semaine). Positif = tu es récupéré, prêt à performer. Négatif = tu accumules de la fatigue, normal en bloc d\'entraînement mais à ne pas tenir trop longtemps.',
  },
  {
    name: 'Endurance fondamentale',
    alias: 'Z1–Z3',
    short: 'Les minutes passées en aisance respiratoire.',
    long: 'Temps cumulé sous 80% de ta FC max — l\'allure où tu peux tenir une conversation. La règle des 80/20 dit que ~80% du volume hebdomadaire doit se faire ici. C\'est ce qui construit ta caisse sans accumuler de fatigue inutile.',
  },
  {
    name: 'Seuil et au-delà',
    alias: 'Z4–Z5',
    short: 'Les minutes vraiment dures.',
    long: 'Temps cumulé au-dessus de 80% FC max : tempo rapide, seuil, VO2max. Très efficace mais coûteux à récupérer. ~20% du volume hebdo suffit pour progresser sans casser.',
  },
];

function metricBlock(m) {
  return el('div', { className: 'ca-metric-glossary' },
    el('div', { className: 'ca-metric-glossary-head' },
      el('span', { className: 'ca-metric-glossary-name' }, m.name),
      el('span', { className: 'ca-metric-glossary-alias' }, m.alias),
    ),
    el('div', { className: 'ca-metric-glossary-short' }, m.short),
    el('div', { className: 'ca-metric-glossary-long' }, m.long),
  );
}

export async function renderExplication(container) {
  container.innerHTML = '';

  const intro = el('div', { className: 'ca-section' },
    sectionTitle('Comprendre tes métriques'),
    el('p', { className: 'ca-metric-explain', style: { maxWidth: '720px', fontSize: '13px', marginBottom: '8px' } },
      'PacePilot s\'appuie sur des indicateurs scientifiques (Banister, Foster, Hulin, Seiler) renommés ici pour qu\'ils parlent en français courant. Voici à quoi chacun sert au quotidien.',
    ),
  );
  container.appendChild(intro);

  const list = el('div', { className: 'ca-glossary-list' });
  for (const m of METRICS) list.appendChild(metricBlock(m));
  container.appendChild(list);
}
