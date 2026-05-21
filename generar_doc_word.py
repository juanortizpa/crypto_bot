"""
Script para generar un documento Word explicativo del Crypto Trading Bot.
"""
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
import os

doc = Document()

# ── Estilos ──────────────────────────────────────────────────────────
style = doc.styles['Normal']
font = style.font
font.name = 'Calibri'
font.size = Pt(11)
style.paragraph_format.space_after = Pt(6)

for level in range(1, 4):
    hs = doc.styles[f'Heading {level}']
    hs.font.color.rgb = RGBColor(0x1A, 0x3C, 0x6E)

def add_shaded_cell(cell, text, bold=False, color=None, bg=None):
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.bold = bold
    if color:
        run.font.color.rgb = color
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if bg:
        shading = OxmlElement('w:shd')
        shading.set(qn('w:fill'), bg)
        cell._tc.get_or_add_tcPr().append(shading)

def set_cell_shading(cell, color):
    shading = OxmlElement('w:shd')
    shading.set(qn('w:fill'), color)
    cell._tc.get_or_add_tcPr().append(shading)

def add_styled_table(doc, headers, rows, col_widths=None):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = 'Light Grid Accent 1'
    # Header
    for i, h in enumerate(headers):
        cell = table.rows[0].cells[i]
        add_shaded_cell(cell, h, bold=True, color=RGBColor(0xFF, 0xFF, 0xFF))
        set_cell_shading(cell, '1A3C6E')
    # Data
    for r_idx, row in enumerate(rows):
        for c_idx, val in enumerate(row):
            cell = table.rows[r_idx + 1].cells[c_idx]
            cell.text = str(val)
    return table

# ═══════════════════════════════════════════════════════════════════════
# PORTADA
# ═══════════════════════════════════════════════════════════════════════
doc.add_paragraph()
doc.add_paragraph()
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run('CRYPTO TRADING BOT')
run.bold = True
run.font.size = Pt(28)
run.font.color.rgb = RGBColor(0x1A, 0x3C, 0x6E)

sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = sub.add_run('Sistema Automatizado de Predicción y Trading en Binance')
run.font.size = Pt(14)
run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

doc.add_paragraph()
sub2 = doc.add_paragraph()
sub2.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = sub2.add_run('6 Modelos Competitivos  ·  Gate de 16 Factores  ·  Monitoreo en Tiempo Real')
run.font.size = Pt(12)
run.font.color.rgb = RGBColor(0x77, 0x77, 0x77)

doc.add_paragraph()
info = doc.add_paragraph()
info.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = info.add_run('Autor: Juan (firu)  ·  Versión: 1.0  ·  Fecha: Mayo 2026')
run.font.size = Pt(11)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════
# ÍNDICE
# ═══════════════════════════════════════════════════════════════════════
doc.add_heading('Índice', level=1)
toc_items = [
    '1. Resumen Ejecutivo',
    '2. Objetivo del Proyecto',
    '3. Arquitectura del Sistema',
    '4. Stack Técnico',
    '5. Datos de Entrenamiento',
    '6. Fuentes de Datos',
    '7. Gate de 16 Factores',
    '8. Los 6 Modelos de Trading',
    '9. Sistema de Predicciones',
    '10. Monitoreo en Tiempo Real',
    '11. Position Sizing',
    '12. Pipeline de Entrenamiento (Event-Driven)',
    '13. Base de Datos SQLite',
    '14. Seguridad y Risk Guards',
    '15. Cómo Ejecutar',
    '16. Roadmap y Mejoras Futuras',
]
for item in toc_items:
    p = doc.add_paragraph(item)
    p.paragraph_format.space_after = Pt(2)

doc.add_page_break()

# ═══════════════════════════════════════════════════════════════════════
# 1. RESUMEN EJECUTIVO
# ═══════════════════════════════════════════════════════════════════════
doc.add_heading('1. Resumen Ejecutivo', level=1)
doc.add_paragraph(
    'El Crypto Trading Bot es un sistema automatizado de predicción y monitoreo '
    'de criptomonedas diseñado para operar en Binance (testnet primero, mainnet después). '
    'Combina análisis técnico con procesamiento de noticias en tiempo real para generar '
    'señales de compra/venta a través de 6 modelos competitivos que compiten entre sí.'
)
doc.add_paragraph(
    'El sistema se entrenó con 4.6 millones de velas (klines) de 5 minutos del año 2024, '
    'abarcando los 20 principales pares del mercado y 39 eventos globales significativos. '
    'El mejor modelo (Modelo B - Momentum Burst) alcanzó un 97.3% de win rate en backtest.'
)
doc.add_paragraph(
    'El bot opera con un enfoque "forward-looking": no usa backtest histórico para predecir, '
    'sino que evalúa condiciones actuales del mercado en tiempo real cada 5 minutos. '
    'Todas las predicciones se guardan en una base de datos SQLite para su posterior análisis '
    'y comparación de rendimiento entre modelos.'
)

# Métricas clave
doc.add_heading('Métricas Clave', level=2)
add_styled_table(doc,
    ['Métrica', 'Valor'],
    [
        ['Período de entrenamiento', '2024 (1 año completo)'],
        ['Timeframe', '5 minutos'],
        ['Total klines', '4.6 millones'],
        ['Pares entrenados', 'TOP 20 (10 stable + 10 volatile)'],
        ['Eventos globales', '39 eventos (Trump, Fed, Elon, regulaciones)'],
        ['Ventanas de eventos', '11,563 event windows sintéticas'],
        ['Modelos', '6 (A-F) + Meta ensemble'],
        ['Mejor win rate', '97.3% (Modelo B - Momentum Burst)'],
        ['Monitoreo', 'Cada 5 minutos, 24/7'],
        ['Cierre dinámico', 'Por P&L, momentum, volatilidad (no por tiempo)'],
    ]
)

# ═══════════════════════════════════════════════════════════════════════
# 2. OBJETIVO DEL PROYECTO
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('2. Objetivo del Proyecto', level=1)

doc.add_heading('Objetivo Principal', level=2)
doc.add_paragraph(
    'Construir un bot de trading automatizado de criptomonedas que sea capaz de predecir '
    'movimientos de precio a corto plazo (1-12 horas) utilizando exclusivamente datos públicos '
    'y que pueda identificar cuál de los 6 modelos tiene mejor rendimiento en diferentes condiciones del mercado.'
)

doc.add_heading('Objetivos Específicos', level=2)
objectives = [
    ('Predicción de Precios', 'Predecir movimientos de precio usando análisis técnico (SMA, RSI, ATR, MACD) combinado con sentimiento de mercado y noticias en tiempo real.'),
    ('Selección de Modelos', 'Ejecutar 6 modelos de trading en paralelo sobre los mismos datos y determinar cuál tiene mejor win rate en distintas condiciones de mercado.'),
    ('Monitoreo Continuo', 'Monitorear posiciones abiertas cada 5 minutos y cerrar trades de forma dinámica basándose en condiciones de P&L, momentum y volatilidad.'),
    ('Operación en Testnet', 'Validar toda la lógica en Binance Testnet antes de migrar a mainnet, minimizando riesgos de capital.'),
    ('Transparencia', 'Mantener un sistema completamente auditable con todas las predicciones, decisiones y resultados almacenados en SQLite.'),
]
for title, desc in objectives:
    p = doc.add_paragraph(style='List Bullet')
    run = p.add_run(f'{title}: ')
    run.bold = True
    p.add_run(desc)

