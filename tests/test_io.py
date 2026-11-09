from pathlib import Path

import numpy as np
import pytest

from flashsync import io

DATA = Path(__file__).parent / "data"


def test_camera_id():
    assert io.camera_id("CAM01_CAM 01.avi") == 1
    assert io.camera_id(r"F:\x\CAM08_CAM 08.avi") == 8
    assert io.camera_id("Cam_3.mp4") == 3
    assert io.camera_id("take.avi") is None


def test_flash_log():
    df = io.load_flash_log(DATA / "esp32_flashes_sample.txt")
    assert len(df) == 7
    assert df["kind"].iloc[0] == "MASTER"
    # MASTER → перший REGULAR — нерегулярний інтервал 1.21 с, далі рівно 1 с
    gaps = np.diff(df["t_esp_s"].to_numpy())
    assert gaps[0] == pytest.approx(1.21, abs=1e-3)
    assert np.allclose(gaps[1:], 1.0, atol=1e-4)
    assert io.flash_period(df) == pytest.approx(1.0, abs=1e-4)
    # годинник ESP32 збігається з t_est_s
    assert np.allclose(df["t_esp_s"], df["t_est_s"], atol=2e-4)


def test_flash_log_32bit_wrap(tmp_path):
    p = tmp_path / "wrap.txt"
    us = [(1 << 32) - 500_000, 500_000]          # переповнення між спалахами
    p.write_text("".join(f"REGULAR\t{i}\t{u}\t-\t{i}.0\t{i}.0\n" for i, u in enumerate(us)))
    df = io.load_flash_log(p)
    assert df["t_esp_s"].iloc[1] - df["t_esp_s"].iloc[0] == pytest.approx(1.0)


def test_capture_start_times():
    st = io.capture_start_times(DATA / "ffmpeg_sample.log")
    assert len(st) == 6
    first = st["cam01_cam 01.avi"]
    rel = sorted(t - first for t in st.values())
    assert rel[0] == 0.0
    assert np.all(np.diff(rel) > 0.4) and np.all(np.diff(rel) < 0.6)   # крок ~0.5 с


def test_video_roundtrip(tmp_path):
    cv2 = pytest.importorskip("cv2")
    p = tmp_path / "CAM02_CAM 02.avi"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"MJPG"), 50, (64, 48))
    for i in range(10):
        w.write(np.full((48, 64, 3), i * 20, np.uint8))
    w.release()
    meta = io.video_meta(p)
    assert (meta.width, meta.height, meta.n_frames) == (64, 48, 10)
    assert meta.fps == pytest.approx(50)
    frames = list(io.iter_frames(p, gray=True))
    assert len(frames) == 10
    assert abs(int(frames[5][1].mean()) - 100) < 5
    take = io.load_take(tmp_path)
    assert take.camera_ids == [2] and take.flash_log is None
