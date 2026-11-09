# FlashSync

Синхронізація 8-камерного відео мокап-студії за спалахами світлодіодів ESP32.
Курсовий проєкт з Computer Vision (robotdreams), захист 16.11.2026.

## Задача

8 камер Xiaomi Yi (MJPEG AVI, 1920×1080 @ 50 fps, запис через Mocap Director) не мають апаратного genlock:

- **зсув (offset)** — камери стартують по черзі, з кроком ~0.5 с;
- **дрейф (drift)** — годинники трактів відрізняються на сотні ppm, тож зсув росте з часом;
- **повтори кадрів** — карта захоплення інколи дублює кадр, і всі наступні кадри зсуваються.

ESP32 блимає світлодіодами (2–4 у полі зору кожної камери), а Mocap Director пише лог
`esp32_flashes.txt` з часом кожного спалаху за годинником ESP32. **Цей лог — ground truth.**

Мета: для кожної камери знайти `t_esp = a · t_cam + b` і показати, що похибка синхронізації
менша за один кадр (20 мс).

## Структура

```
flashsync/      бібліотека: io, led_detect, flash_detect, subframe, fit, evaluate
scripts/        CLI-скрипти
tests/          pytest; tests/data — короткі фрагменти справжніх логів
notebooks/      аналіз і графіки для презентації
results/        графіки й таблиці (без сирих відео)
docs/PLAN.md    план проєкту
```

## Встановлення

```bash
pip install -r requirements.txt
pytest
python scripts/inspect_take.py "шлях/до/Take_001"
```

Сирі AVI в репозиторій не потрапляють (`.gitignore`).

## Прогрес

- [x] `io.py` — читання AVI, парсер `esp32_flashes.txt`, час старту камер з `ffmpeg.log`
- [ ] `led_detect.py` — автоматичний пошук LED
- [ ] `flash_detect.py` — моменти спалахів
- [ ] `subframe.py` — уточнення через rolling shutter
- [ ] `fit.py` — зіставлення з ESP32 і регресія offset + drift
- [ ] `evaluate.py` — метрики, базові методи, графіки
- [ ] демо до/після