doc.add_heading('Filosofía de Diseño', level=2)
doc.add_paragraph(
    'El proyecto se basa en estos principios fundamentales:'
)
philosophy = [
    ('Forward-looking', 'No usa backtest histórico para predecir. Cada predicción se basa en condiciones actuales del mercado.'),
    ('No blackbox', 'Todo el sistema es de reglas explícitas (no ML opaco). Cada decisión se puede rastrear a factores concretos.'),
    ('Competitivo', '6 modelos compiten en paralelo. El mejor emerge naturalmente por win rate, no por diseño.'),
    ('Cierre dinámico', 'Los trades no se cierran por tiempo fijo, sino por condiciones de mercado.'),
    ('Paper trading first', 'Validación exhaustiva en testnet antes de arriesgar capital real.'),
]
for title, desc in philosophy:
    p = doc.add_paragraph(style='List Bullet')
    run = p.add_run(f'{title}: ')
    run.bold = True
    p.add_run(desc)

# ═══════════════════════════════════════════════════════════════════════
# 3. ARQUITECTURA DEL SISTEMA
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('3. Arquitectura del Sistema', level=1)

doc.add_paragraph(
    'El sistema está organizado en 4 capas principales que procesan datos desde la obtención '
    'hasta la ejecución y almacenamiento:'
)

doc.add_heading('Diagrama de Arquitectura', level=2)
arch_text = """
┌─────────────────────────────────────────────────────────────┐
│                   CRYPTO TRADING BOT                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐      ┌──────────────┐  ┌──────────────┐  │
│  │ Data Layer  │◄─────┤ Binance API  │  │ Sentiment    │  │
│  │ (OHLCV)     │      │ (klines)     │  │ (News/FNG)   │  │
│  └──────┬──────┘      └──────────────┘  └──────────────┘  │
│         │                                                   │
│         ▼                                                   │
│  ┌────────────────────────────────────┐                   │
│  │     16-FACTOR GATE SYSTEM          │                   │
│  │  (Análisis técnico + sentimiento)  │                   │
│  │   GREEN / YELLOW / RED signals     │                   │
│  └────────────┬───────────────────────┘                   │
│               │                                             │
│               ▼                                             │
│  ┌────────────────────────────────────┐                   │
│  │   6 COMPETITIVE MODELS             │                   │
│  │  A: Scalp Conservative (4h)        │                   │
│  │  B: Momentum Burst (2h)            │                   │
│  │  C: News Spike (4h)                │                   │
│  │  D: Dip Scalper (8h)               │                   │
│  │  E: Breakout Micro (6h)            │                   │
│  │  F: Trend Rider (12h)              │                   │
│  └────────────┬───────────────────────┘                   │
│               │                                             │
│               ▼                                             │
│  ┌────────────────────────────────────┐                   │
│  │  Real-Time Monitor (5-min checks)  │                   │
│  │  ├─ Dynamic Close Logic            │                   │
│  │  ├─ P&L tracking                   │                   │
│  │  └─ Data Validation                │                   │
│  └────────────┬───────────────────────┘                   │
│               │                                             │
│               ▼                                             │
│  ┌────────────────────────────────────┐                   │
│  │   SQLite Database                  │                   │
│  │   └─ predictions.db (outcomes)     │                   │
│  └────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
"""
p = doc.add_paragraph()
run = p.add_run(arch_text)
run.font.size = Pt(8)
run.font.name = 'Consolas'

doc.add_heading('Estructura de Carpetas', level=2)
folder_structure = """
crypto_bot/
├── bot/                           CORE - Módulos principales
│   ├── crypto_data.py            Descarga OHLCV + indicadores técnicos
│   ├── crypto_gate.py            Gate de 16 factores (GREEN/YELLOW/RED)
│   ├── crypto_models.py          Lógica de los 6 modelos
│   ├── crypto_news.py            Análisis de sentimiento (Google RSS)
│   ├── predictions.py            Engine de predicciones + BD SQLite
│   ├── predictions_realtime.py   Monitor en tiempo real (5-min checks)
│   ├── position_sizing.py        Cálculo de posición y stop/target
│   ├── sentiment.py              Análisis de sentimiento avanzado
│   ├── top20_pairs.py            Lista de 20 pares entrenados
│   └── logger.py                 Logging centralizado
│
├── model_d_training/             PIPELINE - Entrenamiento event-driven
│   ├── step1_extract_event_features.py
│   ├── step2_train_event_models.py
│   ├── step3_walkforward_validation.py
│   ├── step4_expand_event_windows.py
│   └── step5_train_final_models.py
│
├── state/crypto_predictions.db   Base de datos SQLite
├── logs/                         Logs de ejecución
├── run_crypto_models.py          PUNTO DE ENTRADA principal (CLI)
├── binance_client.py             Cliente API de Binance
├── .env                          Configuración (API keys)
└── requirements.txt              Dependencias Python
"""
p = doc.add_paragraph()
run = p.add_run(folder_structure)
run.font.size = Pt(8)
run.font.name = 'Consolas'

doc.add_heading('Flujo de Datos', level=2)
doc.add_paragraph('El procesamiento sigue 3 etapas principales:')

doc.add_heading('Etapa 1: Predicción Diaria (cada mañana)', level=3)
steps = [
    '1. Obtener OHLCV de Binance para los 20 pares entrenados (velas 1h + 1d)',
    '2. Calcular indicadores técnicos: SMA(20/50/200), RSI(14), ATR(14), MACD, volumen promedio',
    '3. Obtener sentimiento macro: Fear & Greed Index (alternative.me), Dominancia BTC (CoinGecko)',
    '4. Procesar noticias: Google News RSS -> 250+ keywords -> 8 figuras de poder -> score ponderado',
    '5. Ejecutar Gate de 16 factores: cada factor produce GREEN/YELLOW/RED',
    '6. Evaluar 6 modelos en paralelo: cada modelo filtra según su umbral de gate + filtros extra',
    '7. Calcular position sizing: capital distribuido proporcionalmente a confianza',
    '8. Guardar predicciones en SQLite con estado PENDING',
]
for s in steps:
    doc.add_paragraph(s, style='List Number')

doc.add_heading('Etapa 2: Monitoreo Continuo (cada 5 minutos)', level=3)
steps2 = [
    '1. Obtener predicciones con estado PENDING desde la BD',
    '2. Para cada una, evaluar condiciones dinámicas de cierre:',
    '   a. ¿P&L >= +3%? → Cierre WIN anticipado',
    '   b. ¿Precio <= stop? → Cierre LOSS por stop hit',
    '   c. ¿Precio >= target? → Cierre WIN por target hit',
    '   d. ¿Momentum se invirtió? (gate más rojo que verde) → Cierre LOSS',
    '   e. ¿Volatilidad colapsó? → Cierre LOSS',
    '3. Actualizar BD con outcome, P&L, horas mantenidas',
    '4. Esperar 5 minutos y repetir',
]
for s in steps2:
    doc.add_paragraph(s, style='List Number')

