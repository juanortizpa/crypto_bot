"""
CLI del Bot de Trading Crypto.

USO:
  python bot_crypto.py run               → corre el bot por 12h (cap maximo)
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
        # Loop principal con cap de 12h
        hours = None
        for i, a in enumerate(sys.argv):
            if a == "--hours" and i + 1 < len(sys.argv):
                hours = float(sys.argv[i + 1])
            elif a == "--dry-run":
                os.environ["CRYPTO_DRY_RUN"] = "true"
        from bot.runner import run
        run(max_hours=hours)

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
                    outcome = "WIN" if pnl_pct > 0 else "LOSS"
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
        from bot.crypto_news import print_news_report
        print_news_report(symbol)

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
              CRYPTO TRADING BOT — CLI
  ============================================================
   run [--hours N] [--dry-run]   Loop principal (max 12h)
   risk                          Estado del risk guard
   risk-reset [--force]          Resetea risk guard
   events                        Eventos macro proximos
   ml <PAR>                      Inferencia ML standalone para un par
   ml-eval                       Evalua retrospectivamente decisiones ML pasadas
   ml-report                     Reporte de calidad de decisiones ML
   cleanup [PAR]                 Cierra todas las preds PENDING (o solo PAR)
   scan                          Escanea pares, rankea por gate
   gate <PAR>                    Gate de 16 factores para un par
   predict <PAR>                 Guarda prediccion (sin comprar)
   news [PAR]                    Sentimiento de noticias crypto
   fear                          Fear & Greed Index actual
   compare                       Tabla comparativa de 4 modelos
   pending                       Predicciones pendientes
   report                        Reporte de precision completo
   outcomes                      Resuelve predicciones + compara
   status                        Test de conexion a Binance
  ============================================================
   Sesion: cap maximo 12h. Freeze 2h antes del fin.
   Cierre forzoso 15 min antes del fin (no quedan trades abiertos).
   Modelos: A=BTC Follower  B=Altcoin Season
            C=News Spike    D=Dip Buyer
  ============================================================
    """)


if __name__ == "__main__":
    main()
