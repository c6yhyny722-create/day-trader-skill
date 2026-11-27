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
import bisect
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

# Oro y plata: no hay velas gratuitas del contado (TVC:GOLD, TVC:SILVER) por hora, así que la
# regla se calcula con los futuros de COMEX (mismo horario; el contado suele cotizar algo más
# barato). Los niveles exactos de las fichas hay que comprobarlos en TradingView, o pasar sus
# velas con --offline (formato de mcp-tv-get-ohlcv).
MATERIAS = {
    "ORO": {"yahoo": "GC=F", "tv": "TVC:GOLD", "fuente": "futuros COMEX del oro (GC=F, Yahoo)"},
    "PLATA": {"yahoo": "SI=F", "tv": "TVC:SILVER", "fuente": "futuros COMEX de la plata (SI=F, Yahoo)"},
}
ALIAS = {"GOLD": "ORO", "XAU": "ORO", "XAUUSD": "ORO", "SILVER": "PLATA", "XAG": "PLATA", "XAGUSD": "PLATA"}
YAHOO_CHART = "https://query2.finance.yahoo.com/v8/finance/chart/%s?interval=60m&range=%s"
DESFASE_SESION = 2 * 3600   # la sesión del oro empieza a las 22:00/23:00 UTC: cuenta para el día siguiente


def es_materia(moneda):
    return moneda in MATERIAS


def simbolo_tv(moneda):
    return MATERIAS[moneda]["tv"] if moneda in MATERIAS else "BITSTAMP:%sUSD" % moneda


def par(moneda):
    return moneda.lower() + ("" if moneda in MATERIAS else "usd")


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


