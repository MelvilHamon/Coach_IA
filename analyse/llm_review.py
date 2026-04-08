"""
llm_review.py — Review LLM (GPT) par activité.

Génère une analyse coach pour n'importe quelle activité via son ID Strava.
La review est mise en cache dans data/reviews/{activity_id}.json.

Usage CLI :
    python3 analyse/llm_review.py <activity_id> [--force]
    python3 analyse/llm_review.py          # dernière activité
"""

import json
import os
from datetime import timezone

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Legacy defaults (single-user fallback)
_DEFAULT_DATA_DIR = os.path.join(_ROOT, "data")
_DEFAULT_CONFIG   = os.path.join(_ROOT, "config.json")


def _resolve_paths(data_dir: str | None = None, config_path: str | None = None) -> dict:
    """Resolve all paths, user-scoped if data_dir is provided."""
    d = data_dir or _DEFAULT_DATA_DIR
    if config_path:
        cfg = config_path
    elif data_dir:
        cfg = os.path.join(d, "config.json")
    else:
        cfg = _DEFAULT_CONFIG
    return {
        "enriched":    os.path.join(d, "activities_enriched.csv"),
        "memoire":     os.path.join(d, "memoire.txt"),
        "reviews_dir": os.path.join(d, "reviews"),
        "config":      cfg,
    }


def _load_config(config_path: str) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def _review_path(activity_id: int, reviews_dir: str) -> str:
    return os.path.join(reviews_dir, f"{activity_id}.json")


