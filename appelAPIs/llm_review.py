"""
llm_review.py — Review LLM (GPT) par activité.

Étend appelChat.py pour permettre la review de n'importe quelle activité
(pas seulement la dernière) via un paramètre activity_id.

La review est mise en cache dans data/reviews/{activity_id}.json.
"""

import json
import os

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def _load_cached_review(activity_id: int, reviews_dir: str) -> dict | None:
    path = _review_path(activity_id, reviews_dir)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def _save_review(activity_id: int, review: dict, reviews_dir: str) -> None:
    os.makedirs(reviews_dir, exist_ok=True)
    with open(_review_path(activity_id, reviews_dir), "w", encoding="utf-8") as f:
        json.dump(review, f, indent=2, ensure_ascii=False)


def _format_value(v, unit: str = "", na: str = "N/A") -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return na
    if isinstance(v, float):
        return f"{v:.1f}{unit}"
    return f"{v}{unit}"


def _build_prompt(row: pd.Series, context_week: pd.DataFrame, memoire: str) -> str:
    """Construit le prompt enrichi pour GPT."""

    # ── Métriques de la séance ────────────────────────────────────────────────
    pace_raw = row.get("Allure (min/km)")
    if pace_raw and not (isinstance(pace_raw, float) and pd.isna(pace_raw)):
        m = int(pace_raw)
        s = int((pace_raw - m) * 60)
        pace_str = f"{m}:{s:02d} min/km"
    else:
        pace_str = "N/A"

    zones_str = ""
    for z in ("z1", "z2", "z3", "z4", "z5"):
        pct = row.get(f"{z}_pct")
        min_ = row.get(f"{z}_min")
        if pct and not (isinstance(pct, float) and pd.isna(pct)):
            zones_str += f"    {z.upper()} : {pct:.0f}% ({min_:.0f} min)\n"
    if not zones_str:
        zones_str = "    Non disponible (pas de stream FC)\n"

    acwr_val = row.get("acwr_km")
    acwr_str = _format_value(acwr_val)
    if acwr_val and not (isinstance(acwr_val, float) and pd.isna(acwr_val)):
        from analyse.metrics import acwr_label
        acwr_str += f" ({acwr_label(float(acwr_val))})"

    # ── Contexte de la semaine ────────────────────────────────────────────────
    week_km    = row.get("weekly_km")
    week_elev  = row.get("weekly_elevation_m")
    week_var   = row.get("load_variation_pct")
    week_str   = f"{_format_value(week_km, ' km')} de volume, {_format_value(week_elev, ' m D+')}"
    if week_var and not (isinstance(week_var, float) and pd.isna(week_var)):
        trend = "↑" if week_var > 0 else "↓"
        week_str += f" — variation vs semaine précédente : {trend}{abs(week_var):.0f}%"
        if abs(week_var) > 30:
            week_str += " ⚠️ variation > 30%"

    context_acts = context_week.tail(5)
    context_lines = []
    for _, r in context_acts.iterrows():
        if r["ID"] == row["ID"]:
            continue
        d = pd.to_datetime(r["Date"]).strftime("%d/%m")
        context_lines.append(
            f"  • {d} — {r.get('session_type', r['Type'])} "
            f"{_format_value(r.get('Distance (km)'), ' km')} "
            f"TRIMP={_format_value(r.get('trimp'))}"
        )
    recent_str = "\n".join(context_lines) if context_lines else "  (aucune activité récente)"

    # ── Prompt ────────────────────────────────────────────────────────────────
    date_fr = pd.to_datetime(row["Date"]).strftime("%d/%m/%Y")
    prompt = f"""
Profil athlète :
{memoire}

---
SÉANCE DU {date_fr} — {row.get("Nom", "")} [{row.get("session_type", row.get("Type", "Run"))}]

Métriques clés :
  • Distance      : {_format_value(row.get("Distance (km)"), " km")}
  • Durée         : {_format_value(row.get("Temps (min)"), " min")}
  • Allure moy.   : {pace_str}
  • FC moy.       : {_format_value(row.get("Fréquence cardiaque (bpm)"), " bpm")}
  • Dénivelé      : {_format_value(row.get("Dénivelé (m)"), " m")}
  • TRIMP         : {_format_value(row.get("trimp"))}
  • hrTSS         : {_format_value(row.get("hrtss"))}
  • Efficiency F. : {_format_value(row.get("efficiency_factor"))}
  • Découplag FC  : {_format_value(row.get("decoupling_pct"), "%")}
  • ACWR (7/28j)  : {acwr_str}

Zones FC (% FC_max) :
{zones_str}
Contexte semaine :
  {week_str}

Activités récentes (5 dernières) :
{recent_str}

---
Réponds en français. Structure ta réponse en 4 parties courtes :
1. Qualité de la séance (exécution, cohérence avec le type détecté)
2. Cohérence avec la charge de la semaine (volume, ACWR, tendance)
3. Signaux de fatigue ou de surcharge à surveiller
4. Conseil concret pour la prochaine sortie
"""
    return prompt.strip()


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
    dict avec clés : activity_id, date, session_type, review (str), cached (bool)
    """
    paths = _resolve_paths(data_dir, config_path)

    if not force:
        cached = _load_cached_review(activity_id, paths["reviews_dir"])
        if cached:
            cached["cached"] = True
            return cached

    # Charger les données enrichies
    enriched = paths["enriched"]
    if not os.path.exists(enriched):
        raise FileNotFoundError(
            f"Fichier enrichi introuvable : {enriched}\n"
            "Lancer d'abord : python3 analyse/run_analysis.py"
        )

    df = pd.read_csv(enriched)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)

    row_mask = df["ID"] == activity_id
    if not row_mask.any():
        raise ValueError(f"Activité {activity_id} introuvable dans {enriched}")

    row = df[row_mask].iloc[0]
    act_date = row["Date"]

    # Contexte : activités des 14 derniers jours
    window_start = act_date - pd.Timedelta(days=14)
    context_week = df[df["Date"] >= window_start].copy()

    # Profil athlète
    memoire = ""
    if os.path.exists(paths["memoire"]):
        with open(paths["memoire"], encoding="utf-8") as f:
            memoire = f.read()

    config  = _load_config(paths["config"])
    llm_cfg = config.get("llm", {})
    prompt  = _build_prompt(row, context_week, memoire)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=llm_cfg.get("model", "gpt-4o-mini"),
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un coach sportif expert en course à pied et trail. "
                    "Tu analyses les données d'entraînement avec précision et donnes des conseils "
                    "personnalisés, concis et actionnables. Tu te bases sur les métriques de charge "
                    "(TRIMP, hrTSS, ACWR), les zones FC et la progression à long terme."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=llm_cfg.get("temperature", 0.7),
    )

    review_text = response.choices[0].message.content

    result = {
        "activity_id":   activity_id,
        "date":          act_date.strftime("%Y-%m-%d"),
        "session_type":  str(row.get("session_type", "")),
        "review":        review_text,
        "model":         llm_cfg.get("model", "gpt-4o-mini"),
        "cached":        False,
    }
    _save_review(activity_id, result, paths["reviews_dir"])
    return result


# ── CLI direct ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    paths = _resolve_paths()
    if len(sys.argv) < 2:
        # Dernière activité par défaut
        df = pd.read_csv(paths["enriched"])
        act_id = int(df["ID"].iloc[-1])
        print(f"Aucun ID fourni — revue de la dernière activité ({act_id})")
    else:
        act_id = int(sys.argv[1])

    result = generate_review(act_id, force=("--force" in sys.argv))
    print(f"\n{'─'*60}")
    print(f"Review {'(cache)' if result['cached'] else '(nouveau)'} — {result['date']} [{result['session_type']}]")
    print(f"{'─'*60}\n")
    print(result["review"])
