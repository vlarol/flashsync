"""Внесок субкадрового уточнення і поправки на повтори кадрів (train → test).

    python scripts/subframe_ablation.py <тейк>

Спалахи кожної камери ділимо навпіл за часом: на першій половині (train) підганяємо
модель (і E, R для субкадрового методу), на другій (test) міряємо похибку
t_esp − модель(t_cam). Потрібні сигнали з scripts/run_take.py (results/run/<тейк>/).
"""
import argparse
import csv
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flashsync import io, flash_detect as fd, fit, subframe as sf  # noqa: E402


def load_signals(path: Path) -> fd.LedSignals:
    z = np.load(path)
    return fd.LedSignals(z["t"], z["v"], z["dup"], float(z["fps"]), [tuple(p) for p in z["leds"]], z["rows"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("take")
    ap.add_argument("--run-dir", default="results/run")
    args = ap.parse_args()

    take = io.load_take(args.take)
    log = take.flashes()
    run = Path(args.run_dir) / take.folder.name
    rows, curves = [], {}
    for cid in take.camera_ids:
        sig = load_signals(run / f"signals_CAM{cid:02d}.npz")
        H = io.video_meta(take.videos[cid]).height
        m = fit.match_flashes(fd.detect_flashes(sig), log)
        mid = float(np.median(m.esp_t))
        methods = {}

        # B2 — до кадру, номінальна шкала; B2+dup — до кадру, з поправкою на повтори
        for name, tt in (("B2", sig.t), ("B2+dup", fd.effective_time(sig))):
            lut = dict(zip(np.round(sig.t, 6), tt))
            x = np.array([lut[round(c, 6)] for c in m.cam_t])
            tr = m.esp_t <= mid
            mdl = fit.fit_linear(x[tr], m.esp_t[tr])
            methods[name] = (m.esp_t, (m.esp_t - mdl(x)) * 1000, mdl)

        for name, fx in (("subframe", False), ("subframe+dup", True)):
            res = sf.fit_subframe(sig, H, m, train_until=mid, fix_dups=fx)
            methods[name] = (res.esp_t, (res.esp_t - res.model(res.cam_t)) * 1000, res.model, res)

        row = {"camera": f"CAM{cid:02d}", "flashes": len(m.esp_t),
               "irregular_dups": len(fd.irregular_dups(sig.dup))}
        for name, (et, r, mdl, *rest) in methods.items():
            test = et > mid
            row[f"{name}_test_rms_ms"] = round(float(np.sqrt(np.mean(r[test] ** 2))), 2)
            row[f"{name}_test_max_ms"] = round(float(np.abs(r[test]).max()), 2)
            row[f"{name}_drift_ppm"] = round(mdl.drift_ppm, 1)
        best = methods["subframe+dup"][3]
        row["E_ms"], row["R_ms"], row["R_identifiable"] = round(best.E * 1000, 1), round(best.R * 1000, 1), best.R_identifiable
        rows.append(row)
        curves[cid] = (mid, methods)
        print(row)

    out = run
    with open(out / "subframe_ablation.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # графік: залишки в часі для кожного методу, усі камери
    names = ["B2", "B2+dup", "subframe", "subframe+dup"]
    colors = ["#94a3b8", "#64748b", "#f59e0b", "#2563eb"]
    fig, axes = plt.subplots(len(curves), 1, figsize=(11, 1.2 + 1.5 * len(curves)), sharex=True, squeeze=False)
    for ax, (cid, (mid, methods)) in zip(axes[:, 0], curves.items()):
        ax.axvspan(mid, max(methods["B2"][0]) + 0.5, color="#e2e8f0", lw=0)
        for n, c in zip(names, colors):
            et, r = methods[n][0], methods[n][1]
            ax.plot(et, r, "o-", ms=2.5, lw=0.9, color=c, label=n)
        ax.axhspan(-10, 10, color="#22c55e", alpha=0.08, lw=0)
        ax.set_ylim(-35, 35)
        ax.set_ylabel(f"CAM{cid:02d}\nмс", fontsize=8)
        ax.tick_params(labelsize=7)
    axes[0, 0].legend(fontsize=7, ncol=4, loc="upper left")
    axes[-1, 0].set_xlabel("час ESP32, с   (сіра зона — test, зелена смуга — ±½ кадру)")
    fig.suptitle("Похибка синхронізації кожного спалаху: модель підігнана на train, перевірка на test", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "subframe_ablation.png", dpi=110)
    print(f"→ {out / 'subframe_ablation.csv'}, {out / 'subframe_ablation.png'}")


if __name__ == "__main__":
    main()
