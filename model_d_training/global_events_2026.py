"""
CALENDAR DE EVENTOS GLOBALES 2026
Para marcar momentos de VOLATILIDAD ALTA en klines.

Impacto en crypto:
- FOMC: +++ volatilidad inmediata en BTC/ETH
- Jobs Report: +++ volatilidad (jobs = interés = valuación)
- Trump/Elon tweets: +++ volatilidad especial en altcoins
- SEC decisiones: +++ volatilidad en ETFs y regulation
- ETF approvals: +++ pump inicial
- Bank collapses / hacks: +++ pánico (venta)
"""

from datetime import datetime

# Eventos críticos 2026 que impactarán crypto
GLOBAL_EVENTS_2026 = [
    # ENERO 2026
    {
        "date": "2026-01-14",
        "time": "13:30",  # EST (UTC-5)
        "event": "FOMC Meeting Decision (Jan)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve interest rate decision",
        "affected_pairs": ["BTC", "ETH", "SOL", "MATIC"],
    },
    {
        "date": "2026-01-09",
        "time": "08:30",
        "event": "Jobs Report (December 2025)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },

    # FEBRERO 2026
    {
        "date": "2026-02-06",
        "time": "10:00",
        "event": "Trump Crypto Announcement",
        "impact": "CRITICAL",
        "category": "political",
        "description": "Expected Trump pro-crypto stance announcement",
        "affected_pairs": ["BTC", "DOGE", "XRP"],  # Doge + XRP bombean con Trump
    },
    {
        "date": "2026-02-13",
        "time": "13:30",
        "event": "FOMC Decision (Feb)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve meeting",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-02-10",
        "time": "08:30",
        "event": "Jobs Report (January)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },

    # MARZO 2026
    {
        "date": "2026-03-17",
        "time": "13:30",
        "event": "FOMC Decision (Mar)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve meeting",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-03-20",
        "time": "08:30",
        "event": "Jobs Report (February)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-03-15",
        "time": "10:00",
        "event": "SEC Decision on Bitcoin Spot ETF (Perpetual)",
        "impact": "CRITICAL",
        "category": "regulation",
        "description": "SEC guidance on BTC perpetual futures ETF",
        "affected_pairs": ["BTC"],
    },

    # ABRIL 2026
    {
        "date": "2026-04-15",
        "time": "13:30",
        "event": "FOMC Decision (Apr)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve meeting",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-04-03",
        "time": "08:30",
        "event": "Jobs Report (March)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-04-20",
        "time": "14:00",
        "event": "Elon Musk Tesla / X announcement",
        "impact": "HIGH",
        "category": "influencer",
        "description": "Potential Dogecoin or Bitcoin integration",
        "affected_pairs": ["DOGE", "BTC"],
    },

    # MAYO 2026
    {
        "date": "2026-05-20",
        "time": "13:30",
        "event": "FOMC Decision (May)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve meeting",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-05-08",
        "time": "08:30",
        "event": "Jobs Report (April)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-05-11",
        "time": "09:00",
        "event": "CPI Inflation Data (April)",
        "impact": "HIGH",
        "category": "macro",
        "description": "Consumer Price Index - key for Fed decisions",
        "affected_pairs": ["BTC", "ETH"],
    },

    # JUNIO 2026
    {
        "date": "2026-06-17",
        "time": "13:30",
        "event": "FOMC Decision (Jun)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve meeting",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-06-05",
        "time": "08:30",
        "event": "Jobs Report (May)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-06-10",
        "time": "09:00",
        "event": "CPI Inflation Data (May)",
        "impact": "HIGH",
        "category": "macro",
        "description": "Consumer Price Index",
        "affected_pairs": ["BTC", "ETH"],
    },

    # JULIO 2026
    {
        "date": "2026-07-10",
        "time": "08:30",
        "event": "Jobs Report (June)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-07-14",
        "time": "09:00",
        "event": "CPI Inflation Data (June)",
        "impact": "HIGH",
        "category": "macro",
        "description": "Consumer Price Index",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-07-29",
        "time": "13:30",
        "event": "FOMC Decision (Jul)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve meeting",
        "affected_pairs": ["BTC", "ETH"],
    },

    # AGOSTO 2026
    {
        "date": "2026-08-07",
        "time": "08:30",
        "event": "Jobs Report (July)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-08-12",
        "time": "09:00",
        "event": "CPI Inflation Data (July)",
        "impact": "HIGH",
        "category": "macro",
        "description": "Consumer Price Index",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-08-25",
        "time": "10:00",
        "event": "Jackson Hole Economic Symposium (Fed Chair Speech)",
        "impact": "CRITICAL",
        "category": "monetary_policy",
        "description": "Annual meeting where Fed Chair gives key speech",
        "affected_pairs": ["BTC", "ETH"],
    },

    # SEPTIEMBRE 2026
    {
        "date": "2026-09-16",
        "time": "13:30",
        "event": "FOMC Decision (Sep)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve meeting",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-09-04",
        "time": "08:30",
        "event": "Jobs Report (August)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-09-11",
        "time": "09:00",
        "event": "CPI Inflation Data (August)",
        "impact": "HIGH",
        "category": "macro",
        "description": "Consumer Price Index",
        "affected_pairs": ["BTC", "ETH"],
    },

    # OCTUBRE 2026
    {
        "date": "2026-10-02",
        "time": "08:30",
        "event": "Jobs Report (September)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-10-13",
        "time": "09:00",
        "event": "CPI Inflation Data (September)",
        "impact": "HIGH",
        "category": "macro",
        "description": "Consumer Price Index",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-10-15",
        "time": "10:00",
        "event": "Trump 2026 Midterm Campaign (Crypto Focus)",
        "impact": "HIGH",
        "category": "political",
        "description": "Expected pro-crypto messaging for midterms",
        "affected_pairs": ["BTC", "DOGE"],
    },

    # NOVIEMBRE 2026
    {
        "date": "2026-11-03",
        "time": "00:00",
        "event": "US Midterm Elections 2026",
        "impact": "CRITICAL",
        "category": "political",
        "description": "Congressional elections - crypto regulation outcomes expected",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-11-06",
        "time": "08:30",
        "event": "Jobs Report (October)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-11-12",
        "time": "09:00",
        "event": "CPI Inflation Data (October)",
        "impact": "HIGH",
        "category": "macro",
        "description": "Consumer Price Index",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-11-18",
        "time": "13:30",
        "event": "FOMC Decision (Nov)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve meeting",
        "affected_pairs": ["BTC", "ETH"],
    },

    # DICIEMBRE 2026
    {
        "date": "2026-12-04",
        "time": "08:30",
        "event": "Jobs Report (November)",
        "impact": "HIGH",
        "category": "labor",
        "description": "US Employment situation",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-12-10",
        "time": "09:00",
        "event": "CPI Inflation Data (November)",
        "impact": "HIGH",
        "category": "macro",
        "description": "Consumer Price Index",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-12-16",
        "time": "13:30",
        "event": "FOMC Decision (Dec)",
        "impact": "HIGH",
        "category": "monetary_policy",
        "description": "Federal Reserve year-end meeting",
        "affected_pairs": ["BTC", "ETH"],
    },
    {
        "date": "2026-12-31",
        "time": "23:59",
        "event": "Year End 2026",
        "impact": "MEDIUM",
        "category": "calendar",
        "description": "Year-end rebalancing, holiday volatility",
        "affected_pairs": ["BTC", "ETH"],
    },
]

# Eventos históricos que podrían repetirse en 2026
POTENTIAL_CRISIS_EVENTS = [
    {
        "date": "2026-03-15",  # Históricamente volátil
        "time": "14:00",
        "event": "Banking Crisis Rumor (Potential)",
        "impact": "CRITICAL",
        "category": "crisis",
        "description": "Could mirror 2023-2025 patterns",
        "affected_pairs": ["BTC", "ETH", "USDT"],
    },
    {
        "date": "2026-08-05",  # Verano es volátil
        "time": "10:00",
        "event": "Flash Crash Risk (Potential)",
        "impact": "HIGH",
        "category": "market",
        "description": "Summer liquidity issues",
        "affected_pairs": ["BTC", "ETH"],
    },
]

def get_events_on_date(date_str: str):
    """
    Retorna eventos que ocurren en una fecha específica.

    Args:
        date_str: Formato "2026-01-14"

    Returns:
        Lista de eventos para esa fecha
    """
    all_events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS
    return [e for e in all_events if e["date"] == date_str]

def get_events_in_range(start_date: str, end_date: str):
    """
    Retorna eventos en un rango de fechas.

    Args:
        start_date, end_date: Formato "2026-01-14"

    Returns:
        Lista de eventos ordenados por fecha
    """
    all_events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    filtered = [
        e for e in all_events
        if start <= datetime.strptime(e["date"], "%Y-%m-%d") <= end
    ]
    return sorted(filtered, key=lambda x: x["date"])

def get_high_impact_dates():
    """Retorna todas las fechas con impacto CRITICAL o HIGH"""
    all_events = GLOBAL_EVENTS_2026 + POTENTIAL_CRISIS_EVENTS
    return [
        e["date"] for e in all_events
        if e["impact"] in ["CRITICAL", "HIGH"]
    ]

if __name__ == "__main__":
    # Test
    print(f"Total eventos 2026: {len(GLOBAL_EVENTS_2026) + len(POTENTIAL_CRISIS_EVENTS)}")
    print(f"Eventos HIGH/CRITICAL: {len(get_high_impact_dates())}")
    print("\nPrimeros 5 eventos:")
    for e in GLOBAL_EVENTS_2026[:5]:
        print(f"  {e['date']} {e['event']} ({e['impact']})")
