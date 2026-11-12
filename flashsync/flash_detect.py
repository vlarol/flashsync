"""Сигнал яскравості світлодіодів → моменти спалахів (з точністю до кадру).

Для кожного LED береться маленьке вікно навколо центру (з led_detect) і для кожного
кадру рахується яскравість (середнє найяскравіших пікселів вікна). Далі:

1. Фон — ковзний низький перцентиль за ~3 с (повільні зміни світла, тіні, актор
   не дають хибних спалахів; довгий MASTER-спалах не «з'їдає» фон).
2. Залишок над фоном → поріг: Otsu по гістограмі залишку, але не нижче k·σ шуму.
3. Фронти «увімкнення» і «вимкнення» → імпульси; імпульси різних LED однієї
   камери об'єднуються в спалахи (медіана моментів).

Також визначаються повтори кадрів: карта захоплення інколи віддає той самий кадр
двічі — його мініатюра збігається з попередньою піксель у піксель.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np
from scipy.ndimage import percentile_filter

from . import io


@dataclass
class LedSignals:
    t: np.ndarray            # (N,) номінальний час кадру = індекс / fps, с
    values: np.ndarray       # (N, L) яскравість кожного LED
    dup: np.ndarray          # (N,) кадр — повтор попереднього
    fps: float
    leds: List[Tuple[float, float]]
    rows: np.ndarray         # (N, L, 2·r+1) профіль яскравості по рядках вікна (для subframe)


@dataclass
class Flash:
    frame: int               # перший кадр, де видно спалах
    t_on: float              # час першого «увімкненого» кадру, с (у годиннику файлу)
    t_off: float             # час першого «вимкненого» кадру після спалаху, с
    n_leds: int              # скільки LED побачили цей спалах

    @property
    def duration(self) -> float:
        return self.t_off - self.t_on


def extract_signals(path: str | Path, leds: Sequence[Tuple[float, float]], radius: int = 4,
                    max_frames: Optional[int] = None, progress=None) -> LedSignals:
    """Один прохід по відео: яскравість у вікні (2r+1)² навколо кожного LED."""
    meta = io.video_meta(path)
    H, W = meta.height, meta.width
    boxes = []
    for x, y in leds:
        cx, cy = int(round(x)), int(round(y))
        boxes.append((max(0, cy - radius), min(H, cy + radius + 1), max(0, cx - radius), min(W, cx + radius + 1)))
    vals, rows, dup = [], [], []
    prev = None
    for i, frame in io.iter_frames(path, 0, max_frames, gray=True):
        thumb = cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA)
        dup.append(prev is not None and np.array_equal(thumb, prev))
        prev = thumb
        v, r = [], []
        for y0, y1, x0, x1 in boxes:
            win = frame[y0:y1, x0:x1].astype(np.float32)
            flat = np.sort(win.ravel())
            v.append(flat[-max(3, flat.size // 4):].mean())            # середнє найяскравіших ¼
            rr = win.max(axis=1)
            r.append(np.pad(rr, (0, 2 * radius + 1 - len(rr)), mode="edge"))
        vals.append(v)
        rows.append(r)
        if progress and i % 500 == 0:
            progress(i, meta.n_frames)
    n = len(vals)
    fps = meta.fps or 50.0
    return LedSignals(np.arange(n) / fps, np.array(vals, np.float32), np.array(dup, bool), fps,
                      [tuple(map(float, p)) for p in leds], np.array(rows, np.float32))


def _otsu_threshold(x: np.ndarray) -> float:
    """Поріг Otsu для довільного (не uint8) сигналу через гістограму 256 бінів."""
    lo, hi = float(x.min()), float(x.max())
    if hi - lo < 1e-6:
        return hi
    u8 = np.clip((x - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    t, _ = cv2.threshold(u8.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return lo + t / 255.0 * (hi - lo)


def led_pulses(signal: np.ndarray, fps: float, base_window_s: float = 3.0,
               k_sigma: float = 6.0, min_amp: float = 8.0) -> Tuple[List[Tuple[int, int]], np.ndarray, float]:
    """Імпульси одного LED: список (перший кадр «увімкнено», перший кадр «вимкнено»).

    Повертає також залишок над фоном і поріг — для графіків.
    """
    w = max(3, int(base_window_s * fps)) | 1
    base = percentile_filter(signal, 30, size=w, mode="nearest")
    resid = signal - base
    noise = 1.4826 * float(np.median(np.abs(resid - np.median(resid)))) + 0.5
    thr = max(_otsu_threshold(resid), k_sigma * noise, min_amp)
    on = resid > thr
    edges = np.diff(on.astype(np.int8), prepend=0, append=0)
    starts = np.where(edges == 1)[0]
    ends = np.where(edges == -1)[0]
    return list(zip(starts.tolist(), ends.tolist())), resid, thr


def detect_flashes(sig: LedSignals, merge_frames: int = 5, min_leds: int = 1) -> List[Flash]:
    """Спалахи камери: імпульси всіх LED, об'єднані за часом."""
    pulses = []
    for j in range(sig.values.shape[1]):
        for s, e in led_pulses(sig.values[:, j], sig.fps)[0]:
            pulses.append((s, e, j))
    pulses.sort()
    flashes: List[Flash] = []
    group: list = []

    def close():
        if not group:
            return
        leds = {g[2] for g in group}
        if len(leds) >= min_leds:
            s = int(np.median([g[0] for g in group]))
            e = int(np.median([g[1] for g in group]))
            flashes.append(Flash(s, s / sig.fps, e / sig.fps, len(leds)))

    for p in pulses:
        if group and p[0] - group[0][0] > merge_frames:
            close()
            group = []
        group.append(p)
    close()
    return flashes


def irregular_dups(dup: np.ndarray) -> np.ndarray:
    """Індекси «нерегулярних» повторів кадрів.

    Два різні випадки:
    * камера віддає 25 к/с у 50-кадровий файл — повтор через кадр. Такі повтори займають
      свій часовий слот (кадр справді показується 40 мс) і поправки не потребують;
    * поодинокий повтор — збій захоплення: слот вставлено, а шкала камери не просунулась,
      тож усі наступні кадри насправді на один кадр раніше. Це видно в даних як сходинка
      залишків рівно на 1 кадр.
    Для камер з регулярним візерунком нерегулярні — ті, що ламають чергування.
    """
    idx = np.where(dup)[0]
    if len(idx) == 0:
        return idx
    if len(idx) > 0.3 * len(dup):                 # регулярний візерунок «через кадр»
        gaps = np.diff(idx)
        return idx[1:][gaps != 2]
    return idx


def effective_time(sig: LedSignals) -> np.ndarray:
    """Час кадрів з поправкою на нерегулярні повтори (кожен зсуває наступні кадри на −1 кадр)."""
    irr = irregular_dups(sig.dup)
    shift = np.zeros(len(sig.t))
    for i in irr:
        shift[i:] += 1.0 / sig.fps
    return sig.t - shift

