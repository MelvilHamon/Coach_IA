"""
extract_stades_athle.py — Extrait les stades / pistes d'athlétisme du dataset
data.gouv "Recensement des équipements sportifs" vers data/stades_athle.json.

Critères :
  - type ∈ {Stade d'athlétisme, Piste d'athlétisme isolée,
            Piste d'athlétisme 2 à 4 couloirs, Courses sur piste}
  - lat/lon valides

Longueur de piste :
  - piste_longueur > 50 m   → length_source = "official"
  - sinon, si type est un vrai stade → 400 m, length_source = "inferred_400"
  - sinon                    → null, length_source = "unknown"
"""

import json
import os
import sys

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC  = os.path.join(_ROOT, "data", "data-es-equipement.csv")
_OUT  = os.path.join(_ROOT, "data", "stades_athle.json")

ATHLE_TYPES = {
    "Stade d’athlétisme",
    "Piste d'athlétisme isolée",
    "Piste d'athlétisme 2 à 4 couloirs",
    "Courses sur piste",
}
INFER_400_TYPES = {"Stade d’athlétisme", "Piste d'athlétisme 2 à 4 couloirs"}

COLS = [
    "installation_numero", "numero", "nom", "commune", "type",
    "coordonnees_y", "coordonnees_x",
    "piste_longueur", "aire_nature_sol",
    "sae_couloirs_nb", "aire_eclairage",
]


def _length_and_source(row):
    lg = row["piste_longueur"]
    if pd.notna(lg) and lg > 50:
        return float(lg), "official"
    if row["type"] in INFER_400_TYPES:
        return 400.0, "inferred_400"
    return None, "unknown"


def main():
    df = pd.read_csv(_SRC, sep=";", low_memory=False, usecols=COLS)
    df = df[df["type"].isin(ATHLE_TYPES)]
    df = df[df["coordonnees_y"].notna() & df["coordonnees_x"].notna()]

    records = []
    for _, row in df.iterrows():
        length, source = _length_and_source(row)
        records.append({
            "installation_id": row["installation_numero"],
            "equipement_id": row["numero"],
            "nom": row["nom"],
            "commune": row["commune"],
            "type": row["type"],
            "lat": float(row["coordonnees_y"]),
            "lon": float(row["coordonnees_x"]),
            "piste_longueur_m": length,
            "length_source": source,
            "surface": row["aire_nature_sol"] if pd.notna(row["aire_nature_sol"]) else None,
            "couloirs_nb": int(row["sae_couloirs_nb"]) if pd.notna(row["sae_couloirs_nb"]) and row["sae_couloirs_nb"] > 0 else None,
            "eclairage": bool(row["aire_eclairage"]) if pd.notna(row["aire_eclairage"]) else None,
        })

    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    sources = pd.Series([r["length_source"] for r in records]).value_counts()
    print(f"[OK] {len(records)} stades écrits dans {_OUT}")
    print("Répartition length_source :")
    for k, v in sources.items():
        print(f"  {k:15s} {v:5d}")


if __name__ == "__main__":
    sys.exit(main())
