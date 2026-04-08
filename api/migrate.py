"""
api/migrate.py — Migration des données single-user vers multi-user.

Détecte l'ancien format (data/activities_enriched.csv à la racine),
crée un utilisateur par défaut, et déplace les fichiers vers
data/users/{user_id}/.

Usage :
    python3 -m api.migrate

Ou appelé automatiquement au démarrage si l'ancien format est détecté.
"""

import json
import os
import shutil

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA = os.path.join(_ROOT, "data")


def needs_migration() -> bool:
    """True si l'ancien format single-user est détecté."""
    old_enriched = os.path.join(_DATA, "activities_enriched.csv")
    users_dir = os.path.join(_DATA, "users")
    return os.path.exists(old_enriched) and not os.path.isdir(users_dir)


def migrate(user_id: str) -> dict:
    """
    Déplace les données single-user vers data/users/{user_id}/.
    Retourne un résumé des fichiers migrés.
    """
    target = os.path.join(_DATA, "users", user_id)
    os.makedirs(target, exist_ok=True)

    moved = []

    # Fichiers racine data/
    for fname in [
        "activities_enriched.csv",
        "mes_activites_strava.csv",
        "sync_state.json",
        "personal_records.json",
        "memoire.txt",
    ]:
        src = os.path.join(_DATA, fname)
        dst = os.path.join(target, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.move(src, dst)
            moved.append(fname)

    # config.json depuis la racine projet
    config_src = os.path.join(_ROOT, "config.json")
    config_dst = os.path.join(target, "config.json")
    if os.path.exists(config_src) and not os.path.exists(config_dst):
        shutil.copy2(config_src, config_dst)  # copy, not move — garde l'original comme fallback
        moved.append("config.json")

    # Répertoires data/
    for dirname in ["streams", "gps", "reviews"]:
        src = os.path.join(_DATA, dirname)
        dst = os.path.join(target, dirname)
        if os.path.isdir(src) and not os.path.isdir(dst):
            shutil.move(src, dst)
            moved.append(f"{dirname}/")

    # Garmin
    garmin_src = os.path.join(_DATA, "garmin")
    garmin_dst = os.path.join(target, "garmin")
    if os.path.isdir(garmin_src) and not os.path.isdir(garmin_dst):
        shutil.move(garmin_src, garmin_dst)
        moved.append("garmin/")

    # .garth tokens
    garth_src = os.path.join(_ROOT, ".garth")
    garth_dst = os.path.join(target, ".garth")
    if os.path.isdir(garth_src) and not os.path.isdir(garth_dst):
        shutil.move(garth_src, garth_dst)
        moved.append(".garth/")

    return {"user_id": user_id, "target": target, "moved": moved}


def auto_migrate_if_needed() -> str | None:
    """
    Si migration nécessaire, crée un user 'default' dans la DB et migre.
    Retourne le user_id ou None si pas de migration.
    """
    if not needs_migration():
        return None

    from api.auth import init_db

    init_db()

    # Créer un utilisateur par défaut
    user_id = "default"
    try:
        from api.auth import _db
        from datetime import datetime, timezone
        with _db() as conn:
            existing = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not existing:
            with _db() as conn:
                conn.execute(
                    "INSERT INTO users (id, email, display_name, created_at) VALUES (?, ?, ?, ?)",
                    (user_id, "admin@coachagent.local", "Admin", datetime.now(timezone.utc).isoformat()),
                )
    except Exception:
        pass

    result = migrate(user_id)
    print(f"[migration] Données migrées vers {result['target']}: {', '.join(result['moved'])}")
    return user_id


if __name__ == "__main__":
    uid = auto_migrate_if_needed()
    if uid:
        print(f"Migration terminée pour user '{uid}'")
    else:
        print("Pas de migration nécessaire (format déjà multi-user ou pas de données)")
