"""Tests unitaires compute_acwr_rolling — cas dégénérés explicites."""

from datetime import date, timedelta

from analyse.metrics import compute_acwr_rolling


def _const(start: date, n: int, v: float) -> dict:
    return {start + timedelta(days=i): v for i in range(n)}


def test_returns_none_for_new_athlete():
    """Moins de 7j d'historique → None."""
    loads = _const(date(2026, 6, 1), 5, 10.0)
    assert compute_acwr_rolling(loads, date(2026, 6, 5)) is None


def test_returns_none_when_chronic_is_zero():
    """Semaine entière à 0 → division par zéro → None."""
    loads = _const(date(2026, 5, 1), 28, 0.0)
    assert compute_acwr_rolling(loads, date(2026, 5, 28)) is None


def test_constant_load_ratio_near_one():
    """Charge constante : acute(7j) = 7*L, chronic(28j moyenne) = L → ratio = 7."""
    loads = _const(date(2026, 5, 1), 28, 10.0)
    r = compute_acwr_rolling(loads, date(2026, 5, 28))
    # somme 7j = 70, moyenne 28j = 10 → ratio = 7
    assert r == 7.0


def test_isolated_spike_increases_ratio():
    """Pic isolé en fin de fenêtre → acute monte sans toucher la chronique entière."""
    loads = _const(date(2026, 5, 1), 28, 10.0)
    loads[date(2026, 5, 28)] = 100.0  # spike sur le dernier jour
    r = compute_acwr_rolling(loads, date(2026, 5, 28))
    # somme 7j = 6*10 + 100 = 160 ; moyenne 28j = (27*10 + 100)/28 ≈ 13.21
    # ratio ≈ 160/13.21 ≈ 12.11
    assert r is not None and r > 7.0


def test_empty_dict_returns_none():
    assert compute_acwr_rolling({}, date(2026, 6, 1)) is None
