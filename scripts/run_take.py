"""Тейк → sync.json + графіки.

    python scripts/run_take.py <тейк> [--leds results/led_detect/<тейк>/folded/leds.json]

Кроки: LED (автопошук або готовий leds.json) → сигнали → спалахи → зіставлення з
esp32_flashes.txt → модель t_esp = a·t_cam + b для кожної камери.
Сигнали кешуються в results/run/<тейк>/signals_CAMxx.npz (повторний запуск — секунди).
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flashsync import io, led_detect as ld, flash_detect as fd, fit  # noqa: E402


def load_or_extract(path, leds, cache: Path) -> fd.LedSignals:
    if cache.exists():
        z = np.load(cache)
        if np.allclose(z["leds"], np.array(leds)):
            return fd.LedSignals(z["t"], z["v"], z["dup"], float(z["fps"]), [tuple(p) for p in z["leds"]], z["rows"])
    sig = fd.extract_signals(path, leds, progress=lambda i, n: print(f"   кадр {i}/{n}", end="\r"))
    np.savez_compressed(cache, t=sig.t, v=sig.values, dup=sig.dup, rows=sig.rows, fps=sig.fps, leds=np.array(sig.leds))
    return sig


def plot_signals(sig: fd.LedSignals, flashes, match: fit.Match, title: str, out: Path, seconds=(4, 12)):
    i0, i1 = int(seconds[0] * sig.fps), int(seconds[1] * sig.fps)
    fig, axes = plt.subplots(sig.values.shape[1], 1, figsize=(11, 1.6 + 1.3 * sig.values.shape[1]),
                             sharex=True, squeeze=False)
    for j, ax in enumerate(axes[:, 0]):
        pulses, resid, thr = fd.led_pulses(sig.values[:, j], sig.fps)
        ax.plot(sig.t[i0:i1], resid[i0:i1], lw=0.9, color="#2563eb")
        ax.axhline(thr, color="#dc2626", lw=0.8, ls="--", label="поріг")
        for f in flashes:
            if seconds[0] <= f.t_on <= seconds[1]:
                ax.axvline(f.t_on, color="#16a34a", lw=0.8)
        ax.set_ylabel(f"LED {j + 1}", fontsize=8)
        ax.tick_params(labelsize=7)
    axes[0, 0].legend(fontsize=7, loc="upper right")
    axes[-1, 0].set_xlabel("час у файлі камери, с")
    fig.suptitle(f"{title}: яскравість LED над фоном, зелені лінії — знайдені спалахи", fontsize=10)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("take")
    ap.add_argument("--leds", help="leds.json з scripts/detect_leds.py (інакше — автопошук)")
    ap.add_argument("--out", default="results/run")
    args = ap.parse_args()

    take = io.load_take(args.take)
    log = take.flashes()
    out = Path(args.out) / take.folder.name
    out.mkdir(parents=True, exist_ok=True)
    leds_all = json.loads(Path(args.leds).read_text(encoding="utf-8")) if args.leds else {}
    period = io.flash_period(log)

    result = {"take": str(take.folder), "flashes_in_log": len(log), "period_s": period, "cameras": {}}
    print(f"{'камера':<8}{'кадрів':>8}{'повторів':>10}{'спалахів':>10}{'зіставлено':>12}{'зсув b, с':>11}"
          f"{'дрейф, ppm':>12}{'RMS, мс':>9}")
    for cid in take.camera_ids:
        key = f"cam{cid:02d}"
        if key in leds_all:
            leds = [(c["x"], c["y"]) for c in leds_all[key]]
        else:
            cands, _ = ld.detect_leds(take.videos[cid], ld.DetectParams(period_s=period))
            leds = [(c.x, c.y) for c in cands if c.accepted]
        sig = load_or_extract(take.videos[cid], leds, out / f"signals_CAM{cid:02d}.npz")
        flashes = fd.detect_flashes(sig)
        m = fit.match_flashes(flashes, log)
        resid = (m.esp_t - m.model(m.cam_t)) * 1000
        rms = float(np.sqrt(np.mean(resid ** 2)))
        result["cameras"][key] = {
            "video": take.videos[cid].name, "fps": sig.fps, "frames": int(len(sig.t)),
            "dup_frames": int(sig.dup.sum()), "leds": [list(p) for p in leds],
            "flashes_found": len(flashes), "flashes_matched": int(len(m.cam_t)),
            "master_found": m.master_found,
            "a": m.model.a, "b": m.model.b, "offset_ms": m.model.b * 1000, "drift_ppm": m.model.drift_ppm,
            "residual_rms_ms": rms, "residual_max_ms": float(np.abs(resid).max()),
            "pairs": {"t_cam": m.cam_t.tolist(), "t_esp": m.esp_t.tolist(), "flash_no": m.flash_no.tolist()},
        }
        print(f"CAM{cid:02d}  {len(sig.t):>8}{int(sig.dup.sum()):>10}{len(flashes):>10}"
              f"{len(m.cam_t):>7}/{len(log):<4}{m.model.b:>11.4f}{m.model.drift_ppm:>+12.0f}{rms:>9.1f}")
        plot_signals(sig, flashes, m, f"CAM{cid:02d}", out / f"signal_CAM{cid:02d}.png")

    (out / "sync.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {out / 'sync.json'}")


if __name__ == "__main__":
    main()
