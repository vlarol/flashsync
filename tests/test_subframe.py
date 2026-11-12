"""Синтетика з відомою моделлю експозиції: 2 LED на різній висоті кадру, rolling shutter,
спалахи ESP32 з відомим часом. Перевіряємо, що субкадровий метод точніший за кадровий
і що нерегулярний повтор кадру коректно компенсується."""
import numpy as np
import pandas as pd
import pytest

from flashsync import flash_detect as fd, fit, subframe as sf

FPS = 50.0
T = 1 / FPS
H = 1080
LEDS = [(100, 100), (900, 1000)]      # верх і низ кадру → R визначається


def esp_log(n=40):
    t = [5.0] + [6.2 + k * 1.0 + 0.0037 * k for k in range(n)]   # фаза спалаху «гуляє» відносно кадрів
    return pd.DataFrame({"kind": ["MASTER"] + ["REGULAR"] * n, "flash_no": range(n + 1), "t_esp_s": t})


def make_signals(start=1.234, drift_ppm=150.0, E=0.6 * T, R=0.85 * T, n=2400, dup_at=None, seed=1):
    rng = np.random.default_rng(seed)
    log = esp_log()
    a = 1 - drift_ppm * 1e-6
    true_t = np.arange(n) * T                       # справжній час початку кадрів (годинник камери)
    dup = np.zeros(n, bool)
    if dup_at is not None:                           # збій: слот dup_at — копія попереднього,
        true_t[dup_at:] -= T                         # а шкала камери далі на кадр «відстає»
        dup[dup_at] = True
    vals = np.zeros((n, len(LEDS)), np.float32)
    for j, (_, ly) in enumerate(LEDS):
        y = ly / H
        t0 = a * (true_t + R * y) + start
        t1 = a * (true_t + R * y + E) + start
        for ts, kind in zip(log["t_esp_s"], log["kind"]):
            d = 0.5 if kind == "MASTER" else 0.07
            vals[:, j] += 150 * np.clip(np.minimum(t1, ts + d) - np.maximum(t0, ts), 0, None) / (t1 - t0)
        vals[:, j] += 40 + rng.normal(0, 0.8, n)
    if dup_at is not None:
        vals[dup_at] = vals[dup_at - 1]
    sig = fd.LedSignals(np.arange(n) * T, vals, dup, FPS, LEDS, np.zeros((n, 2, 9), np.float32))
    return sig, log


def test_subframe_beats_frame_level():
    sig, log = make_signals()
    m = fit.match_flashes(fd.detect_flashes(sig), log)
    frame_rms = np.sqrt(np.mean((m.esp_t - fit.fit_linear(m.cam_t, m.esp_t)(m.cam_t)) ** 2))
    res = sf.fit_subframe(sig, H, m)
    sub_rms = np.sqrt(np.mean((res.esp_t - res.model(res.cam_t)) ** 2))
    assert res.R_identifiable
    assert sub_rms < 0.3 * frame_rms
    assert sub_rms < 1.5e-3                          # краще за 1.5 мс
    assert res.model.drift_ppm == pytest.approx(150, abs=40)
    assert res.R == pytest.approx(0.85 * T, abs=0.15 * T)


def test_irregular_dup_is_compensated():
    sig, log = make_signals(dup_at=1300)
    assert list(fd.irregular_dups(sig.dup)) == [1300]
    m = fit.match_flashes(fd.detect_flashes(sig), log)
    bad = sf.fit_subframe(sig, H, m, fix_dups=False)
    good = sf.fit_subframe(sig, H, m, fix_dups=True)
    r_bad = np.abs(bad.esp_t - bad.model(bad.cam_t)).max()
    r_good = np.abs(good.esp_t - good.model(good.cam_t)).max()
    assert r_bad > 5e-3                              # сходинка в пів кадру і більше
    assert r_good < 2e-3


def test_regular_25p_dups_not_irregular():
    dup = np.zeros(100, bool)
    dup[1::2] = True                                 # кожен другий кадр — повтор
    assert len(fd.irregular_dups(dup)) == 0
    dup[50] = True; dup[51] = False                  # збій чергування
    assert len(fd.irregular_dups(dup)) >= 1