doc.add_heading('Etapa 3: Reporte Diario', level=3)
doc.add_paragraph('Al final del día se genera un reporte comparativo:')
report_items = [
    'Win rate global y por modelo',
    'Expectancy (P&L promedio por trade)',
    'Horas promedio de holding',
    'Mejor modelo del día (lider)',
    'Candidatos para auto-execute (WR >= 55% + expectancy positiva)',
]
for item in report_items:
    doc.add_paragraph(item, style='List Bullet')

# ═══════════════════════════════════════════════════════════════════════
# 4. STACK TÉCNICO
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('4. Stack Técnico', level=1)

add_styled_table(doc,
    ['Componente', 'Tecnología / Librería', 'Propósito'],
    [
        ['Lenguaje', 'Python 3.9+', 'Core del sistema'],
        ['API Binance', 'requests + urllib (nativo)', 'Datos OHLCV, órdenes, cuentas'],
        ['Análisis técnico', 'NumPy, Pandas', 'Indicadores: SMA, RSI, ATR, MACD'],
        ['Machine Learning', 'XGBoost, scikit-learn', 'Modelos entrenados (pipeline event-driven)'],
        ['Base de datos', 'SQLite3 (nativo)', 'Predicciones, outcomes, métricas'],
        ['Sentimiento', 'Google News RSS + custom NLP', '250+ keywords + 8 figuras de poder'],
        ['Fear & Greed', 'alternative.me API (gratis)', 'Índice de sentimiento macro (0-100)'],
        ['BTC Dominance', 'CoinGecko API (gratis)', '% del mercado que es Bitcoin'],
        ['Logging', 'logging + archivo rotativo', 'Registro de todas las operaciones'],
        ['Configuración', 'python-dotenv', 'Variables de entorno + API keys'],
        ['Testing', 'pytest', 'Pruebas unitarias y de integración'],
        ['Formateo', 'black, flake8', 'Calidad de código'],
    ]
)

doc.add_heading('Particularidades Técnicas', level=2)
tech_notes = [
    'Sin dependencias pesadas: El cliente Binance usa requests + urllib nativo en lugar de librerías como python-binance, reduciendo la superficie de ataque y dependencias.',
    'Sin blackbox de ML: Aunque se usó XGBoost en el pipeline de entrenamiento, el sistema de predicción en vivo es 100% basado en reglas explícitas. Cada decisión puede rastrearse a factores concretos del Gate.',
    'Caché inteligente: Todas las llamadas a APIs externas (Binance, CoinGecko, alternative.me, Google News) se cachean para reducir latencia y evitar rate limiting.',
    'SQLite nativo: No se requiere servidor de base de datos. La BD es un archivo .db que se respalda fácilmente.',
]
for note in tech_notes:
    doc.add_paragraph(note, style='List Bullet')

# ═══════════════════════════════════════════════════════════════════════
# 5. DATOS DE ENTRENAMIENTO
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('5. Datos de Entrenamiento', level=1)

doc.add_paragraph(
    'El bot fue entrenado con datos históricos de Binance correspondientes al año 2024, '
    'utilizando velas de 5 minutos para los 20 principales pares del mercado. '
    'Este entrenamiento generó un total de 4.6 millones de klines y 11,563 ventanas '
    'de eventos sintéticas basadas en 39 eventos globales significativos.'
)

doc.add_heading('TOP 20 Pares Entrenados', level=2)

doc.add_heading('10 Pares Estables (Mega-cap)', level=3)
stable_table = [
    ['BTCUSDT', 'Bitcoin', 'Ancla del mercado crypto'],
    ['ETHUSDT', 'Ethereum', 'Segunda mayor capitalización'],
    ['BNBUSDT', 'Binance Coin', 'Exchange token líder'],
    ['SOLUSDT', 'Solana', 'L1 de alta velocidad'],
    ['XRPUSDT', 'Ripple', 'Pagos transfronterizos'],
    ['ADAUSDT', 'Cardano', 'L1 con enfoque académico'],
    ['AVAXUSDT', 'Avalanche', 'L1 con subnets'],
    ['DOTUSDT', 'Polkadot', 'Parachains interoperables'],
    ['LINKUSDT', 'Chainlink', 'Oracle líder'],
    ['POLUSDT', 'Polygon (ex-MATIC)', 'L2 de Ethereum'],
]
add_styled_table(doc,
    ['Par', 'Nombre', 'Descripción'],
    stable_table
)

doc.add_heading('10 Pares Volátiles (Alta Beta)', level=3)
volatile_table = [
    ['DOGEUSDT', 'Dogecoin', 'Meme coin, influencia de Elon Musk'],
    ['SHIBUSDT', 'Shiba Inu', 'Meme coin de alta volatilidad'],
    ['NEARUSDT', 'NEAR Protocol', 'Narrativa AI/Cloud'],
    ['APTUSDT', 'Aptos', 'L1 de alta volatilidad'],
    ['SUIUSDT', 'Sui', 'L1 nuevo, movimientos extremos'],
    ['INJUSDT', 'Injective', 'DeFi cross-chain'],
    ['RENDERUSDT', 'Render (ex-RNDR)', 'GPU compute / AI'],
    ['TIAUSDT', 'Celestia', 'Modular DA layer'],
    ['SEIUSDT', 'Sei', 'High-speed blockchain'],
    ['FETUSDT', 'Fetch.ai', 'AI + high volatility'],
]
add_styled_table(doc,
    ['Par', 'Nombre', 'Descripción'],
    volatile_table
)

doc.add_heading('Eventos Globales (39 en total)', level=2)
doc.add_paragraph(
    'El modelo se entrenó con ventanas alrededor de 39 eventos globales significativos de 2024, incluyendo:'
)
events = [
    'Decisiones de la Fed (FOMC): subidas/bajadas de tasas de interés',
    'Eventos de Trump: anuncios políticos, declaraciones sobre crypto',
    'Tweets de Elon Musk: impacto en DOGE, SHIB y mercado general',
    'Decisiones SEC: demandas, aprobaciones de ETF, regulaciones',
    'Eventos de halving de Bitcoin (Abril 2024)',
    'Anuncios de BlackRock/Fidelity sobre ETF spot de Bitcoin y Ethereum',
    'Eventos geopolíticos: conflictos, elecciones, políticas económicas',
    'Hacks y exploits: incidentes de seguridad en exchanges y protocolos',
]
for ev in events:
    doc.add_paragraph(ev, style='List Bullet')

doc.add_heading('Advertencia Crítica', level=2)
doc.add_paragraph(
    '⚠️ El modelo fue entrenado exclusivamente con estos 20 pares. NO debe usarse para predecir '
    'movimientos en pares no entrenados (como PEPE, BONK, ORDI, etc.), ya que los patrones de '
    'volatilidad y correlación con BTC son fundamentalmente diferentes. Expandir a más pares '
    'requiere reentrenamiento completo del pipeline.'
)

# ═══════════════════════════════════════════════════════════════════════
# 6. FUENTES DE DATOS
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('6. Fuentes de Datos', level=1)

