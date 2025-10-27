import pandas as pd
import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler
from scipy.ndimage import gaussian_filter1d
import os


#load data
def load_stream(activity_path):
    df = pd.read_csv(activity_path)
    df["speed_kmh"] = gaussian_filter1d(df["speed_kmh"].ffill(), sigma=2)
    df["bpm"] = gaussian_filter1d(df["bpm"].ffill(), sigma=2)
    return df


# detect intervals of effort based on speed
def detect_intervals(df, min_duration=40, hold_below=10):
    """Détecte les blocs d’effort robustes (anti-bruit)."""
    max_speed = df["speed_kmh"].max()
    effort_threshold = 0.75 * max_speed  # seuil basé sur max
    
    inside = False
    start_time = None
    intervals = []
    below_counter = 0

    for i, speed in enumerate(df["speed_kmh"]):
        t = df.loc[i, "time_s"]

        if not inside and speed > effort_threshold:
            start_time = t
            inside = True
            below_counter = 0

        elif inside:
            if speed < effort_threshold:
                below_counter += 1
            else:
                below_counter = 0

            # Fin si vitesse < seuil pendant X secondes consécutives
            if below_counter >= hold_below:
                end_time = t
                duration = end_time - start_time
                if duration >= min_duration:
                    intervals.append((start_time, end_time))
                inside = False

    return intervals


# Affiner les intervalles grâce à la vitesse moyenne locale. On cherche le dernier point où on est encore au-dessus de 90% de cette moyenne locale pour prendre en compte la décélération
def refine_intervals(df, intervals):
    refined = []
    for start, end in intervals:
        block = df[(df["time_s"] >= start) & (df["time_s"] <= end)]
        mean_speed = block["speed_kmh"].mean()
            
        # Chercher le dernier point où on est encore au-dessus de la moyenne
        above_mean = block[block["speed_kmh"] >= mean_speed]
        above_threshold = block[block["speed_kmh"] >= 0.9 * mean_speed]
        if not above_threshold.empty:
            end = above_threshold["time_s"].iloc[-1]
          
        refined.append((start, end))
    return refined

"""def analyze_internal_recups(df, blocks, round_to=50):
    
    Analyse les récupérations internes (entre répétitions d’un même bloc).

    if blocks.empty:
        return pd.DataFrame()

    # Arrondi comme pour les blocs
    blocks["distance_round"] = (blocks["distance_m"] / round_to).round() * round_to
    blocks = blocks.sort_values("start").reset_index(drop=True)

    recups = []
    for i in range(len(blocks) - 1):
        current = blocks.iloc[i]
        nxt = blocks.iloc[i + 1]

        # Même bloc (ex: tous les 300m ensemble)
        if current["distance_round"] == nxt["distance_round"]:
            recup = df[(df["time_s"] >= current["end"]) & (df["time_s"] <= nxt["start"])]
            if recup.empty:
                continue

            duration = recup["time_s"].iloc[-1] - recup["time_s"].iloc[0]
            mean_speed = recup["speed_kmh"].mean()
            mean_bpm = recup["bpm"].mean()

            recups.append({
                "type": f"Récup entre {int(current['distance_round'])} m",
                "durée": f"{round(duration)} s",
                "allure": format_allure(60 / mean_speed) if mean_speed > 0 else "N/A",
                "bpm moyen": round(mean_bpm, 1) if pd.notna(mean_bpm) else "N/A"
            })

    return pd.DataFrame(recups)
"""

