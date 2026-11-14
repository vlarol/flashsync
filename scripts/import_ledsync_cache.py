"""Імпорт кешу FlashSync (<відео>.ledsync.npz) як сигналів LED цього проєкту.

FlashSync (студійний інструмент) під час аналізу вже зберігає яскравість кожного LED у кожному
кадрі. Коли сирі AVI завеликі, щоб переносити їх (1.5 ГБ на камеру), достатньо цих кешів:

    python scripts/import_ledsync_cache.py <папка з *.ledsync.npz> --name Test_3min_Take_001

→ results/run/<name>/signals_CAMxx.npz (формат flash_detect.LedSignals)
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flashsync import io  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default="results/run")
    args = ap.parse_args()
    out = Path(args.out) / args.name
    out.mkdir(parents=True, exist_ok=True)
    for f in sorted(Path(args.folder).glob("*.ledsync.npz")):
        cid = io.camera_id(f.name.split(".")[0])
        z = np.load(f)
        key = json.loads(str(z["key"]))
        t = z["t"].astype(np.float64)
        fps = 1.0 / float(np.median(np.diff(t)))
        leds = np.array(key["pts"], dtype=np.float64)
        v = z["v"].astype(np.float32)
        np.savez_compressed(out / f"signals_CAM{cid:02d}.npz", t=t - t[0], v=v, dup=z["dup"].astype(bool),
                            rows=np.zeros((len(t), v.shape[1], 1), np.float32), fps=fps, leds=leds)
        print(f"CAM{cid:02d}: {len(t)} кадрів, {fps:.2f} fps, LED {len(leds)}, повторів {int(z['dup'].sum())}")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
