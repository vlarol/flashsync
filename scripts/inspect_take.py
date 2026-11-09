"""Короткий огляд тейку: камери, відео, спалахи ESP32, старт камер.

    python scripts/inspect_take.py "D:/Mocap_Recordings/5_11/S01/SH01/Take_001"
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flashsync import io  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("take", help="папка тейку Mocap Director")
    args = ap.parse_args()

    take = io.load_take(args.take)
    offsets = take.start_offsets()
    print(f"Тейк: {take.folder}")
    print(f"{'камера':<8}{'файл':<22}{'роздільність':>14}{'fps':>8}{'кадрів':>9}{'старт, с':>10}")
    for cid in take.camera_ids:
        m = io.video_meta(take.videos[cid])
        st = f"{offsets[cid]:.3f}" if cid in offsets else "—"
        print(f"CAM{cid:02d}   {m.path.name:<22}{m.width:>8}×{m.height:<5}{m.fps:>8.2f}{m.n_frames:>9}{st:>10}")

    if take.flash_log:
        df = take.flashes()
        counts = df["kind"].value_counts().to_dict()
        print(f"\nСпалахи ESP32: {len(df)} {counts}, період {io.flash_period(df):.4f} с, "
              f"від {df['t_esp_s'].iloc[0]:.3f} до {df['t_esp_s'].iloc[-1]:.3f} с")
        jitter = (df["t_host_s"] - df["t_esp_s"]) * 1000
        print(f"Джитер хоста відносно годинника ESP32: медіана {jitter.median():.1f} мс, макс {jitter.max():.1f} мс")
    else:
        print("\nesp32_flashes.txt не знайдено")


if __name__ == "__main__":
    main()