def format_time(seconds):
    """Convertit un temps en secondes vers mm:ss"""
    minutes = int(seconds // 60)
    sec = int(seconds % 60)
    return f"{minutes:02d}:{sec:02d}"

def print_intervals(intervals):
    """Affiche les intervalles détectés avec début, fin et durée"""
    if not intervals:
        print("⚠️ Aucun intervalle détecté")
        return
    
    print("Intervalles détectés :")
    for idx, (start, end) in enumerate(intervals, 1):
        duree = end - start
        print(f"  • Intervalle {idx}: {format_time(start)} → {format_time(end)} "
              f"(durée {format_time(duree)})")


# Extraire les blocs d’effort et calculer les métriques
def extract_blocks(df, intervals):
    blocks = []
    for start, end in intervals:
        block = df[(df["time_s"] >= start) & (df["time_s"] <= end)].copy()
        if block.empty:
            continue

        block["dt"] = block["time_s"].diff().fillna(0)
        distance = ((block["speed_kmh"] / 3.6) * block["dt"]).sum()
        duration = block["time_s"].iloc[-1] - block["time_s"].iloc[0]
        if duration < 10:
            continue

        effort_cardio = block["bpm"].iloc[-1] - block["bpm"].iloc[0]
        blocks.append({
            "start": block["time_s"].iloc[0],
            "end": block["time_s"].iloc[-1],
            "duration_s": duration,
            "distance_m": distance,
            "mean_speed": block["speed_kmh"].mean(),
            "mean_bpm": block["bpm"].mean(),
            "effort_cardio": effort_cardio
        })
    return pd.DataFrame(blocks)



def filter_relative(blocks, tolerance=0.15, min_reps=1):
    """
    Filtre les blocs 'anormaux' par rapport aux autres :
    - tolerance : ±15% autour de la vitesse médiane du groupe
    - min_reps : il faut au moins 2 répétitions similaires
    """
    if blocks.empty:
        return blocks
    blocks["distance_round"] = (blocks["distance_m"] / 50).round() * 50
    clean_blocks = []
    # On regroupe par distance arrondie
    for dist, grp in blocks.groupby("distance_round"):
        if len(grp) < min_reps:
            continue
        median_speed = grp["mean_speed"].median()
        lower, upper = median_speed * (1 - tolerance), median_speed * (1 + tolerance)
        grp_clean = grp[(grp["mean_speed"] >= lower) & (grp["mean_speed"] <= upper)]
        if not grp_clean.empty:
            clean_blocks.append(grp_clean)
    return pd.concat(clean_blocks) if clean_blocks else pd.DataFrame()


def filter_by_cardio(blocks, min_effort_cardio=7, min_mean_bpm=125, keep_all=False):
    """
    Filtre les blocs selon les critères cardio :
    - effort_cardio >= min_effort_cardio
    - mean_bpm >= min_mean_bpm

    Si keep_all=True, ajoute seulement une colonne 'valid_cardio'
    sans supprimer les répétitions.
    """
    if blocks.empty:
        return blocks

    required = {"effort_cardio", "mean_bpm"}
    missing = required - set(blocks.columns)
    if missing:
        raise ValueError(f"Colonnes manquantes: {missing}")

    blocks = blocks.copy()
    blocks["valid_cardio"] = (
        (blocks["effort_cardio"] >= min_effort_cardio) &
        (blocks["mean_bpm"] >= min_mean_bpm)
    )

    if keep_all:
        return blocks.reset_index(drop=True)
    else:
        return blocks[blocks["valid_cardio"]].reset_index(drop=True)


def is_fractionne(summary, allure_threshold="4:15"):
    """
    Détermine si une séance est du fractionné
    en fonction de l'allure des intervalles détectés.
    - allure_threshold : min/km (ex: "4:15")
    """
    if summary.empty:
        return False
    
    # Convertir allure en secondes/km
    min_part, sec_part = map(int, allure_threshold.split(":"))
    threshold_sec = min_part * 60 + sec_part

    # Prendre les allures moyennes des clusters
    def allure_to_sec(allure_str):
        clean = allure_str.replace(" min/km", "")
        m, s = map(int, clean.split(":")[0:2])
        return m * 60 + s

    allures = [allure_to_sec(a) for a in summary["allure"]]
    min_allure = min(allures)  # plus rapide = plus petit

    return min_allure <= threshold_sec



# Résumer les clusters dans un petit tableau
def summarize_clusters(blocks, round_to=50):
    summaries = []
    # On arrondit les distances
    blocks["distance_round"] = (blocks["distance_m"] / round_to).round() * round_to
    grouped = blocks.groupby("distance_round")
    
    for dist, grp in grouped:
        summaries.append({
            "type": f"{len(grp)} × {int(dist)} m",
            "allure": format_allure(60 / grp['mean_speed'].mean()),
            "durée moyenne": f"{round(grp['duration_s'].mean())} s",
            "bpm moyen": round(grp["mean_bpm"].mean(), 1),
            "effort_cardio moyen": round(grp["effort_cardio"].mean(), 1)
        })
    return pd.DataFrame(summaries)


# Formatage allure en min/km
def format_allure(min_per_km):
    minutes = int(min_per_km)
    seconds = round((min_per_km - minutes) * 60)
    return f"{minutes}:{seconds:02d} min/km"




def main():
  
    df = load_stream("data/streams/15199882103.csv")

    intervals = detect_intervals(df)
    refined = refine_intervals(df, intervals)
  

    blocks = extract_blocks(df, refined)
    filtered_blocks = filter_by_cardio(blocks, min_effort_cardio=0, min_mean_bpm=125, keep_all=False)
    filtered_blocks = filter_relative(filtered_blocks, tolerance=0.15, min_reps=2)

    if filtered_blocks.empty :
        print("Aucun fractionné détecté.")
        return

    summary = summarize_clusters(filtered_blocks, round_to=50)
    is_fractionned_flag = is_fractionne(summary, allure_threshold="4:15")
    print(f"Analyse de la séance : data/streams/15224415568.csv")
    if is_fractionned_flag:
        print("Séance de fractionné détectée.")
        print(summary)
    else:
        print("Aucun fractionné détecté.")

    



 
 

if __name__ == "__main__":
    main()
