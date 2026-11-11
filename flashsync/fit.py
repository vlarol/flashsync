"""Зіставлення спалахів камери зі спалахами ESP32 і модель часу камери.

Модель: t_esp = a · t_cam + b
    b — зсув (коли камера стартувала за годинником ESP32),
    a — масштаб годинника; дрейф = (1 − a) · 10⁶ ppm.

Зіставлення:
1. Якір — MASTER: у відео це найдовший спалах, у лозі — рядок MASTER.
   Різниця їхніх часів — початкова оцінка зсуву b₀.
2. Кожен спалах камери ↔ найближчий спалах лога при поточній моделі (допуск ±⅓ періоду).
3. МНК по зіставлених парах, повторне зіставлення з меншим допуском (кілька ітерацій).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from .flash_detect import Flash


@dataclass
class TimeModel:
    a: float = 1.0
    b: float = 0.0

    def __call__(self, t_cam):
        return self.a * np.asarray(t_cam, dtype=np.float64) + self.b

    @property
    def drift_ppm(self) -> float:
        return (1.0 - self.a) * 1e6


@dataclass
class Match:
    cam_t: np.ndarray        # час спалахів у годиннику камери, с
    esp_t: np.ndarray        # відповідний час ESP32, с
    flash_no: np.ndarray     # номери спалахів з лога
    master_found: bool
    model: TimeModel = field(default_factory=TimeModel)


def fit_linear(t_cam: Sequence[float], t_esp: Sequence[float], drift: bool = True) -> TimeModel:
    """МНК для t_esp = a·t_cam + b (або лише зсуву, якщо drift=False)."""
    x = np.asarray(t_cam, np.float64)
    y = np.asarray(t_esp, np.float64)
    if not drift or len(x) < 2 or np.ptp(x) < 1.0:
        return TimeModel(1.0, float(np.mean(y - x)))
    A = np.vstack([x - x.mean(), np.ones_like(x)]).T
    a, c = np.linalg.lstsq(A, y, rcond=None)[0]
    return TimeModel(float(a), float(c - a * x.mean()))


def _nearest(esp: np.ndarray, pred: np.ndarray, tol: float):
    j = np.clip(np.searchsorted(esp, pred), 1, len(esp) - 1)
    j = np.where(np.abs(esp[j - 1] - pred) <= np.abs(esp[j] - pred), j - 1, j)
    ok = np.abs(esp[j] - pred) <= tol
    # один спалах лога — одна подія камери
    best: Dict[int, int] = {}
    for i in np.where(ok)[0]:
        if j[i] not in best or abs(esp[j[i]] - pred[i]) < abs(esp[j[best[j[i]]]] - pred[best[j[i]]]):
            best[j[i]] = i
    cam_idx = np.array(sorted(best.values()), dtype=int)
    return cam_idx, j[cam_idx]


def match_flashes(flashes: List[Flash], log: pd.DataFrame, offset_guess: Optional[float] = None,
                  iters: int = 5) -> Match:
    """Зіставляє спалахи камери з лого́м ESP32 і підганяє лінійну модель."""
    if not flashes:
        raise ValueError("немає спалахів")
    cam = np.array([f.t_on for f in flashes])
    dur = np.array([f.duration for f in flashes])
    esp = log["t_esp_s"].to_numpy()
    period = float(np.median(np.diff(esp)))

    master_found = False
    if offset_guess is None:
        m_rows = np.where(log["kind"].to_numpy() == "MASTER")[0]
        longest = int(np.argmax(dur))
        if len(m_rows) and dur[longest] > 1.8 * np.median(dur):
            offset_guess = esp[m_rows[0]] - cam[longest]
            master_found = True
        else:
            # без MASTER — перебір зсувів, перемагає той, що зіставляє найбільше спалахів
            cands = (esp[None, :] - cam[:, None]).ravel()
            scores = [len(_nearest(esp, cam + c, period / 3)[0]) for c in cands]
            offset_guess = float(cands[int(np.argmax(scores))])

    model = TimeModel(1.0, float(offset_guess))
    tol = period / 3
    for _ in range(iters):
        ci, ej = _nearest(esp, model(cam), tol)
        if len(ci) < 2:
            break
        model = fit_linear(cam[ci], esp[ej])
        tol = max(0.03, tol / 2)
    ci, ej = _nearest(esp, model(cam), tol)
    return Match(cam[ci], esp[ej], log["flash_no"].to_numpy()[ej], master_found, model)


# ---------------------------------------------------------------------------
# Базові методи для порівняння (таблиця в розділі 4 плану)
# ---------------------------------------------------------------------------

def baseline_b0(start_offsets: Dict[int, float], ref_cam: int, ref_model: TimeModel) -> Dict[int, TimeModel]:
    """B0 — «за номером кадру»: усі камери вважаються стартованими одночасно з еталонною."""
    return {cid: TimeModel(1.0, ref_model.b) for cid in start_offsets}


def baseline_b1(match: Match, master_t_cam: float, master_t_esp: float) -> TimeModel:
    """B1 — лише зсув з одного MASTER-спалаху, без дрейфу."""
    return TimeModel(1.0, master_t_esp - master_t_cam)


def baseline_b2(match: Match) -> TimeModel:
    """B2 — зсув + дрейф МНК по всіх спалахах, точність до кадру."""
    return fit_linear(match.cam_t, match.esp_t)
