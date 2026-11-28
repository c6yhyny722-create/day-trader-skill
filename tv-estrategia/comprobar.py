#!/usr/bin/env python3
"""Comprobación de condiciones sobre velas CERRADAS, con datos de TradingView.

Adaptado del «safety check» del repositorio claude-tradingview-mcp-trading: cada
condición de la estrategia se evalúa con su valor real y sale PASA / NO PASA. Una
señal solo existe si pasan TODAS. Diferencias con aquel: nunca envía órdenes, usa
solo velas cerradas, acepta datos con retraso (lo indica), da la hora de cierre real
en horario de Madrid y no repite una señal de una vela ya notificada.

    python3 comprobar.py reglas.json --datos BITSTAMP:BTCUSD@1h=btc1h.json \\
        --datos BITSTAMP:BTCUSD@4h=btc4h.json [--ahora 2026-11-26T20:05:00Z] \\
        [--estado estado-avisos.json] [--json]

Cada --datos es la respuesta de mcp-tv-get-ohlcv guardada en un archivo: filas
[{t,o,h,l,c,v}], columnas {t:[],o:[],...} o el objeto completo con esas barras dentro.
`t` es el inicio de la vela en segundos Unix (UTC).

Expresiones de las condiciones (reglas.json, "senales"):
    close, open, high, low, volume, un número,
    ema(N), sma(N), rsi(N), atr(N), highest(N), lowest(N)   (highest/lowest incluyen la vela actual)
    ...[K]   desplaza K velas hacia atrás (highest(20)[1] = máximo de las 20 anteriores)
    ...@TF   en otra temporalidad (close@4h, ema(50)@4h): su última vela cerrada
Operadores: > < >= <= cruza_arriba cruza_abajo

Salida: 0 si hay al menos una señal nueva, 1 si no, 2 si hay un error.
"""

import argparse
import datetime
import json
import os
import re
import sys

# Windows: a console or pipe in cp1252/cp850 cannot print emojis or some
# accents, and one such character would kill the whole command. Print UTF-8
# and replace anything that still cannot be shown.
for _stream in (sys.stdout, sys.stderr):
    try:
        if (_stream.encoding or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

INTERVALOS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
              "4h": 14400, "1d": 86400, "1D": 86400, "1w": 604800, "1W": 604800}
OPS = (">", "<", ">=", "<=", "cruza_arriba", "cruza_abajo")
EXPR = re.compile(r"^\s*(?P<nom>[a-z_]+)(?:\((?P<n>\d+)\))?(?:\[(?P<k>\d+)\])?(?:@(?P<tf>\w+))?\s*$")
EPOCH = datetime.datetime(1970, 1, 1)


class Error(Exception):
    pass


# ---------------------------------------------------------------- hora de Madrid

def _ultimo_domingo(anio, mes):
    d = datetime.date(anio, mes + 1, 1) - datetime.timedelta(days=1) if mes < 12 else datetime.date(anio, 12, 31)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def madrid(ts):
    """Segundos Unix -> 'dd-mm-aaaa HH:MM' en Europe/Madrid (CET/CEST, regla de la UE:
    horario de verano desde la 01:00 UTC del último domingo de marzo hasta la 01:00 UTC
    del último domingo de octubre)."""
    utc = EPOCH + datetime.timedelta(seconds=int(ts))
    ini = datetime.datetime.combine(_ultimo_domingo(utc.year, 3), datetime.time(1))
    fin = datetime.datetime.combine(_ultimo_domingo(utc.year, 10), datetime.time(1))
    local = utc + datetime.timedelta(hours=2 if ini <= utc < fin else 1)
    return local.strftime("%d-%m-%Y %H:%M")


def parse_ahora(texto):
    if not texto:
        return int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    t = texto.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise Error("--ahora quiere una hora ISO con zona, p. ej. 2026-11-26T20:05:00Z")
    if dt.tzinfo is None:
        raise Error("--ahora necesita zona horaria (Z o +01:00)")
    return int(dt.timestamp())


# ---------------------------------------------------------------- datos

