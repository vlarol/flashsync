"""Оцінка синхронізації: базові методи проти нашого, train → test.

Протокол (docs/PLAN.md, розділ 4): спалахи кожної камери ділимо за часом ESP32 на train
(перші `train_frac`) і test (решта). Модель підганяється лише на train, похибка —
t_esp − модель(t_cam) — міряється на test. Так перевіряємо, що синхронізація тримається
в часі, а не просто описує ті самі точки.

Методи:
  B0  «за номером кадру»: камера вважається стартованою одночасно з еталонною (без власного зсуву)
  B1  зсув з одного MASTER-спалаху, без дрейфу
  B2  зсув + дрейф МНК по train-спалахах, точність до кадру
  B2+dup  те саме + поправка на нерегулярні повтори кадрів
  Ours    субкадрове уточнення (rolling shutter + часткова засвітка) + поправка на повтори

Метрики:
  * похибка кожної камери відносно годинника ESP32 (RMS, max) на test;
  * міжкамерна похибка: для кожного test-спалаху, який бачать усі камери, — розкид
    (max − min) передбачених моментів між камерами. Саме вона важлива для тріангуляції.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd

from . import fit, flash_detect as fd, subframe as sf

METHODS = ["B0", "B1", "B2", "B2+dup", "Ours"]


@dataclass
class CameraEval:
    camera: int
    flash_no: np.ndarray                       # номери зіставлених спалахів (з лога)
    esp_t: np.ndarray                          # справжній час ESP32
    test: np.ndarray                           # маска test
    pred: Dict[str, np.ndarray] = field(default_factory=dict)    # передбачений час ESP32
    models: Dict[str, fit.TimeModel] = field(default_factory=dict)
    E: float = float("nan")
    R: float = float("nan")

    def errors_ms(self, method: str) -> np.ndarray:
        return (self.esp_t - self.pred[method]) * 1000


def _frame_level_x(sig: fd.LedSignals, cam_t: np.ndarray, fix_dups: bool) -> np.ndarray:
    tt = fd.effective_time(sig) if fix_dups else sig.t
    idx = np.clip(np.round(cam_t * sig.fps).astype(int), 0, len(tt) - 1)
    return tt[idx]


def evaluate_camera(cid: int, sig: fd.LedSignals, frame_height: int, log: pd.DataFrame,
                    train_frac: float = 0.5) -> CameraEval:
    m = fit.match_flashes(fd.detect_flashes(sig), log)
    split = float(np.quantile(m.esp_t, train_frac))
    test = m.esp_t > split
    ev = CameraEval(cid, m.flash_no, m.esp_t, test)

    # B1: лише MASTER
    master_no = log.loc[log["kind"] == "MASTER", "flash_no"]
    if len(master_no) and master_no.iloc[0] in set(m.flash_no):
        k = int(np.where(m.flash_no == master_no.iloc[0])[0][0])
        b1 = fit.TimeModel(1.0, m.esp_t[k] - m.cam_t[k])
    else:                                       # MASTER не видно — перший train-спалах
        b1 = fit.TimeModel(1.0, m.esp_t[0] - m.cam_t[0])
    ev.models["B1"], ev.pred["B1"] = b1, b1(m.cam_t)

    for name, fx in (("B2", False), ("B2+dup", True)):
        x = _frame_level_x(sig, m.cam_t, fx)
        mdl = fit.fit_linear(x[~test], m.esp_t[~test])
        ev.models[name], ev.pred[name] = mdl, mdl(x)

    res = sf.fit_subframe(sig, frame_height, m, train_until=split, fix_dups=True)
    # переносимо субкадрові передбачення на ті самі спалахи (за часом ESP32)
    pred = np.full(len(m.esp_t), np.nan)
    for x, y in zip(res.cam_t, res.esp_t):
        k = int(np.argmin(np.abs(m.esp_t - y)))
        if abs(m.esp_t[k] - y) < 1e-6:
            pred[k] = res.model(x)
    ev.models["Ours"], ev.pred["Ours"] = res.model, pred
    ev.E, ev.R = res.E, res.R
    return ev


def add_b0(evals: List[CameraEval], ref: int) -> None:
    """B0: усі камери з тим самим зсувом, що й еталонна (за номером кадру), без дрейфу.
    Передбачення для камери = t_cam + b_ref; t_cam відновлюємо з B2-моделі цієї камери."""
    ref_ev = next(e for e in evals if e.camera == ref)
    b_ref = ref_ev.models["B2"].b
    for e in evals:
        mdl = e.models["B2"]
        t_cam = (e.pred["B2"] - mdl.b) / mdl.a
        e.models["B0"] = fit.TimeModel(1.0, b_ref)
        e.pred["B0"] = t_cam + b_ref


def summary_table(evals: List[CameraEval]) -> pd.DataFrame:
    rows = []
    for e in evals:
        row = {"camera": f"CAM{e.camera:02d}", "test_flashes": int(e.test.sum())}
        for mth in METHODS:
            r = e.errors_ms(mth)[e.test]
            r = r[np.isfinite(r)]
            row[f"{mth}_rms"] = float(np.sqrt(np.mean(r ** 2))) if len(r) else np.nan
            row[f"{mth}_max"] = float(np.abs(r).max()) if len(r) else np.nan
        row["Ours_drift_ppm"] = e.models["Ours"].drift_ppm
        row["B2_drift_ppm"] = e.models["B2"].drift_ppm
        row["E_ms"], row["R_ms"] = e.E * 1000, e.R * 1000
        rows.append(row)
    return pd.DataFrame(rows)


def inter_camera(evals: List[CameraEval]) -> pd.DataFrame:
    """Розкид передбачених моментів одного спалаху між камерами (test-спалахи, видимі всім)."""
    common = set.intersection(*[set(e.flash_no[e.test].tolist()) for e in evals])
    rows = []
    for mth in METHODS:
        spreads = []
        for no in sorted(common):
            p = []
            for e in evals:
                k = int(np.where(e.flash_no == no)[0][0])
                p.append(e.pred[mth][k] - e.esp_t[k])          # похибка камери на цьому спалаху
            p = np.array(p)
            if np.all(np.isfinite(p)):
                spreads.append((p.max() - p.min()) * 1000)
        s = np.array(spreads)
        rows.append({"method": mth, "flashes": len(s),
                     "spread_rms_ms": float(np.sqrt(np.mean(s ** 2))) if len(s) else np.nan,
                     "spread_max_ms": float(s.max()) if len(s) else np.nan})
    return pd.DataFrame(rows)


def error_vs_horizon(sig: fd.LedSignals, frame_height: int, log: pd.DataFrame,
                     train_seconds=(4, 6, 8, 10, 12)) -> pd.DataFrame:
    """Як похибка залежить від того, скільки секунд спалахів було на train
    (і, відповідно, як далеко вперед модель екстраполює)."""
    m = fit.match_flashes(fd.detect_flashes(sig), log)
    t0 = m.esp_t.min()
    rows = []
    for w in train_seconds:
        frac = np.mean(m.esp_t <= t0 + w)
        if frac < 0.1 or frac > 0.9:
            continue
        # evaluate_camera повторює зіставлення — дешево для одного сигналу
        e = evaluate_camera(0, sig, frame_height, log, train_frac=frac)
        for mth in METHODS[1:]:
            r = e.errors_ms(mth)[e.test]
            r = r[np.isfinite(r)]
            rows.append({"train_s": w, "method": mth, "rms": float(np.sqrt(np.mean(r ** 2))),
                         "max": float(np.abs(r).max())})
    return pd.DataFrame(rows)
