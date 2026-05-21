"""
================================================================
SUBIR DATASETS A HUGGING FACE (uso único, opcional)
================================================================

Sube los datasets pesados de model_d_training/state/ y state/
a un dataset privado o público en Hugging Face Hub.

Por qué:
  - data_extended.db pesa 3.5 GB
  - features_extended.csv pesa 2.0 GB
  - data_2026.db pesa 901 MB
  - GitHub gratuito tiene límite de 100 MB por archivo
  - Hugging Face Datasets es gratis hasta 50 GB por repo

================================================================
PASOS PARA USAR ESTE SCRIPT (solo se corre 1 vez):
================================================================

1. Crear cuenta en https://huggingface.co (gratis)

2. Crear un access token en https://huggingface.co/settings/tokens
   - Tipo: "Write"
   - Copiar el token (empieza con hf_...)

3. Instalar dependencias:
   pip install huggingface_hub

4. Loguearse (una vez):
   huggingface-cli login
   # Pegar el token cuando lo pida

5. Editar HF_USERNAME abajo con tu usuario de Hugging Face

6. Ejecutar:
   python scripts/upload_datasets_to_hf.py

================================================================
"""
import os
import getpass
from pathlib import Path
from huggingface_hub import HfApi, create_repo, login, whoami
from huggingface_hub.utils import LocalTokenNotFoundError

# ============================================================
# CONFIGURACIÓN - EDITAR ANTES DE EJECUTAR
# ============================================================
HF_USERNAME = "jponfiru"  # <-- Cambia esto si tu user de HF es distinto
HF_DATASET_NAME = "crypto-trading-bot-data"
HF_REPO_ID = f"{HF_USERNAME}/{HF_DATASET_NAME}"
PRIVATE = False  # True si quieres el dataset privado

# Archivos a subir (rutas relativas a la raíz del proyecto)
FILES_TO_UPLOAD = [
    "model_d_training/state/data_extended.db",     # 3.5 GB
    "model_d_training/state/data_2026.db",         # 901 MB
    "model_d_training/state/features_extended.csv",# 2.0 GB
    "model_d_training/state/features_d.csv",       # 43 MB
]

# README que se publica junto al dataset en HF
DATASET_README = """---
license: mit
task_categories:
  - time-series-forecasting
  - tabular-classification
language:
  - en
tags:
  - crypto
  - trading
  - binance
  - ohlcv
  - technical-analysis
pretty_name: Crypto Trading Bot Data
size_categories:
  - 1M<n<10M
---

# Crypto Trading Bot - Datasets

Datasets de OHLCV y features generados para entrenar los modelos del proyecto
[crypto_bot](https://github.com/jponfiru/crypto_bot).

## Contenido

| Archivo | Tamaño | Descripción |
|---|---|---|
| `data_extended.db` | 3.5 GB | SQLite con 4.6M klines de los TOP 20 pares (timeframe 5min, 2024-2026) |
| `data_2026.db` | 901 MB | SQLite con klines 2026 separados |
| `features_extended.csv` | 2.0 GB | Features de eventos (11,563 ventanas) ya extraídos |
| `features_d.csv` | 43 MB | Subset compacto de features para entrenar el Modelo D |

## Cómo descargar

```python
from huggingface_hub import snapshot_download
snapshot_download(
    repo_id="jponfiru/crypto-trading-bot-data",
    repo_type="dataset",
    local_dir="model_d_training/state",
)
```

O usando el script incluido en el repo:

```bash
python scripts/download_datasets_from_hf.py
```

## Esquema de `data_extended.db`

Tabla `klines`:
- `symbol` (TEXT): par de trading, ej. BTCUSDT
- `timestamp` (INTEGER): unix ms
- `open`, `high`, `low`, `close` (REAL): precios
- `volume` (REAL): volumen del par base
- `quote_volume` (REAL): volumen en USDT
- `num_trades` (INTEGER)
- `taker_buy_base`, `taker_buy_quote` (REAL): volumen del lado comprador

## Licencia

MIT — uso libre con atribución. Datos descargados de Binance Spot Public Data.
"""


def ensure_login():
    """Verifica que haya un token de HF; si no, lo pide por consola."""
    try:
        user = whoami()
        print(f"[auth] Ya estás logueado como: {user.get('name', user)}")
        return
    except (LocalTokenNotFoundError, Exception):
        pass

    print("\n[auth] No encontré token de Hugging Face guardado.")
    print("       Crea uno en: https://huggingface.co/settings/tokens")
    print("       Asegúrate de marcar permiso 'Write'.\n")
    token = getpass.getpass("Pega tu token aquí (no se mostrará): ").strip()
    if not token:
        raise SystemExit("[auth] Cancelado: no se proporcionó token.")
    login(token=token, add_to_git_credential=False)
    user = whoami()
    print(f"[auth] OK, logueado como: {user.get('name', user)}\n")


def main():
    # 0) Login (interactivo si hace falta)
    ensure_login()

    api = HfApi()

    # 1) Crear el repo (si no existe)
    print(f"[1/3] Creando repo {HF_REPO_ID} (si no existe)...")
    try:
        create_repo(
            repo_id=HF_REPO_ID,
            repo_type="dataset",
            private=PRIVATE,
            exist_ok=True,
        )
        print("      OK")
    except Exception as e:
        print(f"      AVISO: {e}")

    # 2) Subir README del dataset
    print("[2/3] Subiendo README del dataset...")
    readme_path = Path("HF_DATASET_README.md")
    readme_path.write_text(DATASET_README, encoding="utf-8")
    api.upload_file(
        path_or_fileobj=str(readme_path),
        path_in_repo="README.md",
        repo_id=HF_REPO_ID,
        repo_type="dataset",
        commit_message="Add dataset README",
    )
    readme_path.unlink()  # borrar el temporal
    print("      OK")

    # 3) Subir cada archivo
    print(f"[3/3] Subiendo {len(FILES_TO_UPLOAD)} archivos...")
    for rel_path in FILES_TO_UPLOAD:
        local = Path(rel_path)
        if not local.exists():
            print(f"      [SKIP] no existe: {rel_path}")
            continue
        size_mb = local.stat().st_size / 1024 / 1024
        print(f"      Subiendo {rel_path} ({size_mb:.0f} MB)...")
        api.upload_file(
            path_or_fileobj=str(local),
            path_in_repo=local.name,  # solo el nombre, plano en el repo HF
            repo_id=HF_REPO_ID,
            repo_type="dataset",
            commit_message=f"Add {local.name}",
        )
        print(f"        OK")

    print("\n========================================")
    print("LISTO. Dataset disponible en:")
    print(f"  https://huggingface.co/datasets/{HF_REPO_ID}")
    print("========================================\n")


if __name__ == "__main__":
    main()
