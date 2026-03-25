"""
garmin_auth.py — Authentification Garmin initiale avec sauvegarde du token.

À lancer UNE SEULE FOIS pour créer le token persisté dans .garth/.
Tous les autres scripts (sync_garmin.py, sync_garmin_gps.py, get_garmin_gps.py)
chargent ensuite ce token sans jamais refaire de login email/password.

Avantage : charger un token depuis disque est purement local, sans requête HTTP
d'authentification — impossible de déclencher MFA en cours de sync.

Usage :
    python3 appelAPIs/garmin_auth.py

Si Garmin demande un code MFA, l'entrer à l'invite. Le token est ensuite
sauvegardé et réutilisé automatiquement jusqu'à expiration (plusieurs mois).

Quand relancer ce script :
    - Première utilisation (token absent)
    - Erreur "Token Garmin invalide ou expiré" dans un script de sync
    - Changement de mot de passe Garmin
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

_ROOT      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GARTH_DIR = os.path.join(_ROOT, ".garth")


def _get_mfa() -> str:
    """Invite interactive pour le code MFA."""
    return input("Code MFA Garmin (laisser vide si non demandé) : ").strip()


def main() -> None:
    email    = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    if not email or not password:
        print(
            "Erreur : variables GARMIN_EMAIL et GARMIN_PASSWORD absentes du .env\n"
            "Ajouter ces deux lignes dans .env et relancer."
        )
        sys.exit(1)

    try:
        from garminconnect import Garmin
    except ImportError:
        print("Erreur : garminconnect non installé — pip install garminconnect")
        sys.exit(1)

    print(f"Connexion à Garmin Connect ({email})…")
    try:
        api = Garmin(email=email, password=password, prompt_mfa=_get_mfa)
        api.login()
    except Exception as e:
        print(f"\nÉchec de l'authentification : {e}")
        print("Vérifier les identifiants dans .env.")
        sys.exit(1)

    # Sauvegarde du token
    os.makedirs(_GARTH_DIR, exist_ok=True)
    try:
        api.garth.dump(_GARTH_DIR)
    except Exception as e:
        print(f"\nÉchec de la sauvegarde du token : {e}")
        sys.exit(1)

    print(f"\nToken sauvegardé dans {_GARTH_DIR}/")
    print("Les scripts de sync utiliseront ce token automatiquement.")
    print("Relancer ce script uniquement si un sync signale un token expiré.")


if __name__ == "__main__":
    main()
