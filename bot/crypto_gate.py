"""
16-Factor Precision Gate para Crypto — SCALPING con sesion 12h max.

Usa combinacion de:
  - Velas DIARIAS para contexto macro (M1, M2, S4)
  - Velas de 1 HORA para timing y entrada (T1, T2, T3, S1, S2, S3)

FACTORES:
  M1 - Tendencia BTC (diaria)
  M2 - Fear & Greed Index
  M3 - Volatilidad horaria (ATR 1h)
  M4 - Eventos macro proximos (FOMC, CPI, NFP) — NUEVO
  S1 - Momentum corto plazo (4h)
  S2 - Setup tecnico (MAs y RSI en 1h)
  S3 - Volumen 1h vs promedio
  S4 - Dominancia BTC
  T1 - Micro-tendencia (ultimas 6 velas 1h)
  T2 - Buy/Sell ratio (1h)
  T3 - Senal de entrada intrahoraria
  R1 - Risk/Reward ratio
  R2 - Exposicion (predicciones abiertas)
  R3 - Sesion 12h: queda tiempo para abrir trade — NUEVO
  N1 - NOTICIAS (PESO DOBLE)
  X1 - Flash crash/pump veto en ultimas horas — NUEVO (veto duro si RED)
  X2 - Circuit breaker: racha de perdidas — NUEVO (veto duro si RED)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.crypto_data import (
    get_bars, get_price, get_btc_dominance, get_fear_greed,
    get_btc_trend, technical_score, sma, rsi, atr,
    avg_volume, buy_sell_ratio
)
from bot.macro_events import factor_color as macro_factor_color
from bot.session_manager import SessionManager

GREEN  = "GREEN"
YELLOW = "YELLOW"
RED    = "RED"


class GateResult:
    def __init__(self, symbol):
        self.symbol   = symbol
        self.factors  = {}
        self.decision = None
        self.size_mult = 0.0

    def add(self, name, color, reason):
        self.factors[name] = {"color": color, "reason": reason}

    @property
    def green_count(self):
        return sum(1 for f in self.factors.values() if f["color"] == GREEN)

    @property
    def red_count(self):
        return sum(1 for f in self.factors.values() if f["color"] == RED)

    def evaluate(self):
        """
        Umbrales adaptados al gate de 16 factores con vetos duros.

        Vetos duros (cualquiera → ABORT independiente del score):
          - X1 RED  → flash crash o flash pump reciente
          - R3 RED  → no queda tiempo en la sesion 12h
          - M4 RED  → evento macro CRITICAL/HIGH muy cercano

        Umbrales adaptados a 16 factores (~equivalente 18/25 que pide el plan):
          - red_count >= 3      → ABORT
          - green_count >= 12   → EXECUTE_FULL
          - green_count >= 10   → EXECUTE_HALF
          - green_count >= 6    → WATCHLIST
          - resto               → ABORT
        """
        # Vetos duros
        for veto_key in ("X1", "X2", "R3", "M4"):
            f = self.factors.get(veto_key)
            if f and f["color"] == RED:
                self.decision = "ABORT"
                self.size_mult = 0.0
                self.veto_reason = f"{veto_key}: {f['reason']}"
                return self

        # N1 (Noticias) tiene peso doble: contar 2x si es GREEN o RED
        n1 = self.factors.get("N1", {})
        n1_bonus = 0
        if n1.get("color") == GREEN:
            n1_bonus = 1    # ya se conta 1 en green_count, sumar 1 mas
        elif n1.get("color") == RED:
            n1_bonus = -1   # ya se conto 1 en red_count, sumar 1 penalizacion al green

        g = self.green_count + (n1_bonus if n1_bonus > 0 else 0)
        r = self.red_count   + (1 if n1_bonus < 0 else 0)
        if r >= 3:
            self.decision  = "ABORT"
            self.size_mult = 0.0
        elif g >= 12:
            self.decision  = "EXECUTE_FULL"
            self.size_mult = 1.0
        elif g >= 10:
            self.decision  = "EXECUTE_HALF"
            self.size_mult = 0.5
        elif g >= 6:
            self.decision  = "WATCHLIST"
            self.size_mult = 0.0
        else:
            self.decision  = "ABORT"
            self.size_mult = 0.0
        return self

    def report(self):
        lines = [
            f"",
            f"  CRYPTO GATE (scalp 3h): {self.symbol}",
            f"  {'='*54}",
        ]
        labels = {
            "M1": "BTC Trend (diario)",
            "M2": "Fear & Greed",
            "M3": "Volatilidad 1h",
            "M4": "Eventos Macro 4h",
            "S1": "Momentum 4h",
            "S2": "Setup Tecnico 1h",
            "S3": "Volumen 1h",
            "S4": "BTC Dominancia",
            "T1": "Micro-trend 6h",
            "T2": "Buy/Sell 1h",
            "T3": "Senal Entrada",
            "R1": "Risk/Reward",
            "R2": "Exposicion",
            "R3": "Sesion 12h",
            "N1": "Noticias (2x)",
            "X1": "Flash crash veto",
            "X2": "Circuit breaker",
        }
        icons = {GREEN: "[G]", YELLOW: "[Y]", RED: "[R]"}
        for key, label in labels.items():
            f = self.factors.get(key, {"color": YELLOW, "reason": "no evaluado"})
            icon = icons[f["color"]]
            lines.append(f"  {key} {icon} {label:<22} {f['reason']}")
        total = len(self.factors)
        lines += [
            f"  {'='*54}",
            f"  Green: {self.green_count}/{total}  |  Red: {self.red_count}",
            f"  DECISION: {self.decision}  (size x{self.size_mult})",
            f"",
        ]
        return "\n".join(lines)


def run_gate(symbol, entry_price=None, stop_price=None, target_price=None):
    """
    Gate de 13 factores para scalping crypto (1-3 horas).
    Combina contexto diario con timing horario.
    """
    result = GateResult(symbol)
    is_btc = symbol == "BTCUSDT"

    # Obtener velas de diferentes timeframes
    bars_1h = get_bars(symbol, "1h", 50)     # 50 velas de 1h (~2 dias)
    bars_1d = get_bars(symbol, "1d", 60)     # 60 velas diarias
    tech    = technical_score(symbol)         # snapshot tecnico (diario)
    price   = tech.get("price") or (bars_1h[-1]["c"] if bars_1h else None)

    # ── LAYER 1: MACRO (contexto diario) ────────────────────────────

    # M1 — Tendencia BTC
    btc = get_btc_trend()
    btc_trend = btc.get("trend", "UNKNOWN")
    if btc_trend == "BULLISH":
        result.add("M1", GREEN, f"BTC BULLISH — sobre MA20 y MA50")
    elif btc_trend in ("NEUTRAL_BULL", "NEUTRAL"):
        result.add("M1", YELLOW, f"BTC {btc_trend} — sin tendencia clara")
    elif btc_trend == "BEARISH":
        result.add("M1", RED, f"BTC BEARISH — bajo MA50")
    else:
        result.add("M1", YELLOW, f"BTC tendencia mixta")

    # M2 — Fear & Greed Index
    fng = get_fear_greed()
    fng_val = fng["value"]
    fng_class = fng["classification"]
    if fng_val >= 50:
        result.add("M2", GREEN, f"F&G {fng_val} ({fng_class}) — optimista")
    elif fng_val >= 30:
        result.add("M2", YELLOW, f"F&G {fng_val} ({fng_class}) — neutral")
    elif fng_val >= 15:
        result.add("M2", YELLOW, f"F&G {fng_val} ({fng_class}) — miedo")
    else:
        result.add("M2", RED, f"F&G {fng_val} ({fng_class}) — panico")

    # M3 — Volatilidad HORARIA (ATR de velas 1h como % del precio)
    if len(bars_1h) >= 15 and price:
        atr_1h = atr(bars_1h, 14)
        atr_1h_pct = round(atr_1h / price * 100, 2) if atr_1h else None
        if atr_1h_pct:
            # Para velas de 1h, ATR tipico es 0.3-1.5%
            if atr_1h_pct < 1.5:
                result.add("M3", GREEN, f"ATR 1h {atr_1h_pct:.2f}% — calma, bueno para scalp")
            elif atr_1h_pct < 3.0:
                result.add("M3", YELLOW, f"ATR 1h {atr_1h_pct:.2f}% — volatil")
            else:
                result.add("M3", RED, f"ATR 1h {atr_1h_pct:.2f}% — muy volatil, peligroso")
        else:
            result.add("M3", YELLOW, "ATR 1h no calculable")
    else:
        result.add("M3", YELLOW, "Datos 1h insuficientes")

    # ── LAYER 2: SETUP (velas 1h) ──────────────────────────────────

    # S1 — Momentum corto plazo (ultimas 4 horas)
    if len(bars_1h) >= 5:
        ret_4h = (bars_1h[-1]["c"] - bars_1h[-4]["c"]) / bars_1h[-4]["c"] * 100
        if is_btc:
            if ret_4h > 0.5:
                result.add("S1", GREEN, f"BTC +{ret_4h:.2f}% en 4h — momentum alcista")
            elif ret_4h > -0.5:
                result.add("S1", YELLOW, f"BTC {ret_4h:+.2f}% en 4h — lateral")
            else:
                result.add("S1", RED, f"BTC {ret_4h:+.2f}% en 4h — cayendo")
        else:
            btc_1h = get_bars("BTCUSDT", "1h", 5)
            if len(btc_1h) >= 4:
                btc_ret_4h = (btc_1h[-1]["c"] - btc_1h[-4]["c"]) / btc_1h[-4]["c"] * 100
                rs_4h = ret_4h - btc_ret_4h
                if rs_4h > 0.3:
                    result.add("S1", GREEN, f"RS +{rs_4h:.2f}% vs BTC 4h — liderando")
                elif rs_4h > -0.3:
                    result.add("S1", YELLOW, f"RS {rs_4h:+.2f}% vs BTC 4h — inline")
                else:
                    result.add("S1", RED, f"RS {rs_4h:+.2f}% vs BTC 4h — debil")
            else:
                result.add("S1", YELLOW, f"Par {ret_4h:+.2f}% en 4h")
    else:
        result.add("S1", YELLOW, "Datos 1h insuficientes")

    # S2 — Setup tecnico en velas 1h
    if len(bars_1h) >= 21:
        ma20_1h = sma(bars_1h, 20)
        rsi_1h  = rsi(bars_1h, 14)
        price_1h = bars_1h[-1]["c"]

        if ma20_1h and rsi_1h:
            score_s2 = 0
            issues = []
            if price_1h > ma20_1h: score_s2 += 1
            else: issues.append("bajo MA20(1h)")
            if 40 <= rsi_1h <= 70: score_s2 += 1
            elif rsi_1h > 75: issues.append(f"RSI(1h) {rsi_1h} alto")
            else: issues.append(f"RSI(1h) {rsi_1h} bajo")
            # Bonus: precio subiendo vs hace 1h
            if bars_1h[-1]["c"] > bars_1h[-2]["c"]: score_s2 += 1
            else: issues.append("ultima vela roja")

            if score_s2 == 3:
                result.add("S2", GREEN, f">MA20(1h) RSI={rsi_1h} vela verde")
            elif score_s2 == 2:
                result.add("S2", YELLOW, f"Parcial: {', '.join(issues)}")
            else:
                result.add("S2", RED, f"Debil: {', '.join(issues)}")
        else:
            result.add("S2", YELLOW, "Indicadores 1h incompletos")
    else:
        result.add("S2", YELLOW, "Datos 1h insuficientes")

    # S3 — Volumen de la ultima hora vs promedio
    if len(bars_1h) >= 21:
        avg_vol_1h = avg_volume(bars_1h[:-1], 20)  # promedio de 20h previas
        last_vol   = bars_1h[-2]["v"]                # penultima (completa)
        if avg_vol_1h and avg_vol_1h > 0:
            vr = round(last_vol / avg_vol_1h, 2)
            if vr >= 1.3:
                result.add("S3", GREEN, f"Vol 1h {vr:.1f}x avg — interes alto")
            elif vr >= 0.7:
                result.add("S3", YELLOW, f"Vol 1h {vr:.1f}x avg — normal")
            else:
                result.add("S3", YELLOW, f"Vol 1h {vr:.1f}x avg — bajo")
        else:
            result.add("S3", YELLOW, "Vol promedio 1h no calculable")
    else:
        result.add("S3", YELLOW, "Datos vol 1h insuficientes")

    # S4 — Dominancia BTC
    btc_dom = get_btc_dominance()
    if btc_dom and not is_btc:
        if btc_dom < 50:
            result.add("S4", GREEN, f"BTC dom {btc_dom:.1f}% — altcoins fuertes")
        elif btc_dom < 60:
            result.add("S4", YELLOW, f"BTC dom {btc_dom:.1f}% — neutral")
        else:
            result.add("S4", RED, f"BTC dom {btc_dom:.1f}% — altcoins debiles")
    elif is_btc:
        if btc_dom and btc_dom >= 55:
            result.add("S4", GREEN, f"BTC dom {btc_dom:.1f}% — flujo hacia BTC")
        elif btc_dom:
            result.add("S4", YELLOW, f"BTC dom {btc_dom:.1f}%")
        else:
            result.add("S4", YELLOW, "Dominancia no disponible")
    else:
        result.add("S4", YELLOW, "Dominancia no disponible")

    # ── LAYER 3: TIMING (micro, velas 1h) ──────────────────────────

    # T1 — Micro-tendencia (ultimas 6 horas)
    if len(bars_1h) >= 7:
        ret_6h = (bars_1h[-1]["c"] - bars_1h[-6]["c"]) / bars_1h[-6]["c"] * 100
        # Contar velas verdes vs rojas en las ultimas 6
        green_candles = sum(1 for b in bars_1h[-6:] if b["c"] > b["o"])
        if ret_6h > 0.3 and green_candles >= 4:
            result.add("T1", GREEN, f"+{ret_6h:.2f}% 6h, {green_candles}/6 velas verdes")
        elif ret_6h > -0.3:
            result.add("T1", YELLOW, f"{ret_6h:+.2f}% 6h, {green_candles}/6 verdes — lateral")
        else:
            result.add("T1", RED, f"{ret_6h:+.2f}% 6h, solo {green_candles}/6 verdes — bajando")
    else:
        result.add("T1", YELLOW, "Datos 6h insuficientes")

    # T2 — Buy/Sell ratio en velas 1h (ultimas 6h)
    if len(bars_1h) >= 6:
        bs = buy_sell_ratio(bars_1h, 6)
        if bs and bs > 0.52:
            result.add("T2", GREEN, f"B/S 1h {bs:.3f} — compradores activos")
        elif bs and bs > 0.48:
            result.add("T2", YELLOW, f"B/S 1h {bs:.3f} — equilibrado")
        elif bs:
            result.add("T2", YELLOW, f"B/S 1h {bs:.3f} — vendedores activos")
        else:
            result.add("T2", YELLOW, "B/S 1h no disponible")
    else:
        result.add("T2", YELLOW, "Datos B/S insuficientes")

    # T3 — Senal de entrada intrahoraria
    if len(bars_1h) >= 21 and price:
        ma20_1h = sma(bars_1h, 20)
        if ma20_1h:
            pct_vs_ma20 = (price - ma20_1h) / ma20_1h * 100
            # Ultimas 2 velas: la penultima fue roja y la ultima es verde = reversal
            if len(bars_1h) >= 3:
                prev_red  = bars_1h[-2]["c"] < bars_1h[-2]["o"]
                curr_green = bars_1h[-1]["c"] > bars_1h[-1]["o"]
                reversal  = prev_red and curr_green

            if -1.5 <= pct_vs_ma20 <= 0.5:
                result.add("T3", GREEN, f"Pullback a MA20(1h) ({pct_vs_ma20:+.2f}%)")
            elif reversal:
                result.add("T3", GREEN, f"Reversal detectado (vela roja→verde)")
            elif pct_vs_ma20 > 1.5:
                result.add("T3", YELLOW, f"Sobre MA20 +{pct_vs_ma20:.2f}% — extendido")
            else:
                result.add("T3", YELLOW, f"Bajo MA20 {pct_vs_ma20:.2f}% — sin senal")
        else:
            result.add("T3", YELLOW, "MA20(1h) no calculable")
    else:
        result.add("T3", YELLOW, "Datos de entrada insuficientes")

    # ── LAYER 4: RISK ────────────────────────────────────────────────

    # R1 — Risk/Reward (para scalping: stops 1-2%, targets 2-4%)
    if entry_price and stop_price and target_price and stop_price < entry_price:
        risk   = entry_price - stop_price
        reward = target_price - entry_price
        rr     = round(reward / risk, 2) if risk > 0 else 0
        if rr >= 1.5:
            result.add("R1", GREEN, f"R/R {rr:.1f}:1")
        elif rr >= 1.0:
            result.add("R1", YELLOW, f"R/R {rr:.1f}:1 — justo")
        else:
            result.add("R1", RED, f"R/R {rr:.1f}:1 — malo")
    elif price:
        # Auto-estimate para scalping: stop -2%, target +3%
        result.add("R1", GREEN, f"R/R ~1.5:1 (stop -2%, target +3%)")
    else:
        result.add("R1", YELLOW, "Sin datos para R/R")

    # R2 — Exposicion (predicciones abiertas)
    # Limites adaptativos al tamano del portfolio:
    #   <= $1000: max 4 trades   (capital pequeno, no diversificar tanto)
    #   <= $5000: max 6 trades
    #   resto:    max 10 trades
    try:
        from bot.predictions import _conn as pred_conn
        from bot.capital_profile import get_profile
        con = pred_conn()
        n_pending = con.execute(
            "SELECT COUNT(*) FROM predictions WHERE outcome='PENDING'"
        ).fetchone()[0]
        con.close()
        portfolio = get_profile().get("balance", 0) or 500
        if portfolio <= 1000:
            soft_max, hard_max = 3, 4
        elif portfolio <= 5000:
            soft_max, hard_max = 5, 6
        else:
            soft_max, hard_max = 8, 10
        if n_pending < soft_max:
            result.add("R2", GREEN, f"{n_pending}/{hard_max} preds abiertas — OK")
        elif n_pending < hard_max:
            result.add("R2", YELLOW, f"{n_pending}/{hard_max} preds abiertas — al limite")
        else:
            result.add("R2", RED, f"{n_pending}/{hard_max} preds abiertas — demasiadas")
    except Exception:
        result.add("R2", GREEN, "Sin predicciones previas")

    # ── M4 — Eventos macro proximos (FOMC, CPI, NFP, etc.) ───────────
    try:
        m4_color, m4_reason = macro_factor_color(symbol, hours_ahead=4.0)
        result.add("M4", m4_color, m4_reason)
    except Exception as e:
        result.add("M4", YELLOW, f"calendar no disponible: {type(e).__name__}")

    # ── R3 — Tiempo restante en la sesion de 12h ─────────────────────
    try:
        sm = SessionManager.current()
        if sm is None:
            # Sin sesion activa: el gate corre standalone → no veta por tiempo
            result.add("R3", GREEN, "Sin sesion activa (modo standalone)")
        else:
            max_h = sm.max_trade_hours_allowed()
            if max_h <= 0:
                result.add("R3", RED, "Sesion en FREEZE/CLOSE — no abrir")
            elif max_h < 2.0:
                result.add("R3", RED, f"Solo {max_h:.1f}h hasta cierre forzoso")
            elif max_h < 4.0:
                result.add("R3", YELLOW, f"Margen ajustado: {max_h:.1f}h")
            else:
                result.add("R3", GREEN, f"Tiempo OK: {max_h:.1f}h disponibles")
    except Exception as e:
        result.add("R3", YELLOW, f"session check error: {type(e).__name__}")

    # ── X1 — Veto por flash crash / flash pump reciente ──────────────
    # Crash > 5% en 4h -> blackout 6h (RED, veto duro)
    # Pump  > 8% en 4h -> blackout 2h (RED, evitar comprar techo)
    if len(bars_1h) >= 5:
        # cambio en ultimas 4h (vela actual vs hace 4 velas)
        try:
            change_4h = (bars_1h[-1]["c"] - bars_1h[-4]["c"]) / bars_1h[-4]["c"] * 100
            # Crash: maximo drawdown en cualquiera de las ultimas 6 velas
            recent = bars_1h[-6:]
            max_drop = 0.0
            max_rise = 0.0
            for i in range(1, len(recent)):
                seg = (recent[i]["c"] - recent[i-1]["o"]) / recent[i-1]["o"] * 100
                if seg < max_drop: max_drop = seg
                if seg > max_rise: max_rise = seg
            # criterio cumulativo 4h
            if change_4h <= -5.0:
                result.add("X1", RED, f"Flash CRASH 4h {change_4h:+.2f}% — blackout")
            elif change_4h >= 8.0:
                result.add("X1", RED, f"Flash PUMP 4h {change_4h:+.2f}% — techo riesgoso")
            elif max_drop <= -3.5:
                result.add("X1", YELLOW, f"Vela de panico {max_drop:+.2f}% en ultimas 6h")
            elif max_rise >= 5.0:
                result.add("X1", YELLOW, f"Vela explosiva {max_rise:+.2f}% en ultimas 6h")
            else:
                result.add("X1", GREEN, f"Sin extremos: 4h {change_4h:+.2f}%")
        except Exception:
            result.add("X1", YELLOW, "Calculo flash crash no disponible")
    else:
        result.add("X1", YELLOW, "Datos 1h insuficientes para flash check")

    # ── X2 — Circuit breaker: racha de perdidas reciente ─────────────
    # Si el sistema viene perdiendo en serie (regimen hostil), NO abrir
    # entradas nuevas por unas horas. Veto duro.
    try:
        from bot.circuit_breaker import check_circuit_breaker
        blocked, cb_reason = check_circuit_breaker()
        if blocked:
            result.add("X2", RED, f"PAUSA: {cb_reason}")
        else:
            # YELLOW a proposito: no debe inflar green_count (los umbrales
            # de los modelos A-F fueron calibrados con 16 factores).
            # X2 solo actua como veto duro cuando esta RED.
            result.add("X2", YELLOW, "Sin racha de perdidas")
    except Exception as e:
        result.add("X2", YELLOW, f"breaker no disponible: {type(e).__name__}")

    # ── N1 — Sentimiento (PESO DOBLE) ─────────────────────────────────
    try:
        from bot.sentiment import get_sentiment
        sent = get_sentiment(symbol)
        overall = sent.get("overall", "NEUTRAL")
        score   = sent.get("score", 0.0)
        spike   = sent.get("spike", False)
        alerts  = sent.get("alerts", [])
        resumen = alerts[0] if alerts else f"{overall} ({score:+.3f})"

        if spike:
            if score >= 0:
                result.add("N1", GREEN,  f"[2x] SPIKE BULL: {resumen}")
            else:
                result.add("N1", RED,    f"[2x] SPIKE BEAR: {resumen}")
        elif overall == "BULLISH" and score >= 0.25:
            result.add("N1", GREEN,  f"[2x] BULLISH: {resumen}")
        elif overall == "BEARISH" and score <= -0.3:
            result.add("N1", RED,    f"[2x] BEARISH: {resumen}")
        elif overall == "BEARISH":
            result.add("N1", YELLOW, f"[2x] Mixto: {resumen}")
        else:
            result.add("N1", YELLOW, f"[2x] Neutral ({score:+.3f})")
    except Exception:
        result.add("N1", YELLOW, "Sentimiento no disponible")

    return result.evaluate()
