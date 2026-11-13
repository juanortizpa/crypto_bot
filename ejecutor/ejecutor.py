#!/usr/bin/env python3
"""
Ejecutor del bot de rotacion para el celular (o cualquier equipo fuera de EE.UU.).

GitHub decide cada dia y publica `orden.json` en la rama `paper-state`.
Este programa:
  1. lee esa orden,
  2. si el modo es `live`, ajusta tu cartera en Binance a esos pesos
     (solo con el capital que configuraste y solo con monedas que el mismo compro),
  3. publica el resultado (live.json) para el panel web.

Solo usa la libreria estandar de Python. Comandos:
  python ejecutor.py configurar   pide las claves y las guarda en este equipo
  python ejecutor.py prueba       comprueba la conexion (solo lectura) y publica el resultado
  python ejecutor.py ciclo        ejecuta el ciclo del dia (lo que corre la tarea programada)
  python ejecutor.py ip           muestra tu IP publica (la que Binance exige en la lista de IP de confianza)
  python ejecutor.py estado       muestra la cartera que gestiona el bot
  python ejecutor.py ciclo --simulado   recorre el ciclo con precios reales pero SIN enviar ordenes

Las claves de Binance y el token de GitHub quedan SOLO en este equipo
(~/.bot_rotacion/config.json, permisos 600). Nunca se suben a ningun lado.
"""
import base64
import getpass
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
import re
import socket

# Binance valida la IP de origen de cada orden contra la lista de IP de confianza
# de la clave. Se fuerza IPv4 hacia Binance (y hacia el servicio que dice tu IP)
# para que la IP que ve sea siempre una sola, la que anotas en la lista.
_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_v4(host, port, family=0, type=0, proto=0, flags=0):
    if isinstance(host, str) and host.endswith(("binance.com", "ipify.org")):
        family = socket.AF_INET
    return _getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _getaddrinfo_v4

VERSION = 1
REPO = os.environ.get("BOT_REPO", "juanortizpa/crypto_bot")
RAMA = os.environ.get("BOT_RAMA", "paper-state")
HOME = os.path.join(os.path.expanduser("~"), ".bot_rotacion")
CONFIG = os.path.join(HOME, "config.json")
ESTADO = os.path.join(HOME, "estado.json")
LOG = os.path.join(HOME, "registro.txt")
BINANCE = "https://api.binance.com"
UA = {"User-Agent": "bot-rotacion-ejecutor/1"}
MIN_TRADE_USD = 10.0
MIN_TRADE_FRAC = 0.02
MAX_EDAD_ORDEN_DIAS = 3


# ── utilidades ────────────────────────────────────────────────────────

