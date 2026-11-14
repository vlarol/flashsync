"""Читання даних одного тейку Mocap Director.

Тейк — це папка з такими файлами:
    CAM01_CAM 01.avi … CAM08_CAM 08.avi   сирі MJPEG AVI (stream copy з карт захоплення)
    esp32_flashes.txt                     лог спалахів ESP32 (ground truth часу)
    ffmpeg.log                            лог запису (звідси час старту кожної камери)
    metadata.json                         метадані Mocap Director (опційно)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Номер камери з назви файлу
# ---------------------------------------------------------------------------

_CAM_RE = re.compile(r"cam(?:era)?[\s_\-]*0*(\d+)", re.IGNORECASE)


def camera_id(name: str) -> Optional[int]:
    """'CAM01_CAM 01.avi' → 1, 'Cam_3.mp4' → 3, 'take.avi' → None."""
    stem = re.split(r"[\\/]", str(name))[-1].rsplit(".", 1)[0]
    m = _CAM_RE.search(stem)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# esp32_flashes.txt
# ---------------------------------------------------------------------------

FLASH_COLUMNS = ["kind", "flash_no", "esp_us", "host_utc", "t_host_s", "t_est_s"]


def load_flash_log(path: str | Path) -> pd.DataFrame:
    """Парсить лог спалахів ESP32.

    Повертає DataFrame з колонками:
        kind      MASTER / REGULAR / PRE
        flash_no  номер спалаху з прошивки
        esp_us    сирий лічильник плати, мкс
        t_host_s  час приходу рядка на ПК (з джитером), с від старту запису
        t_esp_s   час спалаху за годинником ESP32, с від старту запису  ← ground truth

    t_esp_s = t_est_s першого рядка + (esp_us - esp_us[0]) / 1e6.
    Лічильник може бути 32-бітним (переповнюється кожні ~71.6 хв) — переповнення
    розгортається; 64-бітні значення обробляються так само.
    """
    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t") if "\t" in line else line.split()
            if len(parts) < len(FLASH_COLUMNS):
                continue
            try:
                rows.append({
                    "kind": parts[0].upper(),
                    "flash_no": int(parts[1]),
                    "esp_us": int(parts[2]),
                    "host_utc": parts[3],
                    "t_host_s": float(parts[4]),
                    "t_est_s": float(parts[5]),
                })
            except ValueError:
                continue
    if not rows:
        raise ValueError(f"{path}: не знайдено жодного рядка зі спалахом")

    df = pd.DataFrame(rows)
    d = np.diff(df["esp_us"].to_numpy(dtype=np.int64))
    d = np.where(d < 0, d + (1 << 32), d)                 # переповнення 32-біт лічильника
    df["t_esp_s"] = df["t_est_s"].iloc[0] + np.concatenate([[0], np.cumsum(d)]) / 1e6
    return df


def flash_period(df: pd.DataFrame) -> float:
    """Медіанний інтервал між REGULAR-спалахами, с."""
    reg = df.loc[df["kind"] == "REGULAR", "t_esp_s"].to_numpy()
    t = reg if len(reg) >= 2 else df["t_esp_s"].to_numpy()
    return float(np.median(np.diff(t))) if len(t) >= 2 else float("nan")


# ---------------------------------------------------------------------------
# ffmpeg.log → час старту кожної камери
# ---------------------------------------------------------------------------

_RE_IN = re.compile(r"^\s*Stream #(\d+):\d+.*?Video:.*?start ([\d.]+)")
_RE_MAP = re.compile(r"^\s*Stream #(\d+):\d+ -> #(\d+):\d+ \(copy\)")
_RE_OUT = re.compile(r"^Output #(\d+), \w+, to '(.+)':")


def capture_start_times(ffmpeg_log: str | Path) -> Dict[str, float]:
    """Абсолютний час старту захоплення (годинник dshow, с) для кожного AVI.

    DirectShow відкриває камери по черзі, тож AVI стартують із кроком ~0.5 с.
    Ланцюжок: вхід #k (start …) → 'Stream #k:0 -> #N:0 (copy)' → 'Output #N … to <файл>'.
    Ключ — ім'я файлу в нижньому регістрі.
    """
    starts: Dict[int, float] = {}
    maps: Dict[int, int] = {}
    outs: Dict[int, str] = {}
    with open(ffmpeg_log, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.replace("\r", "\n").split("\n")[0]
            if m := _RE_IN.match(line):
                starts[int(m[1])] = float(m[2])
            elif m := _RE_MAP.match(line):
                maps[int(m[2])] = int(m[1])
            elif m := _RE_OUT.match(line):
                outs[int(m[1])] = re.split(r"[\\/]", m[2])[-1].lower()
    return {name: starts[maps[o]] for o, name in outs.items() if o in maps and maps[o] in starts}


# ---------------------------------------------------------------------------
# Відео
# ---------------------------------------------------------------------------

@dataclass
class VideoMeta:
    path: Path
    width: int
    height: int
    fps: float
    n_frames: int

    @property
    def frame_dur(self) -> float:
        return 1.0 / self.fps if self.fps else float("nan")


def video_meta(path: str | Path) -> VideoMeta:
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"Не вдалося відкрити відео: {path}")
    try:
        return VideoMeta(Path(path),
                         int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                         int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                         float(cap.get(cv2.CAP_PROP_FPS)),
                         int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))
    finally:
        cap.release()


def iter_frames(path: str | Path, start: int = 0, stop: Optional[int] = None,
                gray: bool = False) -> Iterator[Tuple[int, np.ndarray]]:
    """Послідовно віддає (номер кадру, кадр BGR або grayscale)."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise IOError(f"Не вдалося відкрити відео: {path}")
    try:
        if start:
            cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        i = start
        while stop is None or i < stop:
            ok, frame = cap.read()
            if not ok:
                break
            yield i, (cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if gray else frame)
            i += 1
    finally:
        cap.release()


