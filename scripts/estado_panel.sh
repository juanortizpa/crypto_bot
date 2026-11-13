#!/usr/bin/env bash
# Guarda y restaura el estado del bot de rotacion en la rama `paper-state`.
#   scripts/estado_panel.sh restaurar          -> trae los archivos de la rama a reports/ y state/
#   scripts/estado_panel.sh guardar [mensaje]  -> publica en la rama los archivos que escribe GitHub
#
# Hay dos escritores en la rama:
#   - este workflow (simulacion, orden diaria, paneles)
#   - el ejecutor del celular (live.json y conexion.json), via la API de GitHub
# Por eso `guardar` NUNCA reescribe los archivos del celular, y reintenta si el
# celular publico algo entre medias.
set -u
DE_GITHUB="rotation_state.json rotation_trades.csv rotation_equity.csv dashboard.json ultimo_ciclo.txt orden.json dashboard_live.json"
DEL_CELULAR="live.json conexion.json"

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
      for f in $DE_GITHUB $DEL_CELULAR; do
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
    for f in $DE_GITHUB; do
      d="$(destino "$f")"
      [ -f "$d" ] && cp "$d" "$tmp/$f"
    done
    git config user.name  "rotation-bot"
    git config user.email "rotation-bot@users.noreply.github.com"
    for intento in 1 2 3 4; do
      if git fetch origin paper-state --depth 1 2>/dev/null; then
        git checkout -q -f -B paper-state FETCH_HEAD
      else
        git checkout -q -f --orphan paper-state
        git rm -rfq . || true
      fi
      for f in $DE_GITHUB; do
        if [ -f "$tmp/$f" ]; then cp "$tmp/$f" "$f" && git add "$f"
        elif [ -f "$f" ]; then git rm -q "$f"; fi
      done
      git commit -qm "${2:-estado} $(date -u +%F)" || { echo "sin cambios"; exit 0; }
      if git push -q origin paper-state; then echo "estado guardado"; exit 0; fi
      echo "la rama cambio mientras se guardaba (intento $intento); reintentando"
      sleep $((intento * 5))
    done
    echo "no se pudo guardar el estado"; exit 1
    ;;
  *)
    echo "uso: $0 restaurar | guardar [mensaje]"; exit 2 ;;
esac
