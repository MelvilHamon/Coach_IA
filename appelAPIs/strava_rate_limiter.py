"""
strava_rate_limiter.py — Gestion centralisée des rate limits Strava.

Limites Strava :
  - Globales : 600 req / 15 min,  6 000 req / jour
  - Lecture  : 300 req / 15 min,  3 000 req / jour

L'API Strava renvoie deux headers :
  X-RateLimit-Limit: "600,30000"   (15min, daily)  — parfois différent du doc
  X-RateLimit-Usage: "123,456"     (15min, daily)

Ce module :
  1. Parse ces headers après chaque requête
  2. Calcule un sleep adaptatif basé sur le quota restant
  3. Pause longue si on approche des limites
  4. Expose strava_get() comme remplacement de requests.get()
"""

import threading
import time

import requests

# ── Limites conservatrices (lecture = contrainte la plus serrée) ─────────────

LIMIT_15MIN = 300       # read limit per 15-min window
LIMIT_DAILY = 3000      # read limit per day
WARN_THRESHOLD = 0.85   # commence à ralentir à 85% d'usage
PAUSE_THRESHOLD = 0.95  # pause longue à 95%


class StravaRateLimiter:
    """Thread-safe rate limiter basé sur les headers Strava."""

    def __init__(self):
        self._lock = threading.Lock()
        # Usage courant (mis à jour par les headers)
        self.usage_15min = 0
        self.usage_daily = 0
        # Limites (mises à jour par les headers, défauts conservateurs)
        self.limit_15min = LIMIT_15MIN
        self.limit_daily = LIMIT_DAILY
        self.total_requests = 0

    def _update_from_headers(self, response: requests.Response):
        """Parse les headers X-RateLimit-* de la réponse Strava."""
        limit_header = response.headers.get("X-RateLimit-Limit", "")
        usage_header = response.headers.get("X-RateLimit-Usage", "")

        if limit_header and usage_header:
            try:
                limits = [int(x.strip()) for x in limit_header.split(",")]
                usages = [int(x.strip()) for x in usage_header.split(",")]

                with self._lock:
                    if len(limits) >= 2:
                        # On prend le min entre le header et nos limites de lecture
                        self.limit_15min = min(limits[0], LIMIT_15MIN)
                        self.limit_daily = min(limits[1], LIMIT_DAILY)
                    if len(usages) >= 2:
                        self.usage_15min = usages[0]
                        self.usage_daily = usages[1]
            except (ValueError, IndexError):
                pass

    def _compute_delay(self) -> float:
        """Calcule le délai avant la prochaine requête."""
        with self._lock:
            ratio_15min = self.usage_15min / self.limit_15min if self.limit_15min else 1
            ratio_daily = self.usage_daily / self.limit_daily if self.limit_daily else 1
            ratio = max(ratio_15min, ratio_daily)

        if ratio >= PAUSE_THRESHOLD:
            # Proche de la limite : pause de 60s (attend que la fenêtre glisse)
            remaining_15min = self.limit_15min - self.usage_15min
            if remaining_15min <= 2:
                return 60.0
            return 15.0
        elif ratio >= WARN_THRESHOLD:
            # Zone de ralentissement : 3-10s selon la proximité
            return 3.0 + 7.0 * ((ratio - WARN_THRESHOLD) / (PAUSE_THRESHOLD - WARN_THRESHOLD))
        else:
            # Confortable : délai minimal adaptatif
            # Plus on a consommé, plus on espace (0.3s → 2s)
            return 0.3 + 1.7 * ratio

    def wait_if_needed(self):
        """Attend le délai approprié avant une requête."""
        delay = self._compute_delay()
        if delay > 0:
            time.sleep(delay)

    def get(self, url: str, **kwargs) -> requests.Response:
        """
        Remplacement de requests.get() avec gestion des rate limits.
        Attend avant la requête, puis met à jour l'état depuis les headers.
        Gère le HTTP 429 (Too Many Requests) avec retry automatique.
        """
        self.wait_if_needed()

        response = requests.get(url, **kwargs)

        self._update_from_headers(response)

        with self._lock:
            self.total_requests += 1

        # Si rate-limited (429), attendre et retenter une fois
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "900"))
            wait_time = min(retry_after, 900)  # max 15 min
            print(f"[RateLimit] HTTP 429 — pause de {wait_time}s avant retry…")
            time.sleep(wait_time)
            response = requests.get(url, **kwargs)
            self._update_from_headers(response)

        return response

    def status(self) -> dict:
        """Retourne l'état actuel du rate limiter."""
        with self._lock:
            return {
                "usage_15min": self.usage_15min,
                "limit_15min": self.limit_15min,
                "usage_daily": self.usage_daily,
                "limit_daily": self.limit_daily,
                "remaining_15min": self.limit_15min - self.usage_15min,
                "remaining_daily": self.limit_daily - self.usage_daily,
                "total_requests": self.total_requests,
            }


# ── Singleton global ─────────────────────────────────────────────────────────

_limiter = StravaRateLimiter()


def strava_get(url: str, **kwargs) -> requests.Response:
    """Point d'entrée unique pour tous les GET vers l'API Strava."""
    return _limiter.get(url, **kwargs)


def get_rate_limit_status() -> dict:
    """Retourne l'état courant des rate limits."""
    return _limiter.status()


def reset_limiter():
    """Reset le limiter (utile pour les tests)."""
    global _limiter
    _limiter = StravaRateLimiter()
