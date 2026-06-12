# start_24_7.ps1 - Lanzador 24/7 con watchdog para Windows (portatil).
#
# IMPORTANTE: archivo 100% ASCII (sin acentos ni guiones largos) porque
# Windows PowerShell 5.1 lee los .ps1 sin BOM como ANSI y los caracteres
# especiales rompen el parseo de las cadenas.
#
# Uso (PowerShell, desde la carpeta del proyecto):
#   .\start_24_7.ps1                # dry-run (paper), 31 dias
#   .\start_24_7.ps1 -Live          # testnet real (BINANCE_MODE=testnet en .env)
#   .\start_24_7.ps1 -Days 30
#
# Que hace:
#   1. Evita que el portatil se suspenda mientras corre (powercfg).
#   2. Activa el venv y lanza `python bot_crypto.py forever`.
#   3. Si el proceso Python muere (crash del interprete, OOM), lo relanza
#      con backoff. El orquestador interno ya maneja crashes de sesion;
#      este watchdog cubre el caso en que muere el proceso completo.
#
# IMPORTANTE antes de arrancar el mes:
#   - Conecta el portatil a la corriente.
#   - Windows Update: pausa las actualizaciones o configura horas activas,
#     un reboot automatico mata el bot (las posiciones quedan PENDING y se
#     retoman al relanzar, pero pierdes horas de monitoreo).
#   - Cierra editores que tengan abiertas las .db de state/.

param(
    [switch]$Live,
    [double]$Days = 31
)

$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

# 1) Evitar suspension mientras corre (solo con corriente: ac)
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 10   # la pantalla si puede apagarse

# 2) Activar venv
$venv = Join-Path $PSScriptRoot ".venv\Scripts\Activate.ps1"
if (Test-Path $venv) { . $venv } else { Write-Host "AVISO: no se encontro .venv - usando python global" }

$mode = if ($Live) { "--live" } else { "--dry-run" }
$deadline = (Get-Date).AddDays($Days)
$backoff = 30

Write-Host "=== 24/7 hasta $deadline | modo $mode ==="

while ((Get-Date) -lt $deadline) {
    $remaining = ($deadline - (Get-Date)).TotalDays
    $remainingRounded = [math]::Round($remaining, 1)
    Write-Host "[watchdog] lanzando forever ($remainingRounded dias restantes)..."
    python bot_crypto.py forever --days $remaining $mode
    $code = $LASTEXITCODE
    if ((Get-Date) -ge $deadline) { break }
    if ($code -eq 0) {
        Write-Host "[watchdog] forever termino limpio (exit 0) - fin."
        break
    }
    Write-Host "[watchdog] proceso murio (exit $code) - relanzo en $backoff s"
    Start-Sleep -Seconds $backoff
    $backoff = [math]::Min($backoff * 2, 900)
}

Write-Host "=== Prueba 24/7 terminada. Revisa reports\summary.csv y corre: python bot_crypto.py readiness ==="
