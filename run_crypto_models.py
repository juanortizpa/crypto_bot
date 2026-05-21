"""
Script de predicciones CRYPTO — corre los 6 modelos sobre los 8 pares.
Diseñado para operaciones de 1-3 horas (scalping).

USO:
  python run_crypto_models.py            -> escanea y guarda predicciones
  python run_crypto_models.py report     -> compara los 6 modelos
  python run_crypto_models.py outcomes   -> resuelve predicciones vencidas
  python run_crypto_models.py pending    -> muestra predicciones pendientes
  python run_crypto_models.py full       -> outcomes + nuevas predicciones

  MODO REAL-TIME (NUEVO):
  python run_crypto_models.py monitor    -> monitorea cada 5 min (cierre dinámico)
  python run_crypto_models.py validate   -> verifica cobertura de datos
  python run_crypto_models.py audit      -> compara lógica antigua vs nueva

FLUJO RECOMENDADO (con monitor real-time):
  1. python run_crypto_models.py full
     → Resuelve predicciones anteriores
     → Genera nuevas predicciones
  2. python run_crypto_models.py monitor
     → Corre en terminal, monitorea cada 5 min
     → Cierra dinámicamente basado en condiciones
     → Presiona Ctrl+C para detener
  3. Luego vuelve a step 1
"""
import sys, os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(__file__))

from bot.crypto_data    import technical_score, clear_cache
from bot.crypto_gate    import run_gate
from bot.crypto_models  import MODELS, evaluate_model
from bot.predictions    import predict, check_outcomes, compare_models, pending_summary, MAX_HOURS
from bot.logger         import log
from binance_client     import CRYPTO_PAIRS, PAIR_NAMES


def _ya_predicho_reciente(sym, model_id, con):
    """
    Retorna True si ya existe una prediccion PENDING de este par+modelo
    en las ultimas MAX_HOURS horas (evita duplicados dentro de la ventana).
    """
    cutoff = (datetime.now() - timedelta(hours=MAX_HOURS)).isoformat()
    row = con.execute(
        "SELECT id FROM predictions WHERE symbol=? AND model=? AND outcome='PENDING' AND predicted_at > ?",
        (sym, model_id, cutoff)
    ).fetchone()
    return row is not None


def run_predictions():
    from bot.predictions import _conn
    clear_cache()
    log("INFO", f"=== CRYPTO SCALPING — 6 MODELOS x 8 PARES (ventana {MAX_HOURS}h) ===")

    total_guardadas  = {mid: 0 for mid in MODELS}
    total_duplicados = 0
    total_rechazados = 0
    con_check = _conn()

    for pair in CRYPTO_PAIRS:
        name = PAIR_NAMES.get(pair, pair)
        log("INFO", f"  Analizando {name} ({pair})...")
        try:
            gate = run_gate(pair)
            tech = technical_score(pair)

            for mid in MODELS:
                if _ya_predicho_reciente(pair, mid, con_check):
                    total_duplicados += 1
                    continue
                califica, stop, target = evaluate_model(mid, gate, tech)
                if califica:
                    predict(
                        pair,
                        verbose=False,
                        model=mid,
                        stop_price=stop,
                        target_price=target,
                        gate=gate,
                        tech=tech,
                    )
                    total_guardadas[mid] += 1
                    price = tech.get("price", 0)
                    stop_pct = round((1 - stop/price)*100, 1) if price else "?"
                    tgt_pct  = round((target/price - 1)*100, 1) if price else "?"
                    log("INFO", f"    [{mid}] {pair} CALIFICA — stop -{stop_pct}% / target +{tgt_pct}%")
                else:
                    total_rechazados += 1

        except Exception as e:
            log("WARN", f"  Error en {pair}: {e}")

    con_check.close()

    sep = "=" * 58
    total = sum(total_guardadas.values())
    print(f"\n  {sep}")
    print(f"  PREDICCIONES CRYPTO — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Ventana: {MAX_HOURS}h por prediccion")
    print(f"  {sep}")
    for mid, minfo in MODELS.items():
        n = total_guardadas[mid]
        icon = "+" if n > 0 else " "
        print(f"  {icon} Modelo {mid} ({minfo['name']:<20}): {n} nueva{'s' if n != 1 else ''}")
    print(f"  {sep}")
    print(f"  Total nuevas:  {total}")
    print(f"  Duplicados:    {total_duplicados} (ya predichos en ventana {MAX_HOURS}h)")
    print(f"  Rechazados:    {total_rechazados} (no califican)")
    print(f"  {sep}")
    if total > 0:
        print(f"  Corre 'python run_crypto_models.py outcomes' en {MAX_HOURS}h para resolver.\n")
    else:
        print(f"  Ningun par califico. Intenta en unas horas.\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "report":
        compare_models()
    elif cmd == "outcomes":
        check_outcomes()
        compare_models()
    elif cmd == "pending":
        pending_summary()
    elif cmd == "full":
        # Ciclo completo: resolver anteriores + generar nuevas
        print("  === PASO 1: Resolviendo predicciones anteriores ===")
        check_outcomes()
        print()
        print("  === PASO 2: Generando nuevas predicciones ===")
        run_predictions()
        print("  === PASO 3: Comparacion de modelos ===")
        compare_models()
    elif cmd == "monitor":
        # NUEVO: Monitoreo en tiempo real con cierre dinámico
        from bot.predictions_realtime import monitor_positions_realtime
        monitor_positions_realtime()
    elif cmd == "validate":
        # NUEVO: Validar cobertura de datos
        from bot.predictions_realtime import validate_data_coverage
        validate_data_coverage()
    elif cmd == "audit":
        # NUEVO: Comparar lógica antigua vs nueva
        from bot.predictions_realtime import compare_close_logic
        compare_close_logic()
    else:
        run_predictions()
