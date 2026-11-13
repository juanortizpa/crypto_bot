#!/usr/bin/env bash
# Guarda y restaura el estado del bot de rotacion en la rama `paper-state`.
#   scripts/estado_panel.sh restaurar   -> trae los archivos de la rama a state/ y reports/
#   scripts/estado_panel.sh guardar     -> publica los archivos de state/ y reports/ en la rama
# Lo usan los workflows de GitHub Actions; el panel web lee esa rama.
set -u
ARCHIVOS="rotation_state.json rotation_trades.csv rotation_equity.csv dashboard.json ultimo_ciclo.txt \
rotation_state_live.json rotation_trades_live.csv rotation_equity_live.csv dashboard_live.json ultimo_ciclo_live.txt conexion.json"

destino() {            # donde vive cada archivo dentro del repo
  case "$1" in
    rotation_state*.json) echo "state/$1" ;;
    *) echo "reports/$1" ;;
  esac
}

case "${1:-}" in
  restaurar)
    mkdir -p state reports
    if git fetch origin paper-state --depth 1 2>/dev/null; then
      for f in $ARCHIVOS; do
        d="$(destino "$f")"
        git show "FETCH_HEAD:$f" > "$d" 2>/dev/null || rm -f "$d"
      done
      echo "estado restaurado desde paper-state"
    else
      echo "primera ejecucion: no existe la rama paper-state"
    fi
    ;;
  guardar)
    tmp="$(mktemp -d)"
    for f in $ARCHIVOS; do
      d="$(destino "$f")"
      [ -f "$d" ] && cp "$d" "$tmp/$f"
    done
    git config user.name  "rotation-bot"
    git config user.email "rotation-bot@users.noreply.github.com"
    if git fetch origin paper-state --depth 1 2>/dev/null; then
      git checkout -q -B paper-state FETCH_HEAD
    else
      git checkout -q --orphan paper-state
      git rm -rfq . || true
    fi
    for f in $ARCHIVOS; do
      [ -f "$tmp/$f" ] && cp "$tmp/$f" "$f" && git add "$f"
    done
    git commit -qm "${2:-estado} $(date -u +%F)" || echo "sin cambios"
    git push -q origin paper-state
    ;;
  *)
    echo "uso: $0 restaurar | guardar [mensaje]"; exit 2 ;;
esac
