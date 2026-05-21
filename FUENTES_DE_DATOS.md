# FUENTES DE DATOS DEL BOT — ¿De dónde obtiene información?

## 📊 RESUMEN EJECUTIVO

El bot entrena con **4 FUENTES DE DATOS EN TIEMPO REAL** (no usa datos históricos, es 100% forward-looking):

| Fuente | Proveedor | Uso | Actualización |
|--------|-----------|-----|---------------|
| **Velas OHLCV** | Binance API | Indicadores técnicos | Cada vela (1h, 4h, 1d) |
| **Precio actual** | Binance API | P&L, entradas/salidas | Real-time |
| **Fear & Greed Index** | alternative.me | Sentimiento macro | 1x día |
| **Noticias crypto** | Google News RSS | Sentimiento de eventos | Real-time |
| **Dominancia BTC** | CoinGecko | Contexto de mercado | 1x día |

---

## 1️⃣ DATOS TÉCNICOS (Binance API)

### Velas OHLCV

**¿Qué descarga?**
- Open, High, Low, Close, Volume
- Timeframes: **1 hora** (timing) + **1 día** (contexto macro)
- 50 velas de 1h (~2 días) + 60 velas diarias (~3 meses)
- Pares: 8 coins principales (BTC, ETH, SOL, BNB, DOGE, XRP, ADA, AVAX)

**¿Para qué?**
Calcular estos indicadores técnicos:

| Indicador | Cálculo | Uso |
|-----------|---------|-----|
| **SMA (20, 50, 200)** | Promedio móvil simple | Tendencia general |
| **EMA (12, 26)** | Promedio móvil exponencial | Tendencia rápida |
| **RSI (14)** | Fuerza relativa de cambios | Sobrecompra/sobreventa |
| **ATR (14)** | Rango verdadero promedio | Volatilidad y stops |
| **MACD** | Convergencia-divergencia | Momentum |
| **Volumen promedio (20)** | Volumen vs histórico | Confirmación |
| **Buy/Sell Ratio** | Volumen comprador vs total | Presión de compra |

---

## 2️⃣ SENTIMIENTO MACRO (Fear & Greed Index)

### ¿De dónde?
**API gratuita**: `alternative.me/fng`

### ¿Qué es?
Índice que combina:
- **Volatilidad** (30%) - medida de miedo
- **Volumen de mercado** (25%) - actividad total
- **Momentum** (25%) - dirección del mercado
- **Dominancia BTC** (10%) - si alts ganan o pierden
- **Trends en Google** (10%) - búsquedas relacionadas

**Escala: 0-100**
```
  0-24 = Extreme Fear    🔴 (oportunidad de compra)
 25-44 = Fear            🟠
 45-55 = Neutral         🟡
 56-74 = Greed           🟢
 75+ = Extreme Greed     🔴 (cuidado, sobrecalentado)
```

### Factor N1 en el Gate
```
FNG >= 50   → GREEN   (optimismo, compra)
FNG 30-50   → YELLOW  (neutral)
FNG < 30    → RED     (pánico, cuidado)
```

---

## 3️⃣ NOTICIAS (Google News RSS + Análisis de Sentimiento)

### ¿De dónde?
Google News RSS feeds públicos (gratis, sin API key)

### ¿Qué busca?
**250+ palabras clave** en 4 categorías:

#### 🟢 BULLISH (ganancias esperadas)
```
"rally", "surge", "breakout", "etf approved", "halving",
"institutional buying", "adoption", "partnership", etc.
```

#### 🔴 BEARISH (pérdidas esperadas)
```
"crash", "ban", "regulation", "hack", "exploit",
"sec investigation", "liquidation", "selloff", etc.
```

#### 👤 FIGURAS DE PODER (peso reforzado 2-3x)
| Persona | Peso | Impacto |
|---------|------|--------|
| **Trump** | 3.0x | Mayor influencia política en crypto |
| **Powell (Fed)** | 2.5x | Tasas afectan crypto |
| **Elon Musk** | 2.5x | Mueve DOGE, SHIB especialmente |
| **SEC/Gensler** | 2.0x | Regulación |
| **BlackRock/ETF** | 1.8x | Flujos institucionales |
| **China** | 1.3x | Bans, regulación |

#### ⚡ EVENTOS CRÍTICOS (boost 2x extra)
```
"ETF approval", "halving", "BlackRock filing",
"SEC lawsuit", "Hack detectado", "Depeg de stablecoin"
```

### Factor N1 en el Gate
```
Noticia bullish → GREEN (peso doble en el gate)
Noticia bearish → RED   (peso doble en el gate)
Sin noticias    → YELLOW (neutral)
```

**Importante**: Las noticias tienen **PESO DOBLE** vs acciones porque:
- Crypto es 24/7 (mercado abierto siempre)
- Un tweet de Elon puede mover DOGE 30% en minutos
- Las noticias son directamente accionables (no hay gaps overnight)

---

## 4️⃣ DOMINANCIA BTC & TENDENCIA BTC

### ¿De dónde?
CoinGecko API (gratis, público)

### ¿Qué es?
**BTC Dominance** = % del mercado crypto que es Bitcoin
```
BTC Dom alta (> 60%)    → Altcoins débiles, vender alts
BTC Dom baja (< 40%)    → "Altseason", fuerza en alts
```

### Factor M1 en el Gate
```
BTC en SMA20 y arriba   → GREEN  (tendencia alcista)
BTC en SMA20-50         → YELLOW (neutral)
BTC bajo SMA50          → RED    (tendencia bajista)
```

---

