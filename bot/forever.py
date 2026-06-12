"""
Orquestador 24/7 — corre el bot de forma continua durante semanas encadenando
sesiones del runner, con mantenimiento programado entre sesiones.

    python bot_crypto.py forever --dry-run            # paper 24/7 (default 31 dias)
    python bot_crypto.py forever --days 30 --dry-run
    python bot_crypto.py forever --live               # testnet (BINANCE_MODE=testnet)

Ciclo de cada vuelta:
  1. PRE  — preflight: conexion a Binance (espera con backoff si no hay red),
            espacio en disco, integridad de la DB, estado de guards.
            Resuelve outcomes pendientes (path-check 5m) y evalua decisiones ML.
  2. RUN  — una sesion del runner (default 8h) en modo CARRY-OVER: al terminar
            la sesion las posiciones quedan PENDING y la siguiente las retoma.
            Un crash de la sesion NO mata el orquestador: backoff y reintento.
  3. POST — outcomes + ml-eval + reporte diario (reports/daily_*.md + summary.csv).
  4. MANT — tareas programadas (persistidas en state/forever_state.json):
            - backup de DBs              cada CRYPTO_BACKUP_DAYS        (1)
            - refresco de datos          cada CRYPTO_DATA_REFRESH_DAYS  (1)
              (klines 5m + data_extended con macro DXY/SP500/VIX del ML vivo)
            - retrain meta/exit model    cada CRYPTO_MODELS_RETRAIN_DAYS (3)
              (solo si hay >= MIN_SAMPLES trades post-fix; si no, espera)
            - retrain ensemble Modelo D  cada CRYPTO_ENSEMBLE_RETRAIN_DAYS (14)
              con quality gate OOS; se pospone si hay posiciones abiertas
              (max 2 dias de gracia) para no dejar trades sin monitor.

Risk guard en modo desatendido:
  - DAILY_LOSS_*    -> auto-reset al dia calendario siguiente (es un limite diario).
  - CONSEC_LOSSES_* -> auto-reset tras 12h de cooldown (el circuit breaker X2
                       mantiene su propia pausa independiente).
  - DRAWDOWN_*      -> NUNCA se auto-resetea. El bot queda en modo solo-monitoreo
                       (cierra abiertas, reportes, heartbeat ALERT) hasta reset
                       manual: la prueba de mes se considera fallida si llega aqui.

Ctrl+C termina ordenadamente: cierra el ciclo actual, genera el reporte del dia
y deja las posiciones PENDING (se retoman al relanzar).
"""
import os
import sys
import time
import json
import shutil
import sqlite3
import traceback
from datetime import datetime, date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── Defaults del modo 24/7 (ANTES de importar runner/session_manager,
#    que leen el entorno en import-time) ──────────────────────────────────
os.environ.setdefault("CRYPTO_CARRY_OVER", "true")
os.environ.setdefault("CRYPTO_SESSION_HOURS", "8")
os.environ.setdefault("CRYPTO_FREEZE_HOURS", "0.25")

from bot.logger import log
from bot.heartbeat import beat

STATE_PATH = os.path.join(ROOT, "state", "forever_state.json")

SESSION_HOURS = float(os.environ.get("CRYPTO_SESSION_HOURS", "8"))
BACKUP_DAYS = float(os.environ.get("CRYPTO_BACKUP_DAYS", "1"))
DATA_REFRESH_DAYS = float(os.environ.get("CRYPTO_DATA_REFRESH_DAYS", "1"))
MODELS_RETRAIN_DAYS = float(os.environ.get("CRYPTO_MODELS_RETRAIN_DAYS", "3"))
ENSEMBLE_RETRAIN_DAYS = float(os.environ.get("CRYPTO_ENSEMBLE_RETRAIN_DAYS", "14"))
ENSEMBLE_GRACE_DAYS = float(os.environ.get("CRYPTO_ENSEMBLE_GRACE_DAYS", "2"))
MIN_FREE_DISK_MB = float(os.environ.get("CRYPTO_MIN_FREE_DISK_MB", "300"))
CONSEC_COOLDOWN_H = float(os.environ.get("CB_COOLDOWN_H", "12"))


# ── Estado persistente del orquestador ──────────────────────────────────

def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st: dict):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception as e:
        log("WARN", f"forever: no se pudo guardar estado: {e}")


