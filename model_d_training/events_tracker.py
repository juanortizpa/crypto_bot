"""
EVENTS TRACKER
Marca klines 5min que fueron afectados por eventos globales.

Lógica:
1. Evento ocurre en timestamp T
2. Marcar klines [T-30min, T+120min] como "EVENT_WINDOW"
3. Calcular volatilidad post-evento
4. Guardar en DB: event_id, timestamp, pair, impact_type

Esto permite al modelo aprender patrones de reacción a noticias.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd
from global_events_2026 import (
    GLOBAL_EVENTS_2026,
    POTENTIAL_CRISIS_EVENTS,
    get_events_in_range,
)

class EventsTracker:
    def __init__(self, db_path: str = "state/data_2026.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
        self._create_events_table()

    def _create_events_table(self):
        """Crea tabla de eventos si no existe"""
        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            event_date TEXT NOT NULL,
            event_time TEXT NOT NULL,
            event_name TEXT NOT NULL,
            impact TEXT NOT NULL,
            category TEXT NOT NULL,
            affected_pairs TEXT NOT NULL
        )
        """)

        self.cursor.execute("""
        CREATE TABLE IF NOT EXISTS kline_events (
            id INTEGER PRIMARY KEY,
            pair TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            event_id INTEGER,
            minutes_from_event INTEGER,
            in_event_window INTEGER,
            volatility_impact REAL,
            FOREIGN KEY (event_id) REFERENCES events(id)
        )
        """)
        self.conn.commit()

    def insert_events(self):
        """Inserta eventos de 2026 en la tabla"""
        all_events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS

        for event in all_events:
            # Verificar si ya existe
            self.cursor.execute(
                """SELECT id FROM events WHERE event_date = ? AND event_name = ?""",
                (event["date"], event["event_name"]),
            )
            if self.cursor.fetchone():
                continue  # Ya existe

            self.cursor.execute(
                """
            INSERT INTO events (event_date, event_time, event_name, impact, category, affected_pairs)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    event["date"],
                    event.get("time", "13:30"),
                    event["event"],
                    event["impact"],
                    event["category"],
                    ",".join(event.get("affected_pairs", [])),
                ),
            )
        self.conn.commit()
        print(f"✅ Insertados {len(all_events)} eventos")

    def mark_event_windows(self, pair: str, start_date: str, end_date: str):
        """
        Marca klines afectados por eventos en una ventana de tiempo.

        Ventana de evento:
        - 30 min ANTES: anticipación
        - 120 min DESPUÉS: reacción
        """
        # Obtener eventos en el rango
        events = get_events_in_range(start_date, end_date)

        for event in events:
            event_dt = datetime.strptime(f"{event['date']} {event.get('time', '13:30')}", "%Y-%m-%d %H:%M")

            # Marcar ventana: -30min a +120min
            window_start = event_dt - timedelta(minutes=30)
            window_end = event_dt + timedelta(minutes=120)

            # Obtener klines en la ventana
            self.cursor.execute(
                """
            SELECT id, timestamp FROM ohlcv
            WHERE pair = ? AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
            """,
                (pair, window_start.isoformat(), window_end.isoformat()),
            )

            klines = self.cursor.fetchall()

            # Actualizar klines con info de evento
            for kline_id, kline_ts in klines:
                kline_dt = datetime.fromisoformat(kline_ts)
                minutes_from_event = int((kline_dt - event_dt).total_seconds() / 60)
                in_window = 1 if window_start <= kline_dt <= window_end else 0

                self.cursor.execute(
                    """
                INSERT INTO kline_events (pair, timestamp, event_id, minutes_from_event, in_event_window)
                VALUES (?, ?, ?, ?, ?)
                """,
                    (pair, kline_ts, event["id"], minutes_from_event, in_window),
                )

            self.conn.commit()

    def calculate_event_volatility(self, pair: str, hours_after_event: int = 4):
        """
        Calcula volatilidad de klines dentro de N horas post-evento.
        """
        self.cursor.execute(
            """
        SELECT ke.event_id, ke.timestamp, o.close, o.high, o.low
        FROM kline_events ke
        JOIN ohlcv o ON ke.timestamp = o.timestamp AND ke.pair = o.pair
        WHERE ke.pair = ? AND ke.minutes_from_event > 0 AND ke.minutes_from_event < ?
        ORDER BY ke.event_id, ke.timestamp
        """,
            (pair, hours_after_event * 60),
        )

        results = self.cursor.fetchall()

        # Agrupar por evento y calcular volatilidad
        event_volatilities = {}
        for event_id, ts, close, high, low in results:
            if event_id not in event_volatilities:
                event_volatilities[event_id] = {
                    "closes": [],
                    "highs": [],
                    "lows": [],
                }

            event_volatilities[event_id]["closes"].append(close)
            event_volatilities[event_id]["highs"].append(high)
            event_volatilities[event_id]["lows"].append(low)

        # Calcular volatilidad por evento
        for event_id, data in event_volatilities.items():
            if len(data["closes"]) > 1:
                closes = pd.Series(data["closes"])
                volatility = closes.pct_change().std()

                self.cursor.execute(
                    """
                UPDATE kline_events SET volatility_impact = ?
                WHERE event_id = ? AND pair = ?
                """,
                    (volatility, event_id, pair),
                )

        self.conn.commit()
        print(f"✅ Calculada volatilidad de eventos para {pair}")

    def get_event_context(self, pair: str, timestamp: str) -> Dict:
        """
        Retorna contexto de eventos para un kline específico.

        Returns:
            {
                'in_event_window': bool,
                'event_name': str,
                'impact': str,
                'minutes_from_event': int,
                'category': str,
            }
        """
        self.cursor.execute(
            """
        SELECT e.event_name, e.impact, ke.minutes_from_event, e.category
        FROM kline_events ke
        JOIN events e ON ke.event_id = e.id
        WHERE ke.pair = ? AND ke.timestamp = ?
        """,
            (pair, timestamp),
        )

        result = self.cursor.fetchone()

        if result:
            return {
                "in_event_window": True,
                "event_name": result[0],
                "impact": result[1],
                "minutes_from_event": result[2],
                "category": result[3],
            }
        return {
            "in_event_window": False,
            "event_name": None,
            "impact": None,
            "minutes_from_event": None,
            "category": None,
        }

    def get_stats(self) -> Dict:
        """Retorna estadísticas de eventos y sus impactos"""
        self.cursor.execute("SELECT COUNT(*) FROM events")
        total_events = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM kline_events WHERE in_event_window = 1")
        total_marked_klines = self.cursor.fetchone()[0]

        self.cursor.execute(
            """
        SELECT COUNT(*) FROM kline_events
        WHERE in_event_window = 1 AND volatility_impact > 0.02
        """
        )
        high_vol_events = self.cursor.fetchone()[0]

        return {
            "total_events": total_events,
            "klines_marked": total_marked_klines,
            "high_volatility_klines": high_vol_events,
            "high_vol_percentage": f"{(high_vol_events / max(total_marked_klines, 1)) * 100:.1f}%",
        }

    def close(self):
        self.conn.close()


if __name__ == "__main__":
    # Test
    tracker = EventsTracker()
    tracker.insert_events()

    print("\nEstadísticas de eventos:")
    stats = tracker.get_stats()
    for key, val in stats.items():
        print(f"  {key}: {val}")

    tracker.close()
