# Script Python : Générer un résumé détaillé sortie par sortie à partir du fichier CSV avec commentaires et archivage

import pandas as pd
from datetime import datetime
import os

# Charger le fichier CSV généré par le script Strava
fichier_csv = "./data/mes_activites_strava.csv"
df = pd.read_csv(fichier_csv)

# Charger le fichier des activités déjà résumées, s'il existe
fichier_resume = "./data/resume_sorties.txt"
activites_deja_resumees = set()
if os.path.exists(fichier_resume):
    with open(fichier_resume, "r", encoding="utf-8") as f:
        for ligne in f:
            if "–" in ligne:
                titre = ligne.strip()
                activites_deja_resumees.add(titre)

# Convertir la date en format datetime pour tri et affichage
if 'Date' in df.columns:
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values(by='Date', ascending=True)

# Ne garder que les 5 dernières sorties
df = df.tail(5)

# Construire un résumé textuel sortie par sortie, uniquement pour les nouvelles
resumes = []

for _, row in df.iterrows():
    date = row['Date'].strftime("%A %d %B %Y")
    nom = row['Nom']
    distance = row['Distance (km)']
    temps = row['Temps (min)']
    allure = row['Allure (min/km)']
    denivele = row['Dénivelé (m)']
    fc = row['Fréquence cardiaque (bpm)']
    type_act = row['Type']
    commentaire = row['Commentaire'] if 'Commentaire' in row and pd.notna(row['Commentaire']) else ""

    titre_activite = f"{date} – {nom} ({type_act})"
    if titre_activite in activites_deja_resumees:
        continue

    resume = f"{titre_activite}\n"
    resume += f"  • Distance : {distance} km\n"
    resume += f"  • Durée : {temps} minutes\n"
    resume += f"  • Allure moyenne : {allure} min/km\n"
    resume += f"  • Dénivelé : {denivele} m\n"
    if fc:
        resume += f"  • Fréquence cardiaque moyenne : {fc if pd.notna(fc) else 'N/A'} bpm\n"
    if commentaire:
        resume += f"  • Commentaire : {commentaire}\n"

    resumes.append(resume)

# Ajouter les nouveaux résumés à la fin du fichier texte
with open(fichier_resume, "a", encoding="utf-8") as f:
    for r in resumes:
        f.write(r + "\n")

print(f"{len(resumes)} nouvelles sorties ajoutées dans '{fichier_resume}'")