def agrupar_4h(v1):
    """Velas de 4h (bloques UTC) hechas con las de 1h; en mercados con cierres pueden tener
    menos de 4 velas."""
    cubos = {}
    for b in v1:
        cubos.setdefault(b["t"] // H4 * H4, []).append(b)
    return [{"t": t, "o": bs[0]["o"], "h": max(x["h"] for x in bs), "l": min(x["l"] for x in bs),
             "c": bs[-1]["c"], "v": sum(x["v"] for x in bs)} for t, bs in sorted(cubos.items())]


def bajar_yahoo(simbolo, horas):
    rango = "730d" if horas > 24 * 365 else "%dd" % max(5, min(730, horas // 23 + 2))
    doc = json.loads(_get(YAHOO_CHART % (urllib.request.quote(simbolo), rango)).decode("utf-8"))
    res = (doc.get("chart") or {}).get("result") or []
    if not res:
        raise Error("Yahoo no tiene datos de %s" % simbolo)
    r = res[0]
    q = r["indicators"]["quote"][0]
    velas = []
    for i, t in enumerate(r.get("timestamp") or []):
        o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c) or t % H1:
            continue
        velas.append({"t": int(t), "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return velas


def cargar(moneda, offline=None, horas=1000):
    """(velas 1h, velas 4h) de la moneda, en vivo o desde offline/<par>-1h.json y -4h.json
    (en oro y plata, si falta el de 4h se hace con el de 1h)."""
    if offline:
        res = []
        for tf in ("1h", "4h"):
            ruta = os.path.join(offline, "%s-%s.json" % (par(moneda), tf))
            if tf == "4h" and es_materia(moneda) and not os.path.exists(ruta):
                res.append(agrupar_4h(res[0]))
                continue
            try:
                with open(ruta, encoding="utf-8") as fh:
                    res.append(normalizar(json.load(fh)))
            except (OSError, ValueError) as e:
                raise Error("no se pudo leer %s: %s" % (ruta, e))
        return res[0], res[1]
    if es_materia(moneda):
        # al menos 60 días, para que la EMA 50 de 4h salga igual en todos los comandos
        v1 = bajar_yahoo(MATERIAS[moneda]["yahoo"], max(horas, 24 * 60))
        return v1, agrupar_4h(v1)
    return bajar_velas(moneda, H1, horas), bajar_velas(moneda, H4, max(200, horas // 4 + 120))


def cerradas(velas, paso, ahora):
    return [b for b in velas if b["t"] + paso <= ahora]


def revisar_velas(velas, paso, ultimas, huecos=True):
    """Problemas en las `ultimas` velas: huecos de tiempo o velas imposibles (máximo por
    debajo del mínimo, apertura o cierre fuera del rango). Lista vacía si todo cuadra.
    Con huecos=False (oro y plata, que cierran cada día y el fin de semana) no mira huecos."""
    tramo = velas[-ultimas:]
    out = []
    for a, b in zip(tramo, tramo[1:]):
        if huecos and b["t"] - a["t"] != paso:
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

class _Mapa(dict):
    orden = ()


def mapa_contexto(v4):
    """{inicio de la vela de 4h: (cierre, EMA 50)} calculado una vez."""
    es = ema([b["c"] for b in v4], N_EMA)
    m = _Mapa((b["t"], (b["c"], e)) for b, e in zip(v4, es))
    m.orden = sorted(m)
    return m


def contexto(v4, inicio_1h, mapa=None):
    """(cierre 4h, EMA 50 4h) de la última vela de 4h anterior a la que contiene la vela de 1h
    (en oro y plata, después de un cierre de mercado, la última que hubo)."""
    mapa = mapa if mapa is not None else mapa_contexto(v4)
    i = bisect.bisect_left(mapa.orden, inicio_1h // H4 * H4) - 1
    return mapa[mapa.orden[i]] if i >= 0 else (None, None)


def senal_en(v1, j, v4, mapa=None):
    """Señal de la vela 1h j (cerrada) o None. Igual que evaluar() del script de Pine."""
    if j < N_RUPTURA:
        return None
    c4, e4 = contexto(v4, v1[j]["t"], mapa)
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
    continuo = not es_materia(moneda)
    max_retraso = 24 if continuo else 72        # oro y plata cierran el fin de semana
    if retraso > max_retraso * 3600:
        res.update(ahora="NO EVALUABLE", motivo="el último dato tiene más de %d h de retraso" % max_retraso)
        return res
    problemas = (revisar_velas(v1, H1, vigencia + N_RUPTURA + 1, continuo) +
                 revisar_velas(v4, H4, N_EMA, continuo))
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
    desde = ult["t"] - vigencia * H1           # horas reales: en oro y plata hay cierres de mercado
    for j in range(len(v1) - 1, N_RUPTURA - 1, -1):
        if v1[j]["t"] <= desde:
            break
        s = senal_en(v1, j, v4)
        if s:
            ultima = s
            break
    res["ultima_senal"] = ultima
    if ultima:
        ultima["seguimiento"] = seguir(ultima, v1)
        ultima["nota_stop"] = nota_stop(ultima["R"], atr(v1)[ultima["j"]])
    seg = (ultima or {}).get("seguimiento") or {}
    if ultima and ultima["j"] == len(v1) - 1:
        res["ahora"] = "%s activada%s" % (ultima["lado"], "" if ultima["en_zona"] else " (fuera de zona)")
    elif ultima and ultima["en_zona"] and seg.get("estado") == "abierta" and seg.get("en_zona"):
        # la señal saltó horas antes, no ha tocado stop ni objetivo y el precio sigue en la zona
        res["ahora"] = "%s en zona (señal de las %s)" % (ultima["lado"], hora(ultima["cierre_ts"])[-5:])
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
    out, mapa = [], mapa_contexto(v4)
    for j in range(N_RUPTURA, len(v1)):
        s = senal_en(v1, j, v4, mapa)
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


def historial(v1, v4, horas=720, lado=None):
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


# ---------------------------------------------------------------- filtros y estudio a fondo

# Filtros decididos ANTES de mirar resultados, cada uno con una razón de mercado.
FILTROS = [
    ("ninguno", "la regla tal cual"),
    ("horas", "solo velas que cierran de 15:00 a 19:00 (Madrid), con Nueva York abierta"),
    ("volumen", "volumen de la vela de la señal por encima de su media de 20"),
    ("diario", "a favor de la tendencia diaria (cierre del día anterior frente a su EMA 50)"),
    ("extremo", "no vender con RSI diario < 30 ni comprar con RSI diario > 70"),
]


def diarias_de(v1, desfase=0, minimo=24):
    """Velas diarias (día UTC, como el diario de Bitstamp en TradingView) hechas con las de 1h.
    En oro y plata (desfase de 2 h, mínimo 20 velas) cada sesión cuenta para el día en que cierra."""
    dias = {}
    for b in v1:
        dias.setdefault((b["t"] + desfase) // 86400 * 86400, []).append(b)
    out = []
    for t in sorted(dias):
        bs = dias[t]
        if len(bs) >= minimo:
            out.append({"t": t, "o": bs[0]["o"], "h": max(x["h"] for x in bs), "l": min(x["l"] for x in bs),
                        "c": bs[-1]["c"], "v": sum(x["v"] for x in bs)})
    return out


def diarias_para(v1, moneda=None):
    return diarias_de(v1, DESFASE_SESION, 20) if moneda and es_materia(moneda) else diarias_de(v1)


def datos_filtros(v1, moneda=None):
    """Lo que necesitan los filtros, calculado una vez."""
    vols = [b["v"] for b in v1]
    vmed = [None if i < 20 else sum(vols[i - 20:i]) / 20.0 for i in range(len(v1))]
    d = diarias_para(v1, moneda)
    cs = [b["c"] for b in d]
    e50 = ema(cs, 50)
    rs = [None] * len(cs)
    for i in range(15, len(cs)):
        rs[i] = rsi(cs[max(0, i - 200):i + 1])
    dia = {b["t"]: (b["c"], e, r) for b, e, r in zip(d, e50, rs)}
    desfase = DESFASE_SESION if moneda and es_materia(moneda) else 0
    return {"vmed": vmed, "dia": dia, "dias": sorted(dia), "desfase": desfase}


def pasa_filtro(nombre, s, v1, extra):
    if nombre == "ninguno":
        return True
    largo = s["lado"] == "COMPRA"
    if nombre == "horas":
        return 15 <= a_madrid(s["cierre_ts"]).hour <= 19
    if nombre == "volumen":
        m = extra["vmed"][s["j"]]
        return m is not None and v1[s["j"]]["v"] > m
    hoy = (s["t"] + extra.get("desfase", 0)) // 86400 * 86400
    dias = extra.get("dias") or sorted(extra["dia"])
    i = bisect.bisect_left(dias, hoy) - 1
    ayer = extra["dia"][dias[i]] if i >= 0 else None
    if not ayer or ayer[1] is None or ayer[2] is None:
        return False
    c, e, r = ayer
    if nombre == "diario":
        return c > e if largo else c < e
    if nombre == "extremo":
        return r < 70 if largo else r > 30
    raise Error("filtro desconocido: %s" % nombre)


def estudio_filtros(v1, v4, horas=720, coste_pct=0.1, tramos=3, min_ops=30, margen=0.05, moneda=None):
    """Cada filtro y cada stop (regla y 1,5 ATR), objetivo 2R, en `tramos` periodos seguidos.
    Un filtro se da por bueno solo si mejora a la regla en TODOS los periodos, con margen y
    con al menos `min_ops` operaciones en cada uno."""
    lista, atrs, extra = senales(v1, v4), atr(v1), datos_filtros(v1, moneda)
    t0, t1 = v1[N_RUPTURA]["t"], v1[-1]["t"]
    cortes = [t0 + (t1 - t0) * k // tramos for k in range(tramos + 1)]
    cortes[-1] = t1 + H1 * 10
    filas = []
    for stop_modo in ("regla", "atr15"):
        for nombre, texto in FILTROS:
            sel = [x for x in lista if pasa_filtro(nombre, x, v1, extra)]
            ops = operaciones(v1, sel, horas, stop_modo, OBJETIVO_R, coste_pct, atrs)
            partes = [resumen([o for o in ops if cortes[k] <= o["ts"] < cortes[k + 1]]) for k in range(tramos)]
            filas.append({"filtro": nombre, "texto": texto, "stop": stop_modo, "total": resumen(ops),
                          "partes": partes, "por_lado": {l: resumen([o for o in ops if o["lado"] == l])
                                                         for l in ("COMPRA", "VENTA")}})
    base = filas[0]
    for f in filas:
        f["robusto"] = f is not base and all(
            p.get("n", 0) >= min_ops and b.get("n", 0) and p["R_medio"] > b["R_medio"] + margen
            for p, b in zip(f["partes"], base["partes"]))
    return {"cortes": cortes, "filas": filas, "coste_pct": coste_pct, "horas": horas}


def perfil_horario(v1):
    """Movimiento medio (rango en %) y volumen relativo de cada hora de Madrid."""
    rangos, vols = {}, {}
    for a, b in zip(v1, v1[1:]):
        h = a_madrid(b["t"]).hour
        rangos.setdefault(h, []).append(100.0 * (b["h"] - b["l"]) / a["c"])
        vols.setdefault(h, []).append(b["v"])
    vm = statistics.mean(v for vs in vols.values() for v in vs) or 1.0
    return {h: (statistics.mean(rangos[h]), statistics.mean(vols[h]) / vm) for h in sorted(rangos)}


def giros(v4, n=3, cuantos=8):
    """Máximos y mínimos de giro en 4h (más alto o más bajo que las n velas de cada lado)."""
    out = []
    for i in range(n, len(v4) - n):
        b = v4[i]
        lados = [v4[i + k] for k in range(-n, n + 1) if k]
        if all(b["h"] > x["h"] for x in lados):
            out.append(("resistencia", b["h"], b["t"]))
        if all(b["l"] < x["l"] for x in lados):
            out.append(("soporte", b["l"], b["t"]))
    return out[-cuantos:]


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
        "Símbolo:     %s" % simbolo_tv(moneda),
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
    out += ["", texto_datos(resultados), CIERRE]
    return "\n".join(out)


def texto_datos(resultados):
    ms = [r["moneda"] for r in resultados]
    partes = []
    if any(not es_materia(m) for m in ms):
        partes.append("cripto: Bitstamp")
    for m in ms:
        if es_materia(m):
            partes.append("%s: %s" % (m.lower(), MATERIAS[m]["fuente"]))
    return "Datos: velas cerradas (%s), horas de Madrid." % "; ".join(partes)


def aviso_materia(moneda, offline):
    if not es_materia(moneda) or offline:
        return ""
    return ("⚠️ %s: los niveles salen de los %s. %s es el precio al contado y suele estar algo más "
            "barato (en el oro, unos 30 $). Comprueba el nivel en TradingView antes de crear la alerta, "
            "o pásame las velas de %s. Las señales y los estudios en R sí valen." % (
                moneda, MATERIAS[moneda]["fuente"], simbolo_tv(moneda), simbolo_tv(moneda)))


# ---------------------------------------------------------------- comandos

def _monedas(lista):
    out = []
    for m in (lista or MONEDAS):
        m = m.upper().replace("BITSTAMP:", "").replace("TVC:", "")
        m = ALIAS.get(m, m)
        out.append(m if m in MATERIAS else m.replace("USD", ""))
    return out


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
    if aviso_materia(m, a.offline):
        print("\n" + aviso_materia(m, a.offline))
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
    hist = historial(v1c, v4c, 720, lado)
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
                   "stop %d · sin cerrar a los 30 días %d · R medio %s, sin costes (hasta stop u objetivo)." % (n, lado, sum(h["fin"] == "objetivo" for h in hist),
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


def estudio(datos, horas=720, coste_pct=0.1, lado=None):
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


def cmd_afondo(a):
    ahora = parse_ahora(a.ahora)
    m = a.moneda.upper()
    v1, v4 = cargar(m, a.offline, a.dias * 24)
    v1, v4 = cerradas(v1, H1, ahora), cerradas(v4, H4, ahora)
    r = estado_moneda(m, v1, v4, ahora)
    out = [informe([r]).rsplit("\n\nDatos:", 1)[0], ""]
    d = diarias_para(v1, m)
    if aviso_materia(m, a.offline):
        out += [aviso_materia(m, a.offline), "Los futuros cambian de contrato cada pocos meses: ese salto de precio puede "
                "crear alguna ruptura falsa en la historia.", ""]
    if len(d) >= 50:
        cs = [b["c"] for b in d]
        e20, e50 = ema(cs, 20)[-1], ema(cs, 50)[-1]
        e200 = ema(cs, 200)[-1] if len(cs) >= 200 else None
        at = atr(d)[-1]
        cambio = lambda n: pct(100 * (cs[-1] / cs[-1 - n] - 1), 1) if len(cs) > n else "sin dato"
        out += ["Diario (cierre %s): EMA 20 %s · EMA 50 %s · EMA 200 %s · RSI %s · ATR %s (%s)." % (
                    fmt(cs[-1]), fmt(e20), fmt(e50), fmt(e200), fmt(rsi(cs), 1), fmt(at), pct(100 * at / cs[-1], 1)),
                "Cambio: 7 días %s · 30 días %s · 90 días %s · 1 año %s." % (cambio(7), cambio(30), cambio(90), cambio(365))]
        if rsi(cs) < 30:
            out.append("Aviso: RSI diario por debajo de 30, muy vendido: riesgo de rebote fuerte contra las VENTAS.")
        elif rsi(cs) > 70:
            out.append("Aviso: RSI diario por encima de 70, muy comprado: riesgo de caída fuerte contra las COMPRAS.")
    out += ["", "Niveles de giro en 4h (los más recientes):"]
    for tipo, p, t in giros(v4):
        out.append("  %s %s (%s)" % (tipo, fmt(p), hora(t)))
    ph = perfil_horario(v1[-24 * 90:])
    top = sorted(ph.items(), key=lambda x: -x[1][0])[:4]
    low = sorted(ph.items(), key=lambda x: x[1][0])[:3]
    out += ["", "Horas de más movimiento (Madrid, últimos 90 días): " + ", ".join(
        "%02d:00 (%s, volumen ×%s)" % (h, pct(rg), fmt(vr, 1)) for h, (rg, vr) in top),
        "Horas más tranquilas: " + ", ".join("%02d:00 (%s)" % (h, pct(rg)) for h, (rg, vr) in low)]
    est = estudio_filtros(v1, v4, a.horas, a.coste, moneda=m)
    c = est["cortes"]
    fecha = lambda t: a_madrid(t).strftime("%d/%m/%Y")
    out += ["", "Estudio de la regla con filtros · %s a %s (%s velas de 1h) · objetivo 2R · coste %s · máximo %d h" % (
        fecha(c[0]), fecha(v1[-1]["t"]), fmt(len(v1), 0), pct(est["coste_pct"]), est["horas"]),
        "Periodos: P1 hasta %s · P2 hasta %s · P3 hasta hoy." % (fecha(c[1]), fecha(c[2])),
        "| Filtro | Stop | Ops | Aciertos | R P1 | R P2 | R P3 | R medio | Compras R | Ventas R |",
        "|---|---|---|---|---|---|---|---|---|---|"]
    rm = lambda x: fmt(x["R_medio"], 2) if x.get("n") else "-"
    for f in est["filas"]:
        t = f["total"]
        out.append("| %s%s | %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
            f["filtro"], " ✅" if f["robusto"] else "", "regla" if f["stop"] == "regla" else "1,5 ATR",
            t.get("n", 0), pct(t["acierto"], 0) if t.get("n") else "-", rm(f["partes"][0]), rm(f["partes"][1]),
            rm(f["partes"][2]), rm(t), rm(f["por_lado"]["COMPRA"]), rm(f["por_lado"]["VENTA"])))
    buenos = [f for f in est["filas"] if f["robusto"]]
    out.append("")
    out.append("Filtros: " + "; ".join("%s = %s" % (n, t) for n, t in FILTROS[1:]) + ".")
    if buenos:
        out.append("✅ = mejora a la regla en los 3 periodos, con margen y operaciones suficientes. "
                   "Es una PROPUESTA: la regla no se cambia sin que lo decidas tú.")
    else:
        out.append("Ningún filtro mejora a la regla en los 3 periodos: no conviene añadir ninguno todavía.")
    out += ["", "Un estudio del pasado no garantiza el futuro.", CIERRE]
    print("\n".join(out))
    return 0


def ventaja(v1, v4, horas=720, coste_pct=0.1, tramos=3, moneda=None):
    """Cómo le ha ido a la regla en esta moneda: total y último periodo, sin y con el filtro
    de horas. Sirve para ordenar oportunidades, no para cambiar la regla."""
    lista, atrs, extra = senales(v1, v4), atr(v1), datos_filtros(v1, moneda)
    t0, t1 = v1[N_RUPTURA]["t"], v1[-1]["t"]
    ultimo = t0 + (t1 - t0) * (tramos - 1) // tramos
    out = {}
    for nombre in ("ninguno", "horas"):
        sel = [x for x in lista if pasa_filtro(nombre, x, v1, extra)]
        ops = operaciones(v1, sel, horas, "regla", OBJETIVO_R, coste_pct, atrs)
        out[nombre] = {"total": resumen(ops), "ultimo": resumen([o for o in ops if o["ts"] >= ultimo]),
                       "compra": resumen([o for o in ops if o["lado"] == "COMPRA"]),
                       "venta": resumen([o for o in ops if o["lado"] == "VENTA"])}
    return out


def oportunidad(r, vent):
    """Ficha corta de una moneda para el ranking: estado, disparo, distancia y ventaja."""
    o = {"moneda": r["moneda"], "ahora": r.get("ahora"), "r": r, "ventaja": vent}
    if r.get("ahora") == "NO EVALUABLE":
        o["orden"] = (3, 99)
        return o
    a = r.get("atr") or 0
    if r.get("compra_si") is not None:
        lado, nivel = "COMPRA", r["compra_si"]
    else:
        lado, nivel = "VENTA", r["venta_si"]
    o.update(lado=lado, nivel=nivel, dist_pct=100.0 * abs(nivel - r["cierre"]) / r["cierre"],
             dist_atr=abs(nivel - r["cierre"]) / a if a else None)
    hist = vent["ninguno"][lado.lower()] if vent else {}
    o["r_lado"] = hist.get("R_medio") if hist.get("n") else None
    activa = r["ahora"].startswith(("COMPRA", "VENTA"))
    sin_ventaja = o["r_lado"] is not None and o["r_lado"] <= 0
    o["orden"] = (0 if activa else 2 if sin_ventaja else 1, o["dist_atr"] if o["dist_atr"] is not None else 99)
    return o


def cmd_oportunidades(a):
    ahora = parse_ahora(a.ahora)
    ops = []
    for m in _monedas(a.monedas):
        try:
            v1, v4 = cargar(m, a.offline, a.dias * 24)
            v1, v4 = cerradas(v1, H1, ahora), cerradas(v4, H4, ahora)
            r = estado_moneda(m, v1, v4, ahora)
            ops.append(oportunidad(r, ventaja(v1, v4, moneda=m) if r.get("ahora") != "NO EVALUABLE" else None))
        except Error as e:
            ops.append({"moneda": m, "ahora": "NO EVALUABLE", "motivo": str(e), "orden": (3, 99)})
    ops.sort(key=lambda o: o["orden"])
    rm = lambda x: fmt(x["R_medio"], 2) if x and x.get("n") else "-"
    out = ["| # | Moneda | Ahora | Disparo | Distancia | Regla 3 años (este lado) | Último año |",
           "|---|---|---|---|---|---|---|"]
    for i, o in enumerate(ops, 1):
        if o.get("ahora") == "NO EVALUABLE":
            out.append("| %d | %s | NO EVALUABLE | | | | |" % (i, o["moneda"]))
            continue
        lado = o["lado"]
        disparo = "%s vela 1h %s %s" % (ICONO[lado] + " " + lado, ">" if lado == "COMPRA" else "<", fmt(o["nivel"]))
        dist = "%s (%s ATR)" % (pct(o["dist_pct"], 1), fmt(o["dist_atr"], 1) if o["dist_atr"] is not None else "-")
        v = o["ventaja"]["ninguno"]
        out.append("| %d | %s | %s | %s | %s | %s R | %s R |" % (
            i, o["moneda"], etiqueta_ahora(o["ahora"]), disparo, dist, rm(v[lado.lower()]), rm(v["ultimo"])))
    out += ["", "Orden: primero las que tienen señal activa; después las que están más cerca de su disparo "
            "(en ATR de 1h) y cuya regla ha ganado en ese lado en 3 años; al final, las que no han ganado.",
            "Regla 3 años = resultado medio por operación de la regla en esa moneda y ese lado (COMPRA o VENTA), "
            "con costes. Último año = todas sus operaciones del último año.", ""]
    for o in ops:
        if o.get("ahora") == "NO EVALUABLE":
            out.append("%s: NO EVALUABLE (%s)." % (o["moneda"], o.get("motivo") or o["r"].get("motivo", "sin datos")))
            continue
        h, n = o["ventaja"]["horas"]["total"], o["ventaja"]["ninguno"]["total"]
        if h.get("n") and n.get("n") and h["R_medio"] > n["R_medio"] + 0.05:
            out.append("%s: con el filtro de horas (15:00 a 19:00, Madrid) la regla sube de %s a %s R en 3 años." % (
                o["moneda"], rm(n), rm(h)))
    out += ["", texto_datos([o for o in ops]) + " Un estudio del pasado no garantiza el futuro.",
            CIERRE]
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
        if es_materia(m):
            try:
                doc = json.loads(_get(YAHOO_CHART % (urllib.request.quote(MATERIAS[m]["yahoo"]), "1d")).decode("utf-8"))
                meta = doc["chart"]["result"][0]["meta"]
                print("%s: %s · %s (Madrid) · %s (en %s puede ser algo menor)" % (
                    m, fmt(float(meta["regularMarketPrice"])), hora(int(meta["regularMarketTime"])),
                    MATERIAS[m]["fuente"], simbolo_tv(m)))
            except (Error, KeyError, ValueError, IndexError, TypeError) as e:
                print("%s: NO EVALUABLE (%s)" % (m, e))
            continue
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
                datos = _get(YAHOO_RSS.replace("%s-USD", "%s") % urllib.request.quote(MATERIAS[m]["yahoo"])
                             if es_materia(m) else YAHOO_RSS % m)
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
    s.add_argument("--horas", type=int, default=720,
                   help="horas máximas por operación (720 = 30 días: en la práctica, hasta stop u objetivo)")
    s.add_argument("--horas-datos", type=int, default=2000)
    s.add_argument("--coste", type=float, default=0.1, help="%% de coste ida y vuelta (0,1)")
    s.add_argument("--lado", choices=["compra", "venta"])
    s.add_argument("--json", action="store_true")
    comun(s)
    s.set_defaults(fn=cmd_estudiar)

    s = sub.add_parser("afondo", help="estudio completo de una moneda con años de datos")
    s.add_argument("moneda")
    s.add_argument("--dias", type=int, default=1095, help="días de historia de 1h (1095, unos 3 años)")
    s.add_argument("--horas", type=int, default=720,
                   help="horas máximas por operación (720 = 30 días: en la práctica, hasta stop u objetivo)")
    s.add_argument("--coste", type=float, default=0.1)
    comun(s)
    s.set_defaults(fn=cmd_afondo)

    s = sub.add_parser("oportunidades", help="las 10 monedas ordenadas por oportunidad")
    s.add_argument("monedas", nargs="*")
    s.add_argument("--dias", type=int, default=1095)
    comun(s)
    s.set_defaults(fn=cmd_oportunidades)

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
