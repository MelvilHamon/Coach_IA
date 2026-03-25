# CoachAgent — Contexte Projet
## Modèle recommandé
- Architecture / nouveaux modules / debugging complexe → demander à utiliser Opus
- Corrections CSS / petits bugs / ajouts dans un fichier existant → Sonnet suffit

## Vision
Dashboard de suivi d'entraînement running/trail personnel.
Pipeline Python complet → API FastAPI → Frontend HTML/CSS/JS natif.

## Stack
- Python 3.12, FastAPI, uvicorn
- HTML/CSS/JS natif (pas de framework frontend)
- Plotly pour les graphiques, Mapbox/Leaflet pour la carte GPS
- Garmin Connect API (garminconnect + garth pour l'auth token)
- Strava API (OAuth2)
- OpenAI GPT pour les reviews d'activité

## Architecture
```
CoachAgent/
  appelAPIs/
    RecupDataStrava.py      ← sync activités Strava (pagination, rate-limit)
    get_streams.py          ← streams Strava (FC, vitesse, altitude)
    sync_garmin.py          ← sync autonome Garmin (une seule connexion)
    sync_garmin_gps.py      ← matching Strava→Garmin + stockage GPS
    get_garmin_gps.py       ← fetch GPS unitaire, _garmin_login() avec token garth
    garmin_auth.py          ← auth initiale Garmin, génère .garth/
    match_strava_garmin.py  ← matching post-processing par score multicritère

  analyse/
    detect_fract_v2.py      ← détection fractionné (GMM + machine à états + DBSCAN)
    session_classifier.py   ← classification séance (8 types)
    metrics.py              ← TRIMP, hrTSS, ACWR EWMA, zones FC, EF, decoupling
    gps_metrics.py          ← haversine, vitesse lissée Savitzky-Golay, GAP, D+
    run_analysis.py         ← pipeline principal → activities_enriched.csv
    llm_review.py           ← review GPT par activité, cache dans data/reviews/

  backend/
    app.py                  ← init FastAPI, startup auto-sync
    api/
      routes/
        sync.py             ← POST /api/sync, GET /api/sync/status
        activities.py       ← /api/activities, /api/activities/{id}
        metrics.py          ← /api/metrics/weekly, /api/metrics/acwr
        gps.py              ← /api/gps/{activity_id}
        review.py           ← /api/review/{activity_id}
      deps.py               ← cache mtime, chargement données

  frontend/
    index.html
    css/style.css
    js/
      app.js                ← routing, init, sync auto
      api.js                ← fetch helpers, syncStart(), syncStatus()
      charts.js             ← graphiques Plotly
      map.js                ← carte GPS
      components.js         ← cards, tableau, métriques

  data/
    mes_activites_strava.csv
    activities_enriched.csv ← source principale dashboard
    sync_state.json         ← état des syncs
    streams/                ← streams Strava {activity_id}.csv
    gps/                    ← GPS matchés {strava_id}.json
    garmin/
      activities.json       ← index Garmin complet
      streams/              ← GPS brut {garmin_id}.json
      metrics/              ← métriques GPS calculées {garmin_id}.json
      strava_garmin_map.json← mapping {strava_id: garmin_id}
    reviews/                ← reviews GPT {activity_id}.json
    personal_records.json   ← PR par distance

  config.json               ← paramètres athlète + seuils détection
  .garth/                   ← token OAuth Garmin (gitignore)
  .env                      ← GARMIN_EMAIL, GARMIN_PASSWORD, clés API
```

## Données disponibles
- **activities_enriched.csv** : toutes les activités avec TRIMP, hrTSS, zones FC,
  EF, decoupling, session_type, ACWR, weekly_km, injury_risk_score, fitness,
  fatigue, form_score, training_monotony, training_strain, vo2max_estimate
- **Garmin streams** : lat, lon, time_s, altitude_m — ~89 activités avec GPS
- **Strava streams** : time_s, speed_kmh, bpm, altitude_m

## Pipeline ordre de sync
1. sync_garmin.sync_all()          ← Garmin en premier
2. match_strava_garmin             ← matching en mémoire sur index locaux
3. RecupDataStrava.sync_activities()
4. get_streams.sync_all_streams()
5. run_analysis.run_analysis()

## Types de séances détectés
fractionné court / moyen / long / mixte / pyramide symétrique / ascendante /
descendante / tempo-allure / endurance fondamentale / sortie longue / trail /
récupération active / randonnée / autre

## DA Frontend
- Fonts : Cormorant Garamond (titres) + JetBrains Mono (données/labels)
- Palette : #F7F4F0 bg / #141414 ink / #D4380D accent / #2D6A4F success /
  #991B1B danger / #B45309 warning
- Zéro emoji, zéro propriété Plotly dépréciée (titlefont interdit)

## Onglets dashboard
1. Vue d'ensemble — métriques semaine, volume 16 semaines, ACWR
2. Profil — Personal Records par distance, stats globales
3. Historique — tableau filtrable, détail par activité
4. Progression — allure, EF, VO2max estimé
5. Charge — Fitness/Fatigue/Forme, ACWR 90j, Monotony/Strain
6. Analyse — sélecteur activité, carte GPS, profils vitesse/altitude, review LLM

## Fichiers à ne jamais modifier
detect_fract_v2.py, session_classifier.py, gps_metrics.py

## État actuel
<!-- Mettre à jour à chaque session -->
- Dernière feature implémentée :
- Bugs connus :
- Prochaine priorité :