## 🔄 FLUJO DE DATOS EN TIEMPO REAL

```
CADA VEZ QUE PREDICE:

1. Binance API
   ├─ Descarga últimas 50 velas 1h + 60 diarias
   ├─ Obtiene precio actual
   └─ Calcula: SMA, RSI, ATR, MACD, Volumen

2. Fear & Greed Index
   ├─ Obtiene valor actual (0-100)
   └─ Evalúa si <= 25 (extreme fear) = oportunidad

3. Google News RSS
   ├─ Busca noticias del último 1h
   ├─ Analiza sentimiento (bullish/bearish)
   ├─ Aplica peso a figuras de poder
   └─ Suma puntos de impacto

4. CoinGecko
   ├─ Obtiene BTC dominance
   └─ Evalúa si mercado está en "altseason"

5. Database Local
   ├─ Cuántas predicciones abiertas hay (R2)
   └─ Limite de exposición total
```

---

## 📋 EXACTAMENTE QUÉ ENTRA AL GATE (13 Factores)

```
LAYER MACRO (Contexto diario):
├─ M1: BTC Trend          → SMA20/50 de BTC diario
├─ M2: Fear & Greed       → Índice 0-100 de alternative.me
├─ M3: Volatilidad 1h     → ATR en velas 1h
└─ S4: BTC Dominance      → % BTC del mercado (CoinGecko)

LAYER CORTO PLAZO (Timing 1-4h):
├─ S1: Momentum 4h        → SMA20 vs SMA50 en 4h
├─ S2: Setup Técnico 1h   → RSI, MA crossovers en 1h
├─ S3: Volumen 1h         → Vol actual vs promedio 20d
├─ T1: Micro-trend 6h     → Últimas 6 velas 1h
├─ T2: Buy/Sell Ratio     → % de volumen comprador
└─ T3: Señal Entrada      → Pullback a MA20 o breakout

LAYER RIESGO:
├─ R1: Risk/Reward        → Ratio stop/target
└─ R2: Exposición         → Límite de predicciones abiertas

LAYER SENTIMIENTO:
└─ N1: NOTICIAS (2x)      → Análisis RSS + keywords + power figures
```

---

## ❌ QUÉ NO USA

| Cosa | Por qué no |
|------|-----------|
| **Datos históricos backtest** | Forward-looking only (predicciones futuras) |
| **Machine Learning trained** | Sistema de reglas + triggers (interpretable) |
| **Análisis on-chain avanzado** | Costaría API de pago (Glassnode, CryptoQuant) |
| **Órdenes de libros (Order Book)** | Muy volátil y cambia cada ms |
| **Social media (Twitter)** | Twitter API requiere pago ahora |
| **Fundamental data** | P/E, ingresos — crypto no tiene eso |

---

## 📊 EJEMPLO: ¿Cómo entrena para BTCUSDT?

```
Predicción: "¿Compramos BTC en los próximos 3h?"

DATOS QUE RECOPILA:

1. OHLCV (Binance):
   - Últimas 50 velas 1h
   - BTC últimas 60 velas diarias
   - Precio actual: $42,350

2. INDICADORES (calculados):
   - SMA20: $42,100
   - SMA50: $41,800
   - RSI: 58 (neutral)
   - ATR: $450 (volatilidad normal)
   - Volumen: +15% vs promedio

3. SENTIMIENTO:
   - Fear & Greed: 52 (neutral)
   - BTC Dominance: 55% (altseason débil)

4. NOTICIAS (última 1h):
   - Noticia: "Powell says Fed may pause rate hikes"
   - Keyword: "rate hike pause" (bullish)
   - Impacto: +2 puntos GREEN

5. BTC TREND:
   - BTC SMA20 > SMA50 → BULLISH
   - Impacto: GREEN

RESULTADO DEL GATE:
═════════════════════════════════════════
Green:  8/13 ✓✓✓✓✓✓✓✓
Red:    1/13  (solo noticias negativas)
Yellow: 4/13

DECISIÓN: "EXECUTE_FULL" (confianza alta)
Stop:  $41,900 (-1.0%)
Target: $43,300 (+2.3%)
═════════════════════════════════════════
```

---

## 🔐 CONFIABILIDAD DE LAS FUENTES

| Fuente | Confiabilidad | Ventajas | Desventajas |
|--------|--------------|----------|------------|
| **Binance API** | ⭐⭐⭐⭐⭐ | Datos en tiempo real, oficiales | Requiere conexión internet |
| **Fear & Greed** | ⭐⭐⭐⭐ | Agregación de múltiples señales | Puede rezagarse 1-2 horas |
| **Google News RSS** | ⭐⭐⭐⭐ | Actualización rápida, público | Limitado a noticias indexadas |
| **CoinGecko API** | ⭐⭐⭐⭐ | Datos precisos, gratis | Actualización cada 1-5 min |

---

## 🎯 CONCLUSIÓN

**El modelo está entrenado con:**

1. ✅ **Datos técnicos 100% en tiempo real** (Binance API)
2. ✅ **Sentimiento macro actualizado** (Fear & Greed Index)
3. ✅ **Noticias recientes procesadas** (Google News RSS)
4. ✅ **Contexto del mercado total** (BTC Dominance)
5. ✅ **Riesgo calculado dinámicamente** (R1/R2)

**NO usa:**
- ❌ Backtests históricos (demasiado sesgo)
- ❌ Machine Learning entrenado (reglas explícitas)
- ❌ APIs de pago (acceso público solamente)

**Resultado**: Sistema **transparente, auditable, y replicable** que opera con datos públicos.

