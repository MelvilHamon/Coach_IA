import openai
from dotenv import load_dotenv
import os


def obtenir_conseils():
    # Charger la clé API depuis le fichier .env
    load_dotenv()
    openai.api_key = os.getenv("OPENAI_API_KEY")

    # Lire le résumé des sorties (ne prendre que les 5 dernières activités)
    with open("./data/resume_sorties.txt", "r", encoding="utf-8") as f:
        resume_lines = f.readlines()
        resume = "".join(resume_lines[-5:])  # Prend les 5 dernières lignes

    # Charger la mémoire persistante
    with open("./data/memoire.txt", "r", encoding="utf-8") as f:
        memoire = f.read()

    # Message à envoyer
    messages = [
        {"role": "system", "content": "Tu es un coach sportif spécialisé en course à pied. Donne des conseils personnalisés basés sur mon profil et mes dernières activités."},
        {"role": "user", "content": memoire + "\n\nVoici mes 5 dernières activités :\n" + resume}
    ]

    # Appel à l’API ChatGPT
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0.7
    )

    return response['choices'][0]['message']['content']















