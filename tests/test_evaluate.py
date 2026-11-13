"""Оцінка на синтетиці: 3 камери з різним стартом і дрейфом. Очікуваний порядок методів:
B0 ≫ B1 > B2 > Ours, і міжкамерний розкид Ours менший за мілісекунди."""
import numpy as np
import pytest

from flashsync import evaluate as ev
from test_subframe import make_signals, H


@pytest.fixture(scope="module")
def evals():
    out = []
    for cid, (start, drift) in enumerate([(1.0, 100.0), (1.5, -400.0), (2.0, 700.0)], start=1):
        sig, log = make_signals(start=start, drift_ppm=drift, seed=cid)
        out.append(ev.evaluate_camera(cid, sig, H, log))
    ev.add_b0(out, ref=1)
    return out


def test_method_ranking(evals):
    t = ev.summary_table(evals)
    rms = {m: t[f"{m}_rms"].mean() for m in ev.METHODS}
    assert rms["B0"] > 100                 # камери стартували з різницею 0.5–1 с
    assert rms["Ours"] < rms["B2"] < rms["B0"]
    assert rms["Ours"] < 2.0


def test_inter_camera_spread(evals):
    inter = ev.inter_camera(evals).set_index("method")
    assert inter.loc["Ours", "spread_rms_ms"] < 3.0
    assert inter.loc["B0", "spread_rms_ms"] > 500
