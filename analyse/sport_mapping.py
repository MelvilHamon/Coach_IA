"""
sport_mapping.py — Mapping des types Strava vers catégories sport normalisées.

Catégories :
  - "run"   : course à pied (Run, TrailRun, VirtualRun)
  - "velo"  : vélo (Ride, VirtualRide, EBikeRide, Gravel, MountainBikeRide)
  - "autre" : tout le reste (Hike, Swim, Soccer, Workout, etc.)
"""

# Mapping exhaustif sport_type Strava → catégorie normalisée
_SPORT_MAP = {
    # Course à pied
    "Run":          "run",
    "TrailRun":     "run",
    "VirtualRun":   "run",
    # Vélo
    "Ride":              "velo",
    "VirtualRide":       "velo",
    "EBikeRide":         "velo",
    "Gravel":            "velo",
    "GravelRide":        "velo",
    "MountainBikeRide":  "velo",
    # Tout le reste → "autre"
}


def get_sport(strava_type: str) -> str:
    """Retourne la catégorie sport normalisée pour un type Strava."""
    return _SPORT_MAP.get(str(strava_type).strip(), "autre")


def is_run(strava_type: str) -> bool:
    return get_sport(strava_type) == "run"


def is_velo(strava_type: str) -> bool:
    return get_sport(strava_type) == "velo"


# Types de séances vélo
VELO_SESSION_TYPES = {
    "endurance vélo",
    "sortie longue vélo",
    "tempo vélo",
    "intervalles vélo",
    "récupération vélo",
}

# Types de séances running (existants)
RUN_SESSION_TYPES = {
    "endurance fondamentale",
    "fractionné court",
    "fractionné moyen",
    "fractionné long",
    "mixte",
    "tempo / seuil",
    "tempo / allure",
    "sortie longue",
    "trail",
    "récupération active",
}
