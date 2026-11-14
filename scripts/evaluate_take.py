"""Повна оцінка тейку: таблиця методів, міжкамерна похибка, графіки.

    python scripts/run_take.py <тейк> --leds ...      # спершу: сигнали LED
    python scripts/evaluate_take.py <тейк>

→ results/eval/<тейк>/: table.md, per_camera.csv, inter_camera.csv,
  errors_test.png, drift.png, horizon.png
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flashsync import io, evaluate as ev, flash_detect as fd  # noqa: E402

COLORS = {"B0": "#cbd5e1", "B1": "#94a3b8", "B2": "#64748b", "B2+dup": "#f59e0b", "Ours": "#2563eb"}


def load_signals(path: Path) -> fd.LedSignals:
    z = np.load(path)
    return fd.LedSignals(z["t"], z["v"], z["dup"], float(z["fps"]), [tuple(p) for p in z["leds"]], z["rows"])


def fmt(x):
    return "—" if not np.isfinite(x) else (f"{x:.0f}" if x >= 100 else f"{x:.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("take")
    ap.add_argument("--run-dir", default="results/run")
    ap.add_argument("--out", default="results/eval")
    ap.add_argument("--train-frac", type=float, default=0.5)
    ap.add_argument("--name", help="назва тейку в results/ (типово — назва папки)")
    ap.add_argument("--height", type=int, default=1080, help="висота кадру, якщо відео немає поруч")
    ap.add_argument("--horizon", type=float, nargs="+", default=[4, 6, 8, 10, 12],
                    help="скільки секунд спалахів на train для графіка horizon")
    args = ap.parse_args()

    take = io.load_take(args.take, require_videos=False)
    log = take.flashes()
    name = args.name or take.folder.name
    run = Path(args.run_dir) / name
    out = Path(args.out) / name
    cams = take.camera_ids or sorted(int(p.stem[-2:]) for p in run.glob("signals_CAM*.npz"))
    out.mkdir(parents=True, exist_ok=True)

    sigs, heights, evals = {}, {}, []
    for cid in cams:
        sigs[cid] = load_signals(run / f"signals_CAM{cid:02d}.npz")
        heights[cid] = io.video_meta(take.videos[cid]).height if cid in take.videos else args.height
        evals.append(ev.evaluate_camera(cid, sigs[cid], heights[cid], log, args.train_frac))
    ev.add_b0(evals, ref=cams[0])

    per = ev.summary_table(evals)
    inter = ev.inter_camera(evals)
    per.round(2).to_csv(out / "per_camera.csv", index=False)
    inter.round(2).to_csv(out / "inter_camera.csv", index=False)

    # ---- таблиця markdown ----
    lines = ["| Метод | RMS відносно ESP32, мс | 95% спалахів у межах, мс | Найгірший спалах, мс | Розкид між камерами RMS / max, мс |",
             "|---|---|---|---|---|"]
    names = {"B0": "B0 — за номером кадру", "B1": "B1 — зсув з MASTER, без дрейфу",
             "B2": "B2 — зсув + дрейф, до кадру", "B2+dup": "B2 + поправка на повтори кадрів",
             "Ours": "**Ours — субкадрове уточнення + поправка**"}
    for m in ev.METHODS:
        i = inter[inter["method"] == m].iloc[0]
        lines.append(f"| {names[m]} | {fmt(per[f'{m}_rms'].mean())} | {fmt(per[f'{m}_p95'].mean())} | {fmt(per[f'{m}_max'].max())} | "
                     f"{fmt(i['spread_rms_ms'])} / {fmt(i['spread_max_ms'])} |")
    lines += ["", "| Камера | test-спалахів | " + " | ".join(ev.METHODS) + " | дрейф Ours, ppm | E, мс | R, мс |",
              "|---|---|" + "---|" * (len(ev.METHODS) + 3)]
    for _, r in per.iterrows():
        lines.append(f"| {r['camera']} | {r['test_flashes']} | " +
                     " | ".join(fmt(r[f'{m}_rms']) for m in ev.METHODS) +
                     f" | {r['Ours_drift_ppm']:+.0f} | {r['E_ms']:.0f} | {r['R_ms']:.0f} |")
    (out / "table.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    # ---- графік 1: похибка на test (без B0 — вона в сотні мс) ----
    fig, axes = plt.subplots(len(evals), 1, figsize=(11, 1.2 + 1.4 * len(evals)), sharex=True, squeeze=False)
    for ax, e in zip(axes[:, 0], evals):
        for m in ev.METHODS[1:]:
            ax.plot(e.esp_t, e.errors_ms(m), "o-", ms=2.5, lw=0.9, color=COLORS[m], label=m)
        ax.axvspan(e.esp_t[e.test].min(), e.esp_t.max(), color="#e2e8f0", lw=0, zorder=0)
        ax.axhspan(-10, 10, color="#22c55e", alpha=0.08, lw=0)
        ax.set_ylim(-40, 40)
        ax.set_ylabel(f"CAM{e.camera:02d}\nмс", fontsize=8)
        ax.tick_params(labelsize=7)
    axes[0, 0].legend(fontsize=7, ncol=4, loc="upper left")
    axes[-1, 0].set_xlabel("час ESP32, с  (сіра зона — test; зелена смуга — ±½ кадру)")
    fig.suptitle("Похибка відносно годинника ESP32 на кожному спалаху", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "errors_test.png", dpi=110)
    plt.close(fig)

    # ---- графік 2: міжкамерна похибка (стовпчики, лог-шкала) ----
    fig, ax = plt.subplots(figsize=(7, 3.6))
    vals = [inter.set_index("method").loc[m, "spread_rms_ms"] for m in ev.METHODS]
    bars = ax.bar(ev.METHODS, vals, color=[COLORS[m] for m in ev.METHODS])
    ax.set_yscale("log")
    ax.axhline(20, color="#dc2626", lw=0.8, ls="--")
    ax.text(len(vals) - 0.5, 21, "1 кадр (20 мс)", color="#dc2626", fontsize=8, ha="right", va="bottom")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v * 1.1, fmt(v), ha="center", fontsize=8)
    ax.set_ylabel("розкид між камерами, мс (RMS)")
    ax.set_title("Наскільки камери розходяться на одному й тому самому спалаху (test)", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "inter_camera.png", dpi=110)
    plt.close(fig)

    # ---- графік 3: дрейф кожної камери ----
    fig, ax = plt.subplots(figsize=(7, 3.2))
    x = np.arange(len(per))
    ax.bar(x - 0.2, per["B2_drift_ppm"], 0.4, color=COLORS["B2"], label="B2 (до кадру)")
    ax.bar(x + 0.2, per["Ours_drift_ppm"], 0.4, color=COLORS["Ours"], label="Ours")
    ax.axhline(0, color="#334155", lw=0.6)
    ax.set_xticks(x, per["camera"])
    ax.set_ylabel("дрейф, ppm")
    ax.legend(fontsize=8)
    ax.set_title("Оцінений дрейф годинника камери відносно ESP32", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "drift.png", dpi=110)
    plt.close(fig)

    # ---- графік 4: похибка vs довжина train ----
    hor = []
    for cid in cams:
        h = ev.error_vs_horizon(sigs[cid], heights[cid], log, train_seconds=args.horizon)
        h["camera"] = cid
        hor.append(h)
    import pandas as pd
    hor = pd.concat(hor)
    hor.round(2).to_csv(out / "horizon.csv", index=False)
    g = hor.groupby(["train_s", "method"])["rms"].mean().unstack()
    fig, ax = plt.subplots(figsize=(7, 3.4))
    for m in ev.METHODS[1:]:
        if m in g:
            ax.plot(g.index, g[m], "o-", color=COLORS[m], label=m)
    ax.set_yscale("log")
    ax.set_xlabel("скільки секунд спалахів на train (решта тейку — test)")
    ax.set_ylabel("RMS на test, мс (середнє по камерах)")
    ax.legend(fontsize=8)
    ax.set_title("Скільки даних треба, щоб модель трималась далі в часі", fontsize=10)
    fig.tight_layout()
    fig.savefig(out / "horizon.png", dpi=110)
    plt.close(fig)
    print(f"\n→ {out}")


if __name__ == "__main__":
    main()
