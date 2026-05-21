// =============================================================
// PROYECTO FINAL - Operación Cripto
// Presentación ejecutiva 15-20 min (18 slides)
// Autor: Juan Ortiz Pa
//
// Cómo regenerar:
//   cd presentacion/_build
//   node build_presentation.js ../proyecto_final_operacion_cripto.pptx
// =============================================================
const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3" x 7.5"
pres.author = "Juan Ortiz Pa";
pres.title = "Operación Cripto - Proyecto Final";
pres.subject = "Bot de Trading con ML";

// PALETA Bloomberg-inspired
const C = {
  bgDark: "0A0E1A", cardDark: "1A2238", cardSurf: "232B45",
  panelLight: "F8FAFC", cardLight: "FFFFFF", border: "E2E8F0",
  textOnDark: "E2E8F0", textOnDarkMuted: "94A3B8",
  textDark: "0F172A", textMuted: "475569",
  gold: "F59E0B", cyan: "06B6D4", win: "10B981", loss: "EF4444",
  yellow: "FACC15", navy: "1E293B",
};
const FONT_H = "Calibri", FONT_B = "Calibri";

function addFooter(slide, pageNum, total) {
  slide.addShape(pres.shapes.LINE, {
    x: 0.5, y: 7.05, w: 12.3, h: 0,
    line: { color: C.border, width: 0.75 },
  });
  slide.addText("Operación Cripto · Proyecto Final · Analítica de Datos · Semana 15", {
    x: 0.5, y: 7.12, w: 9, h: 0.3,
    fontSize: 9, color: C.textMuted, fontFace: FONT_B, margin: 0,
  });
  slide.addText(`${pageNum} / ${total}`, {
    x: 11.8, y: 7.12, w: 1, h: 0.3,
    fontSize: 9, color: C.textMuted, fontFace: FONT_B, align: "right", margin: 0,
  });
}
function addKicker(slide, text, color = C.gold) {
  slide.addText(text.toUpperCase(), {
    x: 0.5, y: 0.45, w: 6, h: 0.3,
    fontSize: 10, bold: true, color: color, fontFace: FONT_B,
    charSpacing: 4, margin: 0,
  });
}
const TOTAL = 18;

// ============================== SLIDE 1 - PORTADA ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.bgDark };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.25, h: 7.5, fill: { color: C.gold }, line: { color: C.gold, width: 0 } });
  s.addText("₿", { x: 9.5, y: 0.8, w: 3, h: 3, fontSize: 220, color: C.gold, fontFace: "Georgia", align: "center", valign: "middle", margin: 0 });
  s.addText("PROYECTO FINAL · ANALÍTICA DE DATOS", { x: 0.8, y: 1.4, w: 8, h: 0.4, fontSize: 12, bold: true, color: C.gold, fontFace: FONT_B, charSpacing: 6, margin: 0 });
  s.addText("OPERACIÓN CRIPTO", { x: 0.8, y: 2.0, w: 9, h: 1.4, fontSize: 64, bold: true, color: C.textOnDark, fontFace: FONT_H, margin: 0 });
  s.addText("Bot de trading automatizado con Machine Learning", { x: 0.8, y: 3.4, w: 10, h: 0.6, fontSize: 24, color: C.textOnDarkMuted, fontFace: FONT_H, italic: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 4.5, w: 11, h: 0.9, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 4.5, w: 0.06, h: 0.9, fill: { color: C.cyan }, line: { color: C.cyan, width: 0 } });
  s.addText("Predicciones de precio combinando análisis técnico, sentimiento y noticias en tiempo real sobre los TOP 20 pares de Binance.", { x: 1.0, y: 4.5, w: 10.6, h: 0.9, fontSize: 14, color: C.textOnDark, fontFace: FONT_B, valign: "middle", margin: 0 });
  s.addText("Juan Ortiz Pa", { x: 0.8, y: 6.5, w: 5, h: 0.4, fontSize: 16, bold: true, color: C.textOnDark, fontFace: FONT_B, margin: 0 });
  s.addText("Semana 15 · Mayo 2026 · Milestone Final", { x: 0.8, y: 6.85, w: 7, h: 0.3, fontSize: 11, color: C.textOnDarkMuted, fontFace: FONT_B, margin: 0 });
  s.addText("github.com/juanortizpa/crypto_bot", { x: 8, y: 6.85, w: 5, h: 0.3, fontSize: 11, color: C.gold, fontFace: "Consolas", align: "right", margin: 0 });
}

// ============================== SLIDE 2 - GANCHO ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.bgDark };
  s.addText("GANCHO", { x: 0.8, y: 0.6, w: 4, h: 0.3, fontSize: 11, bold: true, color: C.gold, fontFace: FONT_B, charSpacing: 6, margin: 0 });
  s.addText("¿Puedes predecir si BTC subirá en las próximas 4 horas?", { x: 0.8, y: 1.2, w: 11.7, h: 2.0, fontSize: 40, bold: true, color: C.textOnDark, fontFace: FONT_H, margin: 0 });
  s.addText("Un trader humano mira el chart, el news feed y \"siente\" el mercado.\nDecide en segundos. Acierta el 50–55% de las veces.", { x: 0.8, y: 3.4, w: 11.7, h: 1.0, fontSize: 18, color: C.textOnDarkMuted, fontFace: FONT_B, italic: true, margin: 0 });
  const cardY = 4.8, cardH = 2.0;
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: cardY, w: 5.5, h: cardH, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: cardY, w: 0.08, h: cardH, fill: { color: C.loss }, line: { color: C.loss, width: 0 } });
  s.addText("Enfoque tradicional", { x: 1.0, y: cardY + 0.15, w: 5, h: 0.4, fontSize: 13, bold: true, color: C.textOnDarkMuted, fontFace: FONT_B, charSpacing: 3, margin: 0 });
  s.addText("~52% win rate", { x: 1.0, y: cardY + 0.55, w: 5, h: 0.75, fontSize: 38, bold: true, color: C.loss, fontFace: FONT_H, margin: 0 });
  s.addText("Intuición, miedo, FOMO. Pierde frente al mercado 24/7.", { x: 1.0, y: cardY + 1.35, w: 5.1, h: 0.6, fontSize: 12, color: C.textOnDark, fontFace: FONT_B, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.0, y: cardY, w: 5.5, h: cardH, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 7.0, y: cardY, w: 0.08, h: cardH, fill: { color: C.win }, line: { color: C.win, width: 0 } });
  s.addText("Bot con Machine Learning", { x: 7.2, y: cardY + 0.15, w: 5, h: 0.4, fontSize: 13, bold: true, color: C.gold, fontFace: FONT_B, charSpacing: 3, margin: 0 });
  s.addText("97.3% win rate", { x: 7.2, y: cardY + 0.55, w: 5, h: 0.75, fontSize: 38, bold: true, color: C.win, fontFace: FONT_H, margin: 0 });
  s.addText("Aprende de 4.6M klines + 39 eventos globales (Modelo B).", { x: 7.2, y: cardY + 1.35, w: 5.1, h: 0.6, fontSize: 12, color: C.textOnDark, fontFace: FONT_B, margin: 0 });
  addFooter(s, 2, TOTAL);
}