def _load_cached(activity_id: int, reviews_dir: str) -> dict | None:
    p = _review_path(activity_id, reviews_dir)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save(activity_id: int, data: dict, reviews_dir: str) -> None:
    os.makedirs(reviews_dir, exist_ok=True)
    with open(_review_path(activity_id, reviews_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _fmt(v, unit: str = "", na: str = "N/A", decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return na
    if isinstance(v, float):
        return f"{v:.{decimals}f}{unit}"
    return f"{v}{unit}"


def _build_prompt(row: pd.Series, context: pd.DataFrame, memoire: str) -> str:
    # Allure
    pace_raw = row.get("Allure (min/km)")
    if pace_raw and not (isinstance(pace_raw, float) and np.isnan(pace_raw)):
        m, s = int(pace_raw), int((pace_raw - int(pace_raw)) * 60)
        pace_str = f"{m}:{s:02d} min/km"
    else:
        pace_str = "N/A"

    # Zones FC
    zones_str = ""
    for z in ("z1", "z2", "z3", "z4", "z5"):
        pct = row.get(f"{z}_pct")
        mn  = row.get(f"{z}_min")
        if pct and not (isinstance(pct, float) and np.isnan(pct)):
            zones_str += f"    {z.upper()} : {pct:.0f}% ({mn:.0f} min)\n"
    if not zones_str:
        zones_str = "    Non disponible (pas de stream FC)\n"

    # ACWR avec label
    from metrics import acwr_label
    acwr_val = row.get("acwr_km")
    acwr_str = _fmt(acwr_val)
    if acwr_val and not (isinstance(acwr_val, float) and np.isnan(acwr_val)):
        acwr_str += f" ({acwr_label(float(acwr_val))})"

    # Risque blessure
    risk_score = row.get("injury_risk_score")
    risk_label = row.get("injury_risk_label", "N/A")
    risk_str   = f"{_fmt(risk_score, decimals=0)}/100 — {risk_label}"
    flags = []
    for flag, label in [("flag_acwr", "ACWR élevé"), ("flag_monotony", "monotonie"),
                         ("flag_load_spike", "pic de charge"), ("flag_consecutive", "jours consécutifs")]:
        v = row.get(flag)
        if v is True or v == "True":
            flags.append(label)
    if flags:
        risk_str += f" (flags : {', '.join(flags)})"

    # Forme/fatigue
    form_str = (f"fitness={_fmt(row.get('fitness_score'), decimals=0)}  "
                f"fatigue={_fmt(row.get('fatigue_score'), decimals=0)}  "
                f"form={_fmt(row.get('form_score'), decimals=0)}")

    # Contexte semaine
    week_str = (f"{_fmt(row.get('weekly_km'), ' km')} de volume, "
                f"{_fmt(row.get('weekly_elevation_m'), ' m D+', decimals=0)}")
    week_var = row.get("load_variation_pct")
    if week_var and not (isinstance(week_var, float) and np.isnan(week_var)):
        trend = "↑" if week_var > 0 else "↓"
        week_str += f" — variation : {trend}{abs(week_var):.0f}%"
        if abs(week_var) > 30:
            week_str += " ⚠️"

    # Activités récentes
    recent_lines = []
    for _, r in context.tail(5).iterrows():
        if r["ID"] == row["ID"]:
            continue
        d = pd.to_datetime(r["Date"]).strftime("%d/%m")
        recent_lines.append(
            f"  • {d} — {r.get('session_type', r['Type'])} "
            f"{_fmt(r.get('Distance (km)'), ' km')}  "
            f"TRIMP={_fmt(r.get('trimp'), decimals=0)}"
        )
    recent_str = "\n".join(recent_lines) if recent_lines else "  (aucune)"

    date_fr = pd.to_datetime(row["Date"]).strftime("%d/%m/%Y")
    return f"""
Profil athlète :
{memoire}

---
SÉANCE DU {date_fr} — {row.get("Nom", "")} [{row.get("session_type", row.get("Type", "Run"))}]

Métriques clés :
  • Distance      : {_fmt(row.get("Distance (km)"), " km")}
  • Durée         : {_fmt(row.get("Temps (min)"), " min")}
  • Allure moy.   : {pace_str}
  • FC moy.       : {_fmt(row.get("Fréquence cardiaque (bpm)"), " bpm", decimals=0)}
  • Dénivelé      : {_fmt(row.get("Dénivelé (m)"), " m", decimals=0)}
  • TRIMP         : {_fmt(row.get("trimp"))}
  • hrTSS         : {_fmt(row.get("hrtss"))}
  • Efficiency F. : {_fmt(row.get("efficiency_factor"), decimals=4)}
  • Découplag FC  : {_fmt(row.get("decoupling_pct"), "%")}
  • VO2max estimé : {_fmt(row.get("vo2max_estimate"), " mL/kg/min")}
  • ACWR (km)     : {acwr_str}

Zones FC :
{zones_str}
Charge et forme :
  Semaine  : {week_str}
  TSB      : {form_str}
  Risque   : {risk_str}

Activités récentes (14 derniers jours) :
{recent_str}

---
Réponds en français. Structure ta réponse en 4 parties courtes :
1. Qualité de la séance (exécution, cohérence avec le type détecté)
2. Cohérence avec la charge de la semaine (volume, ACWR, tendance)
3. Signaux de fatigue ou de surcharge à surveiller
4. Conseil concret pour la prochaine sortie
""".strip()


def generate_review(
    activity_id: int,
    force: bool = False,
    data_dir: str | None = None,
    config_path: str | None = None,
) -> dict:
    """
    Génère (ou recharge depuis le cache) la review GPT pour une activité.

    Paramètres
    ----------
    activity_id : ID Strava de l'activité
    force       : recalculer même si le cache existe
    data_dir    : répertoire de données utilisateur (défaut: data/)
    config_path : chemin vers config.json (défaut: config.json racine)

    Retourne
    --------
    dict avec clés : activity_id, date, session_type, review_text, generated_at, cached
    """
    paths = _resolve_paths(data_dir, config_path)

    if not force:
        cached = _load_cached(activity_id, paths["reviews_dir"])
        if cached:
            cached["cached"] = True
            return cached

    enriched = paths["enriched"]
    if not os.path.exists(enriched):
        raise FileNotFoundError(
            f"Fichier enrichi introuvable : {enriched}\n"
            "Lancer d'abord : python3 analyse/run_analysis.py"
        )

    df = pd.read_csv(enriched)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)

    mask = df["ID"] == activity_id
    if not mask.any():
        raise ValueError(f"Activité {activity_id} introuvable dans {enriched}")

    row      = df[mask].iloc[0]
    act_date = row["Date"]
    window   = df[df["Date"] >= act_date - pd.Timedelta(days=14)].copy()

    memoire = ""
    if os.path.exists(paths["memoire"]):
        with open(paths["memoire"], encoding="utf-8") as f:
            memoire = f.read()

    config  = _load_config(paths["config"])
    llm_cfg = config.get("llm", {})
    prompt  = _build_prompt(row, window, memoire)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp   = client.chat.completions.create(
        model=llm_cfg.get("model", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un coach sportif expert en course à pied et trail. "
                    "Tu analyses les données d'entraînement avec précision et donnes "
                    "des conseils personnalisés, concis et actionnables. Tu te bases "
                    "sur les métriques de charge (TRIMP, hrTSS, ACWR), les zones FC, "
                    "le TSB et la progression à long terme."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=llm_cfg.get("temperature", 0.7),
    )

    result = {
        "activity_id":  activity_id,
        "date":         act_date.strftime("%Y-%m-%d"),
        "session_type": str(row.get("session_type", "")),
        "review_text":  resp.choices[0].message.content,
        "generated_at": pd.Timestamp.now(tz=timezone.utc).isoformat(),
        "model":        llm_cfg.get("model", "gpt-4o-mini"),
        "cached":       False,
    }
    _save(activity_id, result, paths["reviews_dir"])
    return result


if __name__ == "__main__":
    import sys

    paths = _resolve_paths()
    if len(sys.argv) < 2:
        df  = pd.read_csv(paths["enriched"])
        aid = int(df["ID"].iloc[-1])
        print(f"Aucun ID fourni — revue de la dernière activité ({aid})")
    else:
        aid = int(sys.argv[1])

    result = generate_review(aid, force="--force" in sys.argv)
    print(f"\n{'─'*60}")
    print(f"Review {'(cache)' if result['cached'] else '(nouveau)'} — "
          f"{result['date']} [{result['session_type']}]")
    print(f"{'─'*60}\n")
    print(result["review_text"])
