"""Синтетичне відео: фон + 2 LED, що блимають раз на секунду, + «актор» —
велика пляма, що рухається кадром. Наш метод має знайти обидва LED і не взяти актора."""
import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from flashsync import led_detect as ld  # noqa: E402

LEDS = [(120, 40), (260, 75)]          # другий LED одразу над зоною руху актора
FPS = 50


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    p = tmp_path_factory.mktemp("v") / "CAM01_CAM 01.avi"
    W, H = 320, 200
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[0:H, 0:W]
    ax = 160.0
    for i in range(FPS * 8):
        img = np.full((H, W), 60, np.float32) + rng.normal(0, 2, (H, W))
        ax = float(np.clip(ax + rng.normal(0, 6), 30, 290))   # актор блукає (випадкове блукання)
        img[(np.abs(xx - ax) < 18) & (yy > 90)] = 200
        if (i % FPS) < 4:                                   # спалах 4 кадри на секунду
            for (lx, ly) in LEDS:
                img[(xx - lx) ** 2 + (yy - ly) ** 2 <= 9] = 250
        w.write(cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR))
    w.release()
    return p


def _params(**kw):
    return ld.DetectParams(start_s=0.5, duration_s=6.0, scale=1.0, period_s=1.0, **kw)


def test_folded_finds_leds_not_actor(video):
    cands, maps = ld.detect_leds(video, _params())
    acc = [(c.x, c.y) for c in cands if c.accepted]
    m = ld.match_to_reference(acc, LEDS, tol_px=3)
    assert m["recall"] == 1.0
    assert m["precision"] == 1.0
    assert m["mean_err_px"] < 1.0


def test_folded_map_suppresses_motion(video):
    p = _params()
    stack, fps = ld.load_stack(video, p)
    folded = ld.folded_map(stack, p.period_s * fps)
    naive = ld.flicker_map(stack)
    actor = (slice(100, 190), slice(30, 290))
    # у наївній карті рух актора яскравий, у складеній — майже зникає
    assert naive[actor].max() > 100
    assert folded[actor].mean() < 0.35 * naive[actor].mean()     # ≥3× слабше вже за 6 циклів
    assert folded[LEDS[0][1], LEDS[0][0]] > 20


def test_periodicity_score():
    t = np.arange(500)
    pulse = ((t % 50) < 4).astype(float)
    assert ld._periodicity(pulse, 50, 1.0) > 0.8
    assert ld._periodicity(np.random.default_rng(1).normal(size=500), 50, 1.0) < 0.3
