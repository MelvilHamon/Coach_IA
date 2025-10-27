from openai import OpenAI
from dotenv import load_dotenv
import os
import re


def obtenir_conseils():
    # Charger la clé API depuis le fichier .env
    load_dotenv()
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Lire le résumé des sorties (ne prendre que les 5 dernières activités)
    with open("./data/resume_sorties.txt", "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Trouver les indices de début d'activité (lignes qui commencent par un jour anglais)
    activity_indices = [i for i, line in enumerate(lines) if re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", line)]
    last_5_indices = activity_indices[-5:]

    # Extraire les 5 dernières activités
    activities = []
    for idx, start in enumerate(last_5_indices):
        end = last_5_indices[idx + 1] if idx + 1 < len(last_5_indices) else len(lines)
        activities.append("".join(lines[start:end]))
    resume = "\n".join(activities)


    # Charger la mémoire persistante
    with open("./data/memoire.txt", "r", encoding="utf-8") as f:
        memoire = f.read()

    # Message à envoyer
    messages = [
        {"role": "system", "content": "Tu es un coach sportif spécialisé en course à pied. Donne des conseils personnalisés basés sur mon profil et mes dernières activités."},
        {"role": "user", "content": memoire + "\n\nVoici mes 5 dernières activités :\n" + resume}
    ]

    # Appel à l’API ChatGPT
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0.7
    )

    return response.choices[0].message.content