doc.add_paragraph(
    'El bot utiliza exclusivamente fuentes de datos públicas y gratuitas, lo que garantiza '
    'que cualquier persona pueda replicar el sistema sin necesidad de suscripciones pagas.'
)

add_styled_table(doc,
    ['Fuente', 'Proveedor', 'Datos Obtenidos', 'Frecuencia'],
    [
        ['Velas OHLCV', 'Binance API', 'Open, High, Low, Close, Volume', 'Cada vela (1h, 4h, 1d)'],
        ['Precio actual', 'Binance API', 'Último precio negociado', 'Tiempo real'],
        ['Fear & Greed', 'alternative.me', 'Índice 0-100 + clasificación', '1 vez por día'],
        ['Noticias', 'Google News RSS', 'Titulares + descripciones', 'Tiempo real (1-5 min delay)'],
        ['Dominancia BTC', 'CoinGecko', '% del mercado total', '1 vez por día'],
        ['24h stats', 'Binance API', 'PriceChange, volume, high/low', 'Tiempo real'],
    ]
)

doc.add_heading('Procesamiento de Noticias', level=2)
doc.add_paragraph(
    'El sistema de sentimiento analiza noticias de Google News RSS usando un diccionario '
    'de más de 250 palabras clave clasificadas como BULLISH o BEARISH, con pesos especiales '
    'para figuras de poder en el ecosistema crypto:'
)

add_styled_table(doc,
    ['Figura', 'Peso', 'Impacto'],
    [
        ['Trump', '3.0x', 'Mayor influencia política en crypto (estrategia, reservas)'],
        ['Powell / Fed', '2.5x', 'Tasas de interés afectan activos de riesgo'],
        ['Elon Musk', '2.5x', 'Mueve DOGE, SHIB y sentimiento general'],
        ['SEC / Gensler', '2.0x', 'Regulación, demandas, aprobaciones'],
        ['BlackRock / ETF', '1.8x', 'Flujos institucionales, adopción'],
        ['Hacks / Seguridad', '2.0x', 'Incidentes de seguridad, impacto inmediato'],
        ['China', '1.3x', 'Políticas de bans / regulación'],
    ]
)

doc.add_paragraph(
    'Las noticias tienen PESO DOBLE en el Gate en comparación con otros factores, '
    'porque el mercado crypto opera 24/7 y un solo tweet de una figura influyente '
    'puede mover el mercado 10-30% en minutos.'
)

# ═══════════════════════════════════════════════════════════════════════
# 7. GATE DE 16 FACTORES
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('7. Gate de 16 Factores', level=1)

doc.add_paragraph(
    'El corazón del sistema es un "Gate" de 16 factores que evalúa el mercado desde '
    '4 perspectivas: macroeconómica, técnica a corto plazo, timing de entrada y riesgo. '
    'Cada factor produce un semáforo: GREEN (+1 punto), YELLOW (0 puntos) o RED (-1 punto).'
)

doc.add_paragraph(
    'El sistema fue actualizado de 13 a 16 factores para incluir eventos macro cercanos (M4), '
    'control de sesión de 12 horas (R3) y veto por flash crash/pump (X1).'
)

doc.add_heading('Layer 1: Macro (Contexto Diario)', level=2)
macro_factors = [
    ('M1 - BTC Trend', 'Analiza la tendencia de Bitcoin usando SMA20 y SMA50 diarios. BULLISH si precio > ambas medias, BEARISH si bajo SMA50.', 'Contexto general del mercado'),
    ('M2 - Fear & Greed', 'Índice 0-100 de alternative.me. Combina volatilidad (30%), volumen (25%), momentum (25%), dominancia BTC (10%) y trends Google (10%).', 'Sentimiento macro'),
    ('M3 - Volatilidad 1h', 'ATR de velas de 1 hora como porcentaje del precio. <1.5% es GREEN (calma), >3% es RED (muy volátil).', 'Riesgo de slippage'),
    ('M4 - Eventos Macro', 'Detección de eventos próximos: FOMC, CPI, NFP, decisiones de bancos centrales en las próximas 4 horas.', 'Evitar entrar antes de noticias'),
    ('S4 - BTC Dominance', 'Porcentaje del mercado total que representa Bitcoin. <50% favorece altcoins, >60% favorece Bitcoin.', 'Contexto altseason vs BTC season'),
]
add_styled_table(doc,
    ['Factor', 'Descripción', 'Propósito'],
    macro_factors
)

doc.add_heading('Layer 2: Setup Técnico (Corto Plazo)', level=2)
setup_factors = [
    ('S1 - Momentum 4h', 'Compara el rendimiento del par vs BTC en las últimas 4 horas. Mide fuerza relativa.', 'Identificar liderazgo'),
    ('S2 - Setup Técnico 1h', 'Evalúa precio vs MA20(1h), RSI(14) y dirección de última vela. Score de 0-3.', 'Confirmación de entrada'),
    ('S3 - Volumen 1h', 'Volumen de la última hora vs promedio de 20 horas. >1.3x indica interés.', 'Confirmación de movimiento'),
]
add_styled_table(doc,
    ['Factor', 'Descripción', 'Propósito'],
    setup_factors
)

doc.add_heading('Layer 3: Timing (Micro-estructura)', level=2)
timing_factors = [
    ('T1 - Micro-trend 6h', 'Rendimiento en últimas 6 velas 1h + conteo de velas verdes/rojas.', 'Dirección inmediata'),
    ('T2 - Buy/Sell Ratio', 'Proporción de volumen comprador vs total en últimas 6h. >0.52 = compradores activos.', 'Presión de compra'),
    ('T3 - Señal Entrada', 'Detección de pullback a MA20(1h) o reversal (vela roja seguida de verde).', 'Punto de entrada preciso'),
]
add_styled_table(doc,
    ['Factor', 'Descripción', 'Propósito'],
    timing_factors
)

doc.add_heading('Layer 4: Riesgo', level=2)
risk_factors = [
    ('R1 - Risk/Reward', 'Ratio entre stop y target. >=1.5:1 es GREEN.', 'Asegurar trades rentables'),
    ('R2 - Exposición', 'Cantidad de predicciones abiertas vs máximos por tamaño de portfolio.', 'Control de riesgo'),
    ('R3 - Sesión 12h', 'Tiempo restante en la ventana de trading de 12 horas.', 'Evitar cierres forzosos'),
]
add_styled_table(doc,
    ['Factor', 'Descripción', 'Propósito'],
    risk_factors
)

doc.add_heading('Layer 5: Sentimiento + Vetos', level=2)
special_factors = [
    ('N1 - Noticias (PESO 2x)', 'Análisis de Google News RSS con 250+ keywords y 8 figuras de poder. Peso doble porque crypto es 24/7 y reacciona instantáneamente a noticias.', 'Sentimiento'),
    ('X1 - Flash Crash Veto', 'Detección de movimientos extremos: crash >5% en 4h (blackout 6h) o pump >8% en 4h (evitar comprar techo). VETO DURO si RED.', 'Protección catastrófica'),
]
add_styled_table(doc,
    ['Factor', 'Descripción', 'Propósito'],
    special_factors
)

