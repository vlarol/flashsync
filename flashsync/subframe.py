"""Субкадрове уточнення моменту спалаху (rolling shutter + часткова засвітка).

Модель експозиції. Кадр n починається в момент t_n (годинник камери). Сенсор Xiaomi Yi
має rolling shutter: рядок на висоті y (0 — верх, 1 — низ кадру) починає експонуватись
на R·y пізніше і експонується протягом E:

    рядок y кадру n бачить світло з інтервалу [t_n + R·y,  t_n + R·y + E]

Якщо спалах вмикається в момент t_s посередині цього інтервалу, LED у кадрі засвічений
частково — на частку f = (t_n + R·y + E − t_s) / E. Звідси

    t_s = t_n + R·y + E · (1 − f)              (фронт увімкнення)
    t_e = t_n + R·y + E · f                    (фронт вимкнення, f — частка ще засвіченого)

f береться з яскравості: f = залишок_над_фоном / амплітуда_повністю_засвіченого_кадру.

Невідомі E (експозиція) і R (час зчитування сенсора) підбираються з даних: перебором
шукаємо ті, за яких лінійна модель t_esp = a·t + b дає найменші залишки на train-спалахах.
LED на різній висоті кадру роблять R помітним; без цього R не визначається (ми це повідомляємо).

Повтори кадрів (камери, що віддають 25 к/с у 50-кадровий файл) викидаються:
працюємо лише з унікальними кадрами та їхнім справжнім інтервалом.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .flash_detect import LedSignals, led_pulses, effective_time
from . import fit


@dataclass
class Edge:
    t_frame: float     # час початку кадру, в якому видно фронт (годинник камери), с
    frac: float        # частка засвітки цього кадру 0..1
    partial: bool      # чи справді кадр частково засвічений (інакше фронт між кадрами)
    rising: bool
    y: float           # висота LED у кадрі, 0..1
    led: int
    flash_t: float     # грубий час спалаху (перший засвічений кадр) — щоб згрупувати фронти
    pulse_len: float = 0.0   # тривалість імпульсу цього LED у кадрах·T, с (MASTER довгий)


def _unique_frames(sig: LedSignals, fix_dups: bool = True):
    keep = np.where(~sig.dup)[0]
    t = (effective_time(sig) if fix_dups else sig.t)[keep]
    dt = np.median(np.diff(t)) if len(t) > 1 else 1 / sig.fps
    return keep, t, float(dt)


def find_edges(sig: LedSignals, frame_height: int, fix_dups: bool = True) -> List[Edge]:
    """Фронти увімкнення/вимкнення кожного LED з часткою засвітки крайніх кадрів."""
    keep, t, T = _unique_frames(sig, fix_dups)
    edges: List[Edge] = []
    for j, (_, ly) in enumerate(sig.leds):
        y = float(ly) / frame_height
        v = sig.values[keep, j]
        pulses, resid, thr = led_pulses(v, 1.0 / T)
        for s, e in pulses:
            if s < 1 or e >= len(v) - 1 or e - s < 2:
                continue
            plateau = resid[s:e]
            amp = float(np.percentile(plateau, 75))
            if amp <= 0:
                continue
            f_prev, f_on = resid[s - 1] / amp, resid[s] / amp
            plen = float(t[e] - t[s])
            # фронт увімкнення: частково засвічений або кадр s-1 (трохи світла), або кадр s
            if f_prev > 0.05:
                edges.append(Edge(t[s - 1], float(np.clip(f_prev, 0, 1)), True, True, y, j, t[s], plen))
            elif f_on < 0.95:
                edges.append(Edge(t[s], float(np.clip(f_on, 0, 1)), True, True, y, j, t[s], plen))
            else:
                edges.append(Edge(t[s], 1.0, False, True, y, j, t[s], plen))
            # фронт вимкнення: частково засвічений або останній «увімкнений», або перший «вимкнений»
            f_last, f_next = resid[e - 1] / amp, resid[e] / amp
            if f_next > 0.05:
                edges.append(Edge(t[e], float(np.clip(f_next, 0, 1)), True, False, y, j, t[s], plen))
            elif f_last < 0.95:
                edges.append(Edge(t[e - 1], float(np.clip(f_last, 0, 1)), True, False, y, j, t[s], plen))
            else:
                edges.append(Edge(t[e], 0.0, False, False, y, j, t[s], plen))
    return edges


def edge_times(edges: Sequence[Edge], E: float, R: float, T: float) -> np.ndarray:
    """Момент кожного фронту за моделлю експозиції (годинник камери)."""
    out = np.empty(len(edges))
    for i, ed in enumerate(edges):
        base = ed.t_frame + R * ed.y
        if not ed.partial:
            # фронт потрапив у проміжок між кінцем експозиції попереднього кадру
            # (base − T + E) і початком цього (base) — беремо середину проміжку
            out[i] = base - max(T - E, 0.0) / 2
        elif ed.rising:
            out[i] = base + E * (1.0 - ed.frac)
        else:
            out[i] = base + E * ed.frac
    return out


def flash_onsets(edges: Sequence[Edge], E: float, R: float, T: float, duration: Optional[float] = None):
    """Субкадровий момент кожного спалаху: середнє оцінок від усіх LED і обох фронтів.

    Фронт вимкнення дає t_e; момент увімкнення = t_e − тривалість. Тривалість, якщо не задана,
    оцінюється як медіана (t_e − t_s) по LED, де видно обидва фронти.
    Повертає (грубі часи спалахів, субкадрові часи).
    """
    te = edge_times(edges, E, R, T)
    # фронти різних LED одного спалаху можуть мати різний «перший кадр» (±1) —
    # групуємо за близькістю грубого часу
    order = np.argsort([ed.flash_t for ed in edges])
    groups, cur = [], []
    for i in order:
        if cur and edges[i].flash_t - edges[cur[-1]].flash_t > 0.2:
            groups.append(cur)
            cur = []
        cur.append(i)
    if cur:
        groups.append(cur)
    med_len = float(np.median([ed.pulse_len for ed in edges])) if edges else 0.0
    if duration is None:
        d = []
        for g in groups:
            r = [te[i] for i in g if edges[i].rising]
            f = [te[i] for i in g if not edges[i].rising]
            if r and f and abs(edges[g[0]].pulse_len - med_len) < 0.5 * med_len + 0.02:
                d.append(np.mean(f) - np.mean(r))
        duration = float(np.median(d)) if d else 0.0
    coarse, fine = [], []
    for g in groups:
        normal = abs(np.median([edges[i].pulse_len for i in g]) - med_len) < 0.5 * med_len + 0.02
        r = [te[i] for i in g if edges[i].rising and edges[i].partial] or \
            [te[i] for i in g if edges[i].rising]
        f = []
        if normal:            # для довгого MASTER тривалість інша — беремо лише фронт увімкнення
            f = [te[i] - duration for i in g if not edges[i].rising and edges[i].partial] or \
                [te[i] - duration for i in g if not edges[i].rising]
        est = r + f
        if est:
            coarse.append(float(np.median([edges[i].flash_t for i in g])))
            fine.append(float(np.median(est)))
    return np.array(coarse), np.array(fine), duration


@dataclass
class SubframeResult:
    E: float
    R: float
    duration: float
    model: fit.TimeModel
    cam_t: np.ndarray          # субкадрові моменти зіставлених спалахів
    esp_t: np.ndarray
    rms_ms: float
    R_identifiable: bool


def fit_subframe(sig: LedSignals, frame_height: int, match: fit.Match,
                 train_until: Optional[float] = None, fix_dups: bool = True,
                 E_grid=np.arange(0.05, 1.001, 0.05), R_grid=np.arange(0.0, 1.001, 0.05)) -> SubframeResult:
    """Підбір E і R (частки інтервалу кадру) за мінімумом залишків на train-спалахах.

    match — зіставлення з fit.match_flashes (грубі часи спалахів ↔ час ESP32).
    train_until — час ESP32: спалахи до нього — train (на них підбираємо E, R, a, b);
    None — усі спалахи.
    """
    _, _, T = _unique_frames(sig, fix_dups)
    edges = find_edges(sig, frame_height, fix_dups)
    ys = np.array([e.y for e in edges])
    R_ok = np.ptp(ys) >= 0.15 if len(ys) else False
    if not R_ok:
        R_grid = np.array([0.9])
    # грубий час → час ESP32 із зіставлення
    mc, me = np.asarray(match.cam_t), np.asarray(match.esp_t)

    def lookup(c):
        k = int(np.argmin(np.abs(mc - c)))
        return me[k] if abs(mc[k] - c) < 0.2 else None      # ефективний час ≤ кількох кадрів від номінального
    best = None
    for Ef in E_grid:
        for Rf in R_grid:
            coarse, fine, dur = flash_onsets(edges, Ef * T, Rf * T, T)
            pairs = [(fine[i], lookup(c)) for i, c in enumerate(coarse)]
            pairs = [(a_, b_) for a_, b_ in pairs if b_ is not None]
            if len(pairs) < 3:
                continue
            x = np.array([p_[0] for p_ in pairs])
            y = np.array([p_[1] for p_ in pairs])
            m = np.ones(len(x), bool) if train_until is None else y <= train_until
            if m.sum() < 3:
                continue
            mdl = fit.fit_linear(x[m], y[m])
            r = y[m] - mdl(x[m])
            rms = float(np.sqrt(np.mean(r ** 2)))
            if best is None or rms < best[0]:
                best = (rms, Ef * T, Rf * T, dur, mdl, x, y)
    if best is None:
        raise ValueError("замало спалахів для субкадрового уточнення")
    rms, E, R, dur, mdl, x, y = best
    return SubframeResult(E, R, dur, mdl, x, y, rms * 1000, bool(R_ok))
