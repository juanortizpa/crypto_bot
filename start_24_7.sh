#!/usr/bin/env bash
# start_24_7.sh — Lanzador 24/7 con watchdog (Linux/macOS).
#
# Uso:
#   ./start_24_7.sh                # dry-run (paper), 31 dias
#   ./start_24_7.sh --live         # testnet real
#   DAYS=30 ./start_24_7.sh
#
# En un portatil Linux, deshabilita la suspension antes de arrancar:
#   sudo systemctl mask sleep.target suspend.target hibernate.target
set -u
cd "$(dirname "$0")"

DAYS="${DAYS:-31}"
MODE="--dry-run"
[ "${1:-}" = "--live" ] && MODE="--live"

[ -f .venv/bin/activate ] && source .venv/bin/activate

deadline=$(( $(date +%s) + ${DAYS%.*} * 86400 ))
backoff=30

echo "=== 24/7 por $DAYS dias | modo $MODE ==="
while [ "$(date +%s)" -lt "$deadline" ]; do
    remaining_days=$(awk "BEGIN{printf \"%.2f\", ($deadline - $(date +%s)) / 86400}")
    echo "[watchdog] lanzando forever ($remaining_days dias restantes)..."
    python bot_crypto.py forever --days "$remaining_days" "$MODE"
    code=$?
    [ "$(date +%s)" -ge "$deadline" ] && break
    if [ "$code" -eq 0 ]; then
        echo "[watchdog] forever termino limpio — fin."
        break
    fi
    echo "[watchdog] proceso murio (exit $code) — relanzo en ${backoff}s"
    sleep "$backoff"
    backoff=$(( backoff * 2 )); [ "$backoff" -gt 900 ] && backoff=900
done

echo "=== Prueba terminada. Revisa reports/summary.csv y corre: python bot_crypto.py readiness ==="