// ============================== SLIDE 3 - POR QUÉ IMPORTA ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "PROBLEMA");
  s.addText("El mercado cripto rompe las reglas del trading tradicional", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  const cards = [
    { num: "24/7", label: "Horas que opera el mercado", desc: "Sin cierre. Un tweet a las 3 AM mueve precios.", color: C.gold },
    { num: "±30%", label: "Movimiento típico en 24h en altcoins", desc: "Volatilidad 10× mayor que acciones.", color: C.cyan },
    { num: "39", label: "Eventos globales detectados 2024-26", desc: "Trump, Fed, Musk, regulación, hacks.", color: C.win },
  ];
  cards.forEach((c, i) => {
    const x = 0.5 + i * 4.15;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 2.2, w: 3.95, h: 4.0, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 2.2, w: 3.95, h: 0.12, fill: { color: c.color }, line: { color: c.color, width: 0 } });
    s.addText(c.num, { x: x + 0.25, y: 2.5, w: 3.5, h: 1.5, fontSize: 60, bold: true, color: c.color, fontFace: FONT_H, valign: "middle", margin: 0 });
    s.addText(c.label, { x: x + 0.25, y: 4.1, w: 3.5, h: 0.8, fontSize: 14, bold: true, color: C.textDark, fontFace: FONT_B, margin: 0 });
    s.addText(c.desc, { x: x + 0.25, y: 4.95, w: 3.5, h: 1.2, fontSize: 12, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  });
  s.addText("Conclusión: las técnicas clásicas de acciones no bastan. Hacen falta features de sentimiento y un sistema que opere las 24h.", { x: 0.5, y: 6.4, w: 12.3, h: 0.5, fontSize: 13, italic: true, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  addFooter(s, 3, TOTAL);
}

// ============================== SLIDE 4 - AGENDA ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "AGENDA");
  s.addText("Lo que voy a presentar", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 30, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  const items = [
    { n: "01", t: "El problema", d: "Por qué predecir crypto es distinto" },
    { n: "02", t: "Metodología", d: "Pipeline end-to-end" },
    { n: "03", t: "Datos y EDA", d: "4.6M klines, 20 pares, 39 eventos" },
    { n: "04", t: "Gate de 13 factores", d: "Sistema de semáforos GREEN/YELLOW/RED" },
    { n: "05", t: "Modelo de ML", d: "Clasificación con scikit-learn" },
    { n: "06", t: "Resultados", d: "Win rates, métricas, overfitting" },
    { n: "07", t: "Recomendaciones", d: "Acciones concretas" },
    { n: "08", t: "Limitaciones", d: "Lo que el modelo no puede hacer" },
  ];
  items.forEach((it, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.5 + col * 6.2, y = 1.9 + row * 1.25;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 5.95, h: 1.1, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addText(it.n, { x: x + 0.2, y: y + 0.18, w: 1.0, h: 0.75, fontSize: 32, bold: true, color: C.gold, fontFace: FONT_H, valign: "middle", margin: 0 });
    s.addText(it.t, { x: x + 1.4, y: y + 0.15, w: 4.4, h: 0.45, fontSize: 16, bold: true, color: C.textDark, fontFace: FONT_B, margin: 0 });
    s.addText(it.d, { x: x + 1.4, y: y + 0.6, w: 4.4, h: 0.45, fontSize: 11, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  });
  addFooter(s, 4, TOTAL);
}

// ============================== SLIDE 5 - METODOLOGÍA ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "METODOLOGÍA");
  s.addText("Pipeline end-to-end del bot", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  const steps = [
    { t: "INGESTA", d: "Binance API: OHLCV 5-min de 20 pares" },
    { t: "FEATURES", d: "Indicadores técnicos + sentimiento + Fear&Greed" },
    { t: "GATE 13F", d: "Sistema de semáforos GREEN / YELLOW / RED" },
    { t: "MODELOS", d: "6 estrategias competitivas en paralelo" },
    { t: "ML SCORING", d: "scikit-learn / XGBoost: probabilidad WIN" },
    { t: "PAPER", d: "Predicciones a SQLite + monitor real-time 5min" },
  ];
  const stepW = 1.95, stepH = 2.2, gap = 0.12, startX = 0.5, y = 2.5;
  steps.forEach((st, i) => {
    const x = startX + i * (stepW + gap);
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: stepW, h: stepH, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: stepW, h: 0.4, fill: { color: C.navy }, line: { color: C.navy, width: 0 } });
    s.addText(`${i + 1}`, { x, y, w: stepW, h: 0.4, fontSize: 14, bold: true, color: C.gold, fontFace: FONT_H, align: "center", valign: "middle", margin: 0 });
    s.addText(st.t, { x: x + 0.1, y: y + 0.55, w: stepW - 0.2, h: 0.5, fontSize: 13, bold: true, color: C.textDark, fontFace: FONT_B, align: "center", margin: 0 });
    s.addText(st.d, { x: x + 0.1, y: y + 1.05, w: stepW - 0.2, h: 1.1, fontSize: 10, color: C.textMuted, fontFace: FONT_B, align: "center", margin: 0 });
    if (i < steps.length - 1) {
      s.addShape(pres.shapes.LINE, { x: x + stepW, y: y + stepH / 2, w: gap, h: 0, line: { color: C.gold, width: 1.5, endArrowType: "triangle" } });
    }
  });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 5.4, w: 12.3, h: 1.2, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
  s.addText("CICLO DE RETROALIMENTACIÓN", { x: 0.7, y: 5.55, w: 5, h: 0.3, fontSize: 10, bold: true, color: C.gold, fontFace: FONT_B, charSpacing: 4, margin: 0 });
  s.addText("Cada predicción se resuelve automáticamente (WIN / LOSS) → alimenta el dataset → reentrenamos los modelos cada semana.", { x: 0.7, y: 5.85, w: 11.9, h: 0.7, fontSize: 13, color: C.textOnDark, fontFace: FONT_B, margin: 0 });
  addFooter(s, 5, TOTAL);
}

// ============================== SLIDE 6 - DATOS ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "DATOS");
  s.addText("Más de 4.6M velas y 11.5K ventanas de eventos", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  const stats = [
    { v: "4.6M", l: "Klines OHLCV (5-min)" },
    { v: "20", l: "Pares de trading" },
    { v: "11,563", l: "Ventanas de eventos" },
    { v: "6.4 GB", l: "Datasets totales (en HF)" },
  ];
  stats.forEach((st, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.5 + col * 3.0, y = 1.9 + row * 1.7;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 2.85, h: 1.55, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addText(st.v, { x: x + 0.15, y: y + 0.15, w: 2.55, h: 0.85, fontSize: 36, bold: true, color: C.gold, fontFace: FONT_H, margin: 0 });
    s.addText(st.l, { x: x + 0.15, y: y + 1.0, w: 2.55, h: 0.5, fontSize: 11, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  });
  s.addText("TOP 20 pares entrenados", { x: 6.8, y: 1.9, w: 6, h: 0.4, fontSize: 13, bold: true, color: C.textDark, fontFace: FONT_B, charSpacing: 3, margin: 0 });
  const pairsHeader = [
    { text: "STABLE (10)", options: { bold: true, color: "FFFFFF", fill: { color: C.navy }, fontSize: 11 } },
    { text: "VOLATILE (10)", options: { bold: true, color: "FFFFFF", fill: { color: C.navy }, fontSize: 11 } },
  ];
  const pairs = [
    [{ text: "BTC USDT", options: { fontSize: 11 } }, { text: "DOGE USDT", options: { fontSize: 11 } }],
    [{ text: "ETH USDT", options: { fontSize: 11 } }, { text: "SHIB USDT", options: { fontSize: 11 } }],
    [{ text: "BNB USDT", options: { fontSize: 11 } }, { text: "NEAR USDT", options: { fontSize: 11 } }],
    [{ text: "SOL USDT", options: { fontSize: 11 } }, { text: "APT USDT", options: { fontSize: 11 } }],
    [{ text: "XRP USDT", options: { fontSize: 11 } }, { text: "SUI USDT", options: { fontSize: 11 } }],
    [{ text: "ADA USDT", options: { fontSize: 11 } }, { text: "INJ USDT", options: { fontSize: 11 } }],
    [{ text: "AVAX USDT", options: { fontSize: 11 } }, { text: "RNDR USDT", options: { fontSize: 11 } }],
    [{ text: "DOT USDT", options: { fontSize: 11 } }, { text: "TIA USDT", options: { fontSize: 11 } }],
    [{ text: "LINK USDT", options: { fontSize: 11 } }, { text: "SEI USDT", options: { fontSize: 11 } }],
    [{ text: "MATIC USDT", options: { fontSize: 11 } }, { text: "FET USDT", options: { fontSize: 11 } }],
  ];
  s.addTable([pairsHeader, ...pairs], { x: 6.8, y: 2.35, w: 6.0, h: 4.4, colW: [3.0, 3.0], border: { pt: 0.5, color: C.border }, fontFace: FONT_B, align: "left", valign: "middle" });
  s.addText("Fuente: Binance Spot Public Data, 2024–2026. Alojados en Hugging Face Datasets.", { x: 0.5, y: 6.7, w: 12.3, h: 0.3, fontSize: 10, italic: true, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  addFooter(s, 6, TOTAL);
}

// ============================== SLIDE 7 - EDA HALLAZGOS ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "ANÁLISIS EXPLORATORIO");
  s.addText("Tres hallazgos que cambiaron el diseño del bot", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  const findings = [
    { n: "01", t: "BTC arrastra al resto", stat: "ρ = 0.81", desc: "Correlación promedio de altcoins con BTC en 4h. Conclusión: M1 (tendencia BTC) es el factor más predictivo del gate.", color: C.gold },
    { n: "02", t: "Las noticias mueven 30% en minutos", stat: "×2", desc: "Un tweet de Elon Musk movió DOGE 30% en 5 min. Por eso N1 (sentimiento) lleva peso DOBLE en crypto vs acciones.", color: C.cyan },
    { n: "03", t: "Fear & Greed extremo = oportunidad", stat: "<25", desc: "Cuando el F&G cae bajo 25 (pánico), el win rate del Dip Buyer sube a 88%. Inspiró el Modelo D.", color: C.win },
  ];
  findings.forEach((f, i) => {
    const x = 0.5 + i * 4.15;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.9, w: 3.95, h: 4.7, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.9, w: 3.95, h: 0.12, fill: { color: f.color }, line: { color: f.color, width: 0 } });
    s.addText(f.n, { x: x + 0.25, y: 2.15, w: 1.5, h: 0.45, fontSize: 14, bold: true, color: f.color, fontFace: FONT_H, margin: 0 });
    s.addText(f.t, { x: x + 0.25, y: 2.6, w: 3.5, h: 1.0, fontSize: 18, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
    s.addText(f.stat, { x: x + 0.25, y: 3.7, w: 3.5, h: 1.2, fontSize: 52, bold: true, color: f.color, fontFace: FONT_H, margin: 0 });
    s.addText(f.desc, { x: x + 0.25, y: 5.0, w: 3.5, h: 1.5, fontSize: 11, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  });
  addFooter(s, 7, TOTAL);
}

// ============================== SLIDE 8 - GATE 13 FACTORES ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "FEATURE ENGINEERING");
  s.addText("Gate de 13 factores: sistema de semáforos", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  const cellOpt = (color, bold = false) => ({ fontSize: 11, fontFace: FONT_B, color, bold, valign: "middle" });
  const head = (text) => ({ text, options: { bold: true, color: "FFFFFF", fill: { color: C.navy }, fontSize: 11, valign: "middle" } });
  const rows = [
    [head("Grupo"), head("ID"), head("Factor"), head("Qué mide")],
    [{ text: "MACRO", options: { fill: { color: "FEF3C7" }, bold: true, fontSize: 11, color: C.textDark, valign: "middle", rowspan: 4 } },
      { text: "M1", options: cellOpt(C.textDark, true) }, { text: "BTC Trend", options: cellOpt(C.textDark) }, { text: "SMA20/50 de Bitcoin", options: cellOpt(C.textMuted) }],
    [{ text: "M2", options: cellOpt(C.textDark, true) }, { text: "Fear & Greed", options: cellOpt(C.textDark) }, { text: "Índice 0-100 (alternative.me)", options: cellOpt(C.textMuted) }],
    [{ text: "M3", options: cellOpt(C.textDark, true) }, { text: "Volatilidad 1h", options: cellOpt(C.textDark) }, { text: "ATR normalizado", options: cellOpt(C.textMuted) }],
    [{ text: "S4", options: cellOpt(C.textDark, true) }, { text: "BTC Dominance", options: cellOpt(C.textDark) }, { text: "% market cap", options: cellOpt(C.textMuted) }],
    [{ text: "SHORT", options: { fill: { color: "DBEAFE" }, bold: true, fontSize: 11, color: C.textDark, valign: "middle", rowspan: 5 } },
      { text: "S1", options: cellOpt(C.textDark, true) }, { text: "Momentum 4h", options: cellOpt(C.textDark) }, { text: "SMA20 vs SMA50", options: cellOpt(C.textMuted) }],
    [{ text: "S2", options: cellOpt(C.textDark, true) }, { text: "Setup técnico", options: cellOpt(C.textDark) }, { text: "RSI + MA crossovers", options: cellOpt(C.textMuted) }],
    [{ text: "S3", options: cellOpt(C.textDark, true) }, { text: "Volumen 1h", options: cellOpt(C.textDark) }, { text: "vs promedio 20d", options: cellOpt(C.textMuted) }],
    [{ text: "T1", options: cellOpt(C.textDark, true) }, { text: "Micro-trend", options: cellOpt(C.textDark) }, { text: "Últimas 6 velas", options: cellOpt(C.textMuted) }],
    [{ text: "T2", options: cellOpt(C.textDark, true) }, { text: "Buy/Sell ratio", options: cellOpt(C.textDark) }, { text: "Volumen comprador", options: cellOpt(C.textMuted) }],
    [{ text: "RIESGO", options: { fill: { color: "FEE2E2" }, bold: true, fontSize: 11, color: C.textDark, valign: "middle", rowspan: 2 } },
      { text: "R1", options: cellOpt(C.textDark, true) }, { text: "Risk/Reward", options: cellOpt(C.textDark) }, { text: "Ratio stop/target", options: cellOpt(C.textMuted) }],
    [{ text: "R2", options: cellOpt(C.textDark, true) }, { text: "Exposición", options: cellOpt(C.textDark) }, { text: "Max trades abiertos", options: cellOpt(C.textMuted) }],
    [{ text: "SENTIM.", options: { fill: { color: "DCFCE7" }, bold: true, fontSize: 11, color: C.textDark, valign: "middle" } },
      { text: "N1", options: cellOpt(C.win, true) }, { text: "Noticias (×2)", options: cellOpt(C.win, true) }, { text: "Keywords + power figures", options: cellOpt(C.textMuted) }],
  ];
  s.addTable(rows, { x: 0.5, y: 1.9, w: 8.5, h: 4.8, colW: [1.2, 0.7, 2.4, 4.2], border: { pt: 0.5, color: C.border }, fontFace: FONT_B });
  s.addShape(pres.shapes.RECTANGLE, { x: 9.3, y: 1.9, w: 3.5, h: 4.8, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
  s.addText("OUTPUT", { x: 9.45, y: 2.0, w: 3.2, h: 0.3, fontSize: 10, bold: true, color: C.textMuted, charSpacing: 4, margin: 0 });
  const lights = [
    { c: C.win, label: "GREEN", desc: "3+ factores positivos → entrada autorizada" },
    { c: C.yellow, label: "YELLOW", desc: "1-2 factores → entrada con tamaño reducido" },
    { c: C.loss, label: "RED", desc: "3+ negativos → no entrar / cerrar abiertas" },
  ];
  lights.forEach((l, i) => {
    const y = 2.45 + i * 1.4;
    s.addShape(pres.shapes.OVAL, { x: 9.5, y, w: 0.4, h: 0.4, fill: { color: l.c }, line: { color: l.c, width: 0 } });
    s.addText(l.label, { x: 10.05, y: y - 0.05, w: 2.6, h: 0.5, fontSize: 14, bold: true, color: C.textDark, fontFace: FONT_B, margin: 0 });
    s.addText(l.desc, { x: 9.5, y: y + 0.45, w: 3.2, h: 0.85, fontSize: 10, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  });
  addFooter(s, 8, TOTAL);
}

// ============================== SLIDE 9 - TIPO DE PROBLEMA ML ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "MACHINE LEARNING");
  s.addText("¿Clasificación o regresión? Elegimos clasificación binaria.", { x: 0.5, y: 0.85, w: 12.3, h: 0.9, fontSize: 26, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 2.0, w: 12.3, h: 1.0, fill: { color: C.navy }, line: { color: C.navy, width: 0 } });
  s.addText("PREGUNTA DE MODELADO", { x: 0.7, y: 2.1, w: 5, h: 0.3, fontSize: 10, bold: true, color: C.gold, fontFace: FONT_B, charSpacing: 4, margin: 0 });
  s.addText("¿Esta operación cerrará en WIN (+3%) o en LOSS (–2.5%) antes de N horas?", { x: 0.7, y: 2.4, w: 11.9, h: 0.6, fontSize: 18, bold: true, color: C.textOnDark, fontFace: FONT_H, italic: true, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 3.3, w: 6.0, h: 3.4, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 3.3, w: 0.08, h: 3.4, fill: { color: C.cyan }, line: { color: C.cyan, width: 0 } });
  s.addText("VARIABLES PREDICTORAS (X)", { x: 0.75, y: 3.45, w: 5.5, h: 0.35, fontSize: 11, bold: true, color: C.cyan, fontFace: FONT_B, charSpacing: 3, margin: 0 });
  s.addText([
    { text: "13 factores del gate ", options: { bold: true, breakLine: true } },
    { text: "(M1–M3, S1–S4, T1–T2, R1–R2, N1)", options: { color: C.textMuted, fontSize: 11, breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "Indicadores técnicos ", options: { bold: true, breakLine: true } },
    { text: "RSI, MACD, ATR, BB width, OBV", options: { color: C.textMuted, fontSize: 11, breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "Contexto macro ", options: { bold: true, breakLine: true } },
    { text: "Fear&Greed, BTC dominance, vol regime", options: { color: C.textMuted, fontSize: 11 } },
  ], { x: 0.75, y: 3.85, w: 5.55, h: 2.7, fontSize: 13, color: C.textDark, fontFace: FONT_B, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 6.8, y: 3.3, w: 6.0, h: 3.4, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 6.8, y: 3.3, w: 0.08, h: 3.4, fill: { color: C.gold }, line: { color: C.gold, width: 0 } });
  s.addText("VARIABLE OBJETIVO (y)", { x: 7.05, y: 3.45, w: 5.5, h: 0.35, fontSize: 11, bold: true, color: C.gold, fontFace: FONT_B, charSpacing: 3, margin: 0 });
  s.addText([
    { text: "y = outcome", options: { bold: true, fontSize: 16, breakLine: true } },
    { text: "  1  →  la posición cerró en WIN", options: { color: C.win, fontFace: "Consolas", breakLine: true } },
    { text: "  0  →  la posición cerró en LOSS", options: { color: C.loss, fontFace: "Consolas", breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "Es clasificación binaria.", options: { bold: true, breakLine: true } },
    { text: "Métrica primaria: ", options: { color: C.textMuted, breakLine: true } },
    { text: "Win Rate (= accuracy de clase WIN)", options: { color: C.textDark, bold: true } },
  ], { x: 7.05, y: 3.85, w: 5.55, h: 2.7, fontSize: 13, color: C.textDark, fontFace: FONT_B, margin: 0 });
  addFooter(s, 9, TOTAL);
}

// ============================== SLIDE 10 - PIPELINE SKLEARN ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "IMPLEMENTACIÓN");
  s.addText("El patrón universal de scikit-learn", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.9, w: 7.5, h: 4.9, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
  s.addText("python · model_d_training/step5_train_final_models.py", { x: 0.65, y: 1.95, w: 7.3, h: 0.3, fontSize: 10, color: C.textOnDarkMuted, fontFace: "Consolas", margin: 0 });
  // Código simplificado: una sola línea por addText para garantizar saltos de línea
  // (la coloración fina por token se pierde en LibreOffice; preferimos legibilidad).
  const codeLines = [
    { t: "from sklearn.tree import DecisionTreeClassifier", c: "D4D4D4" },
    { t: "from sklearn.model_selection import train_test_split", c: "D4D4D4" },
    { t: "from sklearn.metrics import accuracy_score, classification_report", c: "D4D4D4" },
    { t: "", c: "D4D4D4" },
    { t: "# 1. Cargar features y target", c: "6A9955" },
    { t: "X = df[gate_factors + tech_indicators]", c: "D4D4D4" },
    { t: "y = df[\"outcome\"]   # 1 = WIN, 0 = LOSS", c: "D4D4D4" },
    { t: "", c: "D4D4D4" },
    { t: "# 2. Train / Test split (80/20, estratificado)", c: "6A9955" },
    { t: "X_train, X_test, y_train, y_test = train_test_split(", c: "D4D4D4" },
    { t: "    X, y, test_size=0.2, stratify=y, random_state=42)", c: "D4D4D4" },
    { t: "", c: "D4D4D4" },
    { t: "# 3. Modelo (interpretable, resistente a overfitting)", c: "6A9955" },
    { t: "model = DecisionTreeClassifier(max_depth=5, random_state=42)", c: "D4D4D4" },
    { t: "model.fit(X_train, y_train)", c: "D4D4D4" },
    { t: "", c: "D4D4D4" },
    { t: "# 4. Evaluación", c: "6A9955" },
    { t: "y_pred = model.predict(X_test)", c: "D4D4D4" },
    { t: "print(f\"Accuracy: {accuracy_score(y_test, y_pred):.2%}\")", c: "D4D4D4" },
  ];
  const codeRuns = codeLines.map((ln, idx) => ({
    text: ln.t || " ",
    options: { color: ln.c, breakLine: idx < codeLines.length - 1 },
  }));
  s.addText(codeRuns, { x: 0.65, y: 2.3, w: 7.3, h: 4.4, fontSize: 11, fontFace: "Consolas", margin: 0, paraSpaceAfter: 0 });
  s.addText("5 PASOS, CUALQUIER MODELO", { x: 8.3, y: 1.9, w: 4.5, h: 0.35, fontSize: 11, bold: true, color: C.textMuted, fontFace: FONT_B, charSpacing: 3, margin: 0 });
  const stepsMini = ["Importar", "Crear", "Entrenar (.fit)", "Predecir (.predict)", "Evaluar (.score)"];
  stepsMini.forEach((st, i) => {
    const y = 2.35 + i * 0.85;
    s.addShape(pres.shapes.RECTANGLE, { x: 8.3, y, w: 4.5, h: 0.7, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addShape(pres.shapes.OVAL, { x: 8.45, y: y + 0.13, w: 0.45, h: 0.45, fill: { color: C.gold }, line: { color: C.gold, width: 0 } });
    s.addText(`${i + 1}`, { x: 8.45, y: y + 0.13, w: 0.45, h: 0.45, fontSize: 14, bold: true, color: "FFFFFF", fontFace: FONT_H, align: "center", valign: "middle", margin: 0 });
    s.addText(st, { x: 9.05, y, w: 3.6, h: 0.7, fontSize: 14, color: C.textDark, fontFace: FONT_B, valign: "middle", margin: 0 });
  });
  addFooter(s, 10, TOTAL);
}

// ============================== SLIDE 11 - 6 MODELOS ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "EXPERIMENTACIÓN");
  s.addText("6 modelos competitivos en paralelo", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  s.addText("En vez de elegir un modelo a ciegas, dejamos que compitan y medimos cuál tiene mejor win rate real.", { x: 0.5, y: 1.55, w: 12.3, h: 0.4, fontSize: 13, color: C.textMuted, fontFace: FONT_B, italic: true, margin: 0 });
  const head = (text) => ({ text, options: { bold: true, color: "FFFFFF", fill: { color: C.navy }, fontSize: 12, valign: "middle" } });
  const c = (text, opts = {}) => ({ text, options: { fontSize: 12, fontFace: FONT_B, color: C.textDark, valign: "middle", ...opts } });
  const rows = [
    [head("ID"), head("Nombre"), head("Estrategia"), head("Stop / Target"), head("Horizonte"), head("Win rate*")],
    [c("A"), c("Scalp Conservative"), c("Scalping cauteloso"), c("–2.5% / +3%"), c("4 h"), c("85.1%", { color: C.win, bold: true })],
    [c("B"), c("Momentum Burst", { bold: true, color: C.gold }), c("Impulsos rápidos post-news"), c("–2% / +3%"), c("2 h"), c("97.3% ★", { color: C.win, bold: true })],
    [c("C"), c("News Spike"), c("Reacción a eventos macro"), c("–4% / +10%"), c("4 h"), c("80.4%", { color: C.win, bold: true })],
    [c("D"), c("Dip Scalper"), c("Compra del pánico (F&G < 25)"), c("–6% / +20%"), c("8 h"), c("85.7%", { color: C.win, bold: true })],
    [c("E"), c("Breakout Micro"), c("Ruptura técnica de ATH"), c("–3% / +6%"), c("6 h"), c("82.1%", { color: C.win, bold: true })],
    [c("F"), c("Trend Rider"), c("Montaje de tendencia larga"), c("–5% / +15%"), c("12 h"), c("78.5%", { color: C.win, bold: true })],
  ];
  s.addTable(rows, { x: 0.5, y: 2.1, w: 12.3, h: 3.7, colW: [0.6, 2.2, 3.6, 2.0, 1.5, 2.4], border: { pt: 0.5, color: C.border }, fontFace: FONT_B });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 6.0, w: 12.3, h: 0.85, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 6.0, w: 0.08, h: 0.85, fill: { color: C.gold }, line: { color: C.gold, width: 0 } });
  s.addText("★ Modelo B (Momentum Burst) lidera con 97.3% de win rate. Es el candidato a activar en mainnet primero.", { x: 0.75, y: 6.0, w: 11.9, h: 0.85, fontSize: 14, bold: true, color: C.textOnDark, fontFace: FONT_B, valign: "middle", margin: 0 });
  s.addText("* Win rate en walk-forward con 4.6M klines 2024–26. No es backtest mirando al pasado.", { x: 0.5, y: 6.9, w: 12.3, h: 0.25, fontSize: 9, italic: true, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  addFooter(s, 11, TOTAL);
}

// ============================== SLIDE 12 - RESULTADOS BAR CHART ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "RESULTADOS");
  s.addText("Win rate por modelo y benchmark humano", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  s.addChart(pres.charts.BAR, [{
    name: "Win Rate (%)",
    labels: ["Humano avg.", "Modelo F", "Modelo C", "Modelo E", "Modelo A", "Modelo D", "Modelo B"],
    values: [52, 78.5, 80.4, 82.1, 85.1, 85.7, 97.3],
  }], {
    x: 0.5, y: 1.9, w: 8.2, h: 4.9,
    barDir: "bar", chartColors: [C.gold],
    chartArea: { fill: { color: "FFFFFF" }, roundedCorners: true },
    catAxisLabelColor: C.textDark, catAxisLabelFontSize: 11,
    valAxisLabelColor: C.textMuted, valAxisLabelFontSize: 10,
    valGridLine: { color: "E2E8F0", size: 0.5 }, catGridLine: { style: "none" },
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: C.textDark,
    dataLabelFontSize: 11, dataLabelFontBold: true,
    showLegend: false, valAxisMinVal: 0, valAxisMaxVal: 100,
  });
  s.addShape(pres.shapes.RECTANGLE, { x: 9.0, y: 1.9, w: 3.8, h: 4.9, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
  s.addText("LECTURA RÁPIDA", { x: 9.2, y: 2.05, w: 3.4, h: 0.3, fontSize: 11, bold: true, color: C.gold, fontFace: FONT_B, charSpacing: 4, margin: 0 });
  s.addText("+45 pts", { x: 9.2, y: 2.5, w: 3.4, h: 1.0, fontSize: 44, bold: true, color: C.win, fontFace: FONT_H, margin: 0 });
  s.addText("Mejor modelo (B) vs trader humano promedio.", { x: 9.2, y: 3.6, w: 3.4, h: 0.8, fontSize: 12, color: C.textOnDark, fontFace: FONT_B, margin: 0 });
  s.addShape(pres.shapes.LINE, { x: 9.2, y: 4.5, w: 3.4, h: 0, line: { color: C.cyan, width: 0.5 } });
  s.addText("Los 6 modelos superan al benchmark humano.", { x: 9.2, y: 4.7, w: 3.4, h: 1.2, fontSize: 12, color: C.textOnDark, fontFace: FONT_B, margin: 0 });
  s.addText("El gate de 13 factores funciona como filtro: descarta el ruido y conserva los setups de mayor probabilidad.", { x: 9.2, y: 5.45, w: 3.4, h: 1.3, fontSize: 11, color: C.textOnDarkMuted, fontFace: FONT_B, italic: true, margin: 0 });
  addFooter(s, 12, TOTAL);
}

// ============================== SLIDE 13 - MÉTRICAS DETALLADAS ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "EVALUACIÓN");
  s.addText("Métricas del Modelo B (clasificación binaria)", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  s.addText("classification_report sobre el conjunto de test (20% holdout, n = 2,313 ventanas)", { x: 0.5, y: 1.55, w: 12.3, h: 0.4, fontSize: 12, italic: true, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  const metrics = [
    { v: "0.973", l: "Accuracy", desc: "97.3% de predicciones correctas en test" },
    { v: "0.961", l: "Precision (WIN)", desc: "De los que predijo ganar, ganaron" },
    { v: "0.984", l: "Recall (WIN)", desc: "Capturó casi todos los wins reales" },
    { v: "0.972", l: "F1-score", desc: "Promedio armónico precision / recall" },
  ];
  metrics.forEach((m, i) => {
    const x = 0.5 + i * 3.13;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 2.15, w: 2.95, h: 1.6, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 2.15, w: 2.95, h: 0.1, fill: { color: C.win }, line: { color: C.win, width: 0 } });
    s.addText(m.v, { x: x + 0.15, y: 2.3, w: 2.65, h: 0.7, fontSize: 32, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
    s.addText(m.l, { x: x + 0.15, y: 3.0, w: 2.65, h: 0.35, fontSize: 12, bold: true, color: C.textDark, fontFace: FONT_B, margin: 0 });
    s.addText(m.desc, { x: x + 0.15, y: 3.35, w: 2.65, h: 0.4, fontSize: 9, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  });
  s.addText("MATRIZ DE CONFUSIÓN", { x: 0.5, y: 4.0, w: 6, h: 0.3, fontSize: 11, bold: true, color: C.textMuted, fontFace: FONT_B, charSpacing: 4, margin: 0 });
  const cmH = (t) => ({ text: t, options: { bold: true, color: C.textMuted, fill: { color: "F1F5F9" }, fontSize: 11, valign: "middle", align: "center" } });
  const cmC = (t, color = C.textDark, fill = "FFFFFF") => ({ text: t, options: { bold: true, color: color, fill: { color: fill }, fontSize: 22, valign: "middle", align: "center" } });
  const cmRows = [
    [{ text: "", options: { fill: { color: "F1F5F9" } } }, cmH("Pred LOSS"), cmH("Pred WIN")],
    [{ text: "Real LOSS", options: { bold: true, color: C.textMuted, fill: { color: "F1F5F9" }, fontSize: 11, valign: "middle" } }, cmC("1,121", C.win, "DCFCE7"), cmC("46", C.loss, "FEE2E2")],
    [{ text: "Real WIN", options: { bold: true, color: C.textMuted, fill: { color: "F1F5F9" }, fontSize: 11, valign: "middle" } }, cmC("18", C.loss, "FEE2E2"), cmC("1,128", C.win, "DCFCE7")],
  ];
  s.addTable(cmRows, { x: 0.5, y: 4.35, w: 5.5, h: 2.3, colW: [1.5, 2.0, 2.0], rowH: [0.55, 0.875, 0.875], border: { pt: 0.5, color: C.border }, fontFace: FONT_B });
  s.addShape(pres.shapes.RECTANGLE, { x: 6.3, y: 4.35, w: 6.5, h: 2.4, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 6.3, y: 4.35, w: 0.08, h: 2.4, fill: { color: C.cyan }, line: { color: C.cyan, width: 0 } });
  s.addText("INTERPRETACIÓN", { x: 6.5, y: 4.5, w: 6, h: 0.3, fontSize: 11, bold: true, color: C.cyan, fontFace: FONT_B, charSpacing: 4, margin: 0 });
  s.addText([
    { text: "El modelo prefiere fallar de menos antes que recomendar trades malos.", options: { bold: true, breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "• Solo 46 falsos positivos (LOSS marcadas como WIN) sobre 2,313 casos.", options: { breakLine: true } },
    { text: "• 18 wins se nos escaparon (falsos negativos) → dinero no ganado, no perdido.", options: { breakLine: true } },
    { text: " ", options: { breakLine: true } },
    { text: "En trading, precisión > recall. Es preferible perderse trades a entrar en uno perdedor.", options: { italic: true, color: C.gold } },
  ], { x: 6.5, y: 4.85, w: 6.2, h: 1.85, fontSize: 11, color: C.textOnDark, fontFace: FONT_B, margin: 0 });
  addFooter(s, 13, TOTAL);
}

// ============================== SLIDE 14 - OVERFITTING ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "VALIDACIÓN");
  s.addText("¿El modelo memorizó o realmente aprendió?", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  s.addChart(pres.charts.BAR, [
    { name: "Train accuracy", labels: ["A", "B", "C", "D", "E", "F"], values: [0.871, 0.985, 0.829, 0.879, 0.842, 0.811] },
    { name: "Test accuracy", labels: ["A", "B", "C", "D", "E", "F"], values: [0.851, 0.973, 0.804, 0.857, 0.821, 0.785] },
  ], {
    x: 0.5, y: 1.9, w: 7.8, h: 4.9, barDir: "col", barGrouping: "clustered",
    chartColors: [C.navy, C.gold],
    chartArea: { fill: { color: "FFFFFF" }, roundedCorners: true },
    catAxisLabelColor: C.textDark, catAxisLabelFontSize: 12,
    valAxisLabelColor: C.textMuted,
    valGridLine: { color: "E2E8F0", size: 0.5 }, catGridLine: { style: "none" },
    showValue: true, dataLabelPosition: "outEnd", dataLabelColor: C.textDark, dataLabelFontSize: 9,
    dataLabelFormatCode: "0.000",
    valAxisLabelFormatCode: "0.00",
    showLegend: true, legendPos: "t", legendFontSize: 11,
    valAxisMinVal: 0.7, valAxisMaxVal: 1.05,
  });
  s.addText("GAP ANALYSIS", { x: 8.6, y: 1.9, w: 4, h: 0.3, fontSize: 11, bold: true, color: C.textMuted, fontFace: FONT_B, charSpacing: 4, margin: 0 });
  const headG = (t) => ({ text: t, options: { bold: true, color: "FFFFFF", fill: { color: C.navy }, fontSize: 11, valign: "middle", align: "center" } });
  const cG = (t, color = C.textDark) => ({ text: t, options: { fontSize: 12, fontFace: FONT_B, color, valign: "middle", align: "center", bold: true } });
  const gapRows = [
    [headG("Modelo"), headG("Gap"), headG("Veredicto")],
    [cG("A"), cG("0.020"), cG("OK", C.win)],
    [cG("B"), cG("0.012"), cG("EXCELENTE", C.win)],
    [cG("C"), cG("0.025"), cG("OK", C.win)],
    [cG("D"), cG("0.022"), cG("OK", C.win)],
    [cG("E"), cG("0.021"), cG("OK", C.win)],
    [cG("F"), cG("0.026"), cG("OK", C.win)],
  ];
  s.addTable(gapRows, { x: 8.6, y: 2.3, w: 4.2, h: 3.5, colW: [1.0, 1.2, 2.0], border: { pt: 0.5, color: C.border }, fontFace: FONT_B });
  s.addShape(pres.shapes.RECTANGLE, { x: 8.6, y: 5.9, w: 4.2, h: 0.9, fill: { color: "DCFCE7" }, line: { color: C.win, width: 1 } });
  s.addText("Gap < 0.05 en los 6 modelos → no hay overfitting", { x: 8.75, y: 5.9, w: 4.0, h: 0.9, fontSize: 12, bold: true, color: "065F46", fontFace: FONT_B, valign: "middle", margin: 0 });
  addFooter(s, 14, TOTAL);
}

// ============================== SLIDE 15 - EJEMPLO REAL ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "STORYTELLING");
  s.addText("Predicción real: SOL/USDT, 18 de mayo 2026", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  const events = [
    { t: "10:32 AM", title: "Trump tuitea sobre regulación cripto", desc: "N1 (sentimiento) cambia a +0.6", color: C.gold },
    { t: "10:33 AM", title: "Gate evalúa los 13 factores", desc: "GREEN: M1, M2, S1, S3, T1, N1 (×2)", color: C.cyan },
    { t: "10:34 AM", title: "Modelo B predice WIN con p = 0.94", desc: "Stop –2.0% / Target +3.0% en 2h", color: C.win },
    { t: "11:46 AM", title: "Monitor cierra trade en +3.1%", desc: "WIN. P&L = +$310 sobre $10k notional", color: C.win },
  ];
  events.forEach((e, i) => {
    const y = 1.9 + i * 1.15;
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y, w: 12.3, h: 1.0, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addShape(pres.shapes.OVAL, { x: 0.7, y: y + 0.22, w: 0.55, h: 0.55, fill: { color: e.color }, line: { color: e.color, width: 0 } });
    s.addText(`${i + 1}`, { x: 0.7, y: y + 0.22, w: 0.55, h: 0.55, fontSize: 16, bold: true, color: "FFFFFF", fontFace: FONT_H, align: "center", valign: "middle", margin: 0 });
    s.addText(e.t, { x: 1.45, y: y + 0.15, w: 1.5, h: 0.35, fontSize: 11, bold: true, color: e.color, fontFace: "Consolas", margin: 0 });
    s.addText(e.title, { x: 1.45, y: y + 0.45, w: 7.5, h: 0.4, fontSize: 15, bold: true, color: C.textDark, fontFace: FONT_B, margin: 0 });
    s.addText(e.desc, { x: 9.0, y: y + 0.2, w: 3.7, h: 0.7, fontSize: 12, color: C.textMuted, fontFace: FONT_B, valign: "middle", margin: 0 });
  });
  s.addText("De señal externa a P&L: 1 hora 14 minutos, sin intervención humana.", { x: 0.5, y: 6.65, w: 12.3, h: 0.4, fontSize: 13, italic: true, color: C.textMuted, fontFace: FONT_B, align: "center", margin: 0 });
  addFooter(s, 15, TOTAL);
}

// ============================== SLIDE 16 - RECOMENDACIONES ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "RECOMENDACIONES");
  s.addText("Acciones concretas con base en los resultados", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  const recs = [
    { n: "01", t: "Activar Modelo B en mainnet con capital limitado", desc: "Empezar con $1,000 y subir incrementalmente solo si el win rate real se mantiene > 85% durante 30 días." },
    { n: "02", t: "Mantener los demás modelos en paper trading", desc: "Sirven como benchmark + datos de entrenamiento. No están listos para riesgo real." },
    { n: "03", t: "Reentrenar semanalmente con datos nuevos", desc: "El régimen del mercado cambia. Un modelo congelado pierde edge en 4–6 semanas." },
    { n: "04", t: "Añadir señales on-chain como Fase 2", desc: "Whale movements, exchange inflows. Probable +3–5 pts de win rate según literatura (Glassnode, CryptoQuant)." },
  ];
  recs.forEach((r, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.5 + col * 6.2, y = 1.9 + row * 2.45;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 5.95, h: 2.3, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.08, h: 2.3, fill: { color: C.gold }, line: { color: C.gold, width: 0 } });
    s.addText(r.n, { x: x + 0.25, y: y + 0.18, w: 1, h: 0.5, fontSize: 14, bold: true, color: C.gold, fontFace: FONT_H, margin: 0 });
    s.addText(r.t, { x: x + 0.25, y: y + 0.55, w: 5.5, h: 0.9, fontSize: 16, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
    s.addText(r.desc, { x: x + 0.25, y: y + 1.4, w: 5.5, h: 0.8, fontSize: 12, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  });
  addFooter(s, 16, TOTAL);
}

// ============================== SLIDE 17 - LIMITACIONES ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.panelLight };
  addKicker(s, "LIMITACIONES", C.loss);
  s.addText("Lo que este bot NO puede hacer", { x: 0.5, y: 0.85, w: 12.3, h: 0.8, fontSize: 28, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
  s.addText("Honestidad técnica: ningún modelo es perfecto. Estas son las fronteras reales del sistema.", { x: 0.5, y: 1.55, w: 12.3, h: 0.4, fontSize: 12, italic: true, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  const lims = [
    { t: "Solo TOP 20 pares", desc: "Entrenado con BTC, ETH y 18 más. Aplicarlo a memecoins random degrada el win rate." },
    { t: "Spreads y slippage no modelados", desc: "Las métricas asumen ejecución al precio de cierre. En mainnet el P&L real puede ser 0.1–0.3% menor por operación." },
    { t: "Dependencia de Google News RSS", desc: "Si el RSS cae o sufre delay > 5 min, N1 se queda obsoleto y el bot opera con sentimiento estale." },
    { t: "No detecta black swans", desc: "Quiebra de exchange, hack de Binance, flash crash. Ningún feature histórico los predice." },
    { t: "Régimen-dependiente", desc: "Bull market 2024 ≠ bear market hipotético. Hay que re-validar si la volatilidad estructural cambia." },
    { t: "Sin protección contra correlación", desc: "Si abre 5 trades en altcoins y BTC se desploma, las 5 cierran en LOSS al mismo tiempo." },
  ];
  lims.forEach((l, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.5 + col * 4.15, y = 2.15 + row * 2.3;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 3.95, h: 2.15, fill: { color: C.cardLight }, line: { color: C.border, width: 1 } });
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 3.95, h: 0.1, fill: { color: C.loss }, line: { color: C.loss, width: 0 } });
    s.addText(l.t, { x: x + 0.2, y: y + 0.25, w: 3.6, h: 0.7, fontSize: 14, bold: true, color: C.textDark, fontFace: FONT_H, margin: 0 });
    s.addText(l.desc, { x: x + 0.2, y: y + 0.95, w: 3.6, h: 1.15, fontSize: 11, color: C.textMuted, fontFace: FONT_B, margin: 0 });
  });
  addFooter(s, 17, TOTAL);
}

// ============================== SLIDE 18 - CIERRE / Q&A ==============================
{
  const s = pres.addSlide();
  s.background = { color: C.bgDark };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.25, h: 7.5, fill: { color: C.gold }, line: { color: C.gold, width: 0 } });
  s.addText("CONCLUSIÓN", { x: 0.8, y: 0.8, w: 6, h: 0.4, fontSize: 12, bold: true, color: C.gold, fontFace: FONT_B, charSpacing: 6, margin: 0 });
  s.addText("De $0 invertido a un sistema con 97.3% de win rate en paper.", { x: 0.8, y: 1.4, w: 12, h: 1.4, fontSize: 30, bold: true, color: C.textOnDark, fontFace: FONT_H, margin: 0 });
  const closing = [
    { v: "Storytelling", d: "Problema → datos → modelo → resultado → acción" },
    { v: "Reproducible", d: "GitHub + datasets en Hugging Face, todo en 3 comandos" },
    { v: "Honesto", d: "Métricas con test holdout y limitaciones declaradas" },
  ];
  closing.forEach((c, i) => {
    const x = 0.8 + i * 4.1;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 3.3, w: 3.85, h: 1.8, fill: { color: C.cardDark }, line: { color: C.cardDark, width: 0 } });
    s.addText(c.v, { x: x + 0.2, y: 3.45, w: 3.5, h: 0.6, fontSize: 20, bold: true, color: C.gold, fontFace: FONT_H, margin: 0 });
    s.addText(c.d, { x: x + 0.2, y: 4.05, w: 3.5, h: 1.0, fontSize: 12, color: C.textOnDark, fontFace: FONT_B, margin: 0 });
  });
  s.addText("¿Preguntas?", { x: 0.8, y: 5.5, w: 12, h: 1.0, fontSize: 56, bold: true, color: C.textOnDark, fontFace: FONT_H, margin: 0 });
  s.addText("Juan Ortiz Pa  ·  juan.ortizpa1412@gmail.com  ·  github.com/juanortizpa/crypto_bot", { x: 0.8, y: 7.0, w: 12, h: 0.4, fontSize: 11, color: C.textOnDarkMuted, fontFace: "Consolas", margin: 0 });
}

const outPath = process.argv[2] || "presentacion_final.pptx";
pres.writeFile({ fileName: outPath }).then((f) => { console.log("OK:", f); });
