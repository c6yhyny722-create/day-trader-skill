#!/usr/bin/env python3
"""trader-cripto: las habilidades del paquete, adaptadas a cripto. Solo análisis y simulación.

Equivalencias con el paquete de acciones:

  escanear   ~ trader-scanner      las 10 monedas del script, estado y niveles de cada una
  senal      ~ trader-entry/exit   la regla «ruptura 20 + contexto 4h» con zona, invalidación y objetivo
  simular    ~ trader-timemachine  10.000 recorridos de las próximas horas y cada señal pasada
  tamano     ~ trader-budget       unidades fraccionarias para un % de riesgo del capital
  riesgo     ~ trader-risk         PASA / BLOQUEA según los límites del usuario
  precio     ~ trader-alerts       último precio de Bitstamp
  ficha      ~ trader-alerts       ficha de alerta de TradingView (propuesta, no se crea)
  noticias   ~ trader-news         titulares de Yahoo Finance por moneda

La regla es la del script de Pine «10 cripto 1h · ruptura 20 + contexto 4h»
(pine/10-cripto-1h): COMPRA si el cierre de 4h anterior está por encima de su EMA 50 y la
vela de 1h cierra por encima del máximo de las 20 anteriores; VENTA al revés. Invalidación:
mínimo (o máximo) de las 10 últimas velas. Zona de entrada: 0,5R desde el nivel roto.
Objetivo: 2R.

Datos: velas públicas de Bitstamp (el mismo mercado que las alertas de TradingView del
usuario), solo velas cerradas, horas en Europe/Madrid. Solo biblioteca estándar, Python 3.8+.
Nunca envía órdenes ni crea alertas.
"""

import argparse
import datetime
import json
import math
import os
import random
import statistics
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

MONEDAS = ["BTC", "ETH", "XRP", "SOL", "HYPE", "ZEC", "DOGE", "LINK", "ADA", "XLM"]
BITSTAMP = "https://www.bitstamp.net/api/v2"
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s-USD&region=US&lang=en-US"
UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; trader-cripto)"
H1, H4 = 3600, 14400
N_RUPTURA, N_STOP, N_EMA = 20, 10, 50
ZONA_R, OBJETIVO_R = 0.5, 2.0
COIN_FLIP, STRONG = 0.05, 0.15          # mismos umbrales que trader-timemachine
EPOCH = datetime.datetime(1970, 1, 1)
CIERRE = "Análisis y simulación. No se han enviado órdenes ni modificado alertas."
DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
ETIQUETAS = [  # (etiqueta, palabras) para las noticias
    ("regulación", ("sec ", "regulat", "lawsuit", "court", "ban ", "law ")),
    ("ETF", ("etf",)),
    ("hackeo", ("hack", "exploit", "breach", "stolen")),
    ("macro", ("fed ", "inflation", "rate cut", "rates", "cpi", "powell", "tariff")),
    ("listado", ("listing", "lists ", "delist")),
    ("ballenas", ("whale",)),
]


class Error(Exception):
    pass


# ---------------------------------------------------------------- hora de Madrid

def _ultimo_domingo(anio, mes):
    d = datetime.date(anio, mes + 1, 1) - datetime.timedelta(days=1) if mes < 12 else datetime.date(anio, 12, 31)
    return d - datetime.timedelta(days=(d.weekday() + 1) % 7)


def a_madrid(ts):
    """Segundos Unix -> datetime local de Madrid (CET/CEST, regla de la UE)."""
    utc = EPOCH + datetime.timedelta(seconds=int(ts))
    ini = datetime.datetime.combine(_ultimo_domingo(utc.year, 3), datetime.time(1))
    fin = datetime.datetime.combine(_ultimo_domingo(utc.year, 10), datetime.time(1))
    return utc + datetime.timedelta(hours=2 if ini <= utc < fin else 1)


def hora(ts):
    return a_madrid(ts).strftime("%d/%m %H:%M")


def es_fin_de_semana(ts):
    return a_madrid(ts).weekday() >= 5


def parse_ahora(texto):
    """'2026-11-27 20:15' (hora de Madrid) o ISO con zona -> segundos Unix. Vacío: ahora."""
    if not texto:
        return int(time.time())
    t = texto.strip().replace("Z", "+00:00")
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise Error("no entiendo la hora %r (usa AAAA-MM-DD HH:MM, hora de Madrid)" % texto)
    if d.tzinfo is not None:
        return int(d.timestamp())
    # hora de Madrid: prueba los dos desfases y se queda con el que cuadra
    for off in (1, 2):
        ts = int((d - datetime.timedelta(hours=off) - EPOCH).total_seconds())
        if a_madrid(ts) == d:
            return ts
    return int((d - datetime.timedelta(hours=1) - EPOCH).total_seconds())


# ---------------------------------------------------------------- formato

def fmt(x, dec=None):
    """Número en formato español; decimales según el precio."""
    if x is None:
        return "sin dato"
    if dec is None:
        a = abs(x)
        dec = 0 if a >= 1000 else 2 if a >= 10 else 3 if a >= 1 else 4 if a >= 0.1 else 6
    s = ("{:,.%df}" % dec).format(x)
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def pct(x, dec=2):
    return fmt(x, dec) + " %"


def unidades_dec(precio):
    """Decimales de las unidades para que el paso valga en torno a 1 dólar o menos."""
    return max(0, min(8, int(math.ceil(math.log10(precio))))) if precio > 0 else 2


def suelo(x, dec):
    f = 10 ** dec
    return math.floor(x * f + 1e-9) / f


# ---------------------------------------------------------------- datos

