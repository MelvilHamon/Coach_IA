import os
import requests
import pandas as pd
from dotenv import load_dotenv

# Chargement des variables d'environnement
load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

# Étape 1 : Obtenir un access_token depuis le refresh_token
def get_access_token():
    response = requests.post(
        url="https://www.strava.com/oauth/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": REFRESH_TOKEN,
        },
    )
    return response.json().get("access_token")

# Étape 2 : Récupérer l'ID de la dernière activité
def get_last_activity_id(csv_path="./data/mes_activites_strava.csv"):
    df = pd.read_csv(csv_path)
    if "ID" in df.columns:
        return df["ID"].max()
    else:
        raise ValueError("La colonne 'ID' est manquante dans le CSV.")

# Étape 3 : Appeler l’API Strava pour récupérer les streams
def get_streams(activity_id, access_token):
    url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams"
    params = {
        "keys": "time,velocity_smooth,heartrate,altitude",
        "key_by_type": "true"
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers, params=params)
    if r.status_code != 200:
        raise Exception(f"Erreur API Strava : {r.status_code}")
    return r.json()

# Étape 4 : Convertir les streams en DataFrame
def streams_to_df(streams_json):
    time = streams_json.get("time", {}).get("data", [])
    speed = streams_json.get("velocity_smooth", {}).get("data", [])
    hr = streams_json.get("heartrate", {}).get("data", [])
    alt = streams_json.get("altitude", {}).get("data", [])
    df = pd.DataFrame({
        "time_s": time,
        "speed_kmh": [v * 3.6 for v in speed] if speed else [None] * len(time),
        "bpm": hr if hr else [None] * len(time),
        "altitude_m": alt if alt else [None] * len(time),
    })
    return df

# Étape 5 : Sauvegarder dans un fichier CSV
def save_streams(df, activity_id, output_dir="./data/streams"):
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{activity_id}.csv")
    df.to_csv(output_path, index=False)
    return output_path



def main():
    access_token = get_access_token()
    activity_id = 15940410865
    
    streams_json = get_streams(activity_id, access_token)
    streams_df = streams_to_df(streams_json)
    
    output_file = save_streams(streams_df, activity_id)
    print(f"Streams sauvegardés dans : {output_file}")  

    
if __name__ == "__main__":
    main()


