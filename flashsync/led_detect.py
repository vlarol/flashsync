"""Автоматичний пошук світлодіодів ESP32 у кадрі нерухомої камери.

Ідея: світлодіод — це маленька пляма, яскравість якої періодично стрибає, а фон
навколо стоїть на місці. Тому:

1. Стек кадрів за кілька секунд (у половинній роздільності, grayscale).
2. Синхронне усереднення по періоду ESP32 (epoch folding): кадри розкладаються
   по фазі циклу спалахів і усереднюються за всі цикли. Світлодіод, що блимає в
   ритм, дає гострий пік за фазою; рух актора, не прив'язаний до ритму,
   усереднюється. Карта: folded = max_фаза − median_фаза.
   Для порівняння рахується й наївна карта max − median по часу.
3. Gaussian blur → бінаризація Otsu → морфологічне відкриття.
4. connectedComponentsWithStats → кандидати-плями; фільтр за площею і
   «круглістю» (заповненість bounding box, співвідношення сторін).
5. Перевірка в часі: яскравість у плямі має бути двомодальною і періодичною з
   періодом ESP32 (автокореляція). Так відсікаються рух актора, тіні, відблиски.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from . import io


@dataclass
class LedCandidate:
    x: float                 # центр у пікселях повного кадру
    y: float
    area: int                # площа плями у половинній роздільності, px
    contrast: float          # (max − median) у центрі плями, рівні 0..255
    on_fraction: float       # частка кадрів, де LED горить
    periodicity: float       # пік автокореляції на періоді ESP32, 0..1
    score: float
    accepted: bool

    def as_dict(self):
        return asdict(self)


@dataclass
class DetectParams:
    start_s: float = 6.0       # з якої секунди брати кадри (після MASTER-спалаху)
    duration_s: float = 10.0   # скільки секунд аналізувати
    scale: float = 0.5         # масштаб для стеку (економія пам'яті)
    blur_ksize: int = 5
    min_area: int = 2          # площа плями в масштабованому кадрі
    max_area: int = 2000       # з ореолом на стіні пляма LED буває великою
    min_fill: float = 0.35     # площа / площа bounding box
    max_aspect: float = 5.0     # ореол LED на стіні буває видовженим
    min_contrast: float = 8.0        # у складеній карті контраст менший: спалах 3–4 кадри з 50
    period_s: float = 1.0      # період спалахів ESP32 (з esp32_flashes.txt)
    method: str = "folded"     # "folded" (наш) або "naive" (max − median + чистий Otsu) — для порівняння
    min_periodicity: float = 0.75
    max_on_fraction: float = 0.25
    merge_px: float = 20.0     # кандидати ближче за це (повний кадр) — один LED


def load_stack(path: str | Path, p: DetectParams) -> Tuple[np.ndarray, float]:
    """Стек grayscale-кадрів (N, H, W) uint8 у масштабі p.scale і fps відео."""
    meta = io.video_meta(path)
    fps = meta.fps or 50.0
    i0 = int(p.start_s * fps)
    i1 = min(meta.n_frames or 10 ** 9, i0 + int(p.duration_s * fps))
    frames = []
    for _, g in io.iter_frames(path, i0, i1, gray=True):
        if p.scale != 1.0:
            g = cv2.resize(g, None, fx=p.scale, fy=p.scale, interpolation=cv2.INTER_AREA)
        frames.append(g)
    if len(frames) < 10:
        raise ValueError(f"{path}: замало кадрів у вікні {p.start_s}–{p.start_s + p.duration_s} с")
    return np.stack(frames), fps


def flicker_map(stack: np.ndarray) -> np.ndarray:
    """Наївна карта: max − median по часу. Ловить і LED, і рух актора."""
    mx = stack.max(axis=0)
    med = np.median(stack, axis=0).astype(np.uint8)
    return cv2.subtract(mx, med)


def folded_map(stack: np.ndarray, period_frames: float) -> np.ndarray:
    """Карта періодичного мерехтіння (epoch folding).

    Кадр n потрапляє у фазовий бін floor((n mod P) / P · B). Для кожного біну —
    середнє за всі цикли, далі max − median по бінах. Події, не прив'язані до
    періоду P (рух, тіні), розмазуються по всіх фазах і майже зникають.
    """
    n = len(stack)
    bins = max(4, int(round(period_frames)))
    phase = ((np.arange(n) % period_frames) / period_frames * bins).astype(int)
    acc = np.zeros((bins,) + stack.shape[1:], np.float32)
    cnt = np.zeros(bins, np.float32)
    for b in range(bins):
        m = phase == b
        if m.any():
            acc[b] = stack[m].mean(axis=0)
            cnt[b] = m.sum()
    acc = acc[cnt > 0]
    prof_max = acc.max(axis=0)
    prof_med = np.median(acc, axis=0)
    return np.clip(prof_max - prof_med, 0, 255).astype(np.uint8)


def _periodicity(sig: np.ndarray, fps: float, period_s: float) -> float:
    """Нормована автокореляція сигналу на лагу ≈ період (найкраща в ±10%)."""
    s = sig - sig.mean()
    denom = float((s * s).sum())
    if denom <= 1e-9:
        return 0.0
    lag = period_s * fps
    best = 0.0
    for L in range(max(1, int(lag * 0.9)), int(lag * 1.1) + 2):
        if L >= len(s):
            break
        best = max(best, float((s[:-L] * s[L:]).sum()) / denom)
    return best


def detect_leds(path: str | Path, p: Optional[DetectParams] = None
                ) -> Tuple[List[LedCandidate], dict]:
    """Шукає світлодіоди у відео. Повертає (кандидати, проміжні карти для візуалізації)."""
    p = p or DetectParams()
    stack, fps = load_stack(path, p)
    naive = flicker_map(stack)
    diff = folded_map(stack, p.period_s * fps) if p.method == "folded" else naive

    k = p.blur_ksize | 1
    blur = cv2.GaussianBlur(diff, (k, k), 0)
    if p.method == "naive":
        # базовий метод з плану: max − median → blur → Otsu → відкриття → компоненти
        _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        return _components(stack, fps, diff, binary, p, naive, float(_))

    # Otsu розділяє «фон / яскраві LED», але коли в кадрі є і яскраві, і тьмяні LED,
    # поріг стає між ними і тьмяні губляться. Тому беремо мінімум з Otsu і робастного
    # порогу шуму (медіана + 6·MAD): майже всі пікселі складеної карти — шум біля нуля.
    otsu_t, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    med = float(np.median(blur))
    mad = 1.4826 * float(np.median(np.abs(blur.astype(np.float32) - med))) + 0.5
    thr = max(p.min_contrast * 0.5, min(otsu_t, med + 6 * mad))
    binary = (blur > thr).astype(np.uint8) * 255
    # закриття зшиває пляму LED, розірвану на кілька шматків; відкриття не робимо —
    # воно стирає тьмяні LED площею кілька пікселів
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    return _components(stack, fps, diff, binary, p, naive, thr)


def _components(stack, fps, diff, binary, p: DetectParams, naive, thr):
    """Плями бінарної карти → кандидати з перевіркою форми й періодичності в часі."""
    n, labels, stats, cents = cv2.connectedComponentsWithStats(binary, connectivity=8)
    cands: List[LedCandidate] = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (p.min_area <= area <= p.max_area):
            continue
        fill = area / float(w * h)
        aspect = max(w, h) / max(1, min(w, h))
        if fill < p.min_fill or aspect > p.max_aspect:
            continue
        # найяскравіша точка мерехтіння всередині плями — центр LED
        mask = labels[y:y + h, x:x + w] == i
        patch = np.where(mask, diff[y:y + h, x:x + w], 0)
        py, px = np.unravel_index(int(patch.argmax()), patch.shape)
        cx, cy = x + px, y + py
        contrast = float(diff[cy, cx])
        if contrast < p.min_contrast:
            continue
        # сигнал у часі: максимум у вікні 3×3 навколо центру
        y0, y1, x0, x1 = max(0, cy - 1), cy + 2, max(0, cx - 1), cx + 2
        sig = stack[:, y0:y1, x0:x1].reshape(len(stack), -1).max(axis=1).astype(np.float32)
        # частка фази циклу, коли LED горить — по складеному профілю (актор, що
        # перекриває LED, у профілі усереднюється й не збільшує «горіння»)
        P = p.period_s * fps
        ph = ((np.arange(len(sig)) % P) / P * max(4, int(round(P)))).astype(int)
        prof = np.array([sig[ph == b].mean() for b in np.unique(ph)])
        on_fraction = float((prof > (prof.min() + prof.max()) / 2).mean())
        per = _periodicity(sig, fps, p.period_s)
        score = per * min(1.0, contrast / 100.0)
        ok = per >= p.min_periodicity and 0 < on_fraction <= p.max_on_fraction
        # субпіксельний центр: зважене середнє по яскравих пікселях плями
        ys, xs = np.nonzero(patch >= 0.8 * patch.max())     # ядро LED, без ореолу на стіні
        wgt = patch[ys, xs].astype(np.float64)
        sx = (x + (xs * wgt).sum() / wgt.sum()) / p.scale
        sy = (y + (ys * wgt).sum() / wgt.sum()) / p.scale
        cands.append(LedCandidate(round(float(sx), 1), round(float(sy), 1), int(area),
                                  round(contrast, 1), round(on_fraction, 3), round(per, 3),
                                  round(score, 3), bool(ok)))
    cands.sort(key=lambda c: -c.score)
    cands = _merge_close(cands, p.merge_px)
    maps = {"threshold": thr, "diff": diff, "naive": naive, "binary": binary, "method": p.method, "median": np.median(stack, axis=0).astype(np.uint8),
            "scale": p.scale, "fps": fps}
    return cands, maps


def _merge_close(cands: List[LedCandidate], dist: float) -> List[LedCandidate]:
    """Залишає найкращого кандидата з кожної групи близьких (вони вже відсортовані)."""
    kept: List[LedCandidate] = []
    for c in cands:
        if all(np.hypot(c.x - k.x, c.y - k.y) > dist for k in kept):
            kept.append(c)
    return kept


def draw_overlay(maps: dict, cands: List[LedCandidate], title: str = "") -> np.ndarray:
    """Зображення для звіту: медіанний кадр + карта мерехтіння + знайдені LED."""
    base = cv2.cvtColor(maps["median"], cv2.COLOR_GRAY2BGR)
    heat = cv2.applyColorMap(cv2.normalize(maps["diff"], None, 0, 255, cv2.NORM_MINMAX), cv2.COLORMAP_INFERNO)
    img = cv2.addWeighted(base, 0.6, heat, 0.4, 0)
    s = maps["scale"]
    for c in cands:
        pt = (int(round(c.x * s)), int(round(c.y * s)))
        color = (80, 255, 80) if c.accepted else (60, 60, 255)
        cv2.circle(img, pt, 12 if c.accepted else 7, color, 2)
        if c.accepted:
            cv2.putText(img, f"{c.periodicity:.2f}", (pt[0] + 14, pt[1] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    if title:
        cv2.putText(img, title, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return img


def match_to_reference(found: List[Tuple[float, float]], ref: List[Tuple[float, float]],
                       tol_px: float = 8.0) -> dict:
    """Порівняння з ручною розміткою: precision / recall / похибка положення."""
    used, errs = set(), []
    for fx, fy in found:
        best, bj = None, None
        for j, (rx, ry) in enumerate(ref):
            if j in used:
                continue
            d = float(np.hypot(fx - rx, fy - ry))
            if d <= tol_px and (best is None or d < best):
                best, bj = d, j
        if bj is not None:
            used.add(bj)
            errs.append(best)
    tp = len(errs)
    return {"tp": tp, "found": len(found), "reference": len(ref),
            "precision": tp / len(found) if found else 0.0,
            "recall": tp / len(ref) if ref else 0.0,
            "mean_err_px": float(np.mean(errs)) if errs else float("nan")}
