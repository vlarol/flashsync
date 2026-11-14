"""Демо «до / після»: ті самі моменти часу ESP32 на всіх камерах.

    python scripts/evaluate_take.py <тейк>            # створює results/eval/<тейк>/sync_models.json
    python scripts/make_demo.py <тейк> [--flash 60] [--slowmo 5]

Верхня половина — «ДО»: кожна камера показує кадр з тим самим номером (як при простому
вирівнюванні за стартом запису). Нижня — «ПІСЛЯ»: для кожного моменту τ береться кадр,
чий момент експозиції за моделлю FlashSync найближчий до τ:

    момент кадру n = a · (t_eff[n] + R/2 + E/2) + b

(t_eff — шкала камери з поправкою на нерегулярні повтори, R/2 — центр кадру з rolling
shutter, E/2 — середина експозиції). Під кожною плиткою — на скільки мілісекунд момент
показаного кадру відходить від τ. Збільшена вставка в куті — перший LED камери:
після синхронізації спалах загоряється на всіх камерах в одному кадрі.

→ results/demo/<тейк>/demo.mp4, demo.gif, frame_*.png
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flashsync import io  # noqa: E402

TILE_W, TILE_H = 480, 270
HEAD = 34
FOOT = 22
BLUE, GREY, RED, GREEN = (235, 99, 37), (139, 116, 100), (38, 38, 220), (94, 197, 34)


class Camera:
    def __init__(self, cid, path, m, leds=None):
        self.cid, self.path = cid, path
        self.fps, self.b0 = m["fps"], m["b0_offset"]
        n = m["frames"]
        shift = np.zeros(n)
        for i in m["irregular_dups"]:
            shift[i:] += 1.0 / self.fps
        t_eff = np.arange(n) / self.fps - shift
        self.moment = m["a"] * (t_eff + m["R"] / 2 + m["E"] / 2) + m["b"]
        ok = np.ones(n, bool)
        ok[m["dup_frames"]] = False               # копії попереднього кадру не показуємо
        self.ok_idx = np.where(ok)[0]
        self.leds = leds
        self.cap, self.pos, self.last = cv2.VideoCapture(str(path)), -1, None

    def frame_after(self, tau):
        k = np.searchsorted(self.moment[self.ok_idx], tau)
        c = [i for i in (k - 1, k) if 0 <= i < len(self.ok_idx)]
        n = min((self.ok_idx[i] for i in c), key=lambda j: abs(self.moment[j] - tau))
        return int(n)

    def frame_before(self, tau):
        return int(np.clip(round((tau - self.b0) * self.fps), 0, len(self.moment) - 1))

    def read(self, n):
        if n == self.pos:
            return self.last
        if not (self.pos < n <= self.pos + 60):
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, n)
            self.pos = n - 1
        while self.pos < n:
            ok, fr = self.cap.read()
            self.pos += 1
            if not ok:
                fr = np.zeros((1080, 1920, 3), np.uint8)
            self.last = fr
        return self.last


def tile(cam, frame, n, err_ms, color):
    h, w = frame.shape[:2]
    t = cv2.resize(frame, (TILE_W, TILE_H), interpolation=cv2.INTER_AREA)
    if cam.leds is not None and len(cam.leds):        # збільшена вставка навколо першого LED
        x, y = (int(v) for v in cam.leds[0])
        r = max(24, h // 30)
        x0, y0 = np.clip(x - r, 0, w - 2 * r), np.clip(y - r, 0, h - 2 * r)
        crop = cv2.resize(frame[y0:y0 + 2 * r, x0:x0 + 2 * r], (96, 96), interpolation=cv2.INTER_NEAREST)
        t[TILE_H - 100:TILE_H - 4, TILE_W - 100:TILE_W - 4] = crop
        cv2.rectangle(t, (TILE_W - 101, TILE_H - 101), (TILE_W - 3, TILE_H - 3), (255, 255, 255), 1)
        sx, sy = TILE_W / w, TILE_H / h
        cv2.circle(t, (int(x * sx), int(y * sy)), 9, (255, 255, 255), 1, cv2.LINE_AA)
    out = np.full((TILE_H + FOOT, TILE_W, 3), 24, np.uint8)
    out[:TILE_H] = t
    cv2.putText(out, f"CAM{cam.cid:02d}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(out, f"CAM{cam.cid:02d}", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(out, f"frame {n}   offset {err_ms:+.0f} ms", (8, TILE_H + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    return out


def grid(tiles, cols):
    rows = -(-len(tiles) // cols)
    blank = np.full_like(tiles[0], 24)
    tiles = tiles + [blank] * (rows * cols - len(tiles))
    return np.vstack([np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(rows)])


def header(width, text, sub, color):
    h = np.full((HEAD, width, 3), 16, np.uint8)
    cv2.rectangle(h, (0, 0), (6, HEAD), color, -1)
    cv2.putText(h, text, (16, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(h, sub, (16 + 14 * len(text) + 20, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1, cv2.LINE_AA)
    return h


def compose(cams, tau, in_flash, cols):
    before, after, eb, ea = [], [], [], []
    for c in cams:
        nb, na = c.frame_before(tau), c.frame_after(tau)
        db, da = (c.moment[nb] - tau) * 1000, (c.moment[na] - tau) * 1000
        eb.append(db); ea.append(da)
        before.append(tile(c, c.read(nb), nb, db, (120, 140, 255)))
        after.append(tile(c, c.read(na), na, da, (140, 230, 140)))
    gb, ga = grid(before, cols), grid(after, cols)
    W = gb.shape[1]
    spread_b, spread_a = max(eb) - min(eb), max(ea) - min(ea)
    top = np.full((40, W, 3), 0, np.uint8)
    cv2.putText(top, f"ESP32 t = {tau:8.3f} s", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    if in_flash:
        cv2.circle(top, (330, 20), 10, (60, 230, 255), -1, cv2.LINE_AA)
        cv2.putText(top, "LED ON", (348, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 230, 255), 2, cv2.LINE_AA)
    return np.vstack([
        top,
        header(W, "BEFORE", f"same frame number   |   shown frames spread {spread_b:.0f} ms", GREY), gb,
        header(W, "AFTER  FlashSync", f"frame picked by the model   |   shown frames spread {spread_a:.0f} ms (<= 1 frame)", BLUE), ga,
    ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("take")
    ap.add_argument("--sync", help="sync_models.json (типово results/eval/<тейк>/sync_models.json)")
    ap.add_argument("--name", help="назва тейку в results/")
    ap.add_argument("--run-dir", default="results/run", help="звідки взяти координати LED (signals_CAMxx.npz)")
    ap.add_argument("--flash", type=float, help="час ESP32 (с), біля якого зробити демо; типово — REGULAR-спалах посередині тейку")
    ap.add_argument("--before", type=float, default=0.25, help="секунд до спалаху")
    ap.add_argument("--after", type=float, default=0.45, help="секунд після початку спалаху")
    ap.add_argument("--step", type=float, default=0.02, help="крок τ, с (20 мс = кадр 50p)")
    ap.add_argument("--slowmo", type=float, default=5.0, help="у скільки разів сповільнити")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--out", default="results/demo")
    args = ap.parse_args()

    take = io.load_take(args.take)
    name = args.name or take.folder.name
    sync = Path(args.sync or Path("results/eval") / name / "sync_models.json")
    models = json.loads(sync.read_text(encoding="utf-8"))["cameras"]
    log = take.flashes()
    reg = log[log["kind"] == "REGULAR"]

    cams = []
    for cid in take.camera_ids:
        key = f"cam{cid:02d}"
        if key not in models:
            print(f"CAM{cid:02d}: немає моделі в {sync}, пропускаю")
            continue
        npz = Path(args.run_dir) / name / f"signals_CAM{cid:02d}.npz"
        leds = np.load(npz)["leds"] if npz.exists() else np.array(models[key].get("leds", []))
        cams.append(Camera(cid, take.videos[cid], models[key], leds))

    # спалах, який бачать усі камери
    lo = max(c.moment[0] for c in cams) + 1.0
    hi = min(c.moment[-1] for c in cams) - 1.0
    cand = reg[(reg["t_esp_s"] > lo) & (reg["t_esp_s"] < hi)]["t_esp_s"].to_numpy()
    if args.flash is not None:
        tf = float(cand[np.argmin(np.abs(cand - args.flash))])
    else:
        tf = float(cand[len(cand) // 2])
    dur = 0.07
    taus = np.arange(tf - args.before, tf + args.after, args.step)
    print(f"спалах t_esp = {tf:.3f} с, {len(taus)} кадрів демо")

    out = Path(args.out) / name
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for tau in taus:
        fr = compose(cams, tau, tf <= tau < tf + dur, args.cols)
        frames.append(fr)
    for k, fr in enumerate(frames):
        if abs(taus[k] - (tf + 0.01)) < args.step / 2 + 1e-9:
            cv2.imwrite(str(out / "frame_flash.png"), fr)
    cv2.imwrite(str(out / "frame_first.png"), frames[0])

    fps_out = 1.0 / args.step / args.slowmo
    h, w = frames[0].shape[:2]
    raw = out / "demo_raw.mp4"
    vw = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps_out, (w, h))
    for fr in frames:
        vw.write(fr)
    vw.release()
    mp4 = out / "demo.mp4"
    if shutil.which("ffmpeg"):      # H.264 — грається в браузері й PowerPoint
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-c:v", "libx264", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", "-crf", "23", str(mp4)], check=True)
        raw.unlink()
    else:
        raw.replace(mp4)
    try:
        import imageio.v2 as imageio
        small = [cv2.cvtColor(cv2.resize(f, (w // 3, h // 3), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
                 for f in frames]
        imageio.mimsave(out / "demo.gif", small, duration=1.0 / fps_out, loop=0)
    except ImportError:
        print("imageio не встановлено — GIF пропущено")
    print(f"→ {mp4}")


if __name__ == "__main__":
    main()