doc.add_heading('Evaluación del Gate', level=2)
doc.add_paragraph('La decisión final del Gate se determina así:')
gate_table = [
    ['green_count >= 11 y red_count < 3', 'EXECUTE_FULL', '1.0', 'Entrar con máxima confianza'],
    ['green_count >= 9 y red_count < 3', 'EXECUTE_HALF', '0.5', 'Entrar con media posición'],
    ['green_count >= 6 y red_count < 3', 'WATCHLIST', '0.0', 'Observar, no entrar'],
    ['red_count >= 3', 'ABORT', '0.0', 'No entrar, mercado adverso'],
    ['X1 = RED (flash crash)', 'ABORT (veto)', '0.0', 'Veto duro independiente del score'],
    ['R3 = RED (sesión acabando)', 'ABORT (veto)', '0.0', 'Veto duro por tiempo insuficiente'],
    ['M4 = RED (evento macro)', 'ABORT (veto)', '0.0', 'Veto duro por evento inminente'],
]
add_styled_table(doc,
    ['Condición', 'Decisión', 'Size Mult', 'Acción'],
    gate_table
)

# ═══════════════════════════════════════════════════════════════════════
# 8. LOS 6 MODELOS DE TRADING
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('8. Los 6 Modelos de Trading', level=1)

doc.add_paragraph(
    'Cada modelo implementa una estrategia diferente y compite en igualdad de condiciones. '
    'Todos reciben los mismos datos del Gate, pero cada uno tiene umbrales y filtros específicos '
    'que determinan si un par califica para entrar.'
)

doc.add_heading('Tabla Comparativa de Modelos', level=2)
add_styled_table(doc,
    ['Modelo', 'Nombre', 'Max Horas', 'Gate Mín', 'RED Máx', 'Filtro Extra', 'Stop', 'Target', 'WR Backtest'],
    [
        ['A', 'Scalp Conservative', '4h', '>=7', '0', 'Ninguno', '-1.5%', '+2.5%', '~85%'],
        ['B', 'Momentum Burst', '2h', '>=5', '0', 'S1 o T1 = GREEN', '-2.0%', '+3.5%', '97.3%'],
        ['C', 'News Spike', '4h', '>=4', '<=1', 'N1 = GREEN', '-1.5%', '+2.0%', '~80%'],
        ['D', 'Dip Scalper', '8h', '>=3', '<=2', 'F&G < 45 o S1 = RED', '-2.5%', '+3.0%', '~85%'],
        ['E', 'Breakout Micro', '6h', '>=5', '0', 'T3 = GREEN', '-2.0%', '+4.0%', '~82%'],
        ['F', 'Trend Rider', '12h', '>=6', '0', 'M1 = GREEN (BTC alcista)', '-1.8%', '+3.0%', '~78%'],
    ]
)

doc.add_heading('Descripción Detallada por Modelo', level=2)

model_details = [
    ('Modelo A — Scalp Conservative',
     'El modelo más conservador. Solo entra cuando el Gate está casi perfecto (>=7 verdes y 0 rojos). '
     'Busca operaciones de scalping de muy bajo riesgo con stops ajustados (-1.5%) y targets modestos (+2.5%). '
     'Ideal para principiantes o en mercados laterales. Su alta exigencia significa que no entra seguido, '
     'pero cuando lo hace, la probabilidad de ganar es alta.'),
    ('Modelo B — Momentum Burst (⭐ Líder)',
     'El modelo estrella con 97.3% de win rate en backtest. Busca impulsos de momentum confirmados '
     '(S1 o T1 en GREEN), indicando que el par está liderando al mercado. Opera con ventanas cortas '
     '(2 horas máximas) para capturar movimientos rápidos. Stop de -2% y target de +3.5%. '
     'Es el candidato principal para auto-execute cuando acumule suficientes trades.'),
    ('Modelo C — News Spike',
     'Modelo orientado a reaccionar a noticias. Tiene los requisitos de Gate más flexibles '
     '(>=4 verdes, máximo 1 rojo), pero requiere que el factor N1 (noticias) esté en GREEN. '
     'Busca capturar spikes de precio causados por anuncios, tweets o eventos. '
     'Stop ajustado (-1.5%) y target modesto (+2%) porque los spikes suelen revertirse rápido.'),
    ('Modelo D — Dip Scalper',
     'El contrarian del grupo. Busca comprar en momentos de miedo/pánico (F&G < 45 o S1 en RED). '
     'Tiene los requisitos de Gate más bajos (>=3 verdes, <=2 rojos) porque entra cuando el mercado '
     'está en condiciones adversas. Opera con stops más amplios (-2.5%) y targets de +3% para dar '
     'espacio al rebote. Ventana larga de 8 horas para esperar la recuperación.'),
    ('Modelo E — Breakout Micro',
     'Modelo técnico que requiere una señal de entrada clara (T3 = GREEN), indicando un pullback '
     'a MA20 o un reversal de vela. Gate exigente (>=5 verdes, 0 rojos). Target agresivo de +4% '
     'con stop de -2%. Ventana de 6 horas para dar tiempo a que el breakout se desarrolle.'),
    ('Modelo F — Trend Rider',
     'El modelo de más larga duración (12 horas). Requiere que BTC esté en tendencia alcista '
     '(M1 = GREEN) y un Gate sólido (>=6 verdes, 0 rojos). Busca "montar la ola" de la tendencia '
     'general del mercado. Stop moderado (-1.8%) y target de +3%.'),
]

for title, desc in model_details:
    doc.add_heading(title, level=3)
    doc.add_paragraph(desc)

doc.add_heading('Stops y Targets Dinámicos', level=2)
doc.add_paragraph(
    'Aunque cada modelo tiene stops y targets por defecto, el sistema ajusta dinámicamente '
    'estos niveles según la volatilidad real del activo (ATR). En activos de alta volatilidad, '
    'los stops se amplían para evitar stops prematuros; en activos de baja volatilidad, '
    'los targets se ajustan para ser alcanzables.'
)

# ═══════════════════════════════════════════════════════════════════════
# 9. SISTEMA DE PREDICCIONES
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('9. Sistema de Predicciones', level=1)

doc.add_paragraph(
    'El engine de predicciones (predictions.py) es el núcleo que orquesta la generación, '
    'seguimiento y resolución de predicciones. Cada predicción representa una operación '
    'potencial con un par específico, un modelo asignado, stop/target prices y estado.'
)

doc.add_heading('Ciclo de Vida de una Predicción', level=2)
lifecycle = [
    ('1. Generación', 'El bot ejecuta run_predictions() que itera sobre todos los pares en CRYPTO_PAIRS y para cada uno ejecuta el Gate y evalúa los 6 modelos. Si un modelo califica, se guarda una predicción con estado PENDING.'),
    ('2. Sizing', 'Después de generar todas las predicciones, asignar_capital() distribuye el capital disponible proporcionalmente a la confianza de cada predicción (basada en gate_score y win_rate histórico del modelo).'),
    ('3. Monitoreo', 'El monitor en tiempo real (predictions_realtime.py) evalúa cada predicción PENDING cada 5 minutos, aplicando la lógica de cierre dinámico.'),
    ('4. Resolución', 'Cuando se cumple una condición de cierre (stop, target, early win, momentum reversal, etc.), la predicción se actualiza con outcome WIN o LOSS, P&L, horas mantenidas y motivo de cierre.'),
    ('5. Reporte', 'Las predicciones cerradas alimentan las estadísticas de win rate por modelo, expectancy y demás métricas que se muestran en compare_models() y accuracy_report().'),
]
for title, desc in lifecycle:
    p = doc.add_paragraph()
    run = p.add_run(f'{title}: ')
    run.bold = True
    p.add_run(desc)