def _due(st: dict, key: str, every_days: float) -> bool:
    last = st.get(key)
    if not last:
        return True
    try:
        return datetime.now() - datetime.fromisoformat(last) >= timedelta(days=every_days)
    except Exception:
        return True


def _mark(st: dict, key: str):
    st[key] = datetime.now().isoformat()
    _save_state(st)


# ── Preflight ────────────────────────────────────────────────────────────

def _wait_for_network():
    """Espera a que Binance responda. Backoff 30s→10min, indefinido."""
    delay = 30
    while True:
        try:
            from binance_client import test_connection
            ok, msg = test_connection()
            if ok:
                return True
            log("WARN", f"forever: Binance no responde ({msg}) — retry en {delay}s")
        except Exception as e:
            log("WARN", f"forever: error de conexion ({e}) — retry en {delay}s")
        beat("WAIT_NETWORK", retry_in_s=delay)
        time.sleep(delay)
        delay = min(delay * 2, 600)


def _check_disk() -> bool:
    try:
        free_mb = shutil.disk_usage(ROOT).free / (1024 * 1024)
        if free_mb < MIN_FREE_DISK_MB:
            log("ERROR", f"forever: solo {free_mb:.0f}MB libres "
                         f"(<{MIN_FREE_DISK_MB:.0f}MB) — limpiar disco")
            return False
        return True
    except Exception:
        return True


def _check_db() -> bool:
    db = os.path.join(ROOT, "state", "crypto_predictions.db")
    if not os.path.exists(db):
        return True  # primera corrida: el runner la crea
    try:
        con = sqlite3.connect(db)
        ok = con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        con.close()
        if not ok:
            log("ERROR", "forever: PRAGMA quick_check fallo en crypto_predictions.db "
                         "— restaurar desde state/backups/")
        return ok
    except Exception as e:
        log("ERROR", f"forever: no se pudo abrir la DB: {e}")
        return False


def _resolve_outcomes():
    """check_outcomes reconstruye con velas 5m stops/targets tocados
    durante huecos sin monitor (entre sesiones, crashes, mantenimiento)."""
    try:
        from bot.predictions import check_outcomes
        check_outcomes()
    except Exception as e:
        log("WARN", f"forever: check_outcomes fallo: {e}")


def _eval_ml():
    try:
        from bot.ml_audit import evaluate_pending
        n = evaluate_pending()
        if n:
            log("INFO", f"forever: {n} decisiones ML evaluadas")
    except Exception as e:
        log("WARN", f"forever: ml-eval fallo: {e}")


def _pending_count() -> int:
    try:
        con = sqlite3.connect(os.path.join(ROOT, "state", "crypto_predictions.db"))
        n = con.execute("SELECT COUNT(*) FROM predictions WHERE outcome='PENDING'").fetchone()[0]
        con.close()
        return n
    except Exception:
        return 0


# ── Risk guard desatendido ───────────────────────────────────────────────

def _handle_risk_guard() -> bool:
    """
    Aplica la politica de auto-recuperacion. Retorna True si se puede operar,
    False si el guard sigue activo (DRAWDOWN: requiere humano).
    """
    from bot.risk_guard import is_tripped, trip_reason, reset, _load_state as rg_state
    if not is_tripped():
        return True

    reason = trip_reason() or ""
    st = rg_state()
    trip_at = st.get("trip_at")
    try:
        trip_dt = datetime.fromisoformat(trip_at) if trip_at else None
    except Exception:
        trip_dt = None

    if reason.startswith("DAILY_LOSS"):
        if trip_dt is None or trip_dt.date() < date.today():
            if reset(force=False):
                log("INFO", f"forever: risk guard auto-reset ({reason} era de un dia anterior)")
                return True
        log("WARN", f"forever: risk guard {reason} — sin nuevas entradas hasta manana")
        return False

    if reason.startswith("CONSEC_LOSSES"):
        if trip_dt is None or datetime.now() - trip_dt >= timedelta(hours=CONSEC_COOLDOWN_H):
            if reset(force=False):
                log("INFO", f"forever: risk guard auto-reset ({reason}, "
                            f"cooldown {CONSEC_COOLDOWN_H:.0f}h cumplido)")
                return True
        log("WARN", f"forever: risk guard {reason} — en cooldown")
        return False

    # DRAWDOWN_* u otro: nunca auto-reset
    log("ERROR", f"forever: risk guard {reason} — REQUIERE RESET MANUAL "
                 f"(python bot_crypto.py risk-reset). Modo solo-monitoreo.")
    return False


