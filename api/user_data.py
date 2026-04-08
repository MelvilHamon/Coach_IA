"""
api/user_data.py — Per-user data directory structure.

All user data lives under data/users/{user_id}/.
"""

import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_USERS_DIR = os.path.join(_ROOT, "data", "users")


class UserPaths:
    """Resolves all data paths for a given user."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.base = os.path.join(_USERS_DIR, user_id)

        # Core files
        self.config_json = os.path.join(self.base, "config.json")
        self.enriched_csv = os.path.join(self.base, "activities_enriched.csv")
        self.strava_csv = os.path.join(self.base, "mes_activites_strava.csv")
        self.sync_state_json = os.path.join(self.base, "sync_state.json")
        self.memoire_txt = os.path.join(self.base, "memoire.txt")
        self.personal_records_json = os.path.join(self.base, "personal_records.json")

        # Directories
        self.streams_dir = os.path.join(self.base, "streams")
        self.gps_dir = os.path.join(self.base, "gps")
        self.reviews_dir = os.path.join(self.base, "reviews")
        self.garth_dir = os.path.join(self.base, ".garth")

        # Garmin sub-structure
        self.garmin_dir = os.path.join(self.base, "garmin")
        self.garmin_activities_json = os.path.join(self.garmin_dir, "activities.json")
        self.garmin_streams_dir = os.path.join(self.garmin_dir, "streams")
        self.garmin_metrics_dir = os.path.join(self.garmin_dir, "metrics")
        self.garmin_map_json = os.path.join(self.garmin_dir, "strava_garmin_map.json")

    def ensure_dirs(self):
        """Create all necessary directories for this user."""
        for d in [
            self.base,
            self.streams_dir,
            self.gps_dir,
            self.reviews_dir,
            self.garth_dir,
            self.garmin_dir,
            self.garmin_streams_dir,
            self.garmin_metrics_dir,
        ]:
            os.makedirs(d, exist_ok=True)

    def exists(self) -> bool:
        return os.path.isdir(self.base)


def get_user_paths(user_id: str) -> UserPaths:
    """Get UserPaths for a user, creating directories if needed."""
    paths = UserPaths(user_id)
    paths.ensure_dirs()
    return paths
