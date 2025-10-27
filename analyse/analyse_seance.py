import pandas as pd
from scipy.ndimage import gaussian_filter1d
from scipy.signal import savgol_filter
import os
import matplotlib as plt

# ======================
# 1. Charger les données
# ======================
def load_stream(activity_path):
    df = pd.read_csv(activity_path)
    df["speed_kmh"] = gaussian_filter1d(df["speed_kmh"].ffill(), sigma=2)
    df["bpm"] = gaussian_filter1d(df["bpm"].ffill(), sigma=2)
    df["speed_kmh"] = savgol_filter(df["speed_kmh"].ffill(), window_length=15, polyorder=2)
    return df


# ================================
# 2. Détecter les intervalles bruts
# ================================
def detect_intervals(df, min_duration=40, hold_below=10):
    """Détecte des intervalles d’effort robustes en vitesse."""
    max_speed = df["speed_kmh"].max()
    mean_speed = df["speed_kmh"].mean()
    effort_threshold = 0.75 * max_speed  
    effort_threshold= 1 * mean_speed

    inside, start_time, below_counter = False, None, 0
    intervals = []

    for i, speed in enumerate(df["speed_kmh"]):
        t = df.loc[i, "time_s"]

        if not inside and speed > effort_threshold:
            start_time, inside, below_counter = t, True, 0

        elif inside:
            if speed < effort_threshold:
                below_counter += 1
            else:
                below_counter = 0

            if below_counter >= hold_below:
                end_time = t
                duration = end_time - start_time
                if duration >= min_duration:
                    intervals.append((start_time, end_time))
                inside = False
    return intervals


def refine_intervals(df, intervals):
    """Ajuste la fin des blocs sur la base de la vitesse moyenne locale."""
    refined = []
    for start, end in intervals:
        block = df[(df["time_s"] >= start) & (df["time_s"] <= end)]
        mean_speed = block["speed_kmh"].mean()
        above_threshold = block[block["speed_kmh"] >= 0.9 * mean_speed]
        if not above_threshold.empty:
            end = above_threshold["time_s"].iloc[-1]
        refined.append((start, end))
    return refined


# ===================================
# 3. Extraire les blocs d’effort
# ===================================
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


# ===================================
# 4. Classifier court / long / autres
# ===================================
def classify_blocks(blocks, short_min_dist=50, short_max_dist=400, min_short_speed = "3:45", min_long_speed = "4:20", min_short_reps=4):
    if blocks.empty:
        return {"court": pd.DataFrame(), "long": pd.DataFrame(), "autres": pd.DataFrame()}

    blocks["distance_round"] = (blocks["distance_m"] / 50).round() * 50
    results = {"court": [], "long": [], "autres": []}
    

    for dist, grp in blocks.groupby("distance_round"):
        m = format_allure(60 / grp['mean_speed'].mean())
        if short_min_dist <= dist <= short_max_dist and len(grp) >= min_short_reps and  m < min_short_speed :
            results["court"].append(grp)
        elif dist > short_max_dist and m < min_long_speed:
            results["long"].append(grp)
        elif m < min_long_speed and dist > short_min_dist :
            results["autres"].append(grp)

    return {k: (pd.concat(v).reset_index(drop=True) if v else pd.DataFrame())
            for k, v in results.items()}

# ===================================
# 5. Analyser les récuparations
# ===================================
def analyze_recups(df, blocks, round_to=50):
    """Analyse les phases de récup entre blocs d’un même type (distance arrondie)."""
    if blocks.empty:
        return pd.DataFrame()

    blocks = blocks.copy()
    blocks["distance_round"] = (blocks["distance_m"] / round_to).round() * round_to
    blocks = blocks.sort_values("start").reset_index(drop=True)

    recups = []
    for i in range(len(blocks) - 1):
        current = blocks.iloc[i]
        nxt = blocks.iloc[i+1]

        # Vérifie qu’il s’agit du même type (ex : deux 300 m consécutifs)
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

# ===================================
# 6. Résumé
# ===================================
def format_allure(min_per_km):
    minutes = int(min_per_km)
    seconds = round((min_per_km - minutes) * 60)
    return f"{minutes}:{seconds:02d} min/km"

def summarize_clusters(blocks, round_to=50):
    summaries = []
    if blocks.empty:
        return pd.DataFrame()
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

# ===================================
# 7. Plot
# ===================================

def plot_speed_with_smoothing(df,df1, df2, h=0.75, H=1.15):
    os.makedirs("./data/graph", exist_ok=True)
    plt.figure(figsize=(12, 6))
    plt.plot(df["time_s"]/60, df["speed_kmh"].ffill(), label="Vitesse brute", color='green',alpha=0.6)
    plt.plot(df["time_s"]/60, df1, label="Vitesse lissée Savitzky-Golay", color='orange', alpha=0.6)
    plt.plot(df["time_s"]/60, df2["speed_kmh"], label="Vitesse lissée Savitzky-Golay", color='blue', alpha=0.6)    
    avg_speed = df["speed_kmh"].mean()
    max_speed = df["speed_kmh"].max()*h
    plt.axhline(y=max_speed, color='g', linestyle='--', label=f"Vitesse max*{h}: {max_speed:.2f} km/h")
    plt.axhline(y=avg_speed, color='r', linestyle='--', label=f"Vitesse moyenne*{H}: {avg_speed:.2f} km/h")
    plt.xlabel("Temps (min)")
    plt.ylabel("Vitesse (km/h)")
    plt.title("Vitesse en fonction du temps avec lissage")
    plt.legend()
    plt.grid()
    plt.savefig("./data/graph/speed_Destruction.png")
    plt.close()


# ===================================
# 7. Main
# ===================================
def main():
    df = load_stream("data/streams/6*800.csv")

    intervals = detect_intervals(df)
    refined = refine_intervals(df, intervals)
    blocks = extract_blocks(df, refined)
    
    plot_speed_with_smoothing(df, intervals, refined)

    classified = classify_blocks(blocks)

    for label, df_cat in classified.items():
        
        if df_cat.empty:
            None
        elif not df_cat.empty:
            print(f"\n=== FRACTIONNÉ {label.upper()} ===")
            print(summarize_clusters(df_cat))
            recups = analyze_recups(df, df_cat)
            if not recups.empty and label != "autres":
                print("\nRécupérations associées :")
                print(recups)
        else:
            print(f"\n=== AUCUN FRACTIONNÉ detecté")


if __name__ == "__main__":
    main()