def _monitor_only_cycle(seconds: float = 300):
    """Con el guard activo: solo monitorear/cerrar abiertas, sin entradas."""
    try:
        from bot.runner import _monitor_open_positions
        _monitor_open_positions(force_close_all=False)
    except Exception as e:
        log("WARN", f"forever: monitor-only fallo: {e}")
    _resolve_outcomes()
    time.sleep(seconds)


# ── Mantenimiento programado ─────────────────────────────────────────────

def _run_maintenance(st: dict):
    from bot import maintenance

    if _due(st, "last_backup", BACKUP_DAYS):
        beat("MAINT_BACKUP")
        maintenance.backup_databases()
        _mark(st, "last_backup")

    if _due(st, "last_data_refresh", DATA_REFRESH_DAYS):
        beat("MAINT_DATA")
        log("INFO", "forever: refresco incremental de datos de mercado...")
        maintenance.refresh_market_data()
        fresh = maintenance.data_freshness()
        log("INFO", f"forever: frescura de datos: {fresh}")
        _mark(st, "last_data_refresh")

    if _due(st, "last_models_retrain", MODELS_RETRAIN_DAYS):
        beat("MAINT_MODELS")
        log("INFO", "forever: chequeando retrain de meta/exit model...")
        res = maintenance.retrain_live_models()
        log("INFO", f"forever: retrain live models: {res}")
        _mark(st, "last_models_retrain")

    if _due(st, "last_ensemble_retrain", ENSEMBLE_RETRAIN_DAYS):
        pending = _pending_count()
        overdue = _due(st, "last_ensemble_retrain",
                       ENSEMBLE_RETRAIN_DAYS + ENSEMBLE_GRACE_DAYS)
        if pending > 0 and not overdue:
            log("INFO", f"forever: ensemble retrain pospuesto — {pending} posiciones "
                        f"abiertas (gracia {ENSEMBLE_GRACE_DAYS:.0f}d)")
        else:
            if pending > 0:
                log("WARN", f"forever: ensemble retrain FORZADO con {pending} abiertas "
                            f"(gracia agotada) — el path-check resolvera el hueco")
            beat("MAINT_ENSEMBLE")
            log("INFO", "forever: reentrenando ensemble Modelo D (pipeline offline)...")
            verdict = maintenance.retrain_ensemble()
            log("INFO", f"forever: ensemble retrain -> {verdict}")
            st["last_ensemble_verdict"] = verdict
            _mark(st, "last_ensemble_retrain")


# ── Reportes ─────────────────────────────────────────────────────────────

def _daily_reports(st: dict):
    """Reporte de hoy tras cada sesion; el de ayer se consolida al cambiar el dia."""
    from bot.daily_report import generate_daily_report
    today = date.today().isoformat()
    try:
        last = st.get("last_report_date")
        if last and last != today:
            generate_daily_report(last)   # version final del dia anterior
        generate_daily_report(today)
        st["last_report_date"] = today
        _save_state(st)
    except Exception as e:
        log("WARN", f"forever: reporte diario fallo: {e}")


# ── Loop principal ───────────────────────────────────────────────────────

