#!/data/data/com.termux/files/usr/bin/bash
# Instalador del ejecutor del bot en Android (Termux).
#   curl -sL https://raw.githubusercontent.com/juanortizpa/crypto_bot/main/ejecutor/instalar.sh | bash
set -e
REPO="juanortizpa/crypto_bot"
DIR="$HOME/bot-rotacion"

echo ">> Instalando Python y el programador de tareas..."
pkg update -y >/dev/null 2>&1 || true
pkg install -y python cronie termux-services >/dev/null

echo ">> Descargando el ejecutor..."
mkdir -p "$DIR"
curl -sfL "https://raw.githubusercontent.com/$REPO/main/ejecutor/ejecutor.py" -o "$DIR/ejecutor.py"
chmod 700 "$DIR/ejecutor.py"

# atajo:  bot configurar | bot prueba | bot estado | bot ciclo | bot registro | bot actualizar
cat > "$PREFIX/bin/bot" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
case "\$1" in
  registro) tail -n 40 "\$HOME/.bot_rotacion/registro.txt" ;;
  actualizar) curl -sfL "https://raw.githubusercontent.com/$REPO/main/ejecutor/ejecutor.py" -o "$DIR/ejecutor.py" && echo "ejecutor actualizado" ;;
  *) python "$DIR/ejecutor.py" "\$@" ;;
esac
EOF
chmod 755 "$PREFIX/bin/bot"

echo ">> Programando el ciclo: cada 3 horas (solo opera una vez por orden diaria)..."
( crontab -l 2>/dev/null | grep -v "bot-rotacion" ; echo "17 */3 * * * termux-wake-lock; python $DIR/ejecutor.py ciclo >/dev/null 2>&1; termux-wake-unlock  # bot-rotacion" ) | crontab -
sv-enable crond >/dev/null 2>&1 || true

echo ""
echo "Listo. Ahora:"
echo "  1) bot configurar   (pega tus claves de Binance, el token de GitHub y el capital)"
echo "  2) bot prueba       (revisa la conexion; el resultado aparece en el panel)"
echo "  3) cierra y vuelve a abrir Termux una vez para que arranque el programador."
echo "  Consejo: en Ajustes de Android quita la optimizacion de bateria para Termux."