doc.add_heading('Trailing Stop Inteligente', level=2)
doc.add_paragraph(
    'A mitad del tiempo de vida de una predicción (según trail_after del modelo), '
    'si el P&L es >= +1%, el stop se mueve a breakeven (precio de entrada). '
    'Esto garantiza que no se pueda perder dinero en ese trade, asegurando '
    'que el peor caso sea un empate en lugar de una pérdida.'
)

doc.add_heading('Deduplicación Inteligente', level=2)
doc.add_paragraph(
    'El sistema evita generar predicciones duplicadas para el mismo par+modelo dentro '
    'de la ventana de MAX_HOURS (12 horas). Si ya existe una predicción PENDING para '
    'ese par y modelo, se salta la generación. Esto evita acumular múltiples entradas '
    'en el mismo activo con la misma estrategia.'
)

# ═══════════════════════════════════════════════════════════════════════
# 10. MONITOREO EN TIEMPO REAL
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('10. Monitoreo en Tiempo Real', level=1)

doc.add_paragraph(
    'Originalmente, el bot cerraba predicciones cuando expiraba su max_hours (tiempo fijo). '
    'Esto causaba dos problemas: (1) trades ganadores se cerraban antes de alcanzar el target, '
    'y (2) trades perdedores se mantenían abiertos hasta el final. '
    'La solución fue implementar un monitor en tiempo real que evalúa condiciones cada 5 minutos.'
)

doc.add_heading('Lógica de Cierre Dinámico', level=2)
doc.add_paragraph(
    'El monitor evalúa 5 condiciones en orden de prioridad para cada predicción PENDING:'
)
close_conditions = [
    'Stop hit (precio <= stop_price) → LOSS inmediato. Protege contra pérdidas mayores.',
    'Target hit (precio >= target_price) → WIN inmediato. Toma ganancias al nivel objetivo.',
    'Ganancia anticipada (P&L >= +3%) → WIN anticipado. No espera al target si ya hay buena ganancia (protege contra reversiones).',
    'Momentum invertido (P&L <= -2% y gate más rojo que verde) → LOSS anticipado. Corta pérdidas cuando el mercado se vuelve adverso.',
    'Volatilidad colapsada (-2% < P&L < 0% y ATR < 0.05%) → LOSS. Si no hay movimiento esperado, mejor salir.',
]
for c in close_conditions:
    doc.add_paragraph(c, style='List Bullet')

doc.add_heading('Parámetros Ajustables', level=2)
add_styled_table(doc,
    ['Parámetro', 'Valor', 'Descripción'],
    [
        ['MONITOR_INTERVAL', '300 segundos (5 min)', 'Frecuencia de chequeo'],
        ['EARLY_CLOSE_PROFIT', '3.0%', 'Ganancia para cierre WIN anticipado'],
        ['EARLY_CLOSE_LOSS', '-2.0%', 'Pérdida para evaluar cierre anticipado'],
        ['VOLATILITY_THRESHOLD', '0.05%', 'Umbral de volatilidad para considerar "baja"'],
    ]
)

doc.add_heading('Ejemplo de Ejecución', level=2)
monitor_example = """[14:35:21] Check #1...
    [D] BTCUSDT   ✓ WIN  +3.45%  (EARLY_WIN_3.5%)
    [A] ETHUSDT   ✗ LOSS -1.82%  (MOMENTUM_REVERSED_-1.8%)
  → 2 trade(s) cerrado(s)

[14:40:21] Check #2...
  → Todos los trades siguen abiertos

[14:45:21] Check #3...
    [E] SOLUSDT   ✓ WIN  +2.10%  (EARLY_WIN_2.1%)
  → 1 trade(s) cerrado(s)"""
p = doc.add_paragraph()
run = p.add_run(monitor_example)
run.font.size = Pt(8)
run.font.name = 'Consolas'

# ═══════════════════════════════════════════════════════════════════════
# 11. POSITION SIZING
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('11. Position Sizing', level=1)

doc.add_paragraph(
    'El sistema de position sizing asigna capital de forma dinámica después de generar las predicciones. '
    'No usa un tamaño fijo por trade, sino que distribuye el capital proporcionalmente a la confianza '
    'de cada predicción.'
)

doc.add_heading('Algoritmo de Asignación', level=2)
sizing_steps = [
    '1. Obtener win rates históricos por modelo desde la base de datos',
    '2. Para cada predicción, calcular confianza = f(gate_score, model_win_rate)',
    '3. Distribuir capital proporcionalmente a la confianza (normalizado)',
    '4. Verificar perfil de capital activo (SURVIVAL, GROWTH, STANDARD)',
    '5. Aplicar reducción por drawdown actual (más DD → menos capital)',
    '6. Aplicar límites: min $5, max 10% del portfolio, hard cap $50 para cuentas pequeñas',
    '7. Verificar risk guard: si el bot está en pausa por DD, asignar 0',
    '8. Verificar sesión 12h: si no se pueden abrir nuevos trades, saltar',
]
for s in sizing_steps:
    doc.add_paragraph(s, style='List Number')

doc.add_heading('Fórmula de Confianza', level=2)
doc.add_paragraph(
    'Confianza = gate_factor × wr_factor\n'
    'Donde gate_factor depende del gate score (0.6 para score bajo, 1.3 para score alto) '
    'y wr_factor depende del win rate histórico del modelo (0.5 para WR <15%, 1.5 para WR >50%).'
)

doc.add_heading('Perfiles de Capital', level=2)
add_styled_table(doc,
    ['Perfil', 'Descripción', 'Posición por Trade', 'Máx Trades'],
    [
        ['SURVIVAL', 'Protección de capital', 'Fija (ej: $10)', '3'],
        ['GROWTH', 'Crecimiento controlado', 'Fija (ej: $25)', '5'],
        ['STANDARD', 'Asignación dinámica', 'Proporcional a confianza', '10'],
    ]
)

doc.add_heading('Guardias de Seguridad', level=2)
safety_guards = [
    'Daily Loss Kill: si se pierde >15% en un día, se detiene el bot',
    'Total DD Kill: si el drawdown total supera 25%, se detiene',
    'Máximo por trade: 10% del portfolio (nunca más)',
    'Mínimo por trade: $5 (límite de Binance)',
    'Cooldown: 60 minutos entre trades del mismo par',
    'Binance Fee: 0.1% considerado en todos los cálculos',
]
for g in safety_guards:
    doc.add_paragraph(g, style='List Bullet')

# ═══════════════════════════════════════════════════════════════════════
# 12. PIPELINE DE ENTRENAMIENTO
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('12. Pipeline de Entrenamiento (Event-Driven)', level=1)