def read_frame(path: str | Path, index: int, gray: bool = False) -> np.ndarray:
    for _, frame in iter_frames(path, index, index + 1, gray):
        return frame
    raise IndexError(f"{path}: кадру {index} немає")


# ---------------------------------------------------------------------------
# Тейк
# ---------------------------------------------------------------------------

@dataclass
class Take:
    folder: Path
    videos: Dict[int, Path]                      # номер камери → AVI
    flash_log: Optional[Path] = None
    ffmpeg_log: Optional[Path] = None
    metadata: dict = field(default_factory=dict)

    @property
    def camera_ids(self) -> List[int]:
        return sorted(self.videos)

    def flashes(self) -> pd.DataFrame:
        if self.flash_log is None:
            raise FileNotFoundError(f"{self.folder}: немає esp32_flashes.txt")
        return load_flash_log(self.flash_log)

    def start_offsets(self) -> Dict[int, float]:
        """Старт кожної камери відносно першої, с (з ffmpeg.log). Порожньо, якщо логу немає."""
        if self.ffmpeg_log is None:
            return {}
        abs_t = capture_start_times(self.ffmpeg_log)
        res = {cid: abs_t[p.name.lower()] for cid, p in self.videos.items() if p.name.lower() in abs_t}
        if not res:
            return {}
        t0 = min(res.values())
        return {cid: t - t0 for cid, t in sorted(res.items())}


def load_take(folder: str | Path, pattern: str = "CAM*.avi", require_videos: bool = True) -> Take:
    folder = Path(folder)
    videos: Dict[int, Path] = {}
    for p in sorted(folder.glob(pattern)):
        if "_synced" in p.stem:
            continue
        cid = camera_id(p.name)
        if cid is not None:
            videos[cid] = p
    if not videos and require_videos:
        raise FileNotFoundError(f"{folder}: не знайдено відео за шаблоном {pattern}")
    flash = folder / "esp32_flashes.txt"
    ff = folder / "ffmpeg.log"
    meta_p = folder / "metadata.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
    return Take(folder, videos,
                flash if flash.exists() else None,
                ff if ff.exists() else None,
                meta)
