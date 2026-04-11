"""
llm_review.py — Review LLM (GPT) par activite.

Genere une analyse coach structuree (JSON) pour n'importe quelle activite
via son ID Strava.  La review est mise en cache dans data/reviews/{activity_id}.json.

Usage CLI :
    python3 analyse/llm_review.py <activity_id> [--force]
    python3 analyse/llm_review.py          # derniere activite
"""

import json
import os
from datetime import timezone

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Legacy defaults (single-user fallback)
_DEFAULT_DATA_DIR = os.path.join(_ROOT, "data")
_DEFAULT_CONFIG = os.path.join(_ROOT, "config.json")


# ── Paths ────────────────────────────────────────────────────────────────────


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
        "enriched": os.path.join(d, "activities_enriched.csv"),
        "memoire": os.path.join(d, "memoire.txt"),
        "reviews_dir": os.path.join(d, "reviews"),
        "feedback_dir": os.path.join(d, "feedback"),
        "streams_dir": os.path.join(d, "streams"),
        "config": cfg,
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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fmt(v, unit: str = "", na: str = "N/A", decimals: int = 1) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return na
    if isinstance(v, float):
        return f"{v:.{decimals}f}{unit}"
    return f"{v}{unit}"


def _load_feedback(activity_id: int, feedback_dir: str) -> dict | None:
    """Charge le feedback utilisateur (ressentis) pour une activite."""
    path = os.path.join(feedback_dir, f"{activity_id}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def _load_splits(activity_id: int, streams_dir: str) -> str:
    """Charge les splits du stream si disponible (pour fractionnés)."""
    path = os.path.join(streams_dir, f"{activity_id}.csv")
    if not os.path.exists(path):
        return ""
    try:
        df = pd.read_csv(path)
        if "distance_m" not in df.columns or "time_s" not in df.columns:
            return ""

        # Calculer les splits au km
        total_dist = df["distance_m"].iloc[-1] if len(df) > 0 else 0
        if total_dist < 1000:
            return ""

        splits = []
        km_count = int(total_dist // 1000)
        for km in range(1, min(km_count + 1, 30)):  # max 30 splits
            target_m = km * 1000
            mask_before = df["distance_m"] <= target_m
            mask_after = df["distance_m"] > (km - 1) * 1000
            segment = df[mask_before & mask_after]
            if segment.empty:
                continue
            dt = segment["time_s"].iloc[-1] - segment["time_s"].iloc[0]
            if dt > 0:
                pace = dt / 60  # min/km approx
                m = int(pace)
                s = int((pace - m) * 60)
                splits.append(f"  km{km}: {m}:{s:02d}/km")

        if splits:
            return "Splits au km :\n" + "\n".join(splits)
    except Exception:
        pass
    return ""


# ── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Tu es un coach sportif expert en course a pied, trail et cyclisme.
Tu analyses les donnees d'entrainement avec precision et donnes des conseils
personnalises, concis et actionnables.

Tu maitrises les metriques suivantes et les utilises dans ton analyse :
- TRIMP / hrTSS : charge interne de la seance
- ACWR (Acute:Chronic Workload Ratio) : ratio charge aigue/chronique, optimal entre 0.8-1.3
- CTL/ATL/TSB (Fitness/Fatigue/Form) : modele Banister de la forme
- Monotonie & Strain : variabilite de la charge (monotonie > 2.0 = risque)
- Efficiency Factor : rapport vitesse/FC (progression = EF qui monte)
- Decouplage aerobie : derive FC (> 5% = endurance aerobie insuffisante)
- Zones FC (Z1-Z5) : repartition de l'effort

IMPORTANT : Tu reponds UNIQUEMENT avec un objet JSON valide (pas de markdown,
pas de texte avant/apres). Le JSON doit suivre exactement cette structure :

{
  "score": <int 1-10>,
  "resume": "<1 phrase de synthese>",
  "execution": "<analyse de l'execution de la seance, 2-3 phrases>",
  "charge": "<coherence avec la charge de la semaine, ACWR, tendance, 2-3 phrases>",
  "fatigue": "<signaux de fatigue ou de surcharge, TSB, monotonie, 2-3 phrases>",
  "conseil": "<conseil concret pour la prochaine sortie, 2-3 phrases>",
  "tags": ["<tag1>", "<tag2>"]
}

Regles pour les champs :
- score : note globale de la seance (1=mauvais, 5=correct, 8=tres bien, 10=exceptionnel)
- tags : 1-3 tags parmi ["bonne_seance", "surcharge", "sous_entrainement", "progression",
  "fatigue", "recuperation_ok", "decouplage_eleve", "monotonie", "pic_charge",
  "seance_cle", "endurance_solide", "intensite_elevee"]
- Toutes les valeurs sont en francais
"""


# ── Prompt builder ───────────────────────────────────────────────────────────


def _build_prompt(row: pd.Series, context: pd.DataFrame, memoire: str,
                  feedback: dict | None = None, splits_str: str = "") -> str:
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
        mn = row.get(f"{z}_min")
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
    risk_str = f"{_fmt(risk_score, decimals=0)}/100 — {risk_label}"
    flags = []
    for flag, label in [("flag_acwr", "ACWR eleve"), ("flag_monotony", "monotonie"),
                         ("flag_load_spike", "pic de charge"), ("flag_consecutive", "jours consecutifs")]:
        v = row.get(flag)
        if v is True or v == "True":
            flags.append(label)
    if flags:
        risk_str += f" (flags : {', '.join(flags)})"

    # Forme/fatigue (Banister)
    ctl_v = row.get("ctl")
    atl_v = row.get("atl")
    tsb_v = row.get("tsb")
    form_str = (f"CTL (fitness)={_fmt(ctl_v, decimals=0)}  "
                f"ATL (fatigue)={_fmt(atl_v, decimals=0)}  "
                f"TSB (form)={_fmt(tsb_v, decimals=0)}")
    if tsb_v and not (isinstance(tsb_v, float) and np.isnan(tsb_v)):
        if tsb_v < -20:
            form_str += " — FATIGUE ELEVEE"
        elif tsb_v > 15:
            form_str += " — bien repose"

    # Monotonie & Strain
    monotony_v = row.get("monotony")
    strain_v = row.get("strain")
    mono_str = _fmt(monotony_v)
    if monotony_v and not (isinstance(monotony_v, float) and np.isnan(monotony_v)):
        if monotony_v > 2.0:
            mono_str += " (ELEVEE — risque surmenage)"
        elif monotony_v > 1.5:
            mono_str += " (moderee)"
    strain_str = _fmt(strain_v, decimals=0)

    # Tendances long terme
    pace_trend = row.get("pace_trend_28d")
    ef_trend = row.get("ef_trend_28d")
    vo2max_est = row.get("vo2max_estimate")
    trend_parts = []
    if pace_trend and not (isinstance(pace_trend, float) and np.isnan(pace_trend)):
        direction = "amelioration" if pace_trend < 0 else "ralentissement"
        trend_parts.append(f"Allure 28j : {direction} ({pace_trend:+.2f} min/km)")
    if ef_trend and not (isinstance(ef_trend, float) and np.isnan(ef_trend)):
        direction = "amelioration" if ef_trend > 0 else "regression"
        trend_parts.append(f"EF 28j : {direction} ({ef_trend:+.4f})")
    if vo2max_est and not (isinstance(vo2max_est, float) and np.isnan(vo2max_est)):
        trend_parts.append(f"VO2max estime : {vo2max_est:.1f} mL/kg/min")
    trend_str = "\n  ".join(trend_parts) if trend_parts else "Donnees insuffisantes"

    # Contexte semaine
    week_str = (f"{_fmt(row.get('weekly_km'), ' km')} de volume, "
                f"{_fmt(row.get('weekly_elevation_m'), ' m D+', decimals=0)}")
    week_var = row.get("load_variation_pct")
    if week_var and not (isinstance(week_var, float) and np.isnan(week_var)):
        trend = "+" if week_var > 0 else ""
        week_str += f" — variation vs semaine prec. : {trend}{week_var:.0f}%"
        if abs(week_var) > 30:
            week_str += " (ATTENTION > 30%)"

    # Activites recentes
    recent_lines = []
    for _, r in context.tail(6).iterrows():
        if r["ID"] == row["ID"]:
            continue
        d = pd.to_datetime(r["Date"]).strftime("%d/%m")
        recent_lines.append(
            f"  - {d} — {r.get('session_type', r['Type'])} "
            f"{_fmt(r.get('Distance (km)'), ' km')}  "
            f"TRIMP={_fmt(r.get('trimp'), decimals=0)}  "
            f"TSB={_fmt(r.get('tsb'), decimals=0)}"
        )
    recent_str = "\n".join(recent_lines) if recent_lines else "  (aucune)"

    # Feedback utilisateur
    feedback_str = ""
    if feedback:
        diff = feedback.get("difficulty")
        sens = feedback.get("sensations")
        parts = []
        if diff:
            parts.append(f"Difficulte ressentie : {diff}/10")
        if sens:
            parts.append(f"Sensations : {sens}")
        if parts:
            feedback_str = "\nRessenti de l'athlete :\n  " + "\n  ".join(parts)

    # Vitesse (velo)
    dist_km = row.get("Distance (km)", 0) or 0
    dur_min = row.get("Temps (min)", 0) or 0
    speed_str = ""
    sport = row.get("sport", "run")
    if sport == "velo" and dist_km > 0 and dur_min > 0:
        speed_kmh = dist_km / (dur_min / 60)
        speed_str = f"\n  - Vitesse moy.  : {speed_kmh:.1f} km/h"

    date_fr = pd.to_datetime(row["Date"]).strftime("%d/%m/%Y")
    return f"""
Profil athlete :
{memoire if memoire else "Non renseigne"}

---
SEANCE DU {date_fr} — {row.get("Nom", "")} [{row.get("session_type", row.get("Type", "Run"))}]

Metriques cles :
  - Distance      : {_fmt(row.get("Distance (km)"), " km")}
  - Duree         : {_fmt(row.get("Temps (min)"), " min")}
  - Allure moy.   : {pace_str}{speed_str}
  - FC moy.       : {_fmt(row.get("Fréquence cardiaque (bpm)"), " bpm", decimals=0)}
  - Denivele      : {_fmt(row.get("Dénivelé (m)"), " m", decimals=0)}
  - TRIMP         : {_fmt(row.get("trimp"))}
  - hrTSS         : {_fmt(row.get("hrtss"))}
  - Efficiency F. : {_fmt(row.get("efficiency_factor"), decimals=4)}
  - Decouplage FC : {_fmt(row.get("decoupling_pct"), "%")}
  - ACWR (km)     : {acwr_str}

Zones FC :
{zones_str}
Charge et forme :
  Semaine       : {week_str}
  Banister      : {form_str}
  Monotonie     : {mono_str}
  Strain        : {strain_str}
  Risque        : {risk_str}

Tendances (28 derniers jours) :
  {trend_str}

Activites recentes (14 derniers jours) :
{recent_str}
{feedback_str}
{f"\\n{splits_str}" if splits_str else ""}
---
Reponds en francais avec un JSON valide.
""".strip()


# ── Generation ───────────────────────────────────────────────────────────────


def generate_review(
    activity_id: int,
    force: bool = False,
    data_dir: str | None = None,
    config_path: str | None = None,
) -> dict:
    """
    Genere (ou recharge depuis le cache) la review GPT structuree pour une activite.

    Retourne
    --------
    dict avec cles : activity_id, date, session_type, review_text, score, tags,
                     sections (dict), generated_at, model, cached
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
        raise ValueError(f"Activite {activity_id} introuvable dans {enriched}")

    row = df[mask].iloc[0]
    act_date = row["Date"]
    window = df[df["Date"] >= act_date - pd.Timedelta(days=14)].copy()

    memoire = ""
    if os.path.exists(paths["memoire"]):
        with open(paths["memoire"], encoding="utf-8") as f:
            memoire = f.read()

    # Feedback utilisateur
    feedback = _load_feedback(activity_id, paths["feedback_dir"])

    # Splits pour les fractionnés
    splits_str = ""
    session_type = str(row.get("session_type", ""))
    if "fractionn" in session_type.lower() or "tempo" in session_type.lower():
        splits_str = _load_splits(activity_id, paths["streams_dir"])

    config = _load_config(paths["config"])
    llm_cfg = config.get("llm", {})
    prompt = _build_prompt(row, window, memoire, feedback=feedback, splits_str=splits_str)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=llm_cfg.get("model", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=llm_cfg.get("temperature", 0.5),
        response_format={"type": "json_object"},
    )

    raw_content = resp.choices[0].message.content

    # Parse le JSON structure
    try:
        review_json = json.loads(raw_content)
    except json.JSONDecodeError:
        # Fallback : stocker le texte brut
        review_json = {
            "score": None,
            "resume": raw_content[:200] if raw_content else "",
            "execution": raw_content or "",
            "charge": "",
            "fatigue": "",
            "conseil": "",
            "tags": [],
        }

    # Construire le review_text lisible (retro-compatibilite)
    review_text_parts = []
    if review_json.get("resume"):
        review_text_parts.append(f"**Resume** : {review_json['resume']}")
    if review_json.get("execution"):
        review_text_parts.append(f"**1. Execution** : {review_json['execution']}")
    if review_json.get("charge"):
        review_text_parts.append(f"**2. Charge** : {review_json['charge']}")
    if review_json.get("fatigue"):
        review_text_parts.append(f"**3. Fatigue** : {review_json['fatigue']}")
    if review_json.get("conseil"):
        review_text_parts.append(f"**4. Conseil** : {review_json['conseil']}")
    review_text = "\n\n".join(review_text_parts)

    result = {
        "activity_id": activity_id,
        "date": act_date.strftime("%Y-%m-%d"),
        "session_type": session_type,
        "review_text": review_text,
        "score": review_json.get("score"),
        "tags": review_json.get("tags", []),
        "sections": {
            "resume": review_json.get("resume", ""),
            "execution": review_json.get("execution", ""),
            "charge": review_json.get("charge", ""),
            "fatigue": review_json.get("fatigue", ""),
            "conseil": review_json.get("conseil", ""),
        },
        "generated_at": pd.Timestamp.now(tz=timezone.utc).isoformat(),
        "model": llm_cfg.get("model", "gpt-4o-mini"),
        "cached": False,
    }
    _save(activity_id, result, paths["reviews_dir"])
    return result


# ── Bilan hebdomadaire ───────────────────────────────────────────────────────

WEEKLY_SYSTEM_PROMPT = """\
Tu es un coach sportif expert en course a pied, trail et cyclisme.
Tu analyses le bilan d'une semaine d'entrainement et donnes un feedback
structure et actionnable.

IMPORTANT : Tu reponds UNIQUEMENT avec un objet JSON valide :

{
  "score_semaine": <int 1-10>,
  "resume": "<1-2 phrases de synthese de la semaine>",
  "volume": "<analyse du volume et de la repartition, 2-3 phrases>",
  "intensite": "<analyse de l'intensite et de la charge, 2-3 phrases>",
  "recuperation": "<etat de recuperation, signes de fatigue, 2-3 phrases>",
  "prochaine_semaine": "<recommandations pour la semaine suivante, 3-4 phrases>",
  "tags": ["<tag1>", "<tag2>"]
}

Tags possibles : ["semaine_legere", "semaine_lourde", "bonne_progression",
"surcharge", "sous_entrainement", "equilibree", "trop_monotone",
"recuperation_necessaire", "pic_forme", "phase_construction"]
"""


def generate_weekly_review(
    user_data_dir: str,
    config_path: str | None = None,
    force: bool = False,
    week_offset: int = 0,
) -> dict:
    """
    Genere un bilan hebdomadaire LLM.

    Parameters
    ----------
    user_data_dir : repertoire de donnees utilisateur
    config_path : chemin vers config.json
    force : recalculer meme si cache existe
    week_offset : 0 = semaine en cours, 1 = semaine precedente, etc.
    """
    paths = _resolve_paths(user_data_dir, config_path)

    enriched = paths["enriched"]
    if not os.path.exists(enriched):
        raise FileNotFoundError(f"Fichier enrichi introuvable : {enriched}")

    df = pd.read_csv(enriched)
    df["Date"] = pd.to_datetime(df["Date"], utc=True)
    df = df.sort_values("Date")

    # Determiner la semaine cible
    now = pd.Timestamp.now(tz=timezone.utc)
    week_start = (now - pd.Timedelta(days=now.weekday()) - pd.Timedelta(weeks=week_offset)).normalize()
    week_end = week_start + pd.Timedelta(days=7)

    # Cache
    cache_key = week_start.strftime("%Y-W%W")
    cache_path = os.path.join(paths["reviews_dir"], f"weekly_{cache_key}.json")
    if not force and os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            cached = json.load(f)
        cached["cached"] = True
        return cached

    # Activites de la semaine
    week_mask = (df["Date"] >= week_start) & (df["Date"] < week_end)
    df_week = df[week_mask]

    if df_week.empty:
        return {
            "week": cache_key,
            "week_start": week_start.strftime("%Y-%m-%d"),
            "activities_count": 0,
            "error": "Aucune activite cette semaine",
            "cached": False,
        }

    # Semaine precedente pour comparaison
    prev_start = week_start - pd.Timedelta(weeks=1)
    prev_mask = (df["Date"] >= prev_start) & (df["Date"] < week_start)
    df_prev = df[prev_mask]

    # Construire le prompt
    memoire = ""
    if os.path.exists(paths["memoire"]):
        with open(paths["memoire"], encoding="utf-8") as f:
            memoire = f.read()

    # Liste des activites de la semaine
    act_lines = []
    total_km = 0
    total_elev = 0
    total_trimp = 0
    for _, r in df_week.iterrows():
        d = pd.to_datetime(r["Date"]).strftime("%A %d/%m")
        dist = float(r.get("Distance (km)", 0) or 0)
        elev = float(r.get("Dénivelé (m)", 0) or 0)
        trimp = float(r.get("trimp", 0) or 0) if not (isinstance(r.get("trimp"), float) and np.isnan(r.get("trimp", 0))) else 0
        total_km += dist
        total_elev += elev
        total_trimp += trimp
        act_lines.append(
            f"  - {d} : {r.get('session_type', r.get('Type', '?'))} — "
            f"{_fmt(dist, ' km')} — D+{_fmt(elev, ' m', decimals=0)} — "
            f"TRIMP={_fmt(trimp, decimals=0)} — "
            f"FC={_fmt(r.get('Fréquence cardiaque (bpm)'), ' bpm', decimals=0)}"
        )

    # Stats semaine precedente
    prev_km = sum(float(r.get("Distance (km)", 0) or 0) for _, r in df_prev.iterrows()) if not df_prev.empty else 0
    variation = ((total_km - prev_km) / prev_km * 100) if prev_km > 0 else 0

    # Derniere ligne de la semaine pour les indicateurs globaux
    last = df_week.iloc[-1]

    act_block = "\n".join(act_lines)
    type_counts = pd.Series([r.get("session_type", "?") for _, r in df_week.iterrows()]).value_counts().to_string()

    prompt = f"""
Profil athlete :
{memoire if memoire else "Non renseigne"}

---
BILAN SEMAINE du {week_start.strftime("%d/%m/%Y")} au {(week_end - pd.Timedelta(days=1)).strftime("%d/%m/%Y")}

Activites ({len(df_week)} seances) :
{act_block}

Totaux semaine :
  - Volume     : {total_km:.1f} km
  - Denivele   : {total_elev:.0f} m D+
  - TRIMP total: {total_trimp:.0f}
  - Variation vs semaine prec. : {variation:+.0f}% ({prev_km:.1f} km -> {total_km:.1f} km)

Indicateurs de forme (fin de semaine) :
  - CTL (fitness) : {_fmt(last.get("ctl"), decimals=0)}
  - ATL (fatigue) : {_fmt(last.get("atl"), decimals=0)}
  - TSB (form)    : {_fmt(last.get("tsb"), decimals=0)}
  - ACWR          : {_fmt(last.get("acwr_km"))}
  - Monotonie     : {_fmt(last.get("monotony"))}
  - Strain        : {_fmt(last.get("strain"), decimals=0)}
  - Risque        : {_fmt(last.get("injury_risk_score"), decimals=0)}/100 — {last.get("injury_risk_label", "N/A")}

Repartition types :
{type_counts}

---
Reponds en francais avec un JSON valide.
""".strip()

    config = _load_config(paths["config"])
    llm_cfg = config.get("llm", {})

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model=llm_cfg.get("model", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": WEEKLY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=llm_cfg.get("temperature", 0.5),
        response_format={"type": "json_object"},
    )

    try:
        review_json = json.loads(resp.choices[0].message.content)
    except json.JSONDecodeError:
        review_json = {"resume": resp.choices[0].message.content, "score_semaine": None, "tags": []}

    result = {
        "week": cache_key,
        "week_start": week_start.strftime("%Y-%m-%d"),
        "activities_count": len(df_week),
        "total_km": round(total_km, 1),
        "total_elevation": round(total_elev, 0),
        "total_trimp": round(total_trimp, 0),
        "score": review_json.get("score_semaine"),
        "tags": review_json.get("tags", []),
        "sections": {
            "resume": review_json.get("resume", ""),
            "volume": review_json.get("volume", ""),
            "intensite": review_json.get("intensite", ""),
            "recuperation": review_json.get("recuperation", ""),
            "prochaine_semaine": review_json.get("prochaine_semaine", ""),
        },
        "generated_at": pd.Timestamp.now(tz=timezone.utc).isoformat(),
        "model": llm_cfg.get("model", "gpt-4o-mini"),
        "cached": False,
    }

    os.makedirs(paths["reviews_dir"], exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


# ── CLI ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import sys

    paths = _resolve_paths()

    if "--weekly" in sys.argv:
        offset = 0
        for i, arg in enumerate(sys.argv):
            if arg == "--offset" and i + 1 < len(sys.argv):
                offset = int(sys.argv[i + 1])
        result = generate_weekly_review(
            _DEFAULT_DATA_DIR,
            force="--force" in sys.argv,
            week_offset=offset,
        )
        print(f"\n{'='*60}")
        print(f"  BILAN SEMAINE {result['week']} — {result['activities_count']} seances")
        print(f"{'='*60}")
        sections = result.get("sections", {})
        for key in ["resume", "volume", "intensite", "recuperation", "prochaine_semaine"]:
            if sections.get(key):
                print(f"\n{key.upper()} :\n{sections[key]}")
        print(f"\nScore : {result.get('score', '?')}/10")
        print(f"Tags : {', '.join(result.get('tags', []))}")
    else:
        if len(sys.argv) < 2 or sys.argv[1].startswith("--"):
            df = pd.read_csv(paths["enriched"])
            aid = int(df["ID"].iloc[-1])
            print(f"Aucun ID fourni — revue de la derniere activite ({aid})")
        else:
            aid = int(sys.argv[1])

        result = generate_review(aid, force="--force" in sys.argv)
        print(f"\n{'='*60}")
        print(f"Review {'(cache)' if result['cached'] else '(nouveau)'} — "
              f"{result['date']} [{result['session_type']}]")
        print(f"Score : {result.get('score', '?')}/10  Tags : {', '.join(result.get('tags', []))}")
        print(f"{'='*60}\n")
        print(result.get("review_text", ""))
