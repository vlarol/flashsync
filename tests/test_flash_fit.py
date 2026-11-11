"""Синтетика: ESP32 блимає (MASTER + щосекундні спалахи), камера стартує із зсувом,
її годинник дрейфує; перевіряємо детекцію спалахів і відновлення зсуву/дрейфу."""
import numpy as np
import pandas as pd
import pytest

from flashsync import flash_detect as fd, fit

FPS = 50.0


def esp_log():
    t = [5.0] + [6.2 + k for k in range(40)]
    kind = ["MASTER"] + ["REGULAR"] * 40
    return pd.DataFrame({"kind": kind, "flash_no": range(len(t)), "t_esp_s": t})


def camera_signal(start=1.37, drift_ppm=300.0, n=2400, master_dur=0.5, dur=0.07, seed=0):
    """Яскравість одного LED у кадрах камери: спалах, якщо інтервал кадру перетинає спалах ESP32."""
    rng = np.random.default_rng(seed)
    log = esp_log()
    a = 1 - drift_ppm * 1e-6                 # t_esp = a·t_cam + start
    t_cam = np.arange(n) / FPS
    t0 = a * t_cam + start
    t1 = a * (t_cam + 0.5 / FPS) + start     # експозиція = пів кадру
    v = 40 + rng.normal(0, 1.5, n)
    for k, (ts, kind) in enumerate(zip(log["t_esp_s"], log["kind"])):
        d = master_dur if kind == "MASTER" else dur
        lit = np.clip(np.minimum(t1, ts + d) - np.maximum(t0, ts), 0, None) / (t1 - t0)
        v += 150 * lit
    v += 25 * np.sin(t_cam / 3)              # повільна зміна освітлення
    return v.astype(np.float32), a, start


def test_led_pulses_finds_all():
    v, _, _ = camera_signal()
    pulses, resid, thr = fd.led_pulses(v, FPS)
    assert len(pulses) == 41                  # MASTER + 40 у кадрі (48 с запису)
    lengths = [e - s for s, e in pulses]
    assert max(lengths) >= 20                 # MASTER ≈ 25 кадрів


def test_match_recovers_offset_and_drift():
    # дрейф 2000 ppm = 96 мс за 48 с — кілька кадрів, тож його видно навіть з точністю до кадру.
    # (300 ppm = 14 мс < кадру: усі інтервали рівно по 50 кадрів, і B2 бачить дрейф 0 —
    #  саме тому потрібне субкадрове уточнення, див. test_frame_level_cannot_see_small_drift)
    v, a, start = camera_signal(drift_ppm=2000)
    sig = fd.LedSignals(np.arange(len(v)) / FPS, v[:, None], np.zeros(len(v), bool), FPS, [(0, 0)],
                        np.zeros((len(v), 1, 9), np.float32))
    flashes = fd.detect_flashes(sig)
    m = fit.match_flashes(flashes, esp_log())
    assert m.master_found
    assert len(m.cam_t) == 41
    assert m.model.drift_ppm == pytest.approx(2000, abs=150)
    # точність до кадру: залишки менші за кадр
    resid = m.esp_t - m.model(m.cam_t)
    assert np.abs(resid).max() < 1 / FPS


def test_fit_linear_exact():
    x = np.linspace(0, 100, 50)
    m = fit.fit_linear(x, 0.9995 * x + 2.5)
    assert m.a == pytest.approx(0.9995) and m.b == pytest.approx(2.5)
    assert m.drift_ppm == pytest.approx(500)


def test_frame_level_cannot_see_small_drift():
    """Документує обмеження B2: малий дрейф ховається в квантуванні кадром."""
    v, _, _ = camera_signal(drift_ppm=300)
    sig = fd.LedSignals(np.arange(len(v)) / FPS, v[:, None], np.zeros(len(v), bool), FPS, [(0, 0)],
                        np.zeros((len(v), 1, 9), np.float32))
    m = fit.match_flashes(fd.detect_flashes(sig), esp_log())
    assert abs(m.model.drift_ppm - 300) > 150