doc.add_paragraph(
    'El pipeline de entrenamiento (model_d_training/) es un sistema event-driven que entrena '
    'los 6 modelos usando datos históricos de Binance. A diferencia de enfoques tradicionales '
    'de ML que usan ventanas deslizantes, este pipeline entrena alrededor de EVENTOS '
    'específicos del mundo real (decisiones Fed, tweets, regulaciones, etc.)'
)

doc.add_heading('Steps del Pipeline', level=2)

pipeline_steps = [
    ('Step 1: Extraer Features de Eventos',
     'step1_extract_event_features.py: Toma los 39 eventos globales de 2024 y extrae ventanas '
     'de datos alrededor de cada evento. Para cada ventana, calcula features técnicas (SMA, RSI, '
     'ATR, volumen, etc.), features de sentimiento (FNG, noticias) y features de mercado '
     '(dominancia BTC, correlaciones).'),
    ('Step 2: Entrenar Modelos por Evento',
     'step2_train_event_models.py: Entrena 6 modelos XGBoost para cada evento, usando las '
     'features extraídas. Cada modelo se optimiza para predecir si el par subirá o bajará '
     'en las siguientes N horas (según el horizonte del modelo).'),
    ('Step 3: Validación Walk-Forward',
     'step3_walkforward_validation.py: Implementa validación walk-forward para evitar overfitting. '
     'Los modelos se entrenan con datos anteriores a un evento y se validan con datos posteriores. '
     'Solo los modelos que pasan esta validación se guardan para producción.'),
    ('Step 4: Expandir Ventanas de Eventos',
     'step4_expand_event_windows.py: Genera ventanas sintéticas adicionales mediante '
     'aumentación de datos (pequeñas variaciones en los parámetros de los eventos) para '
     'mejorar la robustez de los modelos.'),
    ('Step 5: Entrenar Modelos Finales',
     'step5_train_final_models.py: Entrena los modelos finales usando todos los datos '
     'validados y los guarda como archivos .pkl en state/ para su uso en producción.'),
]
for title, desc in pipeline_steps:
    doc.add_heading(title, level=3)
    doc.add_paragraph(desc)

doc.add_heading('Resultados del Entrenamiento', level=2)
training_results = [
    '4.6M klines de 5 minutos procesados',
    '11,563 event windows generadas',
    '39 eventos globales diferentes',
    '6 modelos entrenados (A-F)',
    'Modelo B: 97.3% win rate (líder)',
    'Modelo D (Dip Scalper): ~85% win rate',
]
for r in training_results:
    doc.add_paragraph(r, style='List Bullet')

# ═══════════════════════════════════════════════════════════════════════
# 13. BASE DE DATOS SQLite
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('13. Base de Datos SQLite', level=1)

doc.add_paragraph(
    'Todas las predicciones, outcomes y métricas se almacenan en una base de datos SQLite '
    'ubicada en state/crypto_predictions.db. No requiere servidor, es fácil de respaldar '
    'y se puede consultar directamente con SQL.'
)

doc.add_heading('Schema de la Tabla Predictions', level=2)
schema_text = """CREATE TABLE predictions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model           TEXT DEFAULT 'A',
    symbol          TEXT NOT NULL,
    predicted_at    TEXT NOT NULL,
    price_at_pred   REAL NOT NULL,
    gate_score      INTEGER NOT NULL,
    decision        TEXT NOT NULL,
    factors_json    TEXT NOT NULL,
    stop_price      REAL,
    target_price    REAL,
    rr_ratio        REAL,
    max_hours       REAL DEFAULT 4,
    outcome         TEXT DEFAULT 'PENDING',   -- WIN, LOSS, PENDING
    outcome_date    TEXT,
    price_at_outcome REAL,
    pnl_pct         REAL,
    r_multiple      REAL,
    hours_held      REAL,
    quantity        REAL,
    position_usd    REAL,
    risk_usd        REAL,
    pnl_usd         REAL,
    error_flags     TEXT
)"""
p = doc.add_paragraph()
run = p.add_run(schema_text)
run.font.size = Pt(8)
run.font.name = 'Consolas'

doc.add_heading('Consultas Útiles', level=2)
queries = [
    ('Win Rate por Modelo',
     "SELECT model, COUNT(*) as total, SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins, ROUND(100.0*SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END)/COUNT(*), 1) as wr_pct FROM predictions WHERE outcome IN ('WIN','LOSS') GROUP BY model ORDER BY wr_pct DESC;"),
    ('Predicciones Pendientes',
     "SELECT model, symbol, predicted_at, price_at_pred, gate_score, decision FROM predictions WHERE outcome='PENDING' ORDER BY predicted_at DESC;"),
    ('Últimas Cerradas',
     "SELECT model, symbol, outcome, pnl_pct, hours_held FROM predictions WHERE outcome IN ('WIN','LOSS') ORDER BY outcome_date DESC LIMIT 10;"),
    ('Resumen Diario',
     "SELECT date(predicted_at) as day, COUNT(*) as total, SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) as wins, ROUND(AVG(pnl_pct), 2) as avg_pnl FROM predictions WHERE outcome IN ('WIN','LOSS') GROUP BY day ORDER BY day DESC;"),
]
for title, query in queries:
    doc.add_heading(title, level=3)
    p = doc.add_paragraph()
    run = p.add_run(query)
    run.font.size = Pt(8)
    run.font.name = 'Consolas'

# ═══════════════════════════════════════════════════════════════════════
# 14. SEGURIDAD Y RISK GUARDS
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('14. Seguridad y Risk Guards', level=1)

doc.add_paragraph(
    'El bot implementa múltiples capas de seguridad para proteger el capital, '
    'especialmente diseñadas para la transición de testnet a mainnet.'
)

doc.add_heading('Risk Guards Automáticos', level=2)
risk_guards = [
    ('Daily Loss Kill', 'Si las pérdidas del día superan el 15% del portfolio, el bot se detiene automáticamente hasta el día siguiente.', 'Protege contra pérdidas catastróficas en un solo día.'),
    ('Total DD Kill', 'Si el drawdown total desde el inicio supera el 25%, el bot se detiene permanentemente hasta revisión manual.', 'Límite duro de pérdidas totales.'),
    ('Consecutive Losses', 'Si se registran 5 pérdidas consecutivas, el bot se pausa automáticamente.', 'Detecta cuando el modelo está fallando sistemáticamente.'),
    ('Max Concurrent Trades', 'Límite de trades abiertos simultáneamente según el tamaño del portfolio.', 'Evita sobre-exposición.'),
    ('Position Size Limits', 'Mínimo $5, máximo 10% del portfolio por trade.', 'Distribución de riesgo.'),
    ('Cooldown Period', '60 minutos entre trades del mismo par.', 'Evita overtrading.'),
]
add_styled_table(doc,
    ['Guardia', 'Descripción', 'Propósito'],
    risk_guards
)

doc.add_heading('Seguridad de API Keys', level=2)
api_security = [
    'Las API keys se almacenan en .env, NUNCA en el código fuente',
    '.env está en .gitignore para evitar commits accidentales',
    'Las keys de testnet no tienen permisos para retirar fondos',
    'Para mainnet: usar keys con permisos mínimos (solo trading, sin retiros)',
    'En testnet, el error -2015 es normal (permisos insuficientes) y el bot lo maneja gracefulmente con datos mock',
]
for a in api_security:
    doc.add_paragraph(a, style='List Bullet')

