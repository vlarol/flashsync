const pptxgen = require("pptxgenjs");
const fs = require("fs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");
const { applyTheme } = require(process.env.SKILL + "/scripts/apply_theme.js");

const THEME = {
  name: "FlashSync",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "0B1220", lt1: "FFFFFF", dk2: "1A2436", lt2: "CBD5E1",
    accent1: "F5B700", accent2: "3B82F6", accent3: "94A3B8",
    accent4: "22C55E", accent5: "EF4444", accent6: "64748B",
    hlink: "F5B700", folHlink: "94A3B8",
  },
};
const H = THEME.colors;

async function icon(Comp, color, px = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + color, size: px }));
  const buf = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}
const b64 = (p, mime) => mime + ";base64," + fs.readFileSync(p).toString("base64");

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  pres.title = "FlashSync";
  pres.author = "Vlad Gryban";
  const C = pres.SchemeColor;

  pres.defineSlideMaster({
    title: "TITLE",
    background: { color: H.dk1 },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.7, y: 2.2, w: 5.9, h: 1.6, fontSize: 54, bold: true, color: C.background1, valign: "bottom", align: "left", margin: 0 }, text: "" } },
      { placeholder: { options: { name: "body", type: "body", x: 0.7, y: 3.95, w: 5.9, h: 1.4, fontSize: 20, color: C.background2, valign: "top", margin: 0 }, text: "" } },
    ],
  });
  pres.defineSlideMaster({
    title: "CONTENT",
    background: { color: H.dk1 },
    margin: [0.5, 0.6, 0.5, 0.6],
    slideNumber: { x: 12.35, y: 6.95, w: 0.5, h: 0.3, fontSize: 11, color: H.accent3, align: "right" },
    objects: [
      { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 0.85, fontSize: 32, bold: true, color: C.background1, valign: "middle", align: "left", margin: 0 }, text: "" } },
      { text: { text: "FlashSync · robotdreams Computer Vision", options: { x: 0.6, y: 6.95, w: 6, h: 0.3, fontSize: 11, color: H.accent6, margin: 0 } } },
    ],
  });

  const card = (s, x, y, w, h, name, fill = C.text2) =>
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { type: "none" }, objectName: name });
  const txt = (s, t, o) => s.addText(t, { isTextBox: true, margin: 0, ...o });
  const dot = async (s, x, y, d, Comp, name, fill = C.accent1, ic = H.dk1) => {
    s.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { type: "none" }, objectName: name + " circle" });
    s.addImage({ data: await icon(Comp, ic), x: x + d * 0.25, y: y + d * 0.25, w: d * 0.5, h: d * 0.5, objectName: name + " icon" });
  };

  // ---------- 1. Title ----------
  pres.addSection({ title: "Вступ" });
  let s = pres.addSlide({ masterName: "TITLE", sectionTitle: "Вступ" });
  s.addText("FlashSync", { placeholder: "title" });
  s.addText([
    { text: "Синхронізація 8 камер мокап-студії за спалахами LED — точніше за один кадр", options: { breakLine: true } },
    { text: " ", options: { fontSize: 10, breakLine: true } },
    { text: "Влад Грибан · robotdreams, Computer Vision · 16.11.2026", options: { fontSize: 15, color: C.accent3 } },
  ], { placeholder: "body" });
  s.addImage({ path: "full.jpg", x: 7.1, y: 1.2, w: 5.75, h: 5.75 * 1276 / 1920, objectName: "demo frame" });
  txt(s, "Зверху — той самий номер кадру (розкид 3.2 с). Знизу — після FlashSync: спалах на всіх 8 камерах в один момент.", { x: 7.1, y: 5.15, w: 5.75, h: 0.7, fontSize: 13, color: C.accent3 });
  s.addNotes("FlashSync — мій проєкт синхронізації камер мокап-студії. Праворуч результат: зверху камери після синхронізації, знизу — до.");

  // ---------- 2. Motivation ----------
  pres.addSection({ title: "Motivation" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Motivation" });
  s.addText("8 камер без genlock показують різні моменти часу", { placeholder: "title" });
  txt(s, "3.2 с", { x: 0.6, y: 1.55, w: 4.2, h: 1.2, fontSize: 72, bold: true, color: C.accent1, fontFace: "Arial" });
  txt(s, "розкид між камерами на кадрі з однаковим номером (кінець 3.5-хв запису)", { x: 0.6, y: 2.8, w: 4.2, h: 0.75, fontSize: 15, color: C.background2 });
  const probs = [
    [fa.FaPlay, "Зсув старту", "Камери відкриваються по черзі, ~0.46 с на камеру"],
    [fa.FaClock, "Дрейф годинників", "Зсув повільно росте з часом запису"],
    [fa.FaClone, "Повтори кадрів", "Карта захоплення дублює кадр — усе далі зсувається на 20 мс"],
  ];
  for (let i = 0; i < probs.length; i++) {
    const y = 3.85 + i * 0.95;
    await dot(s, 0.6, y, 0.62, probs[i][0], "problem " + i);
    txt(s, probs[i][1], { x: 1.4, y: y - 0.02, w: 3.6, h: 0.32, fontSize: 16, bold: true, color: C.background1 });
    txt(s, probs[i][2], { x: 1.4, y: y + 0.3, w: 3.6, h: 0.5, fontSize: 13, color: C.background2 });
  }
  s.addImage({ path: "before.jpg", x: 5.4, y: 1.55, w: 7.33, h: 7.33 * 582 / 1920, objectName: "before grid" });
  txt(s, "Тріангуляція в Captury потребує 8 кадрів одного моменту. 20 мс розсинхрону — це 10 см руху кисті при 5 м/с.", { x: 5.4, y: 4.0, w: 7.33, h: 0.8, fontSize: 15, color: C.background2 });
  card(s, 5.4, 5.0, 7.33, 1.55, "goal card");
  txt(s, [
    { text: "Мета: ", options: { bold: true, color: C.accent1 } },
    { text: "для кожної камери знайти t_esp = a · t_cam + b і довести, що похибка менша за один кадр (20 мс)", options: { color: C.background1 } },
  ], { x: 5.7, y: 5.15, w: 6.8, h: 1.25, fontSize: 17, valign: "middle" });
  s.addNotes("Камери стартують по черзі, годинники дрейфують, карта захоплення інколи дублює кадр. Якщо просто взяти кадри з однаковим номером, камери розходяться на 3 секунди. Для тріангуляції це неприйнятно.");

  // ---------- 3. Introduction ----------
  pres.addSection({ title: "Introduction" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Introduction" });
  s.addText("Як синхронізують камери і чому LED + ESP32", { placeholder: "title" });
  const alts = [
    [fa.FaLink, "Genlock", "Ідеально, але дорого — Xiaomi Yi так не вміють"],
    [fa.FaMicrophone, "Аудіо", "Точність ~кадр, ламається від луни й шуму"],
    [fa.FaFilm, "Хлопушка", "Один момент на початку — дрейф і повтори не видно"],
  ];
  for (let i = 0; i < alts.length; i++) {
    const x = 0.6 + i * 2.95;
    card(s, x, 1.6, 2.75, 2.5, "alt card " + i);
    await dot(s, x + 0.3, 1.9, 0.6, alts[i][0], "alt " + i, C.accent6, H.lt1);
    txt(s, alts[i][1], { x: x + 0.3, y: 2.65, w: 2.2, h: 0.4, fontSize: 18, bold: true, color: C.background1 });
    txt(s, alts[i][2], { x: x + 0.3, y: 3.1, w: 2.2, h: 0.9, fontSize: 13, color: C.background2, valign: "top" });
  }
  card(s, 9.45, 1.6, 3.28, 2.5, "ours card", C.accent1);
  await dot(s, 9.75, 1.9, 0.6, fa.FaLightbulb, "ours", C.text1, H.accent1);
  txt(s, "LED + ESP32", { x: 9.75, y: 2.65, w: 2.8, h: 0.4, fontSize: 18, bold: true, color: C.text1 });
  txt(s, "Спалах щосекунди протягом усього запису — видно і зсув, і дрейф, і повтори", { x: 9.75, y: 3.1, w: 2.8, h: 0.9, fontSize: 13, color: C.text1, valign: "top" });
  txt(s, "Ключ: ESP32 записує час кожного спалаху — це ground truth", { x: 0.6, y: 4.5, w: 12.1, h: 0.45, fontSize: 20, bold: true, color: C.background1 });
  s.addText([
    { text: "esp32_flashes.txt: MASTER 0.5 с, потім REGULAR 70 мс щосекунди", options: { bullet: true, breakLine: true } },
    { text: "Модель підганяємо на першій половині запису, похибку міряємо на другій — чесна перевірка", options: { bullet: true, breakLine: true } },
    { text: "2–4 LED у полі зору кожної камери; 1920×1080 MJPEG @ 50 fps", options: { bullet: true } },
  ], { x: 0.6, y: 5.05, w: 12.1, h: 1.6, fontSize: 16, color: C.background2, paraSpaceAfter: 6, isTextBox: true, margin: 0 });
  s.addNotes("Апаратний genlock ці камери не підтримують. Аудіо дає точність лише близько кадру. Хлопушка — один момент, дрейфу не видно. Тому ESP32 блимає щосекунди і записує час кожного спалаху: це і сигнал, і еталон для оцінки.");

  // ---------- 4. Pipeline ----------
  pres.addSection({ title: "Description" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Description" });
  s.addText("Пайплайн: від відео до моделі часу кожної камери", { placeholder: "title" });
  const steps = [
    [fa.FaSearch, "1. Пошук LED", "Epoch folding: усереднення з періодом спалаху → карта мерехтіння → MAD-поріг → морфологія → connected components", "16 / 16 LED, рух актора не заважає"],
    [fa.FaBolt, "2. Спалахи", "Ковзний фон (30-й перцентиль), поріг Otsu / 6σ, об'єднання LED, пошук повторів кадрів", "206 спалахів на камеру"],
    [fa.FaLink, "3. Зіставлення", "Якір MASTER (довгий спалах) → ітеративна регресія t_esp = a·t_cam + b", "зсув + дрейф"],
    [fa.FaCrosshairs, "4. Субкадр", "Часткова засвітка + rolling shutter, поправка на повтори кадрів", "точність ~2 мс"],
  ];
  const sw = 2.82, gap = 0.27;
  for (let i = 0; i < steps.length; i++) {
    const x = 0.6 + i * (sw + gap);
    card(s, x, 1.6, sw, 4.1, "step card " + i, i === 3 ? C.accent1 : C.text2);
    const dark = i === 3;
    await dot(s, x + 0.3, 1.9, 0.7, steps[i][0], "step " + i, dark ? C.text1 : C.accent1, dark ? H.accent1 : H.dk1);
    txt(s, steps[i][1], { x: x + 0.3, y: 2.8, w: sw - 0.6, h: 0.45, fontSize: 19, bold: true, color: dark ? C.text1 : C.background1 });
    txt(s, steps[i][2], { x: x + 0.3, y: 3.3, w: sw - 0.6, h: 1.6, fontSize: 13, color: dark ? C.text1 : C.background2, valign: "top" });
    txt(s, steps[i][3], { x: x + 0.3, y: 5.0, w: sw - 0.6, h: 0.5, fontSize: 13, bold: true, italic: true, color: dark ? C.text1 : C.accent1, valign: "bottom" });
    if (i < 3) s.addImage({ data: await icon(fa.FaChevronRight, H.accent3), x: x + sw + 0.03, y: 3.5, w: 0.21, h: 0.21, objectName: "arrow " + i });
  }
  txt(s, [
    { text: "Результат: ", options: { bold: true, color: C.accent1 } },
    { text: "sync_models.json — a, b, E, R і повтори кадрів для кожної камери → Mocap Director / Captury", options: { color: C.background2 } },
  ], { x: 0.6, y: 6.0, w: 12.1, h: 0.5, fontSize: 16 });
  s.addNotes("Чотири кроки. Спочатку автоматично знаходимо LED: усереднюємо відео з періодом спалаху, і мерехтливі точки виділяються, а рух актора — ні. Потім знаходимо моменти спалахів, зіставляємо з логом ESP32 через MASTER-спалах і підганяємо зсув і дрейф. Останній крок — субкадрове уточнення.");

  // ---------- 5. Subframe ----------
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Description" });
  s.addText("Ключова ідея: точність менша за кадр", { placeholder: "title" });
  const x0 = 0.9, T = 1.3, E = 0.78, fy = 2.45;
  txt(s, "кадри (заливка — експозиція E)", { x: x0, y: 1.6, w: 5, h: 0.3, fontSize: 12, color: C.accent3 });
  const cover = [0, 0.42, 1, 1, 0.64];
  for (let k = 0; k < 5; k++) {
    const fx = x0 + k * T;
    s.addShape(pres.shapes.RECTANGLE, { x: fx, y: fy, w: T - 0.08, h: 0.9, fill: { color: C.text2 }, line: { color: C.accent6, width: 0.75 }, objectName: "frame " + k });
    s.addShape(pres.shapes.RECTANGLE, { x: fx, y: fy, w: E, h: 0.9, fill: { color: C.accent1, transparency: Math.round(100 - cover[k] * 100) }, line: { color: C.accent3, width: 0.75, dashType: "dash" }, objectName: "exposure " + k });
    txt(s, k ? `n+${k}` : "n", { x: fx, y: fy + 0.98, w: T - 0.08, h: 0.28, fontSize: 12, color: C.accent3, align: "center" });
  }
  txt(s, "f = 0.42", { x: x0 + T - 0.1, y: fy - 0.4, w: 1.0, h: 0.3, fontSize: 14, bold: true, color: C.accent1, align: "center" });
  txt(s, "f = 0.64", { x: x0 + 4 * T - 0.1, y: fy - 0.4, w: 1.0, h: 0.3, fontSize: 14, bold: true, color: C.accent1, align: "center" });
  const ledY = 4.2;
  txt(s, "LED (час за ESP32)", { x: x0, y: ledY - 0.35, w: 4, h: 0.3, fontSize: 12, color: C.accent3 });
  s.addShape(pres.shapes.RECTANGLE, { x: x0, y: ledY + 0.18, w: 5 * T - 0.08, h: 0.02, fill: { color: C.accent6 }, line: { type: "none" }, objectName: "time axis" });
  s.addShape(pres.shapes.RECTANGLE, { x: x0 + T + E * 0.58, y: ledY, w: 3 * T + 0.06 * E, h: 0.38, fill: { color: C.accent1 }, line: { type: "none" }, objectName: "flash bar" });
  txt(s, "спалах", { x: x0 + 2.2 * T, y: ledY + 0.04, w: 1.5, h: 0.3, fontSize: 13, bold: true, color: C.text1, align: "center" });
  txt(s, "Частка яскравості f кадру на межі спалаху показує, де саме в межах експозиції він почався — а не лише «в якому кадрі».", { x: x0, y: 4.85, w: 6.4, h: 0.85, fontSize: 15, color: C.background2 });

  card(s, 7.95, 1.6, 4.78, 2.35, "formula card");
  txt(s, "Початок спалаху в часі камери", { x: 8.25, y: 1.8, w: 4.2, h: 0.35, fontSize: 14, color: C.accent3 });
  txt(s, "t = tₙ + R·y + E·(1 − f)", { x: 8.25, y: 2.2, w: 4.2, h: 0.6, fontSize: 24, bold: true, color: C.background1, fontFace: "Cambria" });
  txt(s, "R — rolling shutter (нижні рядки y читаються пізніше)\nE — тривалість експозиції\nR і E підбираються з даних", { x: 8.25, y: 2.85, w: 4.2, h: 1.0, fontSize: 13, color: C.background2 });
  card(s, 7.95, 4.15, 4.78, 2.35, "dup card");
  await dot(s, 8.25, 4.4, 0.55, fa.FaClone, "dup", C.accent5, H.lt1);
  txt(s, "Повтори кадрів", { x: 9.0, y: 4.45, w: 3.5, h: 0.45, fontSize: 18, bold: true, color: C.background1 });
  txt(s, "Один дубль зсуває всі наступні кадри на −20 мс. Знаходимо його за сходинкою в залишках і компенсуємо: розкид між камерами 32 → 16 мс.", { x: 8.25, y: 5.1, w: 4.2, h: 1.3, fontSize: 13, color: C.background2, valign: "top" });
  txt(s, "Субкадрове уточнення: 16 → 7.4 мс", { x: x0, y: 5.75, w: 6.4, h: 0.5, fontSize: 20, bold: true, color: C.accent1 });
  s.addNotes("Спалах 70 мс, кадр 20 мс. На межі спалаху кадр засвічений частково — і частка яскравості каже, в який момент експозиції спалах почався. Враховуємо rolling shutter і експозицію, обидва параметри підбираємо з даних. Окремо знаходимо дублі кадрів: кожен зсуває решту запису на кадр.");

  // ---------- 6. Demo ----------
  pres.addSection({ title: "Demo" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Demo" });
  s.addText("Demo: спалах на 199.6 с — під кінець 3.5-хв запису", { placeholder: "title" });
  const vw = 8.9, vh = vw * 1276 / 1920;
  s.addMedia({ type: "video", path: "demo_3min.mp4", cover: b64("poster.jpg", "image/jpeg"), x: 0.6, y: 1.45, w: vw, h: vh, objectName: "demo video" });
  const dx = 9.85, dw = 2.88;
  txt(s, "ДО", { x: dx, y: 1.6, w: dw, h: 0.4, fontSize: 20, bold: true, color: C.accent3 });
  txt(s, "Кадр з однаковим номером на всіх камерах — розходяться на 3.2 с, актор то є, то немає", { x: dx, y: 2.05, w: dw, h: 1.2, fontSize: 14, color: C.background2, valign: "top" });
  txt(s, "ПІСЛЯ", { x: dx, y: 3.5, w: dw, h: 0.4, fontSize: 20, bold: true, color: C.accent1 });
  txt(s, "Кадр, вибраний моделлю — LED загоряється на всіх 8 камерах одночасно (збільшена вставка)", { x: dx, y: 3.95, w: dw, h: 1.2, fontSize: 14, color: C.background2, valign: "top" });
  txt(s, "Сповільнено в 5 разів", { x: dx, y: 5.6, w: dw, h: 0.35, fontSize: 13, italic: true, color: C.accent3 });
  s.addNotes("Відео сповільнене вп'ятеро. Зверху — кадри з однаковим номером: камери показують моменти з різницею в три секунди. Знизу — кадри, які вибрала модель: спалах загоряється на всіх восьми камерах одночасно. І це під кінець запису — синхронізація трималась усі 3 хвилини.");

  // ---------- 7. Results ----------
  pres.addSection({ title: "Results" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Results" });
  s.addText("Results: 7.4 мс між камерами при кадрі 20 мс", { placeholder: "title" });
  const hdr = (t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.text2 } } });
  const row = (a, b, c, hi) => [a, b, c].map((t) => ({ text: t, options: hi ? { bold: true, color: C.text1, fill: { color: C.accent1 } } : { color: C.background2 } }));
  s.addTable([
    [hdr("Метод"), hdr("RMS відносно ESP32"), hdr("Розкид між камерами")],
    row("B0 — за номером кадру", "1570 мс", "3181 мс"),
    row("B1 — зсув з MASTER", "35 мс", "32 мс"),
    row("B2 — зсув + дрейф, до кадру", "11 мс", "32 мс"),
    row("B2 + поправка на повтори", "5.9 мс", "16 мс"),
    row("FlashSync (субкадр + повтори)", "2.3 мс", "7.4 мс", true),
  ], { x: 0.6, y: 1.55, w: 6.6, colW: [3.1, 1.75, 1.75], rowH: 0.48, fontSize: 14, border: { type: "solid", pt: 0.5, color: H.dk1 }, valign: "middle", margin: [0, 0.1, 0, 0.1], objectName: "results table" });
  txt(s, "8 камер · 3.5 хв · 206 спалахів · модель на 1-й половині, перевірка на 2-й", { x: 0.6, y: 4.55, w: 6.6, h: 0.3, fontSize: 12, color: C.accent3 });
  s.addChart(pres.charts.BAR, [{ name: "Розкид між камерами, мс", labels: ["B0", "B1", "B2", "B2+dup", "Ours"], values: [3181, 31.8, 31.5, 16.1, 7.4] }], {
    x: 7.6, y: 1.45, w: 5.13, h: 3.4, barDir: "col",
    chartColors: [H.accent6, H.accent6, H.accent6, H.accent3, H.accent1],
    valAxisLogScaleBase: 10, valAxisMinVal: 1, valAxisMaxVal: 10000,
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: H.lt1, dataLabelFontSize: 12, dataLabelFormatCode: "General", dataLabelFontFace: "+mn-lt",
    catAxisLabelColor: H.lt2, valAxisLabelColor: H.accent3, catAxisLabelFontSize: 12, valAxisLabelFontSize: 11,
    catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt",
    valGridLine: { color: H.dk2, size: 0.75 }, catGridLine: { style: "none" }, showLegend: false,
    showTitle: true, title: "Розкид між камерами, мс (лог-шкала)", titleColor: H.lt1, titleFontSize: 13, titleFontFace: "+mn-lt",
    objectName: "spread chart",
  });
  const stats = [["2.3 мс", "RMS відносно ESP32; 95% спалахів у межах 4.1 мс"], ["40 с", "спалахів досить, щоб модель трималась 2.7 мс ще 2.5 хв"], ["−4…+22 ppm", "дрейф малий — головне зсув старту, повтори і квантування кадром"]];
  for (let i = 0; i < 3; i++) {
    const x = 0.6 + i * 4.1;
    card(s, x, 5.05, 3.9, 1.6, "stat " + i);
    txt(s, stats[i][0], { x: x + 0.25, y: 5.15, w: 3.4, h: 0.65, fontSize: 30, bold: true, color: C.accent1, fontFace: "Arial" });
    txt(s, stats[i][1], { x: x + 0.25, y: 5.82, w: 3.4, h: 0.75, fontSize: 13, color: C.background2, valign: "top" });
  }
  s.addNotes("Порівняння з базовими методами. За номером кадру — секунди. Один MASTER і навіть зсув плюс дрейф дають понад 30 мс між камерами, більше за кадр. Поправка на повтори — 16 мс, субкадрове уточнення — 7.4 мс між камерами і 2.3 мс відносно ESP32. Слабкі місця: один викид 26 мс через частково перекритий LED, і LED мають бути видні кожній камері.");

  // ---------- 8. Conclusions ----------
  pres.addSection({ title: "Conclusions" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Conclusions" });
  s.addText("Висновки", { placeholder: "title" });
  txt(s, "Синхронізація до кількох мілісекунд без genlock — два світлодіоди і лог ESP32", { x: 0.6, y: 1.5, w: 12.1, h: 0.9, fontSize: 24, bold: true, color: C.accent1 });
  const cols = [
    [fa.FaCheck, "Що вийшло", ["Автопошук LED, 16 / 16", "Субкадрове уточнення + поправка на повтори кадрів", "7.4 мс між камерами, 2.3 мс до ESP32"], C.accent4],
    [fa.FaExclamationTriangle, "Обмеження", ["LED має бути видно кожній камері", "Один викид 26 мс — LED частково перекрито", "R ≈ 0 на 2 камерах — ймовірно, HDMI-карта перетаймінговує рядки"], C.accent5],
    [fa.FaArrowRight, "Далі", ["Інтеграція в Mocap Director", "Перевірка синхронізації під час запису", "Порівняння з апаратним тригером"], C.accent2],
  ];
  for (let i = 0; i < 3; i++) {
    const x = 0.6 + i * 4.1;
    card(s, x, 2.65, 3.9, 3.6, "concl " + i);
    await dot(s, x + 0.3, 2.95, 0.6, cols[i][0], "concl " + i, cols[i][3], H.lt1);
    txt(s, cols[i][1], { x: x + 1.05, y: 3.03, w: 2.6, h: 0.45, fontSize: 19, bold: true, color: C.background1 });
    s.addText(cols[i][2].map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < cols[i][2].length - 1 } })),
      { x: x + 0.3, y: 3.8, w: 3.35, h: 2.25, fontSize: 14, color: C.background2, paraSpaceAfter: 8, valign: "top", isTextBox: true, margin: 0 });
  }
  txt(s, "github.com/vlarol/flashsync", { x: 0.6, y: 6.4, w: 6, h: 0.35, fontSize: 14, color: C.accent3 });
  s.addNotes("Підсумок: синхронізація до кількох мілісекунд без апаратного genlock. Обмеження — LED мають бути в кадрі кожної камери. Далі — інтеграція в Mocap Director. Дякую, готовий до питань.");

  await pres.writeFile({ fileName: "FlashSync.pptx" });
  await applyTheme("FlashSync.pptx", THEME);
  console.log("done");
})();
