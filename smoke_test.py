"""
smoke_test.py — Verificacion rapida de los fixes y mejoras del 2026-06-10.

Corre OFFLINE en su mayoria (no genera trades). Uso:
    python smoke_test.py            # solo checks offline
    python smoke_test.py --network  # incluye checks que llaman a Binance
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

PASS, FAIL = 0, 0

def check(name, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  [OK]   {name}")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL] {name}: {type(e).__name__}: {e}")
        FAIL += 1


# ── 1. Imports de todos los modulos tocados ──────────────────────────────
def t_imports():
    import bot.predictions
    import bot.predictions_realtime
    import bot.crypto_gate
    import bot.crypto_models
    import bot.short_signal
    import bot.circuit_breaker
    import bot.meta_model
    import bot.exit_model
    import bot.runner

# ── 2. GateResult: veto duro X2 funciona ─────────────────────────────────
def t_gate_veto_x2():
    from bot.crypto_gate import GateResult, GREEN, RED
    g = GateResult("TESTUSDT")
    for i in range(12):
        g.add(f"F{i}", GREEN, "test")
    g.add("X2", RED, "PAUSA: test breaker")
    g.evaluate()
    assert g.decision == "ABORT", f"esperaba ABORT, salio {g.decision}"

# ── 3. GateResult: X2 YELLOW no infla el green_count ─────────────────────
def t_gate_x2_neutral():
    from bot.crypto_gate import GateResult, GREEN, YELLOW
    g = GateResult("TESTUSDT")
    for i in range(5):
        g.add(f"F{i}", GREEN, "test")
    g.add("X2", YELLOW, "Sin racha de perdidas")
    assert g.green_count == 5, f"X2 YELLOW no debe contar: {g.green_count}"

# ── 4. evaluate_dynamic_close usa atributos del gate (no dict) ───────────
def t_gate_attr():
    from bot.crypto_gate import GateResult, RED
    g = GateResult("TESTUSDT")
    g.add("M1", RED, "x")
    _ = g.red_count + g.green_count  # atributos, no subscripcion

# ── 5. Circuit breaker responde y falla en abierto ───────────────────────
def t_breaker():
    from bot.circuit_breaker import check_circuit_breaker
    blocked, reason = check_circuit_breaker()
    assert isinstance(blocked, bool) and isinstance(reason, str)

# ── 6. Outcome BE: contabilidad fee-aware en predictions ─────────────────
def t_fee_const():
    from bot.predictions import FEE_RT_PCT, _path_outcome
    assert 0 < FEE_RT_PCT < 1.0
    assert callable(_path_outcome)

# ── 7. ML staleness guard: pkl viejos rechazados ─────────────────────────
def t_ml_guard():
    from bot.meta_model import load_meta_model, ACCOUNTING_FIX_DATE
    from bot.exit_model import load_model
    assert ACCOUNTING_FIX_DATE == "2026-06-10"
    m = load_meta_model()   # debe ser None si el pkl es pre-fix
    e = load_model()
    if m is not None:
        assert (m.get("trained_at") or "")[:10] >= ACCOUNTING_FIX_DATE
    if e is not None:
        assert (e.get("trained_at") or "")[:10] >= ACCOUNTING_FIX_DATE

# ── 8. Monitor importa clear_cache (fix precios congelados) ──────────────
def t_monitor_cache():
    import inspect
    import bot.predictions_realtime as prt
    src = inspect.getsource(prt.monitor_positions_realtime)
    assert "clear_cache()" in src, "el monitor debe limpiar cache por ciclo"

# ── 9. short_signal estructura ───────────────────────────────────────────
def t_short_signal_offline():
    from bot.short_signal import VETO_THRESHOLD, bearish_score
    assert 1 <= VETO_THRESHOLD <= 7

# ── 10. RUTA DEL RUNNER (bot_crypto.py run) ──────────────────────────────
def t_runner_monitor_cache():
    import inspect
    import bot.runner as runner
    src = inspect.getsource(runner._monitor_open_positions)
    assert "clear_cache()" in src, "el monitor del runner debe limpiar cache"

def t_runner_fee_aware():
    import inspect
    import bot.runner as runner
    for fn in (runner._close_position, runner._close_position_row):
        src = inspect.getsource(fn)
        assert "FEE_RT_PCT" in src, f"{fn.__name__} debe ser fee-aware"

def t_trade_monitor_hard_levels():
    import inspect
    from bot import trade_monitor
    src = inspect.getsource(trade_monitor.record_snapshot)
    assert "STOP_HIT_HARD" in src and "TARGET_HIT" in src, \
        "record_snapshot debe aplicar stop/target duros sobre las reglas"

# ── Network checks (opcionales) ──────────────────────────────────────────
def t_short_signal_live():
    from bot.short_signal import bearish_score
    score, reasons = bearish_score("BTCUSDT")
    assert 0 <= score <= 7, f"score fuera de rango: {score}"
    print(f"         BTCUSDT bearish_score={score} {reasons}")

def t_path_outcome_live():
    from bot.predictions import _path_outcome
    from datetime import datetime, timedelta
    now = datetime.now()
    out, px, dt = _path_outcome("BTCUSDT", now - timedelta(hours=6),
                                100.0, 50.0, 1e9, now)
    # stop=50 (imposible tocar), target=1e9 (imposible) -> None esperado
    assert out is None


if __name__ == "__main__":
    network = "--network" in sys.argv
    print("\nSMOKE TEST — fixes 2026-06-10\n" + "=" * 46)
    check("imports de modulos modificados", t_imports)
    check("gate: veto duro X2 (circuit breaker)", t_gate_veto_x2)
    check("gate: X2 neutro no infla green_count", t_gate_x2_neutral)
    check("gate: acceso por atributos (fix monitor)", t_gate_attr)
    check("circuit breaker operativo", t_breaker)
    check("contabilidad fee-aware (FEE_RT_PCT, path)", t_fee_const)
    check("guard de modelos ML contaminados", t_ml_guard)
    check("monitor limpia cache por ciclo", t_monitor_cache)
    check("short_signal estructura", t_short_signal_offline)
    check("runner: monitor limpia cache", t_runner_monitor_cache)
    check("runner: cierres fee-aware", t_runner_fee_aware)
    check("trade_monitor: stop/target duros", t_trade_monitor_hard_levels)
    if network:
        check("short_signal en vivo (BTCUSDT)", t_short_signal_live)
        check("_path_outcome en vivo (BTCUSDT)", t_path_outcome_live)
    print("=" * 46)
    print(f"  {PASS} OK / {FAIL} FAIL\n")
    sys.exit(1 if FAIL else 0)
