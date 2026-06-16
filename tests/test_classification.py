"""
tests/test_classification.py — Non-régression de la classification de séance.

Jeu de référence (vérité terrain) construit à partir de vraies activités, avec
leurs streams allégés (time_s, speed_kmh, bpm) dans tests/fixtures/streams/ et un
profil athlète figé dans tests/fixtures/test_config.json.

Couvre :
  - les vrais fractionnés (court/moyen/long/pyramide/mixte), dont le cas cible du
    2 juin (3×1km noyés dans un footing de 16 km) ;
  - les PIÈGES de sur-segmentation : runs continus dont DBSCAN tire de pseudo-blocs
    avec des récups de quelques secondes — ils ne doivent PAS être classés
    fractionné (garde-fou récup/effort) ;
  - les types non-fractionnés clairs (sortie longue, endurance, tempo, trail, récup).

But : tuner les heuristiques de détection sans régression. Toute modif de
detect_fract_v2 / session_classifier doit garder ce test vert.
"""

import json
import os
import sys

import pandas as pd
import pytest

# R2 désactivé : les streams sont lus en local depuis tests/fixtures/.
for _k in ("R2_BUCKET", "R2_ENDPOINT", "R2_ACCESS_KEY", "R2_SECRET_KEY"):
    os.environ.pop(_k, None)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "analyse"))

from analyse.session_classifier import detect_session_type  # noqa: E402

with open(os.path.join(_FIXTURES, "labeled_sessions.json"), encoding="utf-8") as f:
    _LABELED = json.load(f)

with open(os.path.join(_FIXTURES, "test_config.json"), encoding="utf-8") as f:
    _CONFIG = json.load(f)


def _activity_row(fix: dict) -> pd.Series:
    return pd.Series({
        "Type": fix["sport_type"],
        "Distance (km)": fix["distance_km"],
        "Temps (min)": fix["duration_min"],
        "Dénivelé (m)": fix["elevation_m"],
        "Fréquence cardiaque (bpm)": fix["hr_mean"],
    })


@pytest.mark.parametrize("fix", _LABELED, ids=[str(f["activity_id"]) for f in _LABELED])
def test_session_classification(fix):
    stream_path = os.path.join(_FIXTURES, "streams", f"{fix['activity_id']}.csv")
    assert os.path.exists(stream_path), f"stream manquant pour {fix['activity_id']}"
    got = detect_session_type(_activity_row(fix), stream_path=stream_path, config=_CONFIG)
    assert got == fix["expected_type"], (
        f"activité {fix['activity_id']} ({fix['notes']}): "
        f"attendu {fix['expected_type']!r}, obtenu {got!r}"
    )


def test_june_2_is_fractionne():
    """Régression dédiée : le 3×1km du 2 juin 2026 doit être un fractionné."""
    fix = next(f for f in _LABELED if f["activity_id"] == 18759381772)
    stream_path = os.path.join(_FIXTURES, "streams", "18759381772.csv")
    got = detect_session_type(_activity_row(fix), stream_path=stream_path, config=_CONFIG)
    assert got.startswith("fractionné"), f"obtenu {got!r}"
