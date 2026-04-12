"""
migrate_to_r2.py — Migre les fichiers GPS/streams existants vers Cloudflare R2.

Usage :
    # Dry run (affiche ce qui serait uploade)
    python3 scripts/migrate_to_r2.py --dry-run

    # Migration reelle
    python3 scripts/migrate_to_r2.py

    # Migration + suppression des fichiers locaux apres upload
    python3 scripts/migrate_to_r2.py --delete-local

Variables d'environnement requises :
    R2_BUCKET, R2_ENDPOINT, R2_ACCESS_KEY, R2_SECRET_KEY
"""

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from api.storage import USE_R2, _s3, _R2_BUCKET, _USERS_DIR, _R2_MANAGED


def _collect_files(users_dir: str) -> list[tuple[str, str]]:
    """Collect (local_path, r2_key) pairs for all R2-managed files."""
    pairs = []
    if not os.path.isdir(users_dir):
        return pairs

    for user_id in sorted(os.listdir(users_dir)):
        user_base = os.path.join(users_dir, user_id)
        if not os.path.isdir(user_base):
            continue

        for managed_subdir in _R2_MANAGED:
            subdir_path = os.path.join(user_base, managed_subdir)
            if not os.path.isdir(subdir_path):
                continue

            for fname in sorted(os.listdir(subdir_path)):
                fpath = os.path.join(subdir_path, fname)
                if not os.path.isfile(fpath):
                    continue
                rel = os.path.relpath(fpath, users_dir)
                key = rel.replace("\\", "/")
                pairs.append((fpath, key))

    return pairs


def main():
    parser = argparse.ArgumentParser(description="Migrate local files to Cloudflare R2")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be uploaded")
    parser.add_argument("--delete-local", action="store_true", help="Delete local files after upload")
    args = parser.parse_args()

    if not USE_R2:
        print("ERREUR : variables R2 non configurees.")
        print("Definissez R2_BUCKET, R2_ENDPOINT, R2_ACCESS_KEY, R2_SECRET_KEY")
        sys.exit(1)

    pairs = _collect_files(_USERS_DIR)
    if not pairs:
        print("Aucun fichier a migrer.")
        return

    total_size = sum(os.path.getsize(p) for p, _ in pairs)
    print(f"Fichiers a migrer : {len(pairs)}")
    print(f"Taille totale     : {total_size / 1024 / 1024:.1f} Mo")
    print(f"Bucket            : {_R2_BUCKET}")
    print()

    if args.dry_run:
        for fpath, key in pairs[:20]:
            size = os.path.getsize(fpath)
            print(f"  {key}  ({size / 1024:.1f} Ko)")
        if len(pairs) > 20:
            print(f"  ... et {len(pairs) - 20} autres fichiers")
        print("\n(dry run — rien n'a ete uploade)")
        return

    s3 = _s3()
    uploaded = 0
    errors = 0

    for i, (fpath, key) in enumerate(pairs, 1):
        try:
            content_type = "application/json" if key.endswith(".json") else "text/csv"
            with open(fpath, "rb") as f:
                s3.put_object(Bucket=_R2_BUCKET, Key=key, Body=f.read(),
                              ContentType=content_type)
            uploaded += 1

            if args.delete_local:
                os.remove(fpath)

            if i % 50 == 0 or i == len(pairs):
                print(f"  [{i}/{len(pairs)}] {uploaded} uploades, {errors} erreurs")

        except Exception as e:
            errors += 1
            print(f"  ERREUR {key}: {e}")

    print(f"\nMigration terminee : {uploaded} uploades, {errors} erreurs")
    if args.delete_local and uploaded > 0:
        print(f"Fichiers locaux supprimes : {uploaded}")
        # Clean up empty directories
        for fpath, _ in pairs:
            d = os.path.dirname(fpath)
            try:
                if os.path.isdir(d) and not os.listdir(d):
                    os.rmdir(d)
            except OSError:
                pass


if __name__ == "__main__":
    main()
