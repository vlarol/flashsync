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
- [x] `led_detect.py` — автоматичний пошук LED (epoch folding + Otsu + морфологія + connected components)
- [ ] `flash_detect.py` — моменти спалахів
- [ ] `subframe.py` — уточнення через rolling shutter
- [ ] `fit.py` — зіставлення з ESP32 і регресія offset + drift
- [ ] `evaluate.py` — метрики, базові методи, графіки
- [ ] демо до/після

## Результати

### Пошук LED (`led_detect.py`)

Тейк 2Avitest (6 камер, 1080p50, у кадрі ходить актор). Ручна розмітка — 16 LED.
Знайдений LED вважається правильним, якщо він ближче 12 px до ручної позначки.

| Метод | Recall | Precision | Похибка центру |
|---|---|---|---|
| Базовий: `max − median` → Otsu → відкриття → компоненти | 6/16 (38%) | 6/6 | 1.3 px |
| **Наш: epoch folding → Otsu/MAD → закриття → компоненти + перевірка періодичності** | **16/16 (100%)** | 16/19 (84%) | 3.4 px |

![naive vs folded](results/led_detect/2Avitest_Take001/naive_vs_folded.jpg)

Чому базовий метод не працює: у карті `max − median` рух актора яскравіший за тьмяні LED,
і поріг Otsu стає між ними — тьмяні LED губляться (CAM01, CAM02, CAM08 — жодного).
Синхронне усереднення по періоду ESP32 (1 с) розмазує рух актора по всіх фазах і лишає
гострий пік лише там, де світло блимає в ритм.

Три «зайві» знахідки (CAM02, CAM07, CAM08) теж блимають у ритм ESP32 з періодичністю 0.83–0.90:
це LED біля краю кадру або їхні відблиски на стіні, які не були розмічені вручну. Для
синхронізації вони не шкодять — це той самий сигнал.

Відтворити:

```bash
python scripts/detect_leds.py <тейк> --reference results/led_detect/2Avitest_Take001/manual_leds.json --method naive
python scripts/detect_leds.py <тейк> --reference results/led_detect/2Avitest_Take001/manual_leds.json --method folded
```