def log(msg):
    linea = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(linea, flush=True)
    os.makedirs(HOME, exist_ok=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(linea + "\n")
        if os.path.getsize(LOG) > 2_000_000:          # rotacion simple
            os.replace(LOG, LOG + ".1")
    except OSError:
        pass


def leer_json(path, defecto=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def escribir_json(path, data, privado=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    if privado:
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def http(method, url, data=None, headers=None, timeout=20):
    body = json.dumps(data).encode() if isinstance(data, (dict, list)) else data
    h = dict(UA, **(headers or {}))
    if isinstance(data, (dict, list)):
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None


def ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Binance ───────────────────────────────────────────────────────────

class Binance:
    def __init__(self, key, secret):
        self.key, self.secret = key, secret
        self.offset = 0
        self._info = None

    def publico(self, path, params=None):
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        return http("GET", BINANCE + path + q)

    def firmado(self, method, path, params=None, _reintento=True):
        p = dict(params or {})
        p["timestamp"] = int(time.time() * 1000) + self.offset
        p["recvWindow"] = 10000
        q = urllib.parse.urlencode(p)
        q += "&signature=" + hmac.new(self.secret.encode(), q.encode(), hashlib.sha256).hexdigest()
        code, data = http(method, f"{BINANCE}{path}?{q}", data=b"" if method == "POST" else None,
                          headers={"X-MBX-APIKEY": self.key})
        if _reintento and isinstance(data, dict) and data.get("code") == -1021:   # reloj desviado
            c2, t = self.publico("/api/v3/time")
            if c2 == 200:
                self.offset = int(t["serverTime"]) - int(time.time() * 1000)
                return self.firmado(method, path, params, _reintento=False)
        return code, data

    def precios(self):
        code, data = self.publico("/api/v3/ticker/price")
        if code != 200 or not isinstance(data, list):
            raise RuntimeError(f"no se pudieron leer los precios (HTTP {code})")
        return {d["symbol"]: float(d["price"]) for d in data}

    def filtros(self, sym):
        if self._info is None:
            code, data = self.publico("/api/v3/exchangeInfo", {"permissions": "SPOT"})
            if code != 200:
                raise RuntimeError(f"no se pudo leer exchangeInfo (HTTP {code})")
            self._info = {s["symbol"]: s for s in data["symbols"]}
        s = self._info.get(sym)
        if not s or s.get("status") != "TRADING":
            return None
        f = {"step": 1e-8, "min_qty": 0.0, "min_notional": 5.0}
        for x in s["filters"]:
            if x["filterType"] == "LOT_SIZE":
                f["step"], f["min_qty"] = float(x["stepSize"]), float(x["minQty"])
            elif x["filterType"] in ("NOTIONAL", "MIN_NOTIONAL"):
                f["min_notional"] = float(x.get("minNotional", 5.0))
        f["base"] = s["baseAsset"]
        return f


def redondear(q, step):
    if step <= 0:
        return q
    dec = max(0, -int(math.floor(math.log10(step))))
    return float(f"{math.floor(q / step + 1e-9) * step:.{dec}f}")


def a_texto(q):
    return format(q, "f").rstrip("0").rstrip(".") or "0"


# ── GitHub (publicar resultados para el panel) ────────────────────────

def leer_orden():
    local = os.environ.get("BOT_ORDEN")              # solo para pruebas: leer la orden de un archivo
    if local:
        return leer_json(local)
    url = f"https://raw.githubusercontent.com/{REPO}/{RAMA}/orden.json?t={int(time.time())}"
    code, data = http("GET", url)
    if code != 200 or not isinstance(data, dict):
        raise RuntimeError(f"no se pudo leer la orden del dia (HTTP {code})")
    return data


def publicar(cfg, nombre, contenido, mensaje):
    token = cfg.get("github_token")
    if not token:
        log("  (sin token de GitHub: el resultado no se publica en el panel)")
        return False
    api = f"https://api.github.com/repos/{REPO}/contents/{nombre}"
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    b64 = base64.b64encode(json.dumps(contenido, ensure_ascii=False, indent=1).encode()).decode()
    for intento in range(4):
        code, cur = http("GET", f"{api}?ref={RAMA}", headers=h)
        body = {"message": f"{mensaje} {datetime.now(timezone.utc):%Y-%m-%d}", "content": b64, "branch": RAMA,
                "committer": {"name": "ejecutor-celular", "email": "ejecutor@users.noreply.github.com"}}
        if code == 200 and isinstance(cur, dict):
            body["sha"] = cur["sha"]
        code, resp = http("PUT", api, data=body, headers=h)
        if code in (200, 201):
            return True
        if code in (401, 403, 404):
            log(f"  GitHub rechazo el token (HTTP {code}). Revisa que tenga permiso de escritura en {REPO}.")
            return False
        time.sleep(3 * (intento + 1))                  # 409/422: la rama cambio; reintentar
    log("  no se pudo publicar en GitHub tras varios intentos")
    return False


# ── estado local ──────────────────────────────────────────────────────

def estado_inicial(capital):
    return {"version": VERSION, "capital_inicial": capital, "usdt": capital, "posiciones": {}, "costo": {},
            "pico": capital, "detenido": False, "motivo": None, "ultima_orden": None, "inicio": ahora()[:10],
            "historial": [], "operaciones": []}


def valor(est, precios):
    return est["usdt"] + sum(q * precios.get(s, 0.0) for s, q in est["posiciones"].items())


# ── ordenes ───────────────────────────────────────────────────────────

def operar(bn, est, sym, lado, usd, precio, motivo, simulado):
    """Orden MARKET. Compra por monto en USDT; venta por cantidad. Devuelve True si se ejecuto."""
    f = bn.filtros(sym)
    if not f:
        log(f"  {sym} no se puede operar en Binance ahora; se omite")
        return False
    if lado == "BUY":
        usd = math.floor(usd * 100) / 100
        if usd < max(f["min_notional"], MIN_TRADE_USD * 0.5):
            log(f"  compra de {sym} por {usd:.2f} USDT bajo el minimo de Binance; se omite")
            return False
        params = {"symbol": sym, "side": "BUY", "type": "MARKET", "quoteOrderQty": f"{usd:.2f}"}
    else:
        q = redondear(min(usd / precio, est["posiciones"].get(sym, 0.0)), f["step"])
        if q < f["min_qty"] or q * precio < f["min_notional"]:
            log(f"  venta de {sym} por {q * precio:.2f} USDT bajo el minimo de Binance; se omite")
            return False
        params = {"symbol": sym, "side": "SELL", "type": "MARKET", "quantity": a_texto(q)}
    if simulado:
        if lado == "BUY":
            qty, neto = usd * 0.999 / precio, usd
        else:
            qty, neto = q, q * precio * 0.999
    else:
        code, r = bn.firmado("POST", "/api/v3/order", params)
        if code != 200 or not isinstance(r, dict) or r.get("status") not in ("FILLED", "PARTIALLY_FILLED"):
            log(f"  ORDEN RECHAZADA {lado} {sym}: HTTP {code} {r}")
            return False
        qty = float(r["executedQty"])
        neto = float(r["cummulativeQuoteQty"])
        fills = r.get("fills", [])
        com_base = sum(float(x["commission"]) for x in fills if x.get("commissionAsset") == f["base"])
        com_usdt = sum(float(x["commission"]) for x in fills if x.get("commissionAsset") == "USDT")
        if lado == "BUY":
            qty -= com_base
        else:
            neto -= com_usdt
    c = est["costo"].setdefault(sym, [0.0, 0.0])
    if lado == "BUY":
        est["usdt"] -= neto
        est["posiciones"][sym] = est["posiciones"].get(sym, 0.0) + qty
        c[0] += qty
        c[1] += neto
    else:
        est["usdt"] += neto
        quedan = est["posiciones"].get(sym, 0.0) - qty
        f_rest = max(0.0, quedan / c[0]) if c[0] > 0 else 0.0
        c[0] *= f_rest
        c[1] *= f_rest
        if quedan * precio < 1.0:
            est["posiciones"].pop(sym, None)
            est["costo"].pop(sym, None)
        else:
            est["posiciones"][sym] = quedan
    est["operaciones"].append({"t": ahora(), "s": sym, "lado": lado, "qty": qty, "usd": round(neto, 2),
                               "precio": precio, "motivo": motivo, "simulado": simulado})
    log(f"  {'[SIMULADO] ' if simulado else ''}{lado} {sym} {a_texto(round(qty, 8))} por {neto:.2f} USDT ({motivo})")
    return True


def liquidar(bn, est, precios, motivo, simulado):
    for s in list(est["posiciones"]):
        operar(bn, est, s, "SELL", est["posiciones"][s] * precios[s], precios[s], motivo, simulado)


def validar(orden):
    if orden.get("version") != 1 or orden.get("modo") not in ("paper", "live", "salir"):
        raise RuntimeError("la orden publicada no tiene el formato esperado")
    edad = (datetime.now(timezone.utc).date() - datetime.strptime(orden["asof"], "%Y-%m-%d").date()).days
    if edad > MAX_EDAD_ORDEN_DIAS:
        raise RuntimeError(f"la orden es de hace {edad} dias: GitHub no ha corrido el ciclo; no se opera")
    pesos = orden.get("pesos", {})
    tope = float(orden.get("tope_por_moneda", 0.4)) + 1e-6
    if any(not s.endswith("USDT") or not (0 < w <= tope) for s, w in pesos.items()) or sum(pesos.values()) > 1.0001:
        raise RuntimeError("los pesos publicados no son validos; no se opera")
    return pesos


# ── comandos ──────────────────────────────────────────────────────────

def cargar_config():
    cfg = leer_json(CONFIG)
    if not cfg or not cfg.get("binance_key"):
        sys.exit("Falta configurar. Ejecuta:  python ejecutor.py configurar")
    return cfg


def configurar():
    print("\nConfiguracion del bot (los datos quedan solo en este equipo)\n")
    cfg = leer_json(CONFIG, {}) or {}
    pedir = lambda txt, k, secreto=False: (getpass.getpass if secreto else input)(f"{txt}{' [enter = mantener]' if cfg.get(k) else ''}: ").strip() or cfg.get(k, "")
    cfg["binance_key"] = pedir("API Key de Binance", "binance_key")
    cfg["binance_secret"] = pedir("Secret Key de Binance (no se vera al escribir)", "binance_secret", True)
    cfg["github_token"] = pedir("Token de GitHub para publicar en el panel", "github_token", True)
    cap = pedir("Capital en USDT que el bot puede usar", "capital")
    cfg["capital"] = float(str(cap).replace(",", "."))
    cfg["mostrar_montos"] = input("Mostrar montos en dolares en el panel publico? (s/N): ").strip().lower() in ("s", "si", "sí")
    escribir_json(CONFIG, cfg, privado=True)
    print(f"\nGuardado en {CONFIG} (solo tu usuario puede leerlo). Ahora ejecuta:  python ejecutor.py prueba\n")


def explicar_rechazo(r):
    """Traduce el rechazo de Binance; si es por IP, dice cual IP vio Binance."""
    msg = str(r.get("msg", r)) if isinstance(r, dict) else str(r)
    ip = re.search(r"request ip:\s*([0-9a-fA-F.:]+)", msg)
    if isinstance(r, dict) and r.get("code") == -2015:
        if ip:
            return (f"Binance rechazo la clave: o la IP {ip.group(1)} no esta en la lista de IP de confianza, o falta algun permiso. "
                    f"Agrega {ip.group(1)} en la clave (Restringir acceso a IP de confianza).")
        return "Binance rechazo la clave: revisa la lista de IP de confianza y los permisos."
    return f"rechazadas: {msg[:160]}"


def mostrar_ip():
    """La IP publica (IPv4) desde la que Binance vera tus ordenes."""
    code, ip = http("GET", "https://api.ipify.org?format=json")
    if code != 200 or not isinstance(ip, dict):
        sys.exit("No se pudo averiguar la IP: revisa tu conexion a internet.")
    print(f"\nTu IP publica ahora es:  {ip['ip']}\n")
    print("Es la que debes pegar en Binance (Restringir acceso a IP de confianza).")
    print("Hazlo con el celular conectado a la red desde la que va a operar (por ejemplo el WiFi de tu casa).")
    print("Si algun dia cambia (reinicias el router, usas datos moviles), el bot lo avisara y habra que actualizarla.\n")


def prueba():
    cfg = cargar_config()
    bn = Binance(cfg["binance_key"], cfg["binance_secret"])
    pasos, listo = [], False

    def paso(nombre, ok, detalle):
        pasos.append({"nombre": nombre, "ok": ok, "detalle": detalle})
        log(f"  {'OK' if ok else 'NO'}  {nombre}: {detalle}")
        return ok

    code, _ = bn.publico("/api/v3/ping")
    if paso("Binance responde desde tu celular", code == 200, f"HTTP {code}" + (" (Binance bloquea esta ubicacion)" if code in (451, 403) else "")):
        code, acct = bn.firmado("GET", "/api/v3/account", {"omitZeroBalances": "true"})
        if paso("Las claves son válidas", code == 200, "Binance acepto la firma" if code == 200 else explicar_rechazo(acct)):
            can = bool(acct.get("canTrade"))
            paso("Permiso de operar en Spot", can, "activo" if can else "activa 'Habilitar trading Spot y Margin' en la clave")
            usdt = sum(float(b["free"]) for b in acct.get("balances", []) if b["asset"] == "USDT")
            est = leer_json(ESTADO)
            necesita = cfg["capital"] if not est else max(0.0, est["usdt"])
            ok_usdt = usdt + 1e-6 >= necesita
            paso("USDT suficiente para el capital configurado", ok_usdt,
                 f"hay al menos {necesita:.0f} USDT libres" if ok_usdt else f"faltan USDT libres para cubrir {necesita:.0f}")
            code, rest = bn.firmado("GET", "/sapi/v1/account/apiRestrictions")
            if isinstance(rest, dict) and "enableWithdrawals" in rest:
                sin_retiros = not rest["enableWithdrawals"]
                paso("Retiros desactivados en la clave", sin_retiros, "correcto" if sin_retiros else "PELIGRO: desactiva 'Habilitar retiros' en la clave")
                listo = can and ok_usdt and sin_retiros
            else:
                paso("Retiros desactivados en la clave", False, "no se pudo comprobar; revisalo en Binance")
    try:
        orden = leer_orden()
        paso("Lee la orden diaria de GitHub", True, f"orden del {orden['asof']}, modo {orden['modo']}")
    except Exception as e:
        listo = paso("Lee la orden diaria de GitHub", False, str(e)) and listo
    publicado = publicar(cfg, "conexion.json", {"probado_utc": ahora(), "origen": "celular", "pasos": pasos, "listo": listo}, "prueba de conexion")
    if cfg.get("github_token"):
        paso("Publica en el panel con el token de GitHub", publicado, "correcto" if publicado else "el token no tiene permiso de escritura")
    print("\nLISTO PARA OPERAR\n" if listo and publicado else "\nTODAVIA NO ESTA LISTO: corrige lo marcado NO y repite la prueba\n")


def ciclo(simulado=False):
    cfg = cargar_config()
    bn = Binance(cfg["binance_key"], cfg["binance_secret"])
    estado_path = ESTADO + (".simulado" if simulado else "")
    est = leer_json(estado_path) or estado_inicial(float(cfg["capital"]))
    orden = leer_orden()
    pesos = validar(orden)
    modo = orden["modo"]
    if simulado and modo == "paper":
        modo = "live"                                   # el simulado recorre el ciclo aunque el modo real este apagado
    log(f"Orden del {orden['asof']} · modo {modo} · objetivo {pesos or 'USDT 100%'}")
    if modo == "paper":
        log("  modo real apagado en GitHub (ROT_MODE): no se opera")
        return
    if est.get("ultima_orden") == orden["asof"] and modo == "live":
        log("  esta orden ya se ejecuto: nada que hacer")
        return
    precios = bn.precios()
    for s in set(pesos) | set(est["posiciones"]):
        if s not in precios:
            raise RuntimeError(f"sin precio para {s}")
    eq = valor(est, precios)
    est["pico"] = max(est["pico"], eq)
    caida = (eq / est["pico"] - 1) * 100
    freno = float(orden.get("freno_pct", 40))
    if modo == "salir" and not est["detenido"]:
        log("  SALIDA MANUAL: se vende todo a USDT y el bot se detiene")
        liquidar(bn, est, precios, "LIQUIDACION", simulado)
        est.update(detenido=True, motivo="salida manual: todo vendido a USDT")
    elif not est["detenido"] and caida <= -freno:
        log(f"  FRENO DE EMERGENCIA: caida {caida:.1f}% desde el maximo")
        liquidar(bn, est, precios, "KILL_SWITCH", simulado)
        est.update(detenido=True, motivo=f"freno de emergencia: caida {caida:.1f}%")
    elif est["detenido"]:
        log(f"  bot detenido ({est['motivo']}). Para reanudar borra {estado_path} con la cartera ya en USDT.")
    else:
        umbral = max(MIN_TRADE_USD, MIN_TRADE_FRAC * eq)
        deltas = {s: pesos.get(s, 0.0) * eq - est["posiciones"].get(s, 0.0) * precios[s] for s in set(pesos) | set(est["posiciones"])}
        for s, d in sorted(deltas.items(), key=lambda kv: kv[1]):           # primero ventas
            actual = est["posiciones"].get(s, 0.0) * precios[s]
            if d < 0 and (pesos.get(s, 0.0) == 0 or -d >= umbral):
                operar(bn, est, s, "SELL", actual if pesos.get(s, 0.0) == 0 else -d, precios[s],
                       "SALIDA" if pesos.get(s, 0.0) == 0 else "REBALANCEO", simulado)
        for s, d in sorted(deltas.items(), key=lambda kv: -kv[1]):          # luego compras
            if d >= umbral:
                actual = est["posiciones"].get(s, 0.0) * precios[s]
                operar(bn, est, s, "BUY", min(d, est["usdt"] * 0.995), precios[s],
                       "ENTRADA" if actual < 1.0 else "REBALANCEO", simulado)
        if not any(d < 0 and (pesos.get(s, 0.0) == 0 or -d >= umbral) or d >= umbral for s, d in deltas.items()):
            log("  la cartera ya coincide con el objetivo: no se opera")
    est["ultima_orden"] = orden["asof"]
    eq = valor(est, precios)
    est["pico"] = max(est["pico"], eq)
    est["historial"] = [h for h in est["historial"] if h["d"] != orden["asof"]][-500:]
    est["historial"].append({"d": orden["asof"], "equity": round(eq, 2), "usdt": round(est["usdt"], 2), "on": bool(orden.get("regimen_on"))})
    est["operaciones"] = est["operaciones"][-300:]
    escribir_json(estado_path, est, privado=True)
    log(f"  cartera: {eq:.2f} USDT ({(eq / est['capital_inicial'] - 1) * 100:+.2f}%) · posiciones {sorted(est['posiciones']) or 'ninguna'}")
    if not simulado:
        publicar(cfg, "live.json", reporte(est, precios, cfg, "detenido" if est["detenido"] else "ok"), "ejecucion")


def reporte(est, precios, cfg, estado):
    """Lo que ve el panel. Por privacidad, sin dolares salvo que se pida."""
    ver = bool(cfg.get("mostrar_montos"))
    usd = lambda x: round(float(x), 2) if ver else None
    eq = valor(est, precios)
    ini = est["capital_inicial"]
    pos = []
    for s, q in sorted(est["posiciones"].items()):
        v = q * precios[s]
        c = est["costo"].get(s)
        ent = c[1] / c[0] if c and c[0] > 0 else None
        pos.append({"s": s.replace("USDT", ""), "pct": round(v / eq * 100, 1), "valor": usd(v), "precio": precios[s],
                    "entrada": ent, "pnl_pct": round((precios[s] / ent - 1) * 100, 2) if ent else None})
    hist = [{"d": h["d"], "pct": round((h["equity"] / ini - 1) * 100, 2), "equity": usd(h["equity"]),
             "expo": round((1 - h["usdt"] / h["equity"]) * 100, 1) if h["equity"] else 0.0, "on": h["on"]} for h in est["historial"]]
    return {
        "version": VERSION, "actualizado_utc": ahora(), "montos_visibles": ver,
        "ejecutor": {"estado": estado, "ultima_orden": est.get("ultima_orden"), "motivo": est.get("motivo")},
        "cartera": {"inicial": usd(ini), "equity": usd(eq), "usdt": usd(est["usdt"]),
                    "pnl_pct": round((eq / ini - 1) * 100, 2), "caida_pct": round((eq / max(est["pico"], eq) - 1) * 100, 2),
                    "expo_pct": round((1 - est["usdt"] / eq) * 100, 1) if eq else 0.0, "detenido": est["detenido"],
                    "motivo": est.get("motivo"), "inicio": est.get("inicio"), "ultimo_cierre": est.get("ultima_orden"), "posiciones": pos},
        "historial": hist,
        "operaciones": [{"t": o["t"], "s": o["s"].replace("USDT", ""), "lado": o["lado"], "usd": usd(o["usd"]), "precio": o["precio"],
                         "motivo": o["motivo"]} for o in est["operaciones"][-60:] if not o.get("simulado")][::-1],
        "n_operaciones": sum(1 for o in est["operaciones"] if not o.get("simulado")),
    }


def mostrar_estado():
    cfg = cargar_config()
    est = leer_json(ESTADO)
    if not est:
        print("Todavia no hay cartera real: el primer ciclo en modo live la crea.")
        return
    bn = Binance(cfg["binance_key"], cfg["binance_secret"])
    precios = bn.precios()
    eq = valor(est, precios)
    print(f"\nCartera del bot: {eq:.2f} USDT ({(eq / est['capital_inicial'] - 1) * 100:+.2f}%) · USDT libres del bot {est['usdt']:.2f}")
    for s, q in sorted(est["posiciones"].items()):
        print(f"  {s:<10} {a_texto(round(q, 8)):>16}  {q * precios[s]:>10.2f} USDT")
    print(f"Ultima orden ejecutada: {est.get('ultima_orden')} · {'DETENIDO: ' + str(est['motivo']) if est['detenido'] else 'activo'}\n")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ciclo"
    try:
        if cmd == "configurar":
            configurar()
        elif cmd == "prueba":
            prueba()
        elif cmd == "ip":
            mostrar_ip()
        elif cmd == "estado":
            mostrar_estado()
        elif cmd == "ciclo":
            ciclo(simulado="--simulado" in sys.argv)
        else:
            print(__doc__)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        log(f"ERROR: {e}")
        if cmd == "ciclo" and "--simulado" not in sys.argv:
            cfg = leer_json(CONFIG) or {}
            est = leer_json(ESTADO)
            if est and cfg.get("github_token"):
                try:
                    publicar(cfg, "live.json", dict(reporte(est, {s: 0.0 for s in est["posiciones"]}, cfg, "error"),
                                                    ejecutor={"estado": "error", "motivo": str(e)[:200], "ultima_orden": est.get("ultima_orden")}), "error")
                except Exception:
                    pass
        sys.exit(1)