def par(moneda):
    return moneda.lower() + "usd"


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for intento in (0, 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento == 0:
                time.sleep(3)
                continue
            raise Error("%s respondió HTTP %s" % (url.split("?")[0], e.code))
        except (urllib.error.URLError, OSError) as e:
            raise Error("no se pudo leer %s: %s" % (url.split("?")[0], e))


def normalizar(doc):
    """Velas de Bitstamp, de mcp-tv-get-ohlcv o una lista -> [{t,o,h,l,c,v}] ordenadas."""
    if isinstance(doc, dict):
        if "data" in doc and isinstance(doc["data"], dict) and "ohlc" in doc["data"]:
            doc = doc["data"]["ohlc"]
        else:
            for k in ("bars", "data", "rows", "ohlcv", "ohlc"):
                if k in doc:
                    return normalizar(doc[k])
            if isinstance(doc.get("t"), list):
                n = len(doc["t"])
                doc = [{k: (doc.get(k) or [None] * n)[i] for k in ("t", "o", "h", "l", "c", "v")} for i in range(n)]
    if not isinstance(doc, list):
        raise Error("los datos no tienen velas reconocibles")
    out = {}
    for b in doc:
        if not isinstance(b, dict):
            continue
        t = b.get("t", b.get("timestamp"))
        c = b.get("c", b.get("close"))
        if t is None or c is None:
            continue
        c = float(c)
        out[int(t)] = {"t": int(t), "o": float(b.get("o", b.get("open", c))),
                       "h": float(b.get("h", b.get("high", c))), "l": float(b.get("l", b.get("low", c))),
                       "c": c, "v": float(b.get("v", b.get("volume")) or 0)}
    return [out[k] for k in sorted(out)]


def bajar_velas(moneda, paso, cuantas):
    """Velas de Bitstamp, en páginas de 1.000, de más reciente a más antigua."""
    velas, fin = {}, None
    while len(velas) < cuantas:
        n = min(1000, cuantas - len(velas))
        url = "%s/ohlc/%s/?step=%d&limit=%d" % (BITSTAMP, par(moneda), paso, n)
        if fin:
            url += "&end=%d" % fin
        pagina = normalizar(json.loads(_get(url).decode("utf-8")))
        nuevas = [b for b in pagina if b["t"] not in velas]
        if not nuevas:
            break
        for b in nuevas:
            velas[b["t"]] = b
        fin = min(velas) - 1
        if len(pagina) < n:
            break
    return [velas[k] for k in sorted(velas)]


def cargar(moneda, offline=None, horas=1000):
    """(velas 1h, velas 4h) de la moneda, en vivo o desde offline/<par>-1h.json y -4h.json."""
    if offline:
        res = []
        for tf in ("1h", "4h"):
            ruta = os.path.join(offline, "%s-%s.json" % (par(moneda), tf))
            try:
                with open(ruta, encoding="utf-8") as fh:
                    res.append(normalizar(json.load(fh)))
            except (OSError, ValueError) as e:
                raise Error("no se pudo leer %s: %s" % (ruta, e))
        return res[0], res[1]
    return bajar_velas(moneda, H1, horas), bajar_velas(moneda, H4, max(200, horas // 4 + 120))


def cerradas(velas, paso, ahora):
    return [b for b in velas if b["t"] + paso <= ahora]


def revisar_velas(velas, paso, ultimas):
    """Problemas en las `ultimas` velas: huecos de tiempo o velas imposibles (máximo por
    debajo del mínimo, apertura o cierre fuera del rango). Lista vacía si todo cuadra."""
    tramo = velas[-ultimas:]
    out = []
    for a, b in zip(tramo, tramo[1:]):
        if b["t"] - a["t"] != paso:
            out.append("falta la vela de las %s" % hora(a["t"] + paso))
    for b in tramo:
        if not (b["l"] <= min(b["o"], b["c"]) and max(b["o"], b["c"]) <= b["h"]) or b["c"] <= 0:
            out.append("vela imposible a las %s" % hora(b["t"]))
    return out


# ---------------------------------------------------------------- indicadores

def ema(xs, n):
    out, k, e = [], 2.0 / (n + 1), None
    for i, x in enumerate(xs):
        if i + 1 < n:
            out.append(None)
            continue
        e = sum(xs[i + 1 - n:i + 1]) / n if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def ema_libre(xs, n):
    """EMA que arranca en el primer valor (para el MACD)."""
    out, k, e = [], 2.0 / (n + 1), None
    for x in xs:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(xs, n=14):
    if len(xs) <= n:
        return None
    g = sum(max(xs[i] - xs[i - 1], 0) for i in range(1, n + 1)) / n
    p = sum(max(xs[i - 1] - xs[i], 0) for i in range(1, n + 1)) / n
    for i in range(n + 1, len(xs)):
        d = xs[i] - xs[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        p = (p * (n - 1) + max(-d, 0)) / n
    return 100.0 if p == 0 else 100 - 100 / (1 + g / p)


def indicadores(v1):
    """RSI, MACD, Bollinger y volumen de la última vela 1h cerrada."""
    cs = [b["c"] for b in v1]
    if len(cs) < 35:
        return None
    m = [a - b for a, b in zip(ema_libre(cs, 12), ema_libre(cs, 26))]
    s = ema_libre(m, 9)
    w = cs[-20:]
    media, sd = sum(w) / 20.0, statistics.pstdev(w)
    sup, inf = media + 2 * sd, media - 2 * sd
    vols = [b["v"] for b in v1]
    vmed = sum(vols[-21:-1]) / 20.0
    return {"rsi": rsi(cs), "macd": m[-1], "senal": s[-1], "hist": m[-1] - s[-1],
            "bb_media": media, "bb_sup": sup, "bb_inf": inf,
            "bb_pos": (cs[-1] - inf) / (sup - inf) if sup > inf else 0.5,
            "bb_ancho": (sup - inf) / media * 100 if media else None,
            "vol": vols[-1], "vol_media": vmed, "vol_rel": vols[-1] / vmed if vmed else None}


# ---------------------------------------------------------------- la regla del script

def contexto(v4, inicio_1h):
    """(cierre 4h, EMA 50 4h) de la vela de 4h anterior a la que contiene la vela de 1h."""
    cubo = inicio_1h // H4 * H4
    idx = {b["t"]: i for i, b in enumerate(v4)}
    i = idx.get(cubo - H4)
    if i is None:
        return None, None
    e = ema([b["c"] for b in v4[:i + 1]], N_EMA)[-1]
    return v4[i]["c"], e


def senal_en(v1, j, v4):
    """Señal de la vela 1h j (cerrada) o None. Igual que evaluar() del script de Pine."""
    if j < N_RUPTURA:
        return None
    c4, e4 = contexto(v4, v1[j]["t"])
    if c4 is None or e4 is None:
        return None
    b = v1[j]
    hh = max(x["h"] for x in v1[j - N_RUPTURA:j])
    ll = min(x["l"] for x in v1[j - N_RUPTURA:j])
    if c4 > e4 and b["c"] > hh:
        lado, nivel, stop = "COMPRA", hh, min(x["l"] for x in v1[j - N_STOP + 1:j + 1])
    elif c4 < e4 and b["c"] < ll:
        lado, nivel, stop = "VENTA", ll, max(x["h"] for x in v1[j - N_STOP + 1:j + 1])
    else:
        return None
    R = abs(b["c"] - stop)
    if R <= 0:
        return None
    largo = lado == "COMPRA"
    zona = (nivel, nivel + ZONA_R * R) if largo else (nivel - ZONA_R * R, nivel)
    return {"lado": lado, "j": j, "t": b["t"], "cierre_ts": b["t"] + H1, "entrada": b["c"], "nivel": nivel,
            "stop": stop, "R": R, "zona": zona, "en_zona": zona[0] <= b["c"] <= zona[1],
            "objetivo": b["c"] + OBJETIVO_R * R if largo else b["c"] - OBJETIVO_R * R,
            "contexto": (c4, e4)}


def seguir(s, v1):
    """Qué ha pasado desde la señal: stop, objetivo o sigue abierta (stop primero si ambos en una vela)."""
    largo = s["lado"] == "COMPRA"
    for b in v1[s["j"] + 1:]:
        toca_stop = b["l"] <= s["stop"] if largo else b["h"] >= s["stop"]
        toca_obj = b["h"] >= s["objetivo"] if largo else b["l"] <= s["objetivo"]
        if toca_stop:
            return {"estado": "invalidada", "ts": b["t"] + H1}
        if toca_obj:
            return {"estado": "objetivo", "ts": b["t"] + H1}
    ultimo = v1[-1]["c"]
    zona = s["zona"]
    return {"estado": "abierta", "en_zona": zona[0] <= ultimo <= zona[1], "ultimo": ultimo}


def estado_moneda(moneda, v1, v4, ahora, vigencia=24):
    """Todo lo que la revisión necesita de una moneda."""
    v1, v4 = cerradas(v1, H1, ahora), cerradas(v4, H4, ahora)
    if len(v1) < N_RUPTURA + 2 or len(v4) < N_EMA + 2:
        return {"moneda": moneda, "ahora": "NO EVALUABLE", "motivo": "faltan velas cerradas"}
    ult = v1[-1]
    retraso = (ahora // H1 * H1) - (ult["t"] + H1)
    res = {"moneda": moneda, "cierre": ult["c"], "cierre_ts": ult["t"] + H1, "retraso_h": max(retraso, 0) / 3600.0}
    if retraso > 24 * 3600:
        res.update(ahora="NO EVALUABLE", motivo="el último dato tiene más de 24 h de retraso")
        return res
    problemas = revisar_velas(v1, H1, vigencia + N_RUPTURA + 1) + revisar_velas(v4, H4, N_EMA)
    if problemas:
        res.update(ahora="NO EVALUABLE", motivo="datos dudosos: " + "; ".join(problemas[:3]))
        return res
    # condiciones para la vela siguiente
    # la vela siguiente toma su contexto de la última vela de 4h ya cerrada
    c4, e4 = v4[-1]["c"], ema([b["c"] for b in v4], N_EMA)[-1]
    hh = max(x["h"] for x in v1[-N_RUPTURA:])
    ll = min(x["l"] for x in v1[-N_RUPTURA:])
    alcista = c4 > e4
    res.update(contexto={"cierre4h": c4, "ema50": e4, "alcista": alcista},
               compra_si=hh if alcista else None, venta_si=None if alcista else ll,
               stop_compra=min(x["l"] for x in v1[-N_STOP + 1:]),
               stop_venta=max(x["h"] for x in v1[-N_STOP + 1:]),
               indicadores=indicadores(v1), atr=atr(v1)[-1])
    # última señal dentro de la vigencia
    ultima = None
    for j in range(len(v1) - 1, max(N_RUPTURA - 1, len(v1) - 1 - vigencia), -1):
        s = senal_en(v1, j, v4)
        if s:
            ultima = s
            break
    res["ultima_senal"] = ultima
    if ultima:
        ultima["seguimiento"] = seguir(ultima, v1)
        ultima["nota_stop"] = nota_stop(ultima["R"], atr(v1)[ultima["j"]])
    if ultima and ultima["j"] == len(v1) - 1:
        res["ahora"] = "%s activada%s" % (ultima["lado"], "" if ultima["en_zona"] else " (fuera de zona)")
    else:
        res["ahora"] = "ESPERAR"
    return res


ICONO = {"COMPRA": "🟢", "VENTA": "🔴"}


def nota_stop(R, a):
    """Distancia del stop en ATR de 1h y aviso si está dentro del ruido o muy lejos."""
    if not a:
        return ""
    k = R / a
    if k < 1.0:
        aviso = ": muy cerca, el movimiento normal de una hora puede tocarlo"
    elif k > 4.0:
        aviso = ": muy lejos, la operación sale pequeña"
    else:
        aviso = ""
    return "stop a %s ATR%s" % (fmt(k, 1), aviso)


def etiqueta_ahora(ahora):
    if ahora.startswith("COMPRA"):
        return "🟢 " + ahora
    if ahora.startswith("VENTA"):
        return "🔴 " + ahora
    if ahora == "ESPERAR":
        return "⏸️ ESPERAR"
    return ahora


# ---------------------------------------------------------------- simulación (time machine)

def pool_horario(v1):
    """pool[h] = (o, h, l, c) / cierre anterior de cada vela 1h que empieza a la hora UTC h."""
    pool = [[] for _ in range(24)]
    for i in range(1, len(v1)):
        pc = v1[i - 1]["c"]
        if pc <= 0 or v1[i]["t"] - v1[i - 1]["t"] != H1:
            continue
        b = v1[i]
        pool[(b["t"] // H1) % 24].append((b["o"] / pc, b["h"] / pc, b["l"] / pc, b["c"] / pc))
    return pool


def simular(v1, entrada, stop, objetivo, inicio_ts, horas=48, recorridos=10000, semilla=19, ventana=1):
    """Monte Carlo: reconstruye las próximas `horas` velas tomando, para cada hora del día,
    una vela real de esa hora (± ventana) de la historia descargada."""
    largo = stop < entrada
    riesgo = abs(entrada - stop)
    r_obj = abs(objetivo - entrada) / riesgo
    pool = pool_horario(v1)
    if sum(len(p) for p in pool) < 24 * 20:
        raise Error("hacen falta al menos 20 días de velas de 1h para simular")
    rng = random.Random(semilla)
    h0 = (inicio_ts // H1) % 24
    res, finales, Rs = {"objetivo": 0, "stop": 0, "ninguno": 0}, [], []
    for _ in range(recorridos):
        p, fin = entrada, None
        for k in range(horas):
            h = (h0 + k + rng.randint(-ventana, ventana)) % 24
            cand = pool[h] or pool[(h0 + k) % 24]
            o, hi, lo, c = rng.choice(cand)
            alto, bajo = p * hi, p * lo
            if fin is None:
                if (bajo <= stop) if largo else (alto >= stop):
                    fin = "stop"
                elif (alto >= objetivo) if largo else (bajo <= objetivo):
                    fin = "objetivo"
            p = p * c
        fin = fin or "ninguno"
        res[fin] += 1
        finales.append(p)
        Rs.append(r_obj if fin == "objetivo" else -1.0 if fin == "stop" else
                  ((p - entrada) if largo else (entrada - p)) / riesgo)
    srt = sorted(finales)
    q = lambda f: srt[min(len(srt) - 1, int(f * len(srt)))]
    n = float(recorridos)
    return {"recorridos": recorridos, "horas": horas, "semilla": semilla, "r_objetivo": r_obj,
            "p_objetivo": res["objetivo"] / n, "p_stop": res["stop"] / n, "p_ninguno": res["ninguno"] / n,
            "R_medio": statistics.mean(Rs), "mediana": q(0.5), "p5": q(0.05), "p95": q(0.95)}


def veredicto(mc):
    pt, ps = mc["p_objetivo"], mc["p_stop"]
    if pt + ps <= 0:
        return "Ningún recorrido llegó al objetivo ni al stop: decide el precio al final."
    cuota, empate = pt / (pt + ps), 1.0 / (1.0 + mc["r_objetivo"])
    d = cuota - empate
    if abs(d) < COIN_FLIP:
        cab = "Cerca de quedar a la par"
    elif abs(d) < STRONG:
        cab = "Se inclina hacia el objetivo" if d > 0 else "Se inclina hacia el stop"
    else:
        cab = "Claramente hacia el objetivo" if d > 0 else "Claramente hacia el stop"
    return ("%s: con objetivo a %sR, para no perder el objetivo tiene que llegar antes en el %s de los "
            "recorridos que tocan un lado; llega en el %s." % (
                cab, fmt(mc["r_objetivo"], 1), pct(100 * empate, 0), pct(100 * cuota, 0)))


def atr(v1, n=14):
    """ATR de Wilder de cada vela (None mientras no hay n velas)."""
    tr = [v1[0]["h"] - v1[0]["l"]] + [max(b["h"] - b["l"], abs(b["h"] - a["c"]), abs(b["l"] - a["c"]))
                                      for a, b in zip(v1, v1[1:])]
    out, r = [], None
    for i, x in enumerate(tr):
        if i + 1 < n:
            out.append(None)
            continue
        r = sum(tr[:n]) / n if r is None else (r * (n - 1) + x) / n
        out.append(r)
    return out


# Variantes de stop que se comparan en `estudiar`. "regla" es la del script y la que se usa.
VARIANTES_STOP = [
    ("regla", "mínimo/máximo de 10 velas (la regla)"),
    ("colchon", "regla + 0,25 ATR de colchón"),
    ("atr15", "1,5 ATR desde la entrada"),
    ("min20", "mínimo/máximo de 20 velas"),
]


def stop_variante(modo, s, v1, atrs):
    j, largo, e = s["j"], s["lado"] == "COMPRA", s["entrada"]
    a = atrs[j]
    if modo == "regla":
        return s["stop"]
    if a is None:
        return None
    if modo == "colchon":
        return s["stop"] - 0.25 * a if largo else s["stop"] + 0.25 * a
    if modo == "atr15":
        return e - 1.5 * a if largo else e + 1.5 * a
    if modo == "min20":
        tramo = v1[max(0, j - 19):j + 1]
        return min(x["l"] for x in tramo) if largo else max(x["h"] for x in tramo)
    raise Error("variante de stop desconocida: %s" % modo)


def senales(v1, v4, lado=None, solo_zona=True):
    out = []
    for j in range(N_RUPTURA, len(v1)):
        s = senal_en(v1, j, v4)
        if s and (not lado or s["lado"] == lado) and (s["en_zona"] or not solo_zona):
            out.append(s)
    return out


def operaciones(v1, lista, horas=48, stop_modo="regla", obj_r=OBJETIVO_R, coste_pct=0.0, atrs=None):
    """Cada señal como una operación, sin solaparse: mientras una sigue abierta no se abre
    otra en la misma moneda (las señales seguidas no se cuentan varias veces). Entrada al
    cierre de la vela de la señal; sale en el stop, en el objetivo o al pasar `horas`.
    Si una vela toca stop y objetivo, cuenta el stop. El coste (comisión + diferencial, en %
    ida y vuelta) se descuenta en R."""
    atrs = atrs or atr(v1)
    filas, libre_desde = [], -1
    for s in lista:
        j = s["j"]
        if j <= libre_desde:
            continue
        largo, e = s["lado"] == "COMPRA", s["entrada"]
        stop = stop_variante(stop_modo, s, v1, atrs)
        if stop is None or (largo and stop >= e) or (not largo and stop <= e):
            continue
        R = abs(e - stop)
        obj = e + obj_r * R if largo else e - obj_r * R
        tramo = v1[j + 1:j + 1 + horas]
        if len(tramo) < horas and not any(
                ((b["l"] <= stop or b["h"] >= obj) if largo else (b["h"] >= stop or b["l"] <= obj)) for b in tramo):
            continue  # aún no ha terminado: no se cuenta
        fin, res, k = None, None, j + len(tramo)
        for n, b in enumerate(tramo):
            if (b["l"] <= stop) if largo else (b["h"] >= stop):
                fin, res, k = "stop", -1.0, j + 1 + n
                break
            if (b["h"] >= obj) if largo else (b["l"] <= obj):
                fin, res, k = "objetivo", obj_r, j + 1 + n
                break
        if fin is None:
            p = tramo[-1]["c"]
            fin, res = "ninguno", ((p - e) if largo else (e - p)) / R
        res -= coste_pct / 100.0 * e / R
        libre_desde = k
        filas.append({"ts": s["cierre_ts"], "lado": s["lado"], "fin": fin, "R": res, "riesgo_pct": 100 * R / e})
    return filas


def historial(v1, v4, horas=48, lado=None):
    """Operaciones pasadas de la regla tal cual (sin costes)."""
    return operaciones(v1, senales(v1, v4, lado), horas)


def resumen(filas):
    if not filas:
        return {"n": 0}
    rs = [f["R"] for f in filas]
    gan, per = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return {"n": len(rs), "acierto": 100.0 * sum(1 for r in rs if r > 0) / len(rs),
            "R_medio": sum(rs) / len(rs), "R_total": sum(rs),
            "factor": gan / per if per > 0 else None,
            "objetivo": sum(f["fin"] == "objetivo" for f in filas), "stop": sum(f["fin"] == "stop" for f in filas)}


# ---------------------------------------------------------------- tamaño y riesgo

def tamano(capital, riesgo_pct, entrada, stop, tope_pct=100.0):
    R = abs(entrada - stop)
    if R <= 0:
        raise Error("la entrada y el stop no pueden ser iguales")
    dec = unidades_dec(entrada)
    por_riesgo = capital * riesgo_pct / 100.0 / R
    por_capital = capital * tope_pct / 100.0 / entrada
    limite = "riesgo" if por_riesgo <= por_capital else "capital (sin apalancamiento)"
    u = suelo(min(por_riesgo, por_capital), dec)
    return {"unidades": u, "decimales": dec, "R": R, "importe": u * entrada, "perdida": u * R,
            "limite": limite, "riesgo_objetivo": capital * riesgo_pct / 100.0}


def comprobar_riesgo(capital, riesgo_pct, entrada, stop, objetivos, lado, ahora_ts,
                     abiertas=0, perdida_hoy_pct=0.0, max_pct=1.0, finde_pct=0.75, max_abiertas=3,
                     perdida_diaria_pct=2.0, rb_min=2.0):
    """Lista de (PASA|BLOQUEA|AVISO, texto). Los límites son los del método del usuario."""
    out = []
    largo = lado == "COMPRA"
    if stop is None:
        return [("BLOQUEA", "no hay stop: toda operación necesita invalidación")]
    if (largo and stop >= entrada) or (not largo and stop <= entrada):
        out.append(("BLOQUEA", "el stop está del lado equivocado de la entrada"))
        return out
    out.append(("PASA", "hay stop en %s" % fmt(stop)))
    R = abs(entrada - stop)
    for o in objetivos:
        rb = ((o - entrada) if largo else (entrada - o)) / R
        out.append(("PASA" if rb >= rb_min - 1e-9 else "BLOQUEA",
                    "objetivo %s: beneficio/riesgo %s a 1 (mínimo %s)" % (fmt(o), fmt(rb, 2), fmt(rb_min, 0))))
    tope = finde_pct if es_fin_de_semana(ahora_ts) else max_pct
    motivo = "fin de semana" if es_fin_de_semana(ahora_ts) else "día normal"
    out.append(("PASA" if riesgo_pct <= tope + 1e-9 else "BLOQUEA",
                "riesgo %s del capital (máximo %s, %s)" % (pct(riesgo_pct), pct(tope), motivo)))
    out.append(("PASA" if abiertas < max_abiertas else "BLOQUEA",
                "posiciones abiertas: %d (máximo %d)" % (abiertas, max_abiertas)))
    out.append(("PASA" if perdida_hoy_pct < perdida_diaria_pct else "BLOQUEA",
                "pérdida de hoy: %s (tope diario %s)" % (pct(perdida_hoy_pct), pct(perdida_diaria_pct))))
    t = tamano(capital, riesgo_pct, entrada, stop)
    out.append(("PASA" if t["importe"] <= capital + 1e-6 else "BLOQUEA",
                "importe %s de %s de capital, sin apalancamiento" % (fmt(t["importe"], 2), fmt(capital, 0))))
    if not largo:
        out.append(("AVISO", "VENTA = abrir corto: solo en simulación (en Quantfury se permite)"))
    return out


# ---------------------------------------------------------------- fichas y noticias

def ficha(n, moneda, lado, nivel, marco, condicion, caduca_ts, texto_extra=""):
    if lado == "COMPRA":
        cab, op = "🟢 COMPRA", "🟢 COMPRA (abrir largo)"
    elif lado == "VENTA":
        cab, op = "🔴 VENTA", "🔴 VENTA (abrir corto)"
    else:
        cab, op = "⏸️ ESPERAR", "⏸️ ESPERAR (aviso, no se abre nada)"
    signo = ">" if "encima" in condicion or "alza" in condicion else "<"
    texto = "%s %s, vela %s %s %s%s" % (cab, moneda, marco, "cierra" if "Cierre" in condicion else "cruza",
                                       signo + " " + fmt(nivel), (", " + texto_extra) if texto_extra else "")
    return "\n".join([
        "FICHA %d \u2013 PROPUESTA \u2013 %s" % (n, cab),
        "Símbolo:     BITSTAMP:%sUSD" % moneda,
        "Operación:   %s" % op,
        "Nivel:       %s" % fmt(nivel),
        "Marco:       %s" % marco,
        "Condición:   %s" % condicion,
        "Tipo:        Una vez por cierre de barra",
        "Caducidad:   %s (Madrid)" % hora(caduca_ts),
        "Texto:       \"%s\"" % texto,
    ])


def parse_noticias(xml_bytes, moneda):
    out = []
    try:
        raiz = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return out
    for it in raiz.iter("item"):
        titulo = (it.findtext("title") or "").strip()
        enlace = (it.findtext("link") or "").strip()
        fecha = it.findtext("pubDate") or ""
        try:
            ts = int(datetime.datetime.strptime(fecha.strip(), "%a, %d %b %Y %H:%M:%S %z").timestamp())
        except ValueError:
            continue
        low = " " + titulo.lower() + " "
        tags = [e for e, pals in ETIQUETAS if any(p in low for p in pals)]
        out.append({"moneda": moneda, "ts": ts, "titulo": titulo, "enlace": enlace, "etiquetas": tags})
    return out


# ---------------------------------------------------------------- informes

def linea_tabla(r):
    if r.get("ahora") == "NO EVALUABLE":
        return "| %s | sin dato | NO EVALUABLE | | | |" % r["moneda"]
    compra = "vela 1h cierra > %s" % fmt(r["compra_si"]) if r.get("compra_si") is not None else "no (4h bajista)"
    venta = "vela 1h cierra < %s" % fmt(r["venta_si"]) if r.get("venta_si") is not None else "no (4h alcista)"
    return "| %s | %s (%s) | %s | %s | %s | %s |" % (
        r["moneda"], fmt(r["cierre"]), hora(r["cierre_ts"]), etiqueta_ahora(r["ahora"]), compra, venta,
        hora(r["cierre_ts"] + 24 * H1))


def texto_senal(s):
    seg = s.get("seguimiento") or {}
    if seg.get("estado") == "invalidada":
        ahora = "invalidada: tocó el stop (vela que cerró a las %s)" % hora(seg["ts"])
    elif seg.get("estado") == "objetivo":
        ahora = "llegó al objetivo (vela que cerró a las %s)" % hora(seg["ts"])
    elif seg:
        ahora = "sigue abierta, precio %s %s" % (fmt(seg["ultimo"]), "dentro de la zona" if seg["en_zona"]
                                                   else "fuera de la zona: no perseguir")
    else:
        ahora = ""
    return ("%s %s · vela 1h cerrada a las %s · cierre %s · zona de entrada %s a %s (%s) · "
            "invalidación %s · objetivo 2R %s%s" % (
                ICONO[s["lado"]], s["lado"], hora(s["cierre_ts"]), fmt(s["entrada"]), fmt(s["zona"][0]),
                fmt(s["zona"][1]), "en zona" if s["en_zona"] else "fuera de zona", fmt(s["stop"]),
                fmt(s["objetivo"]), (" · " + s["nota_stop"]) if s.get("nota_stop") else "") +
            ((" · ahora: " + ahora) if ahora else ""))


def informe(resultados):
    out = ["| Activo | Último cierre (hora) | Ahora | 🟢 COMPRA si | 🔴 VENTA si | Caducidad |",
           "|---|---|---|---|---|---|"]
    out += [linea_tabla(r) for r in resultados]
    for r in resultados:
        out.append("")
        if r.get("ahora") == "NO EVALUABLE":
            out.append("%s: NO EVALUABLE, %s." % (r["moneda"], r.get("motivo", "sin datos")))
            continue
        cx = r["contexto"]
        out.append("%s · contexto 4h: cierre %s %s de la EMA 50 (%s): %s." % (
            r["moneda"], fmt(cx["cierre4h"]), "por encima" if cx["alcista"] else "por debajo", fmt(cx["ema50"]),
            "solo se buscan COMPRAS" if cx["alcista"] else "solo se buscan VENTAS"))
        ind = r.get("indicadores")
        if ind:
            out.append("  1h: RSI %s · MACD %s / señal %s / histograma %s · Bollinger %s (ancho %s) · "
                       "volumen %s de su media" % (
                           fmt(ind["rsi"], 2), fmt(ind["macd"]), fmt(ind["senal"]), fmt(ind["hist"]),
                           "mitad alta" if ind["bb_pos"] >= 0.5 else "mitad baja", pct(ind["bb_ancho"], 1),
                           pct(100 * ind["vol_rel"], 0) if ind["vol_rel"] is not None else "sin dato"))
        if r.get("ultima_senal"):
            out.append("  Última señal (24 h): " + texto_senal(r["ultima_senal"]))
        if r.get("retraso_h"):
            out.append("  Aviso: el dato llega con %s h de retraso." % fmt(r["retraso_h"], 0))
    out += ["", "Datos: velas cerradas de Bitstamp, horas de Madrid.", CIERRE]
    return "\n".join(out)


# ---------------------------------------------------------------- comandos

def _monedas(lista):
    ms = [m.upper().replace("USD", "").replace("BITSTAMP:", "") for m in (lista or MONEDAS)]
    return ms


def cmd_escanear(a):
    ahora = parse_ahora(a.ahora)
    res = []
    for m in _monedas(a.monedas):
        try:
            v1, v4 = cargar(m, a.offline, a.horas)
            res.append(estado_moneda(m, v1, v4, ahora, a.vigencia))
        except Error as e:
            res.append({"moneda": m, "ahora": "NO EVALUABLE", "motivo": str(e)})
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str) if a.json else informe(res))
    return 0


def cmd_senal(a):
    ahora = parse_ahora(a.ahora)
    m = _monedas([a.moneda])[0]
    v1, v4 = cargar(m, a.offline, a.horas)
    r = estado_moneda(m, v1, v4, ahora, a.vigencia)
    print(informe([r]).rsplit("\n\nDatos:", 1)[0])
    if r.get("ahora") == "NO EVALUABLE":
        return 1
    print("")
    caduca = r["cierre_ts"] + 24 * H1
    if r.get("compra_si") is not None:
        print(ficha(1, m, "COMPRA", r["compra_si"], "1h", "Cierre por encima", caduca, "revisar volumen"))
        st = r["stop_compra"]
        if st < r["compra_si"]:
            R = r["compra_si"] - st
            print("\nPlan si salta: entrada %s · invalidación %s (mínimo de las 10 últimas velas) · R %s · "
                  "objetivo 2R %s · zona hasta %s · %s. El stop se recalcula con las velas de ese momento." % (
                      fmt(r["compra_si"]), fmt(st), fmt(R), fmt(r["compra_si"] + 2 * R), fmt(r["compra_si"] + 0.5 * R),
                      nota_stop(R, r.get("atr"))))
    if r.get("venta_si") is not None:
        print(ficha(1, m, "VENTA", r["venta_si"], "1h", "Cierre por debajo", caduca, "revisar volumen"))
        st = r["stop_venta"]
        if st > r["venta_si"]:
            R = st - r["venta_si"]
            print("\nPlan si salta: entrada %s · invalidación %s (máximo de las 10 últimas velas) · R %s · "
                  "objetivo 2R %s · zona hasta %s · %s." % (
                      fmt(r["venta_si"]), fmt(st), fmt(R), fmt(r["venta_si"] - 2 * R), fmt(r["venta_si"] - 0.5 * R),
                      nota_stop(R, r.get("atr"))))
    cx = r["contexto"]
    print("")
    print(ficha(2, m, "ESPERAR", cx["ema50"], "4h", "Cierre por debajo" if cx["alcista"] else "Cierre por encima",
                caduca, "cambia la tendencia de 4h"))
    print("\n" + CIERRE)
    return 0


def _plan_de(a, v1, v4, ahora):
    """Entrada, stop y objetivo: de los argumentos o de la última señal de la regla."""
    if a.entrada is not None and a.stop is not None:
        largo = a.stop < a.entrada
        obj = a.objetivo if a.objetivo is not None else a.entrada + (2 if largo else -2) * abs(a.entrada - a.stop)
        return a.entrada, a.stop, obj, "plan indicado"
    r = estado_moneda(a.moneda.upper(), v1, v4, ahora, a.vigencia)
    s = r.get("ultima_senal")
    if s:
        return s["entrada"], s["stop"], s["objetivo"], "señal %s de las %s" % (s["lado"], hora(s["cierre_ts"]))
    if r.get("compra_si") is not None and r["stop_compra"] < r["compra_si"]:
        e = r["compra_si"]
        return e, r["stop_compra"], e + 2 * (e - r["stop_compra"]), "compra hipotética si rompe %s" % fmt(e)
    if r.get("venta_si") is not None and r["stop_venta"] > r["venta_si"]:
        e = r["venta_si"]
        return e, r["stop_venta"], e - 2 * (r["stop_venta"] - e), "venta hipotética si rompe %s" % fmt(e)
    raise Error("no hay plan: indica --entrada y --stop")


def cmd_simular(a):
    ahora = parse_ahora(a.ahora)
    m = a.moneda.upper()
    v1, v4 = cargar(m, a.offline, a.horas_datos)
    v1c, v4c = cerradas(v1, H1, ahora), cerradas(v4, H4, ahora)
    entrada, stop, obj, origen = _plan_de(a, v1c, v4c, ahora)
    lado = "COMPRA" if stop < entrada else "VENTA"
    mc = simular(v1c, entrada, stop, obj, v1c[-1]["t"] + H1, a.horas, a.recorridos, a.semilla)
    hist = historial(v1c, v4c, a.horas, lado)
    dias = (v1c[-1]["t"] - v1c[0]["t"]) / 86400.0
    out = ["%s %s %s (%s) · entrada %s · stop %s · objetivo %s · próximas %d h" % (
        ICONO[lado], lado, m, origen, fmt(entrada), fmt(stop), fmt(obj), a.horas), "",
        "%s recorridos con velas reales de las mismas horas del día (últimos %s días de Bitstamp):" % (
            fmt(mc["recorridos"], 0), fmt(dias, 0)),
        "| Resultado | Probabilidad |", "|---|---|",
        "| Llega antes al objetivo | %s |" % pct(100 * mc["p_objetivo"], 1),
        "| Llega antes al stop | %s |" % pct(100 * mc["p_stop"], 1),
        "| Ni uno ni otro en %d h | %s |" % (a.horas, pct(100 * mc["p_ninguno"], 1)), "",
        "R medio: %s · precio a las %d h: mediana %s (5 %%: %s, 95 %%: %s)" % (
            fmt(mc["R_medio"], 3), a.horas, fmt(mc["mediana"]), fmt(mc["p5"]), fmt(mc["p95"])),
        "Veredicto: " + veredicto(mc), ""]
    if hist:
        n = len(hist)
        out.append("Historia: %d operaciones de %s en zona (sin contar dos veces señales seguidas). Objetivo %d · "
                   "stop %d · ni uno ni otro %d · R medio %s, sin costes." % (n, lado, sum(h["fin"] == "objetivo" for h in hist),
                                    sum(h["fin"] == "stop" for h in hist), sum(h["fin"] == "ninguno" for h in hist),
                                    fmt(statistics.mean(h["R"] for h in hist), 2)))
        if n < 20:
            out.append("Son pocas operaciones: el resultado puede deberse a la suerte.")
    else:
        out.append("Historia: ninguna señal de %s en zona en los datos descargados." % lado)
    out += ["", "Una simulación usa el pasado: no garantiza lo que pasará.", CIERRE]
    print(json.dumps({"montecarlo": mc, "historia": hist}, ensure_ascii=False, indent=1) if a.json else "\n".join(out))
    return 0


OBJETIVOS_R = (1.5, 2.0, 3.0)


def estudio(datos, horas=48, coste_pct=0.1, lado=None):
    """datos = {moneda: (v1, v4)} cerradas. Compara cada stop × objetivo en dos mitades del
    periodo. Devuelve filas por variante (todas las monedas juntas) y por moneda (la regla)."""
    t_ini = max(v1[0]["t"] for v1, _ in datos.values())
    t_fin = min(v1[-1]["t"] for v1, _ in datos.values())
    corte = t_ini + (t_fin - t_ini) // 2
    filas, por_moneda = [], {}
    cache = {m: (senales(v1, v4, lado), atr(v1)) for m, (v1, v4) in datos.items()}
    for modo, texto in VARIANTES_STOP:
        for r in OBJETIVOS_R:
            p1, p2 = [], []
            for m, (v1, v4) in datos.items():
                lista, atrs = cache[m]
                ops = [o for o in operaciones(v1, lista, horas, modo, r, coste_pct, atrs) if o["ts"] >= t_ini]
                p1 += [o for o in ops if o["ts"] < corte]
                p2 += [o for o in ops if o["ts"] >= corte]
                if modo == "regla" and r == OBJETIVO_R:
                    por_moneda[m] = resumen(ops)
            filas.append({"stop": modo, "texto": texto, "objetivo_R": r, "p1": resumen(p1), "p2": resumen(p2),
                          "total": resumen(p1 + p2)})
    return {"desde": t_ini, "corte": corte, "hasta": t_fin, "filas": filas, "por_moneda": por_moneda,
            "coste_pct": coste_pct, "horas": horas}


def conclusion(est, min_ops=30, margen=0.05):
    """Solo propone cambiar la regla si una variante gana en LOS DOS periodos, con margen y
    con operaciones suficientes en cada uno. Si no, la regla se queda como está."""
    base = [f for f in est["filas"] if f["stop"] == "regla" and f["objetivo_R"] == OBJETIVO_R][0]
    mejores = []
    for f in est["filas"]:
        if f is base or f["p1"]["n"] < min_ops or f["p2"]["n"] < min_ops:
            continue
        if base["p1"]["n"] == 0 or base["p2"]["n"] == 0:
            continue
        if (f["p1"]["R_medio"] > base["p1"]["R_medio"] + margen and
                f["p2"]["R_medio"] > base["p2"]["R_medio"] + margen):
            mejores.append(f)
    mejores.sort(key=lambda f: -min(f["p1"]["R_medio"], f["p2"]["R_medio"]))
    return base, mejores


def cmd_estudiar(a):
    ahora = parse_ahora(a.ahora)
    datos, faltan = {}, []
    for m in _monedas(a.monedas):
        try:
            v1, v4 = cargar(m, a.offline, a.horas_datos)
            datos[m] = (cerradas(v1, H1, ahora), cerradas(v4, H4, ahora))
        except Error as e:
            faltan.append("%s (%s)" % (m, e))
    if not datos:
        raise Error("no hay datos de ninguna moneda")
    est = estudio(datos, a.horas, a.coste, a.lado.upper() if a.lado else None)
    if a.json:
        print(json.dumps(est, ensure_ascii=False, indent=1))
        return 0
    rm = lambda r: fmt(r["R_medio"], 2) if r.get("n") else "sin datos"
    out = ["Estudio de la regla «ruptura 20 + contexto 4h» · %d monedas · %s a %s (Madrid)" % (
        len(datos), hora(est["desde"]), hora(est["hasta"])),
        "Periodo 1: hasta %s · periodo 2: desde %s · coste %s ida y vuelta · máximo %d h por operación" % (
            hora(est["corte"]), hora(est["corte"]), pct(est["coste_pct"]), est["horas"]),
        "Operaciones sin solaparse: mientras una sigue abierta no se cuenta otra en la misma moneda.", "",
        "| Stop | Objetivo | Operaciones | Aciertos | R medio P1 | R medio P2 | R medio | Factor |",
        "|---|---|---|---|---|---|---|---|"]
    for f in est["filas"]:
        t = f["total"]
        out.append("| %s | %sR | %d | %s | %s | %s | %s | %s |" % (
            f["texto"], fmt(f["objetivo_R"], 1), t.get("n", 0),
            pct(t["acierto"], 0) if t.get("n") else "-", rm(f["p1"]), rm(f["p2"]), rm(t),
            fmt(t["factor"], 2) if t.get("factor") is not None else "-"))
    out += ["", "La regla, moneda a moneda (stop de 10 velas, objetivo 2R, con costes):",
            "| Moneda | Operaciones | Aciertos | R medio | R total |", "|---|---|---|---|---|"]
    for m, r in sorted(est["por_moneda"].items(), key=lambda x: -(x[1].get("R_medio") or -9)):
        out.append("| %s | %d | %s | %s | %s |" % (m, r.get("n", 0), pct(r["acierto"], 0) if r.get("n") else "-",
                                                   rm(r), fmt(r["R_total"], 1) if r.get("n") else "-"))
    base, mejores = conclusion(est)
    out.append("")
    if mejores:
        f = mejores[0]
        out.append("Conclusión: «%s» con objetivo %sR gana a la regla en los dos periodos (%s y %s R frente a %s y %s). "
                   "Es una PROPUESTA: la regla no se cambia sin que lo decidas tú, y conviene volver a "
                   "comprobarlo con datos nuevos antes de usarla." % (
                       f["texto"], fmt(f["objetivo_R"], 1), rm(f["p1"]), rm(f["p2"]), rm(base["p1"]), rm(base["p2"])))
    else:
        out.append("Conclusión: ninguna variante gana a la regla en los dos periodos con margen suficiente. "
                   "Lo prudente es no tocar el stop ni el objetivo: lo que mejora en un periodo y no en el otro "
                   "suele ser casualidad.")
    if base["total"].get("n") and base["total"]["R_medio"] < 0:
        out.append("Aviso: la regla tal cual pierde de media en este periodo (%s R por operación con costes)." % rm(base["total"]))
    for x in faltan:
        out.append("Sin datos de " + x)
    out += ["", "Un estudio del pasado no garantiza el futuro.", CIERRE]
    print("\n".join(out))
    return 0


def cmd_tamano(a):
    t = tamano(a.capital, a.riesgo, a.entrada, a.stop, a.tope)
    lado = "COMPRA" if a.stop < a.entrada else "VENTA"
    obj = a.objetivo if a.objetivo is not None else a.entrada + (2 if lado == "COMPRA" else -2) * t["R"]
    print("%s %s · entrada %s · stop %s · objetivo %s" % (ICONO[lado], lado, fmt(a.entrada), fmt(a.stop), fmt(obj)))
    print("Cuenta: %s × %s = %s que se arriesgan. %s ÷ %s por unidad = %s unidades." % (
        fmt(a.capital, 0), pct(a.riesgo), fmt(t["riesgo_objetivo"], 2), fmt(t["riesgo_objetivo"], 2),
        fmt(t["R"]), fmt(t["unidades"], t["decimales"])))
    print("| Unidades | Importe | Pierdes en el stop | Ganas en el objetivo |")
    print("|---|---|---|---|")
    print("| %s | %s | %s | %s |" % (fmt(t["unidades"], t["decimales"]), fmt(t["importe"], 2), fmt(t["perdida"], 2),
                                   fmt(t["unidades"] * abs(obj - a.entrada), 2)))
    if t["limite"] != "riesgo":
        print("Lo limita el capital: sin apalancamiento no se puede comprar más.")
    print(CIERRE)
    return 0


def cmd_riesgo(a):
    ahora = parse_ahora(a.ahora)
    lado = "COMPRA" if a.stop is None or a.stop < a.entrada else "VENTA"
    objs = a.objetivo or [a.entrada + (2 if lado == "COMPRA" else -2) * abs(a.entrada - (a.stop or a.entrada))]
    filas = comprobar_riesgo(a.capital, a.riesgo, a.entrada, a.stop, objs, lado, ahora, a.abiertas, a.perdida_hoy)
    bloquea = any(f[0] == "BLOQUEA" for f in filas)
    print("%s %s · %s" % (ICONO[lado], lado, "BLOQUEA" if bloquea else "PASA"))
    for estado, texto in filas:
        print("- %s: %s" % (estado, texto))
    print(CIERRE)
    return 1 if bloquea else 0


def cmd_precio(a):
    for m in _monedas(a.monedas):
        try:
            d = json.loads(_get("%s/ticker/%s/" % (BITSTAMP, par(m))).decode("utf-8"))
            print("%s: %s · %s (Madrid) · Bitstamp" % (m, fmt(float(d["last"])), hora(int(d["timestamp"]))))
        except (Error, KeyError, ValueError) as e:
            print("%s: NO EVALUABLE (%s)" % (m, e))
    return 0


def cmd_ficha(a):
    ahora = parse_ahora(a.ahora)
    caduca = parse_ahora(a.caduca) if a.caduca else ahora + 24 * H1
    cond = a.condicion or ("Cierre por encima" if a.lado.upper() == "COMPRA" else "Cierre por debajo")
    print(ficha(1, a.moneda.upper(), a.lado.upper(), a.nivel, a.marco, cond, caduca, a.texto or ""))
    print("\nEs una ficha PROPUESTA: no existe en TradingView hasta que la crees tú.")
    return 0


def cmd_noticias(a):
    ahora = parse_ahora(a.ahora)
    items, errores = [], []
    for m in _monedas(a.monedas):
        try:
            if a.offline:
                with open(os.path.join(a.offline, "%s-noticias.xml" % par(m)), "rb") as fh:
                    datos = fh.read()
            else:
                datos = _get(YAHOO_RSS % m)
            items += parse_noticias(datos, m)
        except (Error, OSError) as e:
            errores.append("%s: %s" % (m, e))
    vistos, filas = set(), []
    for it in sorted(items, key=lambda x: -x["ts"]):
        if it["ts"] < ahora - a.horas * 3600 or it["titulo"].lower() in vistos:
            continue
        vistos.add(it["titulo"].lower())
        filas.append(it)
    if not filas:
        print("Sin titulares en las últimas %d h." % a.horas)
    for it in filas:
        tags = (" [%s]" % ", ".join(it["etiquetas"])) if it["etiquetas"] else ""
        print("%s · %s%s · %s\n    %s" % (hora(it["ts"]), it["moneda"], tags, it["titulo"], it["enlace"]))
    for e in errores:
        print("Sin noticias de " + e)
    print("\nLos titulares de Yahoo están en inglés. Una noticia no es una señal: manda la regla.")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="Las habilidades del paquete adaptadas a cripto (solo simulación).")
    sub = p.add_subparsers(dest="cmd")

    def comun(sp, datos=True):
        sp.add_argument("--ahora", help="hora de Madrid AAAA-MM-DD HH:MM (por defecto, ahora)")
        if datos:
            sp.add_argument("--offline", help="carpeta con <par>-1h.json y <par>-4h.json")
            sp.add_argument("--vigencia", type=int, default=24, help="horas hacia atrás para la última señal")

    s = sub.add_parser("escanear", help="tabla de las 10 monedas")
    s.add_argument("monedas", nargs="*")
    s.add_argument("--horas", type=int, default=300, help="velas de 1h que se descargan")
    s.add_argument("--json", action="store_true")
    comun(s)
    s.set_defaults(fn=cmd_escanear)

    s = sub.add_parser("senal", help="señal, plan y fichas de una moneda")
    s.add_argument("moneda")
    s.add_argument("--horas", type=int, default=300)
    comun(s)
    s.set_defaults(fn=cmd_senal)

    s = sub.add_parser("simular", help="10.000 recorridos y las señales pasadas")
    s.add_argument("moneda")
    s.add_argument("--entrada", type=float)
    s.add_argument("--stop", type=float)
    s.add_argument("--objetivo", type=float)
    s.add_argument("--horas", type=int, default=48, help="horas que se simulan (48)")
    s.add_argument("--horas-datos", type=int, default=2000, help="velas de 1h de historia (2000, unos 83 días)")
    s.add_argument("--recorridos", type=int, default=10000)
    s.add_argument("--semilla", type=int, default=19)
    s.add_argument("--json", action="store_true")
    comun(s)
    s.set_defaults(fn=cmd_simular)

    s = sub.add_parser("estudiar", help="compara stops y objetivos en dos periodos")
    s.add_argument("monedas", nargs="*")
    s.add_argument("--horas", type=int, default=48, help="horas máximas por operación (48)")
    s.add_argument("--horas-datos", type=int, default=2000)
    s.add_argument("--coste", type=float, default=0.1, help="%% de coste ida y vuelta (0,1)")
    s.add_argument("--lado", choices=["compra", "venta"])
    s.add_argument("--json", action="store_true")
    comun(s)
    s.set_defaults(fn=cmd_estudiar)

    s = sub.add_parser("tamano", help="unidades para un % de riesgo")
    s.add_argument("--capital", type=float, required=True)
    s.add_argument("--riesgo", type=float, default=1.0, help="%% del capital (1)")
    s.add_argument("--entrada", type=float, required=True)
    s.add_argument("--stop", type=float, required=True)
    s.add_argument("--objetivo", type=float)
    s.add_argument("--tope", type=float, default=100.0, help="%% máximo del capital en la posición (100)")
    s.set_defaults(fn=cmd_tamano)

    s = sub.add_parser("riesgo", help="PASA / BLOQUEA según los límites")
    s.add_argument("--capital", type=float, required=True)
    s.add_argument("--riesgo", type=float, default=1.0)
    s.add_argument("--entrada", type=float, required=True)
    s.add_argument("--stop", type=float)
    s.add_argument("--objetivo", type=float, action="append")
    s.add_argument("--abiertas", type=int, default=0)
    s.add_argument("--perdida-hoy", type=float, default=0.0, help="%% del capital perdido hoy")
    comun(s, datos=False)
    s.set_defaults(fn=cmd_riesgo)

    s = sub.add_parser("precio", help="último precio de Bitstamp")
    s.add_argument("monedas", nargs="*")
    s.set_defaults(fn=cmd_precio)

    s = sub.add_parser("ficha", help="ficha de alerta propuesta")
    s.add_argument("moneda")
    s.add_argument("lado", choices=["compra", "venta", "esperar", "COMPRA", "VENTA", "ESPERAR"])
    s.add_argument("nivel", type=float)
    s.add_argument("--marco", default="1h")
    s.add_argument("--condicion")
    s.add_argument("--caduca", help="hora de Madrid AAAA-MM-DD HH:MM (por defecto, 24 h)")
    s.add_argument("--texto")
    comun(s, datos=False)
    s.set_defaults(fn=cmd_ficha)

    s = sub.add_parser("noticias", help="titulares por moneda")
    s.add_argument("monedas", nargs="*")
    s.add_argument("--horas", type=int, default=24)
    s.add_argument("--offline")
    s.add_argument("--ahora")
    s.set_defaults(fn=cmd_noticias)

    a = p.parse_args(argv)
    if not getattr(a, "fn", None):
        p.print_help()
        return 2
    try:
        return a.fn(a)
    except Error as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
