import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter1d
from scipy.signal import savgol_filter

def load_stream(activity_path):
    df = pd.read_csv(activity_path)
    df1 = df.copy()
    df2= df.copy()
    df1 = savgol_filter(df["speed_kmh"].ffill(), window_length=15,polyorder=2)
    df2["speed_kmh"] = savgol_filter(df2["speed_kmh"].ffill(), window_length=51, polyorder=3)
    return df, df1, df2

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


df,df1,df2 = load_stream("data/streams/15940410865.csv")
plot_speed_with_smoothing(df, df1, df2, h=0.75, H=1.15)
print("Graphique de la vitesse sauvegardé dans ./data/graph/speed_Destruction.png")
