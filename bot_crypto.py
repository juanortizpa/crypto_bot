"""
CLI del Bot de Trading Crypto.

USO:
  python bot_crypto.py run               → corre el bot por 12h (cap maximo real) / 17h (dry-run)
  python bot_crypto.py run --hours 6     → corre por N horas
  python bot_crypto.py risk              → estado del risk guard (DD, daily, etc.)
  python bot_crypto.py risk-reset        → resetea risk guard tras revisar
  python bot_crypto.py scan              → escanea pares y muestra resultados
  python bot_crypto.py gate BTCUSDT      → analisis completo de BTC
  python bot_crypto.py predict ETHUSDT   → guarda prediccion para ETH
  python bot_crypto.py news              → noticias crypto ahora
  python bot_crypto.py news DOGEUSDT     → noticias de DOGE
  python bot_crypto.py compare           → que modelo va ganando
  python bot_crypto.py pending           → predicciones pendientes
  python bot_crypto.py status            → estado de la conexion
  python bot_crypto.py fear              → Fear & Greed Index
  python bot_crypto.py events            → eventos macro proximos
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Cargar .env ANTES de importar cualquier modulo (los modulos leen
# os.environ en module-load time, ej. session_manager, risk_guard).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass  # dotenv opcional; si no esta usa env vars del shell


def main():
    if len(sys.argv) < 2:
        _help()
        return

    cmd = sys.argv[1].lower()

    if cmd == "run":
        # Loop principal: cap 12h en real, 17h en dry-run
        hours = None
        is_dry_run = False
        for i, a in enumerate(sys.argv):
            if a == "--hours" and i + 1 < len(sys.argv):
                hours = float(sys.argv[i + 1])
            elif a == "--dry-run":
                os.environ["CRYPTO_DRY_RUN"] = "true"
                is_dry_run = True
        if hours is None:
            hours = float(os.environ.get("CRYPTO_SESSION_HOURS", "12"))
        from bot.runner import run
        run(max_hours=hours)

    elif cmd == "forever":
        # Modo 24/7: encadena sesiones con mantenimiento programado.
        # Ver bot/forever.py y PLAN_24_7.md
        days = None
        dry = None
        for i, a in enumerate(sys.argv):
            if a == "--days" and i + 1 < len(sys.argv):
                days = float(sys.argv[i + 1])
            elif a == "--dry-run":
                dry = True
            elif a == "--live":
                dry = False
        from bot.forever import run_forever
        run_forever(days=days, dry_run=dry)

    elif cmd == "health":
        # Chequeo rapido de salud para vigilancia externa (o por SSH/anydesk)
        from bot.heartbeat import status as hb_status
        import shutil as _shutil
        hb = hb_status()
        fresh = " (STALE ⚠️)" if hb.get("stale") else ""
        print(f"\n  Heartbeat:   {hb.get('phase')} hace {hb.get('age_minutes')} min{fresh}")
        try:
            import sqlite3 as _sq
            con = _sq.connect(os.path.join(os.path.dirname(__file__), "state", "crypto_predictions.db"))
            pend = con.execute("SELECT COUNT(*) FROM predictions WHERE outcome='PENDING'").fetchone()[0]
            last = con.execute("SELECT MAX(outcome_date) FROM predictions "
                               "WHERE outcome IN ('WIN','LOSS','BE')").fetchone()[0]
            con.close()
            print(f"  Pendientes:  {pend}")
            print(f"  Ultimo cierre: {last}")
        except Exception as e:
            print(f"  DB:          error ({e})")
        free_gb = _shutil.disk_usage(os.path.dirname(__file__)).free / (1024**3)
        print(f"  Disco libre: {free_gb:.1f} GB")
        try:
            from bot.risk_guard import is_tripped, trip_reason
            print(f"  Risk guard:  {'TRIPPED — ' + str(trip_reason()) if is_tripped() else 'OK'}")
        except Exception:
            pass
        try:
            from bot.circuit_breaker import check_circuit_breaker
            blocked, reason = check_circuit_breaker()
            print(f"  Circ.breaker: {'BLOCKED — ' + reason if blocked else 'OK'}")
        except Exception:
            pass
        try:
            from bot.model_health import current_status
            print(f"  Drift guard: {current_status()}")
        except Exception:
            pass
        try:
            from bot.maintenance import data_freshness
            print(f"  Datos:       {data_freshness()}")
        except Exception:
            pass
        print()

    elif cmd == "maintain":
        from bot.maintenance import main as maintain_main
        maintain_main(sys.argv[2] if len(sys.argv) >= 3 else "")

    elif cmd == "daily-report":
        from bot.daily_report import generate_daily_report
        day = sys.argv[2] if len(sys.argv) >= 3 else None
        path = generate_daily_report(day)
        print(f"\n  Reporte escrito: {path}")
        print(f"  Resumen acumulado: reports/summary.csv\n")

    elif cmd == "readiness":
        from bot.daily_report import readiness_report
        readiness_report()

    elif cmd == "drift":
        # Drift guard: ¿los modelos ML siguen prediciendo o el mercado cambio?
        from bot.model_health import report as drift_report
        print(drift_report())

    elif cmd == "risk":
        from bot.risk_guard import report as risk_report
        print(risk_report())

    elif cmd == "risk-reset":
        from bot.risk_guard import reset, report
        force = "--force" in sys.argv
        ok = reset(force=force)
        print(f"  Risk guard reset: {'OK' if ok else 'BLOCKED (use --force)'}")
        print(report())

    elif cmd == "cleanup":
        # Cierra todas las predicciones PENDING al precio actual (o las marca
        # como CANCELLED si el ticker esta delistado / precio congelado).
        # Util para limpiar tras un bug o un ticker zombie.
        import sqlite3
        from datetime import datetime
        from bot.trade_monitor import DB_PATH
        from bot.crypto_data import get_price, get_bars

        only_symbol = sys.argv[2].upper() if len(sys.argv) >= 3 else None
        if only_symbol and not only_symbol.endswith("USDT"):
            only_symbol += "USDT"

        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        q = "SELECT * FROM predictions WHERE outcome='PENDING'"
        params = ()
        if only_symbol:
            q += " AND symbol=?"
            params = (only_symbol,)
        rows = con.execute(q, params).fetchall()

        if not rows:
            print(f"  No hay predicciones PENDING{'para '+only_symbol if only_symbol else ''}.")
            con.close()
            return

        print(f"\n  Vas a cerrar {len(rows)} predicciones PENDING:")
        for r in rows:
            print(f"    pred={r['id']} {r['symbol']} entry=${r['price_at_pred']:.6f}")
        confirm = input("\n  Confirmar [s/N]: ").strip().lower()
        if confirm not in ("s", "si", "y", "yes"):
            print("  Cancelado.")
            con.close()
            return

        closed = 0
        cancelled = 0
        for r in rows:
            sym = r["symbol"]
            entry = r["price_at_pred"]
            try:
                # Detectar ticker zombi
                bars = get_bars(sym, "1h", 3)
                is_stale = (bars and len(bars) >= 3
                            and len(set(b["c"] for b in bars[-3:])) == 1)
                price = get_price(sym) if not is_stale else None
                if price and not is_stale:
                    pnl_pct = (price - entry) / entry * 100
                    # Contabilidad fee-aware (igual que predictions/runner)
                    from bot.predictions import FEE_RT_PCT
                    if pnl_pct > FEE_RT_PCT:
                        outcome = "WIN"
                    elif pnl_pct < -FEE_RT_PCT:
                        outcome = "LOSS"
                    else:
                        outcome = "BE"
                    con.execute("""
                        UPDATE predictions
                        SET outcome=?, price_at_outcome=?, pnl_pct=?,
                            outcome_date=?, error_flags=?
                        WHERE id=?
                    """, (outcome, price, round(pnl_pct, 4),
                          datetime.now().isoformat(),
                          "MANUAL_CLEANUP", r["id"]))
                    closed += 1
                    print(f"    [CLOSED] pred={r['id']} {sym} pnl={pnl_pct:+.3f}%")
                else:
                    # Ticker zombi -> CANCELLED, sin afectar pnl
                    con.execute("""
                        UPDATE predictions
                        SET outcome='CANCELLED', pnl_pct=0.0,
                            outcome_date=?, error_flags=?
                        WHERE id=?
                    """, (datetime.now().isoformat(),
                          "CANCELLED_STALE_TICKER", r["id"]))
                    cancelled += 1
                    print(f"    [CANCEL] pred={r['id']} {sym} (ticker zombi)")
            except Exception as e:
                print(f"    [ERROR] pred={r['id']} {sym}: {e}")
        con.commit()
        con.close()
        print(f"\n  Limpiado: {closed} cerrado(s), {cancelled} cancelado(s)\n")

    elif cmd == "ml":
        # Prueba el ensemble ML sobre un simbolo (sin operar)
        if len(sys.argv) < 3:
            print("  Uso: python bot_crypto.py ml BTCUSDT")
            return
        sym = sys.argv[2].upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        try:
            from bot.ml_inference import predict as ml_predict
        except Exception as e:
            print(f"  ml_inference no disponible: {e}")
            return
        import json as _json
        result = ml_predict(sym)
        print(f"\n  ML decision para {sym}:")
        print(_json.dumps(result, indent=2))
        print()

    elif cmd == "ml-eval":
        from bot.ml_audit import evaluate_pending
        n = evaluate_pending()
        print(f"\n  Evaluadas: {n} decisiones\n")

    elif cmd == "ml-report":
        from bot.ml_audit import report
        report()

    elif cmd == "ml-reload":
        from bot.ml_inference import reload_models
        reload_models()
        print("\n  Cache de modelos ML limpiado. Los thresholds de *_best.json se aplicarán en la próxima predicción.\n")

    elif cmd == "ml-debug":
        # Diagnóstico detallado: features en vivo + probs por modelo
        if len(sys.argv) < 3:
            print("  Uso: python bot_crypto.py ml-debug BTCUSDT")
            return
        sym = sys.argv[2].upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        print(f"\n  ML-DEBUG: calculando features y probabilidades para {sym}...\n")
        try:
            from bot.ml_inference import (
                compute_features_live, _load_all_models, _model_predict_proba
            )
            import json as _json

            print(f"  [1/3] Calculando features en vivo (descarga ~7d de velas 1m)...")
            feats = compute_features_live(sym)
            if feats is None:
                print(f"  ERROR: no se pudo computar features para {sym}")
                print(f"         (datos insuficientes o error de red)")
                return

            # Mostrar features clave
            KEY_FEATS = [
                "rsi14_1m", "rsi14_5m", "rsi14_1h", "rsi14_4h",
                "mom_1h", "mom_4h", "mom_12h", "mom_24h",
                "drawdown_7d", "atr_pct_1h", "atr_pct_5m",
                "vol_ratio_1h", "vol_zscore_7d", "taker_buy_ratio_1h",
                "fng_value", "fng_delta_7d",
                "dxy_close", "sp500_close", "vix_close", "gold_close",
                "funding_last", "funding_avg_24h",
                "btc_trend_24h", "eth_trend_24h", "rs_vs_btc_4h",
            ]
            print(f"\n  Features clave ({sym}):")
            for f in KEY_FEATS:
                v = feats.get(f)
                warn = " ⚠️  (= 0, puede ser dato faltante)" if v == 0 and f in (
                    "dxy_close", "sp500_close", "vix_close", "gold_close",
                    "fng_value", "funding_last") else ""
                print(f"    {f:<28} {v!s:>12}{warn}")

            print(f"\n  [2/3] Cargando modelos ML...")
            models = _load_all_models()
            loaded = {k: v for k, v in models.items() if v is not None}
            if not loaded:
                print(f"  ERROR: No se cargó ningún modelo. Verifica model_d_training/results/")
                return

            print(f"\n  [3/3] Probabilidades por modelo:")
            print(f"  {'Modelo':<8} {'Prob':>8} {'Threshold':>11} {'GO?':>6} {'Margen':>8}")
            print(f"  {'-'*48}")
            votes = 0
            for name, info in loaded.items():
                prob = _model_predict_proba(info, feats)
                if prob is None:
                    print(f"  {name:<8} {'ERROR':>8}")
                    continue
                thr = info["threshold"]
                go = prob >= thr
                margin = prob - thr
                flag = "✓ GO" if go else "✗ NO"
                margen_s = f"{margin:+.4f}"
                if go:
                    votes += 1
                print(f"  {name:<8} {prob:>8.4f} {thr:>11.4f} {flag:>6} {margen_s:>8}")

            total = len(loaded)
            if votes == total:
                decision = "FULL ✅"
            elif votes >= (total // 2) + 1:
                decision = "HALF ⚡"
            elif votes >= 1:
                decision = "WATCH 👁"
            else:
                decision = "ABORT ❌"
            print(f"\n  DECISION ENSEMBLE: {decision}  ({votes}/{total} modelos aprobaron)\n")

            # Consejo
            if votes == 0:
                print(f"  DIAGNÓSTICO: Ningún modelo supera su threshold.")
                print(f"    → Posible causa: features macro (DXY/SP500/VIX) = 0")
                print(f"       (verifica que model_d_training/state/data_extended.db tiene data reciente)")
                print(f"    → O: condiciones actuales fuera del rango de entrenamiento")
                print(f"       (el ML se entrenó con RSI≤55 y drawdown≤-2%)")
                rsi_val = feats.get("rsi14_1h", "?")
                dd_val  = feats.get("drawdown_7d", "?")
                print(f"    → RSI 1h actual: {rsi_val}  (entrenamiento: ≤55)")
                print(f"    → Drawdown 7d: {dd_val}%  (entrenamiento: ≤-2%)")
            print()

        except Exception as e:
            import traceback
            print(f"  Error en ml-debug: {e}")
            print(traceback.format_exc())

    elif cmd == "llm":
        # Análisis LLM standalone para cualquier par
        sym_arg = sys.argv[2].upper() if len(sys.argv) >= 3 else "BTC"
        sym_clean = sym_arg.replace("USDT", "")
        sym_full  = sym_clean + "USDT"
        print(f"\n  Consultando Claude para análisis de {sym_clean}...\n")
        from bot.llm_analyst import analyze_news
        from bot.crypto_news import get_news_signal
        signal = get_news_signal(sym_full)
        # Extraer todos los titulares del dict de detalles (son strings)
        headlines = []
        for v in signal.get("details", {}).values():
            headlines.extend(v.get("headlines", []))
        result = analyze_news(headlines, sym_clean)
        emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(result["sentiment"], "⚪")
        print(f"  ══════════════════════════════════════════════════")
        print(f"  🤖  Claude LLM — Análisis de sentimiento")
        print(f"  ══════════════════════════════════════════════════")
        print(f"  Par:          {sym_clean}/USDT")
        print(f"  Sentimiento:  {emoji}  {result['sentiment']}")
        print(f"  Score:        {result['score']:+.2f}  (rango -1.0 a +1.0)")
        print(f"  Confianza:    {result['confidence']:.0%}")
        if result.get("key_signals"):
            print(f"  Señales clave:")
            for sig in result["key_signals"]:
                print(f"    • {sig}")
        print(f"  Razonamiento: {result['reasoning']}")
        print(f"  Modelo LLM:   claude-haiku-4-5 (Anthropic)")
        print(f"  ══════════════════════════════════════════════════\n")

    elif cmd == "events":
        from bot.macro_events import upcoming_event, get_active_regime_modifier
        print(f"\n  Regimen macro actual: {get_active_regime_modifier()}\n")
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "XRPUSDT"]:
            ev = upcoming_event(sym, hours_ahead=72)
            if ev:
                print(f"  {sym}: {ev['event']} en {ev['hours_until']:.1f}h ({ev['impact']})")
            else:
                print(f"  {sym}: sin eventos en proximas 72h")
        print()

    elif cmd == "scan":
        from bot.crypto_scanner import scan, print_scan_report
        results = scan()
        print_scan_report(results)

    elif cmd == "gate":
        if len(sys.argv) < 3:
            print("  Uso: python bot_crypto.py gate BTCUSDT")
            return
        symbol = sys.argv[2].upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        from bot.crypto_gate import run_gate
        gate = run_gate(symbol)
        print(gate.report())

    elif cmd == "predict":
        if len(sys.argv) < 3:
            print("  Uso: python bot_crypto.py predict ETHUSDT")
            return
        symbol = sys.argv[2].upper()
        if not symbol.endswith("USDT"):
            symbol += "USDT"
        from bot.predictions import predict
        predict(symbol)

    elif cmd == "news":
        symbol = None
        if len(sys.argv) >= 3:
            symbol = sys.argv[2].upper()
            if not symbol.endswith("USDT"):
                symbol += "USDT"
        from bot.crypto_news import print_news_report, get_news_signal
        print_news_report(symbol)

        # Análisis LLM de sentimiento con Claude
        sym_clean = (symbol or "CRYPTO").replace("USDT", "")
        print(f"\n  ══════════════════════════════════════════════════")
        print(f"  🤖  ANÁLISIS LLM (Claude) — Sentimiento {sym_clean}")
        print(f"  ══════════════════════════════════════════════════")
        try:
            from bot.llm_analyst import analyze_news
            signal = get_news_signal(symbol or "BTCUSDT")
            headlines = []
            for v in signal.get("details", {}).values():
                headlines.extend(v.get("headlines", []))
            llm = analyze_news(headlines, sym_clean)
            emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡"}.get(llm["sentiment"], "⚪")
            print(f"  Sentimiento:  {emoji}  {llm['sentiment']}")
            print(f"  Score:        {llm['score']:+.2f}  (confianza: {llm['confidence']:.0%})")
            if llm.get("key_signals"):
                print(f"  Señales clave:")
                for sig in llm["key_signals"]:
                    print(f"    • {sig}")
            print(f"  Análisis:     {llm['reasoning']}")
            print(f"  Fuente:       Claude claude-haiku-4-5 (Anthropic API)")
        except Exception as e:
            print(f"  (LLM no disponible: {e})")
        print(f"  ══════════════════════════════════════════════════\n")

    elif cmd == "compare":
        from bot.predictions import compare_models
        compare_models()

    elif cmd == "pending":
        from bot.predictions import pending_summary
        pending_summary()

    elif cmd == "report":
        from bot.predictions import accuracy_report
        accuracy_report()

    elif cmd == "outcomes":
        from bot.predictions import check_outcomes, compare_models
        print("  Resolviendo predicciones pendientes...")
        check_outcomes()
        print("  Listo.\n")
        compare_models()

    elif cmd == "status":
        from binance_client import test_connection
        ok, msg = test_connection()
        print(f"\n  {'[OK]' if ok else '[ERROR]'} {msg}\n")

    elif cmd == "fear":
        from bot.crypto_data import get_fear_greed
        fng = get_fear_greed()
        val = fng["value"]
        cls = fng["classification"]
        bar = "#" * (val // 2)
        print(f"\n  Fear & Greed Index: {val}/100 ({cls})")
        print(f"  [{bar:<50}]")
        if val < 20:
            print(f"  → PANICO EXTREMO — Modelo D (Dip Buyer) activo")
        elif val < 35:
            print(f"  → Miedo — oportunidad potencial")
        elif val < 55:
            print(f"  → Neutral")
        elif val < 75:
            print(f"  → Codicia — cuidado")
        else:
            print(f"  → CODICIA EXTREMA — considerar tomar ganancias")
        print()

    elif cmd in ("help", "-h", "--help"):
        _help()

    else:
        print(f"  Comando '{cmd}' no reconocido.")
        _help()




def _help():
    print("""
  ============================================================
              CRYPTO TRADING BOT -- CLI
  ============================================================
   run [--hours N] [--dry-run]   Loop principal (max 12h real / 17h dry-run)
   forever [--days N] [--dry-run|--live]
                                 Modo 24/7: sesiones encadenadas + mantenimiento
                                 automatico (datos, retrains, reportes). Ver PLAN_24_7.md
   health                        Salud del bot (heartbeat, pendientes, disco, guards)
   maintain <tarea>              Mantenimiento manual: backup|data|models|ensemble
   daily-report [YYYY-MM-DD]     Genera reporte diario en reports/
   readiness                     Veredicto: criterios para pasar a mainnet
   risk                          Estado del risk guard
   risk-reset [--force]          Resetea risk guard
   drift                         Drift guard: ¿el ML sigue prediciendo o cambio el mercado?
   events                        Eventos macro proximos
   llm <PAR>                     Analisis LLM (Claude) para un par
   ml <PAR>                      Inferencia ML standalone para un par
   ml-debug <PAR>                Diagnostico ML: features + probabilidades en vivo
   ml-eval                       Evalua retrospectivamente decisiones ML pasadas
   ml-report                     Reporte de calidad de decisiones ML
   ml-reload                     Recarga thresholds desde *_best.json sin reiniciar
   cleanup [PAR]                 Cierra todas las preds PENDING (o solo PAR)
   scan                          Escanea pares, rankea por gate
   gate <PAR>                    Gate de 16 factores para un par
   predict <PAR>                 Guarda prediccion (sin comprar)
   news [PAR]                    Noticias + analisis LLM de sentimiento
   fear                          Fear & Greed Index actual
   compare                       Tabla comparativa de 4 modelos
   pending                       Predicciones pendientes
   report                        Reporte de precision completo
   outcomes                      Resuelve predicciones + compara
   status                        Test de conexion a Binance
  ============================================================
   Sesion: cap 12h (real) / 17h (dry-run). Freeze 2h antes del fin.
   Cierre forzoso 15 min antes del fin (no quedan trades abiertos).
   Modelos: A=BTC Follower  B=Altcoin Season
            C=News Spike    D=Dip Buyer
  ============================================================
    """)


if __name__ == "__main__":
    main()
