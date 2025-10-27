import requests
import pandas as pd
import os
from dotenv import load_dotenv


load_dotenv()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("REFRESH_TOKEN")

def refresh_access_token():
    response = requests.post(
        url="https://www.strava.com/oauth/token",
        data={
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'refresh_token',
            'refresh_token': REFRESH_TOKEN
        }
    )
    return response.json()['access_token']

def get_activities(token, n=10):
    headers = {'Authorization': f'Bearer {token}'}
    params = {'per_page': n, 'page': 1}
    response = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params)
    return response.json()

def get_activity_description(activity_id, token):
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(f"https://www.strava.com/api/v3/activities/{activity_id}", headers=headers)
    return response.json().get('description', '')

def format_activities(activities, token, existing_ids):
    # Filter new activities
    new_acts = [act for act in activities if isinstance(act, dict) and act['id'] not in existing_ids]
    if not new_acts:
        return pd.DataFrame()

    df = pd.DataFrame(new_acts)
    df['ID'] = df['id']
    df['Nom'] = df['name']
    df['Date'] = df['start_date_local']
    df['Distance (km)'] = (df['distance'] / 1000).round(2)
    df['Temps (min)'] = (df['moving_time'] / 60).round(1)
    df['Allure (min/km)'] = ((df['moving_time'] / 60) / (df['distance'] / 1000)).round(2)
    df['Dénivelé (m)'] = df.get('total_elevation_gain', 0)
    df['Fréquence cardiaque (bpm)'] = df.get('average_heartrate', None)
    df['Type'] = df['type']
    # Fetch description only if needed
    df['Commentaire'] = [get_activity_description(act['id'], token) for act in new_acts]
    # Select columns
    return df[['ID', 'Nom', 'Date', 'Distance (km)', 'Temps (min)', 'Allure (min/km)', 'Dénivelé (m)', 'Fréquence cardiaque (bpm)', 'Type', 'Commentaire']]

if __name__ == "__main__":
    token = refresh_access_token()
    activities = get_activities(token)

    output_path = os.path.abspath("./data/mes_activites_strava.csv")
    if os.path.exists(output_path):
        df_old = pd.read_csv(output_path)
        existing_ids = set(df_old['ID']) if 'ID' in df_old.columns else set()
    else:
        df_old = pd.DataFrame()
        existing_ids = set()

    df_new = format_activities(activities, token, existing_ids)

    if df_new.empty:
        print("Aucune nouvelle activité trouvée.")
    else:
        df_combined = pd.concat([df_old, df_new], ignore_index=True)
        df_combined['Date'] = pd.to_datetime(df_combined['Date'], format='mixed',utc=True)
        df_combined = df_combined.sort_values(by='Date', ascending=True)
        df_combined.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"{len(df_new)} nouvelles activités ajoutées dans : {output_path}")