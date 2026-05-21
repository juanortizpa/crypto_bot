"""
Lista TOP 20 de pares para los bots historicos (2022 y 2024).

Mix de market cap + volatilidad:
  - 10 pares estables / mega-cap (movimientos pequenos pero predecibles)
  - 10 pares volatiles / alta beta (movimientos grandes con BTC)

Esta lista es la que usan los scripts de backtest 2022/2024 para
entrenar los modelos. Se eligio mix para tener:
  * BTC/ETH como ancla (referencia del mercado)
  * altcoins L1 con tendencia clara
  * pares meme/volatiles para cazar pumps
"""

# 10 estables / mega-cap (alta liquidez, movimientos predecibles)
# NOTA: MATIC migrado a POL en Sept 2024 -> usar POLUSDT.
#       RNDR migrado a RENDER -> usar RENDERUSDT.
STABLE_10 = [
    "BTCUSDT",   # Bitcoin
    "ETHUSDT",   # Ethereum
    "BNBUSDT",   # Binance Coin
    "SOLUSDT",   # Solana
    "XRPUSDT",   # Ripple
    "ADAUSDT",   # Cardano
    "AVAXUSDT",  # Avalanche
    "DOTUSDT",   # Polkadot
    "LINKUSDT",  # Chainlink
    "POLUSDT",   # Polygon (POL, ex-MATIC; rebranded Sept-2024)
]

# 10 volatiles / alta beta (movimientos amplios, oportunidades de pump)
VOLATILE_10 = [
    "DOGEUSDT",   # Dogecoin (movido por Elon)
    "SHIBUSDT",   # Shiba Inu (alta beta meme)
    "NEARUSDT",   # NEAR (AI narrative)
    "APTUSDT",    # Aptos (L1 alta volatilidad)
    "SUIUSDT",    # Sui (L1 nuevo)
    "INJUSDT",    # Injective
    "RENDERUSDT", # Render (AI; ex-RNDR rebranded)
    "TIAUSDT",    # Celestia
    "SEIUSDT",    # Sei
    "FETUSDT",    # Fetch.ai (AI / vol alta)
]

# Lista combinada
TOP_20 = STABLE_10 + VOLATILE_10

# Aliases por categoria
TOP_20_BY_CATEGORY = {
    "stable":   STABLE_10,
    "volatile": VOLATILE_10,
    "all":      TOP_20,
}


def get_top20_with_history_since(year):
    """
    Algunos pares no existian en Binance en 2022.
    Esta funcion devuelve solo los que tenian historia desde el year dado.
    """
    if year <= 2022:
        # Pares existentes en Binance desde 2022 o antes
        return [
            "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT","ADAUSDT",
            "AVAXUSDT","DOTUSDT","LINKUSDT","MATICUSDT",
            "DOGEUSDT","SHIBUSDT","NEARUSDT","INJUSDT","RNDRUSDT","FETUSDT",
        ]
    if year <= 2024:
        return TOP_20  # todos disponibles en 2024
    return TOP_20


if __name__ == "__main__":
    print("TOP 20 estables:")
    for p in STABLE_10: print(f"  {p}")
    print("\nTOP 20 volatiles:")
    for p in VOLATILE_10: print(f"  {p}")
    print(f"\nTotal: {len(TOP_20)} pares")
    print(f"Disponibles desde 2022: {len(get_top20_with_history_since(2022))}")
    print(f"Disponibles desde 2024: {len(get_top20_with_history_since(2024))}")