def run_forever(days: float = None, dry_run: bool = None):
    if days is None:
        days = float(os.environ.get("CRYPTO_FOREVER_DAYS", "31"))
    if dry_run is None:
        dry_run = os.environ.get("CRYPTO_DRY_RUN", "true").lower() in ("1", "true", "yes")
    # Propagar a los modulos que leen el env directamente
    os.environ["CRYPTO_DRY_RUN"] = "true" if dry_run else "false"

    st = _load_state()
    if not st.get("started_at"):
        st["started_at"] = datetime.now().isoformat()
        # Primer arranque: NO reentrenar el dia 0. El primer ciclo de retrain
        # ocurre a los N dias configurados — los thresholds/modelos con los
        # que arranca la prueba son los que se validaron a mano.
        st["last_models_retrain"] = st["started_at"]
        st["last_ensemble_retrain"] = st["started_at"]
    st.setdefault("sessions", 0)
    st.setdefault("crashes", 0)
    _save_state(st)

    end_at = datetime.now() + timedelta(days=days)
    consec_crashes = 0

    log("INFO", "=" * 64)
    log("INFO", f"FOREVER 24/7 — hasta {end_at:%Y-%m-%d %H:%M} "
                f"({days:.0f} dias) | sesiones de {SESSION_HOURS:.0f}h | "
                f"dry_run={dry_run} | carry-over=ON")
    log("INFO", f"  data refresh cada {DATA_REFRESH_DAYS:.0f}d | "
                f"meta/exit retrain cada {MODELS_RETRAIN_DAYS:.0f}d | "
                f"ensemble retrain cada {ENSEMBLE_RETRAIN_DAYS:.0f}d")
    log("INFO", "=" * 64)

    try:
        while datetime.now() < end_at:
            # ── PRE ──────────────────────────────────────────────
            beat("PREFLIGHT", sessions=st["sessions"], crashes=st["crashes"])
            _wait_for_network()
            if not _check_disk() or not _check_db():
                log("ERROR", "forever: preflight fallo (disco/DB) — reintento en 30 min")
                beat("PREFLIGHT_FAILED")
                time.sleep(1800)
                continue

            _resolve_outcomes()
            _eval_ml()

            # Risk guard: politica desatendida
            if not _handle_risk_guard():
                from bot.risk_guard import trip_reason
                reason = trip_reason() or "?"
                beat("RISK_TRIPPED", reason=reason)
                _daily_reports(st)
                _monitor_only_cycle(300)
                continue

            # ── MANT (entre sesiones, antes de abrir la siguiente) ─
            try:
                _run_maintenance(st)
            except Exception as e:
                log("WARN", f"forever: mantenimiento fallo (no fatal): {e}")

            # ── RUN ──────────────────────────────────────────────
            hours_left = (end_at - datetime.now()).total_seconds() / 3600
            session_h = min(SESSION_HOURS, max(hours_left, 0.1))
            log("INFO", f"forever: arrancando sesion #{st['sessions'] + 1} "
                        f"({session_h:.1f}h, pendientes={_pending_count()})")
            try:
                from bot.runner import run as run_session
                run_session(max_hours=session_h, dry_run=dry_run)
                st["sessions"] += 1
                consec_crashes = 0
                _save_state(st)
            except KeyboardInterrupt:
                raise
            except Exception:
                st["crashes"] += 1
                consec_crashes += 1
                _save_state(st)
                backoff = min(60 * (2 ** (consec_crashes - 1)), 900)
                log("ERROR", f"forever: la sesion crasheo "
                             f"(#{consec_crashes} seguido) — reinicio en {backoff:.0f}s\n"
                             + traceback.format_exc())
                beat("CRASHED", consec=consec_crashes, retry_in_s=backoff)
                time.sleep(backoff)

            # ── POST ─────────────────────────────────────────────
            beat("POST_SESSION", sessions=st["sessions"])
            _resolve_outcomes()
            _eval_ml()
            _daily_reports(st)

    except KeyboardInterrupt:
        log("INFO", "forever: Ctrl+C — cierre ordenado (posiciones quedan PENDING)")

    # ── Final de la prueba ───────────────────────────────────────
    beat("FINISHED")
    _resolve_outcomes()
    _daily_reports(st)
    try:
        from bot.daily_report import readiness_report
        readiness_report()
    except Exception as e:
        log("WARN", f"forever: readiness report fallo: {e}")
    log("INFO", f"forever: fin. Sesiones={st['sessions']} crashes={st['crashes']}. "
                f"Reportes en reports/, resumen en reports/summary.csv")


if __name__ == "__main__":
    args = sys.argv[1:]
    days = None
    dry = None
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = float(args[i + 1]); i += 2
        elif args[i] == "--dry-run":
            dry = True; i += 1
        elif args[i] == "--live":
            dry = False; i += 1
        else:
            i += 1
    run_forever(days=days, dry_run=dry)
