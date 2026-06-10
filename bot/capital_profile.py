"""Perfiles de capital adaptativos."""
import os, sys

PROFILES = {
    "SURVIVAL": {
        "name": "SURVIVAL", "description": "Ultra conservador",
        "min_balance": 0, "max_balance": 50,
        "position_usd": 5.0, "max_trades": 1, "max_portfolio_pct": 0.50,
        "gate_min": 9, "meta_threshold": 0.72, "min_rr_ratio": 1.5,
        "target_pct_min": 2.0, "stop_pct_max": 2.5,
        "max_tier": 2, "allowed_tiers": [1, 2], "max_hours": 8.0,
    },
    "GROWTH": {
        "name": "GROWTH", "description": "Moderado",
        "min_balance": 50, "max_balance": 200,
        "position_usd": 10.0, "max_trades": 3, "max_portfolio_pct": 0.25,
        "gate_min": 7, "meta_threshold": 0.62, "min_rr_ratio": 2.0,
        "target_pct_min": 5.0, "stop_pct_max": 4.0,
        "max_tier": 5, "allowed_tiers": [1,2,3,4,5], "max_hours": 6.0,
    },
    "STANDARD": {
        "name": "STANDARD", "description": "Normal - sin restricciones",
        "min_balance": 200, "max_balance": float("inf"),
        "position_usd": None, "max_trades": 10, "max_portfolio_pct": 0.15,
        "gate_min": 4, "meta_threshold": 0.58, "min_rr_ratio": 1.5,
        "target_pct_min": 3.0, "stop_pct_max": 5.0,
        "max_tier": 99, "allowed_tiers": list(range(1, 13)), "max_hours": 6.0,
    },
    "TEST": {
        "name": "TEST", "description": "Backtesting agresivo - gate laxo",
        "min_balance": 0, "max_balance": float("inf"),
        "position_usd": 100.0, "max_trades": 50, "max_portfolio_pct": 0.10,
        "gate_min": 3, "meta_threshold": 0.45, "min_rr_ratio": 1.2,
        "target_pct_min": 2.0, "stop_pct_max": 6.0,
        "max_tier": 99, "allowed_tiers": list(range(1, 13)), "max_hours": 12.0,
    },
}

PAIR_TIERS = {}

def _build_pair_tiers():
    global PAIR_TIERS
    if PAIR_TIERS: return
    try:
        from binance_client import CRYPTO_PAIRS
        src_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "binance_client.py")
        with open(src_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        current_tier = 1; in_pairs = False
        import re
        for line in lines:
            s = line.strip()
            if "CRYPTO_PAIRS" in s and "[" in s:
                in_pairs = True; continue
            if in_pairs and s == "]": break
            if in_pairs:
                if "Tier" in s:
                    m = re.search(r"Tier\s+(\d+)", s)
                    if m: current_tier = int(m.group(1))
                elif '"' in s and "USDT" in s:
                    m = re.search(r'"(\w+USDT)"', s)
                    if m: PAIR_TIERS[m.group(1)] = current_tier
        if not PAIR_TIERS:
            for pair in CRYPTO_PAIRS: PAIR_TIERS[pair] = 99
    except Exception: pass


def get_pair_tier(pair):
    _build_pair_tiers()
    return PAIR_TIERS.get(pair, 99)


def filter_pairs_by_profile(pairs, profile):
    _build_pair_tiers()
    max_tier = profile.get("max_tier", 99)
    return [p for p in pairs if get_pair_tier(p) <= max_tier]


_cached_profile = None

def _get_usdt_balance():
    try:
        from binance_client import get_account
        acct = get_account()
        if "error" in acct: return 0.0
        for b in acct.get("balances", []):
            if b["asset"] == "USDT":
                return float(b["free"]) + float(b["locked"])
        return 0.0
    except Exception: return 0.0


def detect_profile(balance=None):
    """TEST_MODE > CRYPTO_PROFILE > CRYPTO_PORTFOLIO > balance real."""
    global _cached_profile
    if balance is None: balance = _get_usdt_balance()

    if os.environ.get("TEST_MODE", "False").lower() == "true":
        p = dict(PROFILES["TEST"]); p["balance"]=balance; p["source"]="test_mode"
        _cached_profile = p; return p

    env_override = os.environ.get("CRYPTO_PROFILE", "").upper()
    if env_override in PROFILES:
        p = dict(PROFILES[env_override]); p["balance"]=balance; p["source"]="env_override"
        _cached_profile = p; return p

    try: sim = float(os.environ.get("CRYPTO_PORTFOLIO", 0) or 0)
    except Exception: sim = 0.0
    if sim > balance: balance = sim

    for name in ["SURVIVAL", "GROWTH", "STANDARD"]:
        prof = PROFILES[name]
        if prof["min_balance"] <= balance < prof["max_balance"]:
            p = dict(prof); p["balance"]=balance; p["source"]="auto"
            _cached_profile = p; return p

    p = dict(PROFILES["STANDARD"]); p["balance"]=balance; p["source"]="fallback"
    _cached_profile = p; return p


def get_profile(balance=None):
    global _cached_profile
    if balance is not None: return detect_profile(balance)
    if _cached_profile is not None: return _cached_profile
    return detect_profile()


def clear_profile_cache():
    global _cached_profile, PAIR_TIERS
    _cached_profile = None; PAIR_TIERS = {}


def print_profile_report(balance=None):
    profile = get_profile(balance)
    _build_pair_tiers()
    from binance_client import CRYPTO_PAIRS
    pares = filter_pairs_by_profile(CRYPTO_PAIRS, profile)
    sep = "=" * 54
    icons = {"SURVIVAL":"[!!]","GROWTH":"[>>]","STANDARD":"[OK]","TEST":"[**]"}
    icon = icons.get(profile["name"], "[??]")
    print(f"\n  {sep}")
    print(f"  PERFIL DE CAPITAL ACTIVO")
    print(f"  {sep}")
    print(f"  {icon} Modo: {profile['name']} - {profile['description']}")
    print(f"  Balance USDT: ${profile['balance']:.2f}")
    print(f"  Deteccion: {profile.get('source','?')}")
    pos = profile['position_usd']
    print(f"  Posicion: " + (f"${pos:.0f}" if pos else "dinamica"))
    print(f"  Max trades: {profile['max_trades']} | Gate min: {profile['gate_min']}/13")
    print(f"  Meta P(WIN): {profile['meta_threshold']:.0%} | R/R min: {profile['min_rr_ratio']:.1f}")
    print(f"  Target min: +{profile['target_pct_min']:.0f}% | Stop max: -{profile['stop_pct_max']:.0f}%")
    print(f"  Tiers 1-{profile['max_tier']} | Pares: {len(pares)}/{len(CRYPTO_PAIRS)}")
    print(f"  {sep}\n")
