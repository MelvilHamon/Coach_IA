"""
fit_builder/workout_utils.py — Fonctions de construction de fichiers .FIT.

Adapté de FitWeaver (https://github.com/AIminov/FitWeaver).
Utilise la bibliothèque fit_tool pour encoder les WorkoutStepMessages.
"""

from datetime import datetime

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.workout_message import WorkoutMessage
from fit_tool.profile.messages.workout_step_message import WorkoutStepMessage
from fit_tool.profile.profile_type import (
    FileType,
    Intensity,
    Manufacturer,
    Sport,
    SubSport,
    WorkoutStepDuration,
    WorkoutStepTarget,
)

# ── Conversion helpers ──────────────────────────────────────────────────────


def pace_to_speed(pace_str: str) -> int:
    """Convertit une allure 'MM:SS' /km en vitesse FIT (mm/s)."""
    if not isinstance(pace_str, str) or ":" not in pace_str:
        raise ValueError(f"Format d'allure invalide '{pace_str}', attendu 'MM:SS'")
    parts = pace_str.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"Format d'allure invalide '{pace_str}', attendu 'MM:SS'")
    mm, ss = int(parts[0]), int(parts[1])
    if mm < 1 or ss < 0 or ss > 59:
        raise ValueError(f"Allure invalide '{pace_str}': minutes >= 1, secondes 0-59")
    total_sec = mm * 60 + ss
    return int(1000.0 / total_sec * 1000)


def km_to_dist(km: float) -> int:
    """Convertit km en unités FIT (mètres / 10)."""
    return int(km * 100)


def sec_to_time(seconds: int) -> int:
    """Convertit secondes en ms (unités FIT)."""
    return int(seconds * 1000)


def bpm_to_fit_hr(bpm: int) -> int:
    """Convertit bpm en unités FIT HR (bpm + 100)."""
    return int(bpm) + 100


# ── Intensity shortcuts ─────────────────────────────────────────────────────

WU = Intensity.WARMUP
CD = Intensity.COOLDOWN
ACT = Intensity.ACTIVE
REC = Intensity.RECOVERY

INTENSITY_MAP = {
    "active": ACT,
    "warmup": WU,
    "cooldown": CD,
    "recovery": REC,
}


def resolve_intensity(value: str | None) -> Intensity:
    if value is None:
        return ACT
    return INTENSITY_MAP.get(value.lower(), ACT)


# ── Step builders ───────────────────────────────────────────────────────────


def make_step(idx, dur_type, dur_val, tgt_type, intensity,
              tgt_val=None, tgt_low=None, tgt_high=None):
    s = WorkoutStepMessage()
    s.message_index = idx
    s.duration_type = dur_type
    s.duration_value = dur_val
    s.target_type = tgt_type
    s.intensity = intensity
    if tgt_val is not None:
        s.target_value = tgt_val
    if tgt_low is not None:
        s.custom_target_value_low = tgt_low
    if tgt_high is not None:
        s.custom_target_value_high = tgt_high
    return s


def dist_pace(idx, km, pace_fast, pace_slow, intensity=ACT):
    """Step basé sur distance avec cible d'allure."""
    return make_step(
        idx,
        WorkoutStepDuration.DISTANCE, km_to_dist(km),
        WorkoutStepTarget.SPEED, intensity,
        tgt_val=0,
        tgt_low=pace_to_speed(pace_slow),
        tgt_high=pace_to_speed(pace_fast),
    )


def dist_open(idx, km, intensity=ACT):
    """Step basé sur distance sans cible."""
    return make_step(
        idx,
        WorkoutStepDuration.DISTANCE, km_to_dist(km),
        WorkoutStepTarget.OPEN, intensity,
    )


def open_step(idx, intensity=ACT):
    """Step libre (bouton lap)."""
    return make_step(
        idx,
        WorkoutStepDuration.OPEN, 0,
        WorkoutStepTarget.OPEN, intensity,
    )


def time_step(idx, seconds, intensity=REC):
    """Step basé sur temps sans cible."""
    return make_step(
        idx,
        WorkoutStepDuration.TIME, sec_to_time(seconds),
        WorkoutStepTarget.OPEN, intensity,
    )


def time_pace(idx, seconds, pace_fast, pace_slow, intensity=ACT):
    """Step basé sur temps avec cible d'allure."""
    return make_step(
        idx,
        WorkoutStepDuration.TIME, sec_to_time(seconds),
        WorkoutStepTarget.SPEED, intensity,
        tgt_val=0,
        tgt_low=pace_to_speed(pace_slow),
        tgt_high=pace_to_speed(pace_fast),
    )


def dist_hr(idx, km, hr_low, hr_high, intensity=ACT):
    """Step basé sur distance avec cible FC."""
    return make_step(
        idx,
        WorkoutStepDuration.DISTANCE, km_to_dist(km),
        WorkoutStepTarget.HEART_RATE, intensity,
        tgt_val=0,
        tgt_low=bpm_to_fit_hr(hr_low),
        tgt_high=bpm_to_fit_hr(hr_high),
    )


def time_hr(idx, seconds, hr_low, hr_high, intensity=ACT):
    """Step basé sur temps avec cible FC."""
    return make_step(
        idx,
        WorkoutStepDuration.TIME, sec_to_time(seconds),
        WorkoutStepTarget.HEART_RATE, intensity,
        tgt_val=0,
        tgt_low=bpm_to_fit_hr(hr_low),
        tgt_high=bpm_to_fit_hr(hr_high),
    )


def repeat_step(idx, back_to, count):
    """Step de répétition."""
    return make_step(
        idx,
        WorkoutStepDuration.REPEAT_UNTIL_STEPS_CMPLT, back_to,
        WorkoutStepTarget.OPEN, ACT,
        tgt_val=count,
    )


# ── Save FIT file ───────────────────────────────────────────────────────────


def save_workout(filepath: str, name: str, steps: list,
                 sport: Sport = Sport.RUNNING,
                 serial_number: int = 12345,
                 time_created_ms: int | None = None):
    """Construit et sauvegarde un fichier .FIT workout."""
    if time_created_ms is None:
        time_created_ms = int(datetime.now().timestamp() * 1000)

    builder = FitFileBuilder()

    fid = FileIdMessage()
    fid.type = FileType.WORKOUT
    fid.manufacturer = Manufacturer.GARMIN.value
    fid.product = 0
    fid.serial_number = serial_number
    fid.time_created = time_created_ms

    wkt = WorkoutMessage()
    wkt.sport = sport
    wkt.sub_sport = SubSport.GENERIC
    wkt.num_valid_steps = len(steps)
    wkt.workout_name = name

    builder.add(fid)
    builder.add(wkt)
    builder.add_all(steps)

    fit_file = builder.build()
    fit_file.to_file(filepath)
