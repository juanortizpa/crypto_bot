"""
Crypto Scanner — escanea los 8 pares principales y rankea por gate score.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bot.crypto_data import technical_score, clear_cache
from bot.crypto_gate import run_gate, GREEN, YELLOW, RED
from bot.logger import log
from binance_client import CRYPTO_PAIRS, PAIR_NAMES


def scan():
    """Escanea todos los pares y retorna los que califican."""
    clear_cache()
    log("INFO", "Starting crypto scan...")
    results = []

    for pair in CRYPTO_PAIRS:
        log("INFO", f"  Scanning {pair}...")
        try:
            gate = run_gate(pair)
            if gate.decision in ("EXECUTE_FULL", "EXECUTE_HALF", "WATCHLIST"):
                tech = technical_score(pair)
                results.append({
                    "symbol":    pair,
                    "name":      PAIR_NAMES.get(pair, pair),
                    "decision":  gate.decision,
                    "green":     gate.green_count,
                    "red":       gate.red_count,
                    "price":     tech.get("price"),
                    "rsi":       tech.get("rsi14"),
                    "vol_ratio": tech.get("vol_ratio"),
                    "change_24h": tech.get("change_24h"),
                    "gate":      gate,
                })
        except Exception as e:
            log("WARN", f"  Error scanning {pair}: {e}")

    results.sort(key=lambda x: (-x["green"], x["red"]))
    log("INFO", f"Crypto scan complete: {len(results)} candidates found")
    return results


def print_scan_report(results):
    if not results:
        print("\n  No hay setups crypto hoy.\n")
        return

    sep = "=" * 70
    print(f"\n  {sep}")
    print(f"  CRYPTO SCAN RESULTS")
    print(f"  {sep}")
    print(f"  {'#':<3} {'Par':<12} {'Gate':<7} {'Decision':<14} {'Precio':>12} {'RSI':>5} {'Vol':>6} {'24h':>7}")
    print(f"  {'-'*68}")

    for i, r in enumerate(results, 1):
        dec_short = {
            "EXECUTE_FULL": "COMPRAR",
            "EXECUTE_HALF": "HALF SIZE",
            "WATCHLIST":    "WATCH",
        }.get(r["decision"], r["decision"])
        rsi_s   = f"{r['rsi']:.0f}" if r["rsi"] else "?"
        vol_s   = f"{r['vol_ratio']:.1f}x" if r["vol_ratio"] else "?"
        price_s = f"${r['price']:,.4f}" if r["price"] else "?"
        chg_s   = f"{r['change_24h']:+.1f}%" if r["change_24h"] else "?"
        # Total dinamico = num. factores realmente evaluados en el gate
        total_factors = len(r["gate"].factors) if r.get("gate") else 16
        print(f"  {i:<3} {r['name']:<12} {r['green']}/{total_factors}  {dec_short:<14} {price_s:>12} {rsi_s:>5} {vol_s:>6} {chg_s:>7}")

    print(f"  {sep}")

    # Top pick detail
    top = results[0]
    if top["decision"] in ("EXECUTE_FULL", "EXECUTE_HALF"):
        print(top["gate"].report())