def leer_barras(ruta):
    try:
        with open(ruta, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        raise Error("no se pudo leer %s: %s" % (ruta, e))
    return normalizar(doc, ruta)


def normalizar(doc, origen="datos"):
    if isinstance(doc, dict):
        for k in ("bars", "data", "rows", "ohlcv"):
            if k in doc:
                return normalizar(doc[k], origen)
        if isinstance(doc.get("t"), list):
            n = len(doc["t"])
            doc = [{k: (doc.get(k) or [None] * n)[i] for k in ("t", "o", "h", "l", "c", "v")} for i in range(n)]
    if not isinstance(doc, list):
        raise Error("%s no tiene velas reconocibles" % origen)
    barras = []
    for b in doc:
        if not isinstance(b, dict) or b.get("t") is None or b.get("c") is None:
            continue
        c = float(b["c"])
        barras.append({"t": int(b["t"]), "o": float(b.get("o", c)), "h": float(b.get("h", c)),
                       "l": float(b.get("l", c)), "c": c, "v": float(b.get("v") or 0)})
    barras.sort(key=lambda x: x["t"])
    return barras


def cerradas(barras, paso, ahora):
    """Solo las velas cuyo cierre (inicio + paso) ya ha pasado."""
    return [b for b in barras if b["t"] + paso <= ahora]


# ---------------------------------------------------------------- indicadores (sobre la serie completa)

def _ema(xs, n):
    out, k, e = [], 2.0 / (n + 1), None
    for i, x in enumerate(xs):
        if i + 1 < n:
            out.append(None)
            continue
        e = sum(xs[i + 1 - n:i + 1]) / n if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def _sma(xs, n):
    return [None if i + 1 < n else sum(xs[i + 1 - n:i + 1]) / n for i in range(len(xs))]


def _rma(xs, n):
    out, r = [], None
    for i, x in enumerate(xs):
        if x is None or i + 1 < n:
            out.append(None)
            continue
        r = sum(xs[i + 1 - n:i + 1]) / n if r is None else (r * (n - 1) + x) / n
        out.append(r)
    return out


def _rsi(xs, n):
    sube = [0.0] + [max(xs[i] - xs[i - 1], 0.0) for i in range(1, len(xs))]
    baja = [0.0] + [max(xs[i - 1] - xs[i], 0.0) for i in range(1, len(xs))]
    up, dn = _rma(sube[1:], n), _rma(baja[1:], n)
    out = [None]
    for u, d in zip(up, dn):
        out.append(None if u is None else (100.0 if d == 0 else 100 - 100 / (1 + u / d)))
    return out


def _atr(barras, n):
    tr = []
    for i, b in enumerate(barras):
        pc = barras[i - 1]["c"] if i else None
        tr.append(b["h"] - b["l"] if pc is None else max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    return _rma(tr, n)


def serie(barras, nom, n):
    base = {"close": "c", "open": "o", "high": "h", "low": "l", "volume": "v"}
    if nom in base:
        return [b[base[nom]] for b in barras]
    if n is None:
        raise Error("%s necesita un periodo, p. ej. %s(14)" % (nom, nom))
    cierres = [b["c"] for b in barras]
    if nom == "ema":
        return _ema(cierres, n)
    if nom == "sma":
        return _sma(cierres, n)
    if nom == "rsi":
        return _rsi(cierres, n)
    if nom == "atr":
        return _atr(barras, n)
    if nom in ("highest", "lowest"):
        campo, f = ("h", max) if nom == "highest" else ("l", min)
        return [None if i + 1 < n else f(b[campo] for b in barras[i + 1 - n:i + 1]) for i in range(len(barras))]
    raise Error("expresión desconocida: %s" % nom)


# ---------------------------------------------------------------- evaluación

def valor(expr, datos, tf_base, atras=0):
    """Valor de una expresión en la última vela cerrada (o `atras` velas antes)."""
    if isinstance(expr, (int, float)):
        return float(expr)
    try:
        return float(expr)
    except (TypeError, ValueError):
        pass
    m = EXPR.match(str(expr))
    if not m:
        raise Error("no entiendo la expresión %r" % expr)
    tf = m.group("tf") or tf_base
    if tf not in datos:
        raise Error("falta --datos para la temporalidad %s (expresión %s)" % (tf, expr))
    barras = datos[tf]
    s = serie(barras, m.group("nom"), int(m.group("n")) if m.group("n") else None)
    i = len(s) - 1 - int(m.group("k") or 0) - atras
    return s[i] if 0 <= i < len(s) else None


def fmt(x):
    if x is None:
        return "sin dato"
    a = abs(x)
    dec = 2 if a >= 100 else 4 if a >= 1 else 6
    return ("{:,.%df}" % dec).format(x).replace(",", "X").replace(".", ",").replace("X", ".")


def condicion(c, datos, tf_base):
    a, op, b = c.get("a"), c.get("op"), c.get("b")
    if op not in OPS:
        raise Error("operador %r no válido (usa %s)" % (op, ", ".join(OPS)))
    va, vb = valor(a, datos, tf_base), valor(b, datos, tf_base)
    texto = c.get("texto") or "%s %s %s" % (a, op, b)
    if va is None or vb is None:
        return {"texto": texto, "pasa": None, "a": va, "b": vb}
    if op in (">", "<", ">=", "<="):
        pasa = {">": va > vb, "<": va < vb, ">=": va >= vb, "<=": va <= vb}[op]
    else:
        pa, pb = valor(a, datos, tf_base, 1), valor(b, datos, tf_base, 1)
        if pa is None or pb is None:
            return {"texto": texto, "pasa": None, "a": va, "b": vb}
        pasa = (pa <= pb and va > vb) if op == "cruza_arriba" else (pa >= pb and va < vb)
    return {"texto": texto, "pasa": bool(pasa), "a": va, "b": vb}


def plan(nombre, reglas, datos, tf, cierre_precio, capital=None, riesgo_pct=1.0):
    """Invalidación, R, zona de entrada, objetivo y tamaño (solo simulación)."""
    inv = (reglas.get("invalidacion") or {}).get(nombre)
    if not inv:
        return None
    stop = valor(inv, datos, tf)
    if stop is None:
        return {"nota": "invalidación NO EVALUABLE (%s sin dato)" % inv}
    largo = stop < cierre_precio
    R = abs(cierre_precio - stop)
    if R == 0:
        return {"nota": "invalidación igual al cierre: sin R, no hay plan"}
    obj_r = float(reglas.get("objetivo_R", 2))
    out = {"direccion": "larga" if largo else "corta", "referencia": cierre_precio, "invalidacion": stop,
           "R": R, "objetivo": cierre_precio + obj_r * R if largo else cierre_precio - obj_r * R, "objetivo_R": obj_r}
    nivel = (reglas.get("nivel") or {}).get(nombre)
    zr = reglas.get("zona_entrada_R")
    if nivel and zr is not None:
        lv = valor(nivel, datos, tf)
        if lv is not None:
            out["zona"] = (lv, lv + float(zr) * R) if largo else (lv - float(zr) * R, lv)
            out["en_zona"] = out["zona"][0] <= cierre_precio <= out["zona"][1]
    if capital:
        por_riesgo = capital * riesgo_pct / 100.0 / R
        por_capital = capital / cierre_precio
        out["cantidad"] = min(por_riesgo, por_capital)
        out["limite"] = "riesgo %g %% del capital" % riesgo_pct if por_riesgo <= por_capital else "capital disponible (sin apalancamiento)"
        out["perdida_en_stop"] = out["cantidad"] * R
    return out


def evaluar_simbolo(simbolo, reglas, datos, ahora, estado, capital=None, riesgo_pct=1.0):
    tf = reglas.get("temporalidad_confirmacion", "1h")
    if tf not in datos or not datos[tf]:
        return {"simbolo": simbolo, "estado": "NO EVALUABLE", "motivo": "sin velas cerradas de %s" % tf}
    paso = INTERVALOS[tf]
    ultima = datos[tf][-1]
    cierre = ultima["t"] + paso
    esperado = (ahora // paso) * paso      # cierre de la última vela que ya debería estar
    retraso = max(esperado - cierre, 0)
    max_ret = float(reglas.get("retraso_maximo_horas", 24)) * 3600
    res = {"simbolo": simbolo, "temporalidad": tf, "cierre_ts": cierre, "cierre_madrid": madrid(cierre),
           "ultimo_cierre": ultima["c"], "retraso_h": round(retraso / 3600.0, 1), "senales": []}
    if retraso > max_ret:
        res.update(estado="NO EVALUABLE", motivo="el último dato tiene más de %g h de retraso" % (max_ret / 3600))
        return res
    hay_nueva = False
    for nombre, conds in (reglas.get("senales") or {}).items():
        filas = [condicion(c, datos, tf) for c in conds]
        if any(f["pasa"] is None for f in filas):
            veredicto = "NO EVALUABLE"
        elif all(f["pasa"] for f in filas):
            clave = "%s|%s|%d" % (simbolo, nombre, cierre)
            veredicto = "YA NOTIFICADA" if clave in estado else "SEÑAL NUEVA"
            if veredicto == "SEÑAL NUEVA":
                estado[clave] = madrid(cierre)
                hay_nueva = True
        else:
            veredicto = "SIN SEÑAL"
        sen = {"nombre": nombre, "veredicto": veredicto, "condiciones": filas}
        if veredicto in ("SEÑAL NUEVA", "YA NOTIFICADA"):
            sen["plan"] = plan(nombre, reglas, datos, tf, ultima["c"], capital, riesgo_pct)
        res["senales"].append(sen)
    res["estado"] = "SEÑAL NUEVA" if hay_nueva else (
        "YA NOTIFICADA" if any(s["veredicto"] == "YA NOTIFICADA" for s in res["senales"]) else
        "NO EVALUABLE" if res["senales"] and all(s["veredicto"] == "NO EVALUABLE" for s in res["senales"]) else
        "SIN SEÑAL")
    return res


def informe(resultados):
    out = ["| Activo | Último cierre y hora (Madrid) | Estado |", "| --- | --- | --- |"]
    for r in resultados:
        hora = r.get("cierre_madrid", "sin dato")
        ret = (" (dato con retraso de %s h)" % ("%g" % r["retraso_h"]).replace(".", ",")) if r.get("retraso_h") else ""
        out.append("| %s | %s · %s%s | %s |" % (r["simbolo"], fmt(r.get("ultimo_cierre")), hora, ret, r["estado"]))
    for r in resultados:
        if r.get("motivo"):
            out.append("\n%s: NO EVALUABLE, %s." % (r["simbolo"], r["motivo"]))
        for s in r.get("senales", []):
            out.append("\n%s · %s · vela de %s cerrada a las %s (Madrid): %s" % (
                r["simbolo"], s["nombre"], r["temporalidad"], r["cierre_madrid"], s["veredicto"]))
            for f in s["condiciones"]:
                marca = "PASA" if f["pasa"] else "NO EVALUABLE" if f["pasa"] is None else "NO PASA"
                out.append("  - %s: %s (%s frente a %s)" % (f["texto"], marca, fmt(f["a"]), fmt(f["b"])))
            pl = s.get("plan")
            if pl and pl.get("nota"):
                out.append("  Plan: %s" % pl["nota"])
            elif pl:
                out.append("  Plan simulado (%s): referencia %s · invalidación %s · R %s · objetivo %sR %s" % (
                    pl["direccion"], fmt(pl["referencia"]), fmt(pl["invalidacion"]), fmt(pl["R"]),
                    ("%g" % pl["objetivo_R"]).replace(".", ","), fmt(pl["objetivo"])))
                if "zona" in pl:
                    out.append("  Zona de entrada: %s a %s (%s)" % (fmt(pl["zona"][0]), fmt(pl["zona"][1]),
                                                                 "dentro" if pl["en_zona"] else "fuera de zona"))
                if "cantidad" in pl:
                    out.append("  Tamaño simulado: %s unidades, pérdida en la invalidación %s (límite: %s)" % (
                        fmt(pl["cantidad"]), fmt(pl["perdida_en_stop"]), pl["limite"]))
    out.append("\nSimulación: no se ha enviado ninguna orden.")
    return "\n".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description="Comprueba las condiciones de una estrategia en velas cerradas.")
    p.add_argument("reglas")
    p.add_argument("--datos", action="append", default=[], metavar="SIMBOLO@TF=ARCHIVO")
    p.add_argument("--ahora")
    p.add_argument("--estado", help="archivo JSON con las velas ya notificadas (se actualiza)")
    p.add_argument("--capital", type=float, help="capital para el tamaño simulado")
    p.add_argument("--riesgo-pct", type=float, default=1.0, help="%% del capital que se arriesga por operación (1)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        with open(a.reglas, encoding="utf-8") as fh:
            reglas = json.load(fh)
        ahora = parse_ahora(a.ahora)
        por_simbolo = {}
        for d in a.datos:
            m = re.match(r"^(?P<s>[^@=]+)@(?P<tf>\w+)=(?P<f>.+)$", d)
            if not m or m.group("tf") not in INTERVALOS:
                raise Error("--datos quiere SIMBOLO@TF=ARCHIVO con TF en %s" % ", ".join(INTERVALOS))
            tf = m.group("tf")
            por_simbolo.setdefault(m.group("s"), {})[tf] = cerradas(leer_barras(m.group("f")), INTERVALOS[tf], ahora)
        estado = {}
        if a.estado and os.path.exists(a.estado):
            with open(a.estado, encoding="utf-8") as fh:
                estado = json.load(fh)
        simbolos = reglas.get("simbolos") or sorted(por_simbolo)
        res = [evaluar_simbolo(s, reglas, por_simbolo.get(s, {}), ahora, estado, a.capital, a.riesgo_pct) for s in simbolos]
        if a.estado:
            with open(a.estado, "w", encoding="utf-8") as fh:
                json.dump(estado, fh, ensure_ascii=False, indent=1, sort_keys=True)
    except Error as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else informe(res))
    return 0 if any(r["estado"] == "SEÑAL NUEVA" for r in res) else 1


if __name__ == "__main__":
    sys.exit(main())
