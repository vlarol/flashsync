"""Автоматичний пошук LED у всіх камерах тейку + порівняння з ручною розміткою.

    python scripts/detect_leds.py "F:/Mocap/.../Take_001" --reference led_layout.json
    python scripts/detect_leds.py TAKE --method naive        # базовий метод для порівняння

Пише у results/led_detect/<take>/: overlay_CAMxx.jpg, leds.json, summary.csv
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flashsync import io, led_detect as ld  # noqa: E402


def load_reference(path):
    """Ручна розмітка: led_layout.json FlashSync ({"cameras": {"cam01": {"points": [...]}}})."""
    j = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cams = j.get("cameras", {})
    if isinstance(cams, list):                 # проєкт FlashSync
        return {io.camera_id(c.get("file") or c.get("name", "")): c["points"] for c in cams if c.get("points")}
    return {int(k.lower().replace("cam", "")): v["points"] for k, v in cams.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("take")
    ap.add_argument("--reference", help="ручна розмітка LED (led_layout.json або проєкт FlashSync)")
    ap.add_argument("--method", choices=["folded", "naive"], default="folded")
    ap.add_argument("--start", type=float, default=6.0)
    ap.add_argument("--duration", type=float, default=10.0)
    ap.add_argument("--out", default="results/led_detect")
    args = ap.parse_args()

    take = io.load_take(args.take)
    period = io.flash_period(take.flashes()) if take.flash_log else 1.0
    params = ld.DetectParams(start_s=args.start, duration_s=args.duration, period_s=period, method=args.method)
    ref = load_reference(args.reference) if args.reference else {}

    out = Path(args.out) / take.folder.name / args.method
    out.mkdir(parents=True, exist_ok=True)
    all_leds, rows = {}, []
    for cid in take.camera_ids:
        t0 = time.time()
        cands, maps = ld.detect_leds(take.videos[cid], params)
        acc = [c for c in cands if c.accepted]
        all_leds[f"cam{cid:02d}"] = [c.as_dict() for c in acc]
        cv2.imwrite(str(out / f"overlay_CAM{cid:02d}.jpg"),
                    ld.draw_overlay(maps, cands, f"CAM{cid:02d}  {args.method}"))
        row = {"camera": f"CAM{cid:02d}", "candidates": len(cands), "accepted": len(acc),
               "seconds": round(time.time() - t0, 1)}
        if cid in ref:
            row.update(ld.match_to_reference([(c.x, c.y) for c in acc], ref[cid], tol_px=12))
        rows.append(row)
        print(row)

    (out / "leds.json").write_text(json.dumps(all_leds, ensure_ascii=False, indent=2), encoding="utf-8")
    keys = sorted({k for r in rows for k in r}, key=lambda k: list(rows[-1]).index(k) if k in rows[-1] else 99)
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    if ref:
        tp = sum(r.get("tp", 0) for r in rows)
        nref = sum(r.get("reference", 0) for r in rows)
        nfound = sum(r["accepted"] for r in rows if "tp" in r)
        print(f"\nУсього: recall {tp}/{nref} = {tp / max(1, nref):.0%}, precision {tp}/{nfound} = {tp / max(1, nfound):.0%}")
    print(f"Результати: {out}")


if __name__ == "__main__":
    main()
