"""
================================================================
DESCARGAR DATASETS DESDE HUGGING FACE
================================================================

Cualquiera que clone este repo desde GitHub debe ejecutar
este script para obtener los datasets pesados (no se suben a
GitHub por límites de tamaño).

Uso:
    pip install huggingface_hub
    python scripts/download_datasets_from_hf.py

No requiere autenticación (el dataset es público).
================================================================
"""
import sys
from pathlib import Path
from huggingface_hub import snapshot_download

HF_REPO_ID = "jponfiru/crypto-trading-bot-data"

# Dónde se van a guardar los archivos descargados
TARGET_DIR = Path(__file__).resolve().parent.parent / "model_d_training" / "state"


def main():
    print("=" * 60)
    print(f" Descargando datasets desde: {HF_REPO_ID}")
    print(f" Destino: {TARGET_DIR}")
    print("=" * 60)

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    try:
        snapshot_download(
            repo_id=HF_REPO_ID,
            repo_type="dataset",
            local_dir=str(TARGET_DIR),
            local_dir_use_symlinks=False,
        )
    except Exception as e:
        print(f"\n[ERROR] No se pudo descargar el dataset: {e}")
        print("\nPosibles causas:")
        print("  1. No tienes conexión a internet")
        print("  2. El dataset aún no existe (el dueño no lo ha subido)")
        print(f"     -> Verifica: https://huggingface.co/datasets/{HF_REPO_ID}")
        print("  3. huggingface_hub no está instalado:")
        print("     pip install huggingface_hub")
        sys.exit(1)

    # Listar lo descargado
    print("\nArchivos disponibles en", TARGET_DIR)
    total_mb = 0
    for f in sorted(TARGET_DIR.iterdir()):
        if f.is_file():
            mb = f.stat().st_size / 1024 / 1024
            total_mb += mb
            print(f"   {f.name:40s} {mb:8.1f} MB")
    print(f"\nTotal descargado: {total_mb:.0f} MB ({total_mb/1024:.2f} GB)")
    print("=" * 60)
    print(" LISTO. Ahora puedes ejecutar el notebook o el bot.")
    print("=" * 60)


if __name__ == "__main__":
    main()
