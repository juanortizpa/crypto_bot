"""
Session Manager — controla el ciclo de vida del bot con cap maximo de 12 horas.

Restricciones:
  - Tiempo total de sesion: 12 horas (configurable via CRYPTO_SESSION_HOURS).
  - Ningun trade puede mantenerse abierto despues del fin de sesion.
  - 2 horas antes del cierre: NO se abren entradas nuevas (FREEZE).
  - 15 min antes del cierre: cierre obligatorio de todo lo que quede abierto.

Uso:
    from bot.session_manager import SessionManager
    sm = SessionManager.start(max_hours=12.0)
    while sm.should_continue():
        if sm.can_open_new_trades():
            # ejecutar logica de scan/entrada
            ...
        # ejecutar logica de monitoreo (siempre)
        ...
        sm.sleep(60)  # esperar antes del siguiente ciclo
    sm.force_close_all()   # cierra todas las posiciones abiertas

Estados:
    OPEN       -> opera normalmente, puede abrir y cerrar
    FREEZE     -> no abre entradas nuevas, solo monitorea/cierra
    SHUTDOWN   -> cierra todo al mercado y termina
"""
import os
import time
import signal
from datetime import datetime, timedelta
from typing import Optional


# Configuracion via env
DEFAULT_MAX_HOURS = float(os.environ.get("CRYPTO_SESSION_HOURS", "12.0"))
FREEZE_BEFORE_HOURS = float(os.environ.get("CRYPTO_FREEZE_HOURS", "2.0"))
FORCE_CLOSE_BEFORE_MIN = float(os.environ.get("CRYPTO_FORCE_CLOSE_MIN", "15.0"))


class SessionManager:
    """Gestiona el tiempo de vida del bot dentro del cap de 12h."""

    _instance: Optional["SessionManager"] = None

    def __init__(self, max_hours: float = DEFAULT_MAX_HOURS):
        self.start_time = datetime.now()
        self.max_hours = max_hours
        self.deadline = self.start_time + timedelta(hours=max_hours)
        self.freeze_at = self.deadline - timedelta(hours=FREEZE_BEFORE_HOURS)
        self.force_close_at = self.deadline - timedelta(minutes=FORCE_CLOSE_BEFORE_MIN)
        self._interrupted = False
        self._setup_signals()

    def _setup_signals(self):
        """Maneja Ctrl+C como shutdown limpio."""
        def handler(signum, frame):
            self._interrupted = True
        try:
            signal.signal(signal.SIGINT, handler)
            signal.signal(signal.SIGTERM, handler)
        except Exception:
            pass  # en algunos contextos (notebooks, threads) no se puede

    @classmethod
    def start(cls, max_hours: float = DEFAULT_MAX_HOURS) -> "SessionManager":
        """Inicializa la sesion global."""
        cls._instance = cls(max_hours=max_hours)
        return cls._instance

    @classmethod
    def current(cls) -> Optional["SessionManager"]:
        """Retorna la sesion activa (None si nunca se llamo start)."""
        return cls._instance

    # ── Estado de la sesion ─────────────────────────────────────────

    def now(self) -> datetime:
        return datetime.now()

    def elapsed_hours(self) -> float:
        return (self.now() - self.start_time).total_seconds() / 3600

    def remaining_hours(self) -> float:
        return max(0.0, (self.deadline - self.now()).total_seconds() / 3600)

    def remaining_until_freeze_hours(self) -> float:
        return max(0.0, (self.freeze_at - self.now()).total_seconds() / 3600)

    def state(self) -> str:
        now = self.now()
        if self._interrupted or now >= self.deadline:
            return "EXPIRED"
        if now >= self.force_close_at:
            return "FORCE_CLOSE"
        if now >= self.freeze_at:
            return "FREEZE"
        return "OPEN"

    def should_continue(self) -> bool:
        """True si el bot debe seguir corriendo el loop principal."""
        return self.state() not in ("EXPIRED",)

    def can_open_new_trades(self) -> bool:
        """True si se permiten entradas nuevas (no en FREEZE ni FORCE_CLOSE)."""
        return self.state() == "OPEN"

    def must_force_close(self) -> bool:
        """True si llego el momento de cerrar todo al mercado."""
        return self.state() in ("FORCE_CLOSE", "EXPIRED")

    # ── Validacion de duracion de trade ─────────────────────────────

    def max_trade_hours_allowed(self) -> float:
        """
        Devuelve cuantas horas como maximo puede durar un trade nuevo
        para que su timeout natural no exceda el cierre forzoso.
        Resta un buffer de 30 min para tener margen de cierre ordenado.
        """
        remaining = (self.force_close_at - self.now()).total_seconds() / 3600
        # Buffer de 30 min para asegurar cierre con tiempo
        return max(0.0, remaining - 0.5)

    def can_fit_trade(self, trade_max_hours: float) -> bool:
        """
        True si un trade con duracion max_hours cabe dentro de la sesion.
        Si esta en FREEZE o FORCE_CLOSE, siempre False.
        """
        if not self.can_open_new_trades():
            return False
        return trade_max_hours <= self.max_trade_hours_allowed()

    # ── Utilidades ──────────────────────────────────────────────────

    def sleep(self, seconds: float):
        """Sleep cancelable: si se interrumpe la sesion sale antes."""
        end = time.time() + seconds
        while time.time() < end and not self._interrupted:
            time.sleep(min(1.0, end - time.time()))

    def report(self) -> str:
        st = self.state()
        return (
            f"\n  ==================================================\n"
            f"  SESSION STATE: {st}\n"
            f"  ==================================================\n"
            f"  Inicio:        {self.start_time:%Y-%m-%d %H:%M:%S}\n"
            f"  Fin previsto:  {self.deadline:%Y-%m-%d %H:%M:%S}\n"
            f"  Transcurrido:  {self.elapsed_hours():.2f}h / {self.max_hours:.1f}h\n"
            f"  Restante:      {self.remaining_hours():.2f}h\n"
            f"  Freeze a las:  {self.freeze_at:%H:%M:%S} "
            f"(en {self.remaining_until_freeze_hours():.2f}h)\n"
            f"  Cierre forzoso:{self.force_close_at:%H:%M:%S}\n"
            f"  Max trade now: {self.max_trade_hours_allowed():.2f}h\n"
            f"  ==================================================\n"
        )

    def force_close_all(self):
        """
        Marca interrupcion. El runner debe iterar y cerrar posiciones abiertas.
        Esta funcion NO ejecuta cierres por si misma — solo cambia el estado.
        """
        self._interrupted = True


def get_session() -> Optional[SessionManager]:
    """Helper: retorna la sesion actual (puede ser None si no iniciada)."""
    return SessionManager.current()


def session_max_trade_hours(default: float = 12.0) -> float:
    """
    Helper: si hay sesion activa devuelve el max permitido por la sesion,
    si no devuelve el default. Lo usan position_sizing y el scanner.
    """
    sm = SessionManager.current()
    if sm is None:
        return default
    return min(default, sm.max_trade_hours_allowed())


def session_allows_entries(default: bool = True) -> bool:
    """Helper: si hay sesion activa, respeta su estado; si no, default."""
    sm = SessionManager.current()
    if sm is None:
        return default
    return sm.can_open_new_trades()