doc.add_heading('Nunca Auto-Ejecuta Si...', level=2)
no_auto = [
    'Win rate del modelo es <= 0% en datos OOS',
    'Profit factor < 1.0',
    'Menos de 15 trades cerrados para evaluar',
    'Risk guard está activado',
    'El mercado está en modo ABORT por el Gate',
]
for n in no_auto:
    doc.add_paragraph(n, style='List Bullet')

# ═══════════════════════════════════════════════════════════════════════
# 15. CÓMO EJECUTAR
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('15. Cómo Ejecutar', level=1)

doc.add_heading('Requisitos Previos', level=2)
prereqs = [
    'Python 3.9 o superior instalado',
    'Acceso a internet (para APIs de Binance, CoinGecko, alternative.me, Google News)',
    'Cuenta en Binance Testnet (opcional pero recomendada): https://testnet.binance.vision',
    'API keys de Binance configuradas en .env',
]
for p in prereqs:
    doc.add_paragraph(p, style='List Bullet')

doc.add_heading('Instalación', level=2)
install_steps = [
    ('Clonar/descargar el proyecto', 'git clone <repo> o descargar ZIP y extraer en la carpeta deseada.'),
    ('Crear virtual environment', 'python -m venv .venv'),
    ('Activar virtual environment', '.\.venv\Scripts\Activate.ps1 (Windows) o source .venv/bin/activate (Linux/Mac)'),
    ('Instalar dependencias', 'pip install -r requirements.txt'),
    ('Configurar .env', 'Crear archivo .env con: BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_MODE=testnet'),
]
for title, cmd in install_steps:
    p = doc.add_paragraph()
    run = p.add_run(f'{title}: ')
    run.bold = True
    p.add_run(cmd)

doc.add_heading('Comandos de Ejecución', level=2)
add_styled_table(doc,
    ['Comando', 'Descripción'],
    [
        ['python run_crypto_models.py full', 'Ciclo completo: resuelve predicciones anteriores + genera nuevas + compara modelos'],
        ['python run_crypto_models.py monitor', 'Monitoreo en tiempo real (cada 5 min, corre hasta Ctrl+C)'],
        ['python run_crypto_models.py validate', 'Valida que todos los pares tienen datos frescos'],
        ['python run_crypto_models.py report', 'Reporte de accuracy con win rate, expectancy, etc.'],
        ['python run_crypto_models.py pending', 'Muestra predicciones pendientes con P&L actual'],
        ['python run_crypto_models.py audit', 'Compara lógica antigua (time-based) vs nueva (dinámica)'],
    ]
)

doc.add_heading('Flujo Diario Recomendado', level=2)
daily_flow = """MAÑANA (9:00 AM):
  1. python run_crypto_models.py full
     └─ Resuelve predicciones del día anterior y genera nuevas

  2. python run_crypto_models.py monitor
     └─ Inicia monitoreo en tiempo real
     └─ Deja la terminal abierta durante el día

TARDE/NOCHE (8:00 PM):
  3. Ctrl+C para detener el monitor
  4. Opcional: python run_crypto_models.py report para ver resultados

REPETIR al día siguiente"""
p = doc.add_paragraph()
run = p.add_run(daily_flow)
run.font.size = Pt(9)
run.font.name = 'Consolas'

doc.add_heading('Migración a Mainnet', level=2)
mainnet_steps = [
    '1. Validar mínimo 2-3 semanas en testnet con win rate > 55%',
    '2. Cambiar BINANCE_MODE=mainnet en .env',
    '3. Empezar con AUTO_EXECUTE=False (solo monitoreo)',
    '4. Capital inicial pequeño: $100-$500',
    '5. Monitoreo activo diario las primeras 2 semanas',
    '6. Escalar gradualmente si win rate se mantiene',
]
for m in mainnet_steps:
    doc.add_paragraph(m, style='List Number')

# ═══════════════════════════════════════════════════════════════════════
# 16. ROADMAP
# ═══════════════════════════════════════════════════════════════════════
doc.add_page_break()
doc.add_heading('16. Roadmap y Mejoras Futuras', level=1)

doc.add_heading('Corto Plazo (Siguientes 2-4 semanas)', level=2)
short_term = [
    'Validación exhaustiva en testnet con los 20 pares entrenados',
    'Ajuste fino de thresholds del Gate basado en datos reales',
    'Implementación de trailing stop dinámico basado en ATR en tiempo real',
    'Corrección del mismatch entre pares entrenados (20) y pares predichos (147+)',
]
for s in short_term:
    doc.add_paragraph(s, style='List Bullet')

doc.add_heading('Mediano Plazo (1-3 meses)', level=2)
mid_term = [
    'Entrenamiento por tiers: DeFi, Memecoins, L2 con modelos específicos',
    'Señales on-chain: ballenas, exchange flows, NUPL (requiere APIs de pago)',
    'Sistema de alertas: Email/SMS/Telegram para wins/losses',
    'Dashboard web para monitoreo en tiempo real',
    'Operación en mainnet con capital real ($100-$500 inicial)',
]
for m in mid_term:
    doc.add_paragraph(m, style='List Bullet')

doc.add_heading('Largo Plazo (3-6 meses)', level=2)
long_term = [
    'Position correlation tracker: evitar sobreexposición a sectores correlacionados',
    'Automated rebalancing del portfolio según condiciones de mercado',
    'WebSocket en lugar de polling cada 5 minutos (reacción instantánea)',
    'Machine Learning adaptativo: aprender patrones de cierre dinámico óptimos',
    'Sistema multi-exchange (Binance + Kraken + Coinbase)',
]
for l in long_term:
    doc.add_paragraph(l, style='List Bullet')

doc.add_heading('Limitaciones Conocidas', level=2)
known_limits = [
    'TOP 20 only: el modelo solo funciona bien con los 20 pares entrenados. No generaliza a otros pares.',
    'Forward-looking: no usa backtest histórico (evita overfitting, pero requiere más datos en vivo).',
    'Testnet behavior: Binance testnet puede tener spreads/liquidez diferentes a mainnet.',
    'News delay: Google News RSS tiene 1-5 minutos de retraso vs noticias en tiempo real.',
    'Crypto 24/7: el mercado nunca cierra, puede haber trades abiertos en cualquier momento.',
    'Sin señales on-chain: APIs de Glassnode/CryptoQuant son de pago.',
    'Sin social media: Twitter API ahora requiere suscripción paga.',
]
for l in known_limits:
    doc.add_paragraph(l, style='List Bullet')

# ── Footer ──────────────────────────────────────────────────────────
doc.add_paragraph()
doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('— Fin del Documento —')
run.font.size = Pt(10)
run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
run.italic = True

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = p.add_run('Crypto Trading Bot v1.0  ·  Mayo 2026  ·  Autor: Juan (firu)')
run.font.size = Pt(9)
run.font.color.rgb = RGBColor(0xAA, 0xAA, 0xAA)

# ── Guardar ─────────────────────────────────────────────────────────
output_path = os.path.join(os.path.dirname(__file__), 'Documentacion_Crypto_Trading_Bot.docx')
doc.save(output_path)
print(f"Documento guardado en: {output_path}")
