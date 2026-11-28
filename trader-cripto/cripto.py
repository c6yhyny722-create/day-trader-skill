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

_PRECISION = [None]   # decimales fijos del activo que se está mostrando (EUR/USD: 5)


def fijar_precision(moneda):
    _PRECISION[0] = MATERIAS.get(moneda, {}).get("dec") if moneda else None


def fmt(x, dec=None):
    """Número en formato español; decimales según el precio (o los del activo, en divisas)."""
    if x is None:
        return "sin dato"
    if dec is None and _PRECISION[0] is not None:
        dec = _PRECISION[0]
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
    "ORO": {"yahoo": "GC=F", "tv": "TVC:GOLD", "fuente": "futuros COMEX del oro (GC=F, Yahoo)", "coste": 0.05},
    "PLATA": {"yahoo": "SI=F", "tv": "TVC:SILVER", "fuente": "futuros COMEX de la plata (SI=F, Yahoo)", "coste": 0.05},
    # Divisas: el precio apenas cambia entre fuentes (1-2 pips), así que los niveles valen tal cual.
    # No hay volumen centralizado: el filtro de volumen no se aplica.
    "EURUSD": {"yahoo": "EURUSD=X", "tv": "FX:EURUSD", "fuente": "Yahoo (EURUSD=X)", "dec": 5, "exacto": True,
               "coste": 0.02},
}
# Divisas mayores (mismas reglas que EUR/USD; las menos líquidas, algo más caras).
for _par, _yh, _dec, _coste in (("GBPUSD", "GBPUSD=X", 5, 0.02), ("USDJPY", "JPY=X", 3, 0.02),
                                ("USDCAD", "CAD=X", 5, 0.025), ("AUDUSD", "AUDUSD=X", 5, 0.025),
                                ("NZDUSD", "NZDUSD=X", 5, 0.025)):
    MATERIAS[_par] = {"yahoo": _yh, "tv": "FX:" + _par, "fuente": "Yahoo (%s)" % _yh, "dec": _dec,
                      "exacto": True, "coste": _coste, "tipo": "divisa"}
MATERIAS["EURUSD"]["tipo"] = "divisa"
MATERIAS["ORO"]["tipo"] = MATERIAS["PLATA"]["tipo"] = "metal"
# Cripto que Bitstamp no tiene: velas de Yahoo, mercado de 24 h como el resto de cripto.
for _c in ("FIL", "THETA", "RUNE", "ATOM"):   # ATOM: en Bitstamp casi no se negocia
    MATERIAS[_c] = {"yahoo": _c + "-USD", "tv": "BINANCE:%sUSDT" % _c, "fuente": "Yahoo (%s-USD)" % _c,
                    "exacto": True, "tipo": "cripto"}
# Acciones de EE. UU.: velas de 1h solo con la bolsa abierta (empiezan a las y media).
for _a in ("AAPL", "TSLA", "MSTR"):
    MATERIAS[_a] = {"yahoo": _a, "tv": "NASDAQ:" + _a, "fuente": "Yahoo (%s)" % _a, "exacto": True,
                    "coste": 0.06, "tipo": "accion"}
ALIAS = {"GOLD": "ORO", "XAU": "ORO", "XAUUSD": "ORO", "SILVER": "PLATA", "XAG": "PLATA", "XAGUSD": "PLATA",
         "EUR": "EURUSD", "EURODOLAR": "EURUSD", "EURODÓLAR": "EURUSD"}
YAHOO_CHART = "https://query2.finance.yahoo.com/v8/finance/chart/%s?interval=60m&range=%s"
DESFASE_SESION = 2 * 3600   # la sesión del oro empieza a las 22:00/23:00 UTC: cuenta para el día siguiente


def texto_coste(c):
    return pct(c) if isinstance(c, (int, float)) else (c or "el de cada activo")


def coste_de(moneda):
    """Coste ida y vuelta en % (comisión + diferencial) por defecto: cripto 0,1; oro y plata
    0,05; EUR/USD 0,02 (1-2 pips)."""
    return MATERIAS.get(moneda, {}).get("coste", 0.1)


def tipo_de(moneda):
    """cripto (Bitstamp o Yahoo), metal, divisa o accion."""
    return MATERIAS.get(moneda, {}).get("tipo", "cripto")


def con_cierres(moneda):
    """Mercados que cierran (huecos normales en las velas): metales, divisas y acciones."""
    return tipo_de(moneda) in ("metal", "divisa", "accion")


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
    ts = r.get("timestamp") or []
    # las velas buenas empiezan siempre al mismo minuto (en punto, o a y media en acciones);
    # la última, si está a medias, llega con otra hora y se descarta
    cuenta = {}
    for t in ts:
        cuenta[t % H1] = cuenta.get(t % H1, 0) + 1
    desfase = max(cuenta, key=cuenta.get) if cuenta else 0
    velas = []
    for i, t in enumerate(ts):
        o, h, l, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c) or t % H1 != desfase:
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


MAX_PLANAS = 0.20


def planas(velas):
    """Parte de velas sin ningún movimiento (máximo = mínimo): un par que casi no se negocia
    da datos engañosos (en Bitstamp, ATOM tenía el 100 %)."""
    return sum(1 for b in velas if b["h"] == b["l"]) / float(len(velas)) if velas else 0.0


def sin_negociacion(velas):
    """Texto del motivo si la fuente casi no negocia este activo; vacío si está bien."""
    f = planas(velas)
    if f > MAX_PLANAS:
        return "en esta fuente casi no se negocia (%s de velas sin movimiento): los datos no sirven" % pct(100 * f, 0)
    return ""


VENTANA_PLANAS = 500


def recortar_inicio_sin_negociacion(velas, ventana=VENTANA_PLANAS):
    """Quita el tramo inicial de la historia en que el par apenas se negociaba (recién
    listado). Devuelve las velas desde el primer tramo de `ventana` velas con menos del 20 %
    de velas planas; si no hay ninguno, las devuelve todas (y `sin_negociacion` lo dirá)."""
    if len(velas) <= ventana:
        return velas
    planas_acum = [0]
    for b in velas:
        planas_acum.append(planas_acum[-1] + (1 if b["h"] == b["l"] else 0))
    for i in range(0, len(velas) - ventana + 1, 24):
        if (planas_acum[i + ventana] - planas_acum[i]) / float(ventana) <= MAX_PLANAS:
            return velas[i:]
    return velas


def preparar_historia(v1, v4):
    """Historia útil: sin el tramo inicial sin negociación (también en 4h). Error si ni las
    últimas velas se negocian."""
    v1 = recortar_inicio_sin_negociacion(v1)
    if sin_negociacion(v1[-VENTANA_PLANAS:]):
        raise Error(sin_negociacion(v1[-VENTANA_PLANAS:]))
    if v1:
        v4 = [b for b in v4 if b["t"] >= v1[0]["t"] // H4 * H4 - N_EMA * 3 * H4]
    return v1, v4


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


def mapa_contexto(v4, n_ema=N_EMA):
    """{inicio de la vela de 4h: (cierre, EMA 50)} calculado una vez."""
    es = ema([b["c"] for b in v4], n_ema)
    m = _Mapa((b["t"], (b["c"], e)) for b, e in zip(v4, es))
    m.orden = sorted(m)
    return m


def contexto(v4, inicio_1h, mapa=None):
    """(cierre 4h, EMA 50 4h) de la última vela de 4h anterior a la que contiene la vela de 1h
    (en oro y plata, después de un cierre de mercado, la última que hubo)."""
    mapa = mapa if mapa is not None else mapa_contexto(v4)
    i = bisect.bisect_left(mapa.orden, inicio_1h // H4 * H4) - 1
    return mapa[mapa.orden[i]] if i >= 0 else (None, None)


def senal_en(v1, j, v4, mapa=None, n_ruptura=N_RUPTURA, n_stop=N_STOP):
    """Señal de la vela 1h j (cerrada) o None. Igual que evaluar() del script de Pine.
    `n_ruptura` y `n_stop` solo cambian en las pruebas de ajustes vecinos (`validar`)."""
    if j < max(n_ruptura, n_stop):
        return None
    c4, e4 = contexto(v4, v1[j]["t"], mapa)
    if c4 is None or e4 is None:
        return None
    b = v1[j]
    hh = max(x["h"] for x in v1[j - n_ruptura:j])
    ll = min(x["l"] for x in v1[j - n_ruptura:j])
    if c4 > e4 and b["c"] > hh:
        lado, nivel, stop = "COMPRA", hh, min(x["l"] for x in v1[j - n_stop + 1:j + 1])
    elif c4 < e4 and b["c"] < ll:
        lado, nivel, stop = "VENTA", ll, max(x["h"] for x in v1[j - n_stop + 1:j + 1])
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
    continuo = not con_cierres(moneda)
    # los mercados que cierran el fin de semana pueden llevar 72 h sin vela (acciones, con festivo, 100)
    max_retraso = 24 if continuo else 100 if tipo_de(moneda) == "accion" else 72
    if retraso > max_retraso * 3600:
        res.update(ahora="NO EVALUABLE", motivo="el último dato tiene más de %d h de retraso" % max_retraso)
        return res
    problemas = (revisar_velas(v1, H1, vigencia + N_RUPTURA + 1, continuo) +
                 revisar_velas(v4, H4, N_EMA, continuo))
    if sin_negociacion(v1[-500:]):
        problemas.insert(0, sin_negociacion(v1[-500:]))
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


def simular(v1, entrada, stop, objetivo, inicio_ts, horas=48, recorridos=10000, semilla=19, ventana=1,
            fugas=None, moneda=None):
    """Monte Carlo: reconstruye las próximas `horas` velas tomando, para cada hora del día,
    una vela real de esa hora (± ventana) de la historia descargada. Con `fugas`, cada
    recorrido se mide también en el mundo real (diferencial variable por hora, comisión,
    deslizamiento y swap): los mismos caminos, dos resultados."""
    f = dict(spread=0.0, comision=0.0, desliz=0.0, swap=0.0)
    f.update(fugas or {})
    d = f["desliz"] / 100.0
    largo = stop < entrada
    riesgo = abs(entrada - stop)
    r_obj = abs(objetivo - entrada) / riesgo
    pool = pool_horario(v1)
    if sum(len(p) for p in pool) < 24 * 20:
        raise Error("hacen falta al menos 20 días de velas de 1h para simular")
    rng = random.Random(semilla)
    h0 = (inicio_ts // H1) % 24
    res, finales, Rs, Rr = {"objetivo": 0, "stop": 0, "ninguno": 0}, [], [], []
    e_real = entrada * (1 + d) if largo else entrada * (1 - d)
    R_real = (e_real - stop) if largo else (stop - e_real)
    for _ in range(recorridos):
        p, fin, k_fin = entrada, None, horas - 1
        for k in range(horas):
            h = (h0 + k + rng.randint(-ventana, ventana)) % 24
            cand = pool[h] or pool[(h0 + k) % 24]
            o, hi, lo, c = rng.choice(cand)
            alto, bajo = p * hi, p * lo
            if fin is None:
                if (bajo <= stop) if largo else (alto >= stop):
                    fin, k_fin = "stop", k
                elif (alto >= objetivo) if largo else (bajo <= objetivo):
                    fin, k_fin = "objetivo", k
            p = p * c
        fin = fin or "ninguno"
        res[fin] += 1
        finales.append(p)
        Rs.append(r_obj if fin == "objetivo" else -1.0 if fin == "stop" else
                  ((p - entrada) if largo else (entrada - p)) / riesgo)
        if fugas and R_real > 0:
            salida = (stop * (1 - d) if largo else stop * (1 + d)) if fin == "stop" else \
                objetivo if fin == "objetivo" else (p * (1 - d) if largo else p * (1 + d))
            t_out = inicio_ts + (k_fin + 1) * H1
            r = ((salida - e_real) if largo else (e_real - salida)) / R_real
            sp = f["spread"] * (factor_spread(inicio_ts, moneda) + factor_spread(t_out, moneda)) / 2
            r -= (sp + 2 * f["comision"]) / 100.0 * e_real / R_real
            r -= noches(inicio_ts, t_out) * f["swap"] / 100.0 * e_real / R_real
            Rr.append(r)
    srt = sorted(finales)
    q = lambda f: srt[min(len(srt) - 1, int(f * len(srt)))]
    n = float(recorridos)
    return {"recorridos": recorridos, "horas": horas, "semilla": semilla, "r_objetivo": r_obj,
            "p_objetivo": res["objetivo"] / n, "p_stop": res["stop"] / n, "p_ninguno": res["ninguno"] / n,
            "R_medio": statistics.mean(Rs), "mediana": q(0.5), "p5": q(0.05), "p95": q(0.95),
            "p_gana": sum(1 for r in Rs if r > 0) / n,
            "R_medio_real": statistics.mean(Rr) if Rr else None,
            "p_gana_real": sum(1 for r in Rr if r > 0) / n if Rr else None}


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


def senales(v1, v4, lado=None, solo_zona=True, n_ruptura=N_RUPTURA, n_stop=N_STOP, n_ema=N_EMA):
    out, mapa = [], mapa_contexto(v4, n_ema)
    for j in range(max(n_ruptura, n_stop), len(v1)):
        s = senal_en(v1, j, v4, mapa, n_ruptura, n_stop)
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


# ---------------------------------------------------------------- las 6 fugas: del backtest a la realidad

# Supuestos por defecto (editables con --spread, --comision, --desliz, --swap). Todos en %:
#   spread: diferencial, se paga una vez por operación (ida y vuelta)
#   comision: por lado (entrada y salida)
#   desliz: deslizamiento por lado en órdenes a mercado (entrada, stop y salida por tiempo;
#           el objetivo es una orden límite y no desliza)
#   swap: coste por noche mantenida (cruce de las 17:00 de Nueva York), sobre el importe
# Cripto: sin apalancamiento no hay swap. Si se opera con apalancamiento o CFD, hay que ponerlo.
FUGAS_CRIPTO = {"spread": 0.08, "comision": 0.0, "desliz": 0.02, "swap": 0.0}
FUGAS = {
    "ORO": {"spread": 0.03, "comision": 0.0, "desliz": 0.01, "swap": 0.015},
    "PLATA": {"spread": 0.03, "comision": 0.0, "desliz": 0.01, "swap": 0.015},
    "EURUSD": {"spread": 0.01, "comision": 0.0, "desliz": 0.005, "swap": 0.005},
    "GBPUSD": {"spread": 0.01, "comision": 0.0, "desliz": 0.005, "swap": 0.005},
    "USDJPY": {"spread": 0.01, "comision": 0.0, "desliz": 0.005, "swap": 0.005},
    "USDCAD": {"spread": 0.015, "comision": 0.0, "desliz": 0.005, "swap": 0.005},
    "AUDUSD": {"spread": 0.015, "comision": 0.0, "desliz": 0.005, "swap": 0.005},
    "NZDUSD": {"spread": 0.015, "comision": 0.0, "desliz": 0.005, "swap": 0.005},
}
FUGAS_ACCION = {"spread": 0.02, "comision": 0.0, "desliz": 0.02, "swap": 0.0}   # sin apalancamiento
ROLLOVER = 22 * 3600   # 17:00 de Nueva York en UTC (invierno); una noche = un cruce de esta hora


def fugas_de(moneda):
    if tipo_de(moneda) == "accion":
        return dict(FUGAS_ACCION)
    return dict(FUGAS.get(moneda, FUGAS_CRIPTO))


def factor_spread(ts, moneda=None):
    """Cuánto se abre el diferencial según la hora (supuesto prudente, editable aquí).
    Cripto: ×1,5 en fin de semana y ×1,3 de 00:00 a 07:00 (Madrid), con poca liquidez.
    Oro, plata y divisas: ×3 en el cambio de día de Nueva York (21:00 a 00:00 UTC) y ×1,5 en
    la sesión asiática (00:00 a 08:00, Madrid). Las noticias fuertes lo abren más y no se
    pueden prever: por eso los supuestos van por el lado prudente."""
    m = a_madrid(ts)
    if moneda and tipo_de(moneda) == "accion":
        return 1.5 if (ts // H1) % 24 in (13, 14) else 1.0     # primera hora de la sesión de Nueva York
    if moneda and con_cierres(moneda):
        if (ts // H1) % 24 in (21, 22, 23):
            return 3.0
        return 1.5 if m.hour < 8 else 1.0
    fac = 1.5 if m.weekday() >= 5 else 1.0
    return fac * (1.3 if m.hour < 7 else 1.0)


def noches(desde, hasta):
    return max(0, (hasta - ROLLOVER) // 86400 - (desde - ROLLOVER) // 86400)


def operaciones_reales(v1, lista, horas=720, fugas=None, siguiente=False, moneda=None, spread_variable=False):
    """Como `operaciones`, con la regla tal cual, pero contando las fugas del mundo real:
    diferencial, comisión y deslizamiento; con `siguiente`, la entrada es la apertura de la
    vela que sigue a la señal (la alerta llega al cierre y se entra después) y, si esa
    apertura ya está fuera de la zona de entrada o pasado el stop, no se entra (no se
    persigue); y el swap por cada noche abierta. El R se mide sobre el riesgo real
    (entrada real hasta el stop). Devuelve también la hora de entrada y de salida."""
    f = dict(spread=0.0, comision=0.0, desliz=0.0, swap=0.0)
    f.update(fugas or {})
    d = f["desliz"] / 100.0
    filas, libre_desde = [], -1
    for s in lista:
        j = s["j"]
        if j <= libre_desde:
            continue
        largo, stop, obj = s["lado"] == "COMPRA", s["stop"], s["objetivo"]
        if siguiente:
            if j + 1 >= len(v1):
                continue
            e0, t_in, desde = v1[j + 1]["o"], v1[j + 1]["t"], j + 1
            lo, hi = s["zona"]
            if not (lo <= e0 <= hi) or ((e0 <= stop) if largo else (e0 >= stop)):
                continue    # abrió fuera de la zona o pasado el stop: no se persigue
        else:
            e0, t_in, desde = s["entrada"], s["cierre_ts"], j + 1
        e = e0 * (1 + d) if largo else e0 * (1 - d)
        R = (e - stop) if largo else (stop - e)
        if R <= 0:
            continue
        tramo = v1[desde:desde + horas]
        toca = lambda b: (b["l"] <= stop or b["h"] >= obj) if largo else (b["h"] >= stop or b["l"] <= obj)
        if len(tramo) < horas and not any(toca(b) for b in tramo):
            continue    # aún no ha terminado
        fin, k, salida = None, desde + len(tramo) - 1, None
        for n, b in enumerate(tramo):
            if (b["l"] <= stop) if largo else (b["h"] >= stop):
                fin, k, salida = "stop", desde + n, stop * (1 - d) if largo else stop * (1 + d)
                break
            if (b["h"] >= obj) if largo else (b["l"] <= obj):
                fin, k, salida = "objetivo", desde + n, obj
                break
        if fin is None:
            fin, salida = "ninguno", tramo[-1]["c"] * (1 - d if largo else 1 + d)
        t_out = v1[k]["t"] + H1
        res = ((salida - e) if largo else (e - salida)) / R
        sp = f["spread"] * ((factor_spread(t_in, moneda) + factor_spread(t_out, moneda)) / 2
                            if spread_variable else 1.0)
        res -= (sp + 2 * f["comision"]) / 100.0 * e / R
        res -= noches(t_in, t_out) * f["swap"] / 100.0 * e / R
        libre_desde = k
        filas.append({"ts": s["cierre_ts"], "entrada_ts": t_in, "salida_ts": t_out, "lado": s["lado"],
                      "fin": fin, "R": res, "riesgo_pct": 100 * R / e})
    return filas


def cartera(por_moneda, max_abiertas=3, tope_diario_R=-2.0):
    """Junta las operaciones de varias monedas en el orden en que se abren y aplica los
    límites del usuario: como mucho `max_abiertas` a la vez y, si en el día (Madrid) ya se ha
    perdido `tope_diario_R` (con 1 % por operación, el 2 % del capital), no se abre ninguna más."""
    todas = sorted(((o["entrada_ts"], m, o) for m, ops in por_moneda.items() for o in ops),
                   key=lambda x: (x[0], x[1]))
    aceptadas = []
    for t, m, o in todas:
        abiertas = sum(1 for _, a in aceptadas if a["salida_ts"] > t)
        dia = a_madrid(t).date()
        perdido = sum(a["R"] for _, a in aceptadas if a["salida_ts"] <= t and a_madrid(a["salida_ts"]).date() == dia)
        if abiertas >= max_abiertas or perdido <= tope_diario_R:
            continue
        aceptadas.append((m, o))
    return aceptadas


PASOS_FUGAS = [
    ("ideal", "Backtest ideal (entra al cierre exacto, sin costes)"),
    ("costes", "+ 01 diferencial (variable por hora) y 04 comisión"),
    ("desliz", "+ 02 deslizamiento"),
    ("retraso", "+ 03 retraso: entra en la vela siguiente y no persigue"),
    ("swap", "+ 05 swap por noche"),
]


def fugas_moneda(v1, v4, moneda, horas=720, fugas=None):
    """Las operaciones de la regla en cada paso, de ideal a real, para una moneda."""
    f = fugas or fugas_de(moneda)
    lista = senales(v1, v4)
    pasos = {
        "ideal": dict(spread=0, comision=0, desliz=0, swap=0),
        "costes": dict(spread=f["spread"], comision=f["comision"], desliz=0, swap=0),
        "desliz": dict(spread=f["spread"], comision=f["comision"], desliz=f["desliz"], swap=0),
        "retraso": dict(spread=f["spread"], comision=f["comision"], desliz=f["desliz"], swap=0),
        "swap": f,
    }
    return {p: operaciones_reales(v1, lista, horas, pasos[p], siguiente=p in ("retraso", "swap"),
                                  moneda=moneda, spread_variable=p != "ideal")
            for p, _ in PASOS_FUGAS}


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
    ("regimen", "no operar con el mercado nervioso o en desplome (régimen del día anterior)"),
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
    if moneda and tipo_de(moneda) == "accion":
        return diarias_de(v1, 0, 4)
    return diarias_de(v1, DESFASE_SESION, 20) if moneda and tipo_de(moneda) in ("metal", "divisa") else diarias_de(v1)


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
    reg = regimen_diario(v1, moneda)
    desfase = DESFASE_SESION if moneda and tipo_de(moneda) in ("metal", "divisa") else 0
    return {"vmed": vmed, "dia": dia, "dias": sorted(dia), "desfase": desfase, "reg": reg, "reg_dias": sorted(reg)}


def pasa_filtro(nombre, s, v1, extra):
    if nombre == "ninguno":
        return True
    largo = s["lado"] == "COMPRA"
    if nombre == "horas":
        return 15 <= a_madrid(s["cierre_ts"]).hour <= 19
    if nombre == "volumen":
        m = extra["vmed"][s["j"]]
        return m is not None and v1[s["j"]]["v"] > m
    if nombre == "regimen":
        r = regimen_de(s["t"], extra.get("reg") or {}, extra.get("reg_dias") or [])
        return r is not None and r not in ("NERVIOSO", "DESPLOME")
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
        f["mejora"] = f is not base and all(
            p.get("n", 0) >= min_ops and b.get("n", 0) and p["R_medio"] > b["R_medio"] + margen
            for p, b in zip(f["partes"], base["partes"]))
        # ✅ solo si además gana dinero: mejorar algo que pierde no lo hace bueno
        f["robusto"] = f["mejora"] and f["total"].get("R_medio", 0) > 0
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
            "limite": limite, "riesgo_objetivo": capital * riesgo_pct / 100.0,
            "unidades_riesgo": suelo(por_riesgo, dec), "apalancamiento": por_riesgo * entrada / capital}


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
    previa = _PRECISION[0]
    out = ["| Activo | Último cierre (hora) | Ahora | 🟢 COMPRA si | 🔴 VENTA si | Caducidad |",
           "|---|---|---|---|---|---|"]
    for r in resultados:
        fijar_precision(r["moneda"])
        out.append(linea_tabla(r))
    for r in resultados:
        fijar_precision(r["moneda"])
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
            out.append("  1h: RSI %s · MACD %s / señal %s / histograma %s · Bollinger %s (ancho %s) · %s" % (
                fmt(ind["rsi"], 2), fmt(ind["macd"]), fmt(ind["senal"]), fmt(ind["hist"]),
                "mitad alta" if ind["bb_pos"] >= 0.5 else "mitad baja", pct(ind["bb_ancho"], 1),
                "volumen %s de su media" % pct(100 * ind["vol_rel"], 0) if ind["vol_rel"] is not None
                else "sin datos de volumen"))
        if r.get("ultima_senal"):
            out.append("  Última señal (24 h): " + texto_senal(r["ultima_senal"]))
        if r.get("retraso_h"):
            out.append("  Aviso: el dato llega con %s h de retraso." % fmt(r["retraso_h"], 0))
    _PRECISION[0] = previa
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
    if not es_materia(moneda) or offline or MATERIAS[moneda].get("exacto"):
        return ""
    return ("⚠️ %s: los niveles salen de los %s. %s es el precio al contado y suele estar algo más "
            "barato (en el oro, unos 30 $). Comprueba el nivel en TradingView antes de crear la alerta, "
            "o pásame las velas de %s. Las señales y los estudios en R sí valen." % (
                moneda, MATERIAS[moneda]["fuente"], simbolo_tv(moneda), simbolo_tv(moneda)))


# ---------------------------------------------------------------- comandos

def _monedas(lista):
    out = []
    for m in (lista or MONEDAS):
        m = m.upper().split(":")[-1].replace("/", "").replace("-", "")
        m = ALIAS.get(m, m)
        if m not in MATERIAS:
            for fin in ("USDT", "USD"):
                if m.endswith(fin) and len(m) > len(fin) and m[:-len(fin)]:
                    m = m[:-len(fin)]
                    break
        out.append(ALIAS.get(m, m))
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
    fijar_precision(m)
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
        print(ficha(1, m, "COMPRA", r["compra_si"], "1h", "Cierre por encima", caduca, "" if MATERIAS.get(m, {}).get("exacto") else "revisar volumen"))
        st = r["stop_compra"]
        if st < r["compra_si"]:
            R = r["compra_si"] - st
            print("\nPlan si salta: entrada %s · invalidación %s (mínimo de las 10 últimas velas) · R %s · "
                  "objetivo 2R %s · zona hasta %s · %s. El stop se recalcula con las velas de ese momento." % (
                      fmt(r["compra_si"]), fmt(st), fmt(R), fmt(r["compra_si"] + 2 * R), fmt(r["compra_si"] + 0.5 * R),
                      nota_stop(R, r.get("atr"))))
    if r.get("venta_si") is not None:
        print(ficha(1, m, "VENTA", r["venta_si"], "1h", "Cierre por debajo", caduca, "" if MATERIAS.get(m, {}).get("exacto") else "revisar volumen"))
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
    r = estado_moneda(_monedas([a.moneda])[0], v1, v4, ahora, a.vigencia)
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
    m = _monedas([a.moneda])[0]
    fijar_precision(m)
    v1, v4 = cargar(m, a.offline, a.horas_datos)
    v1c, v4c = cerradas(v1, H1, ahora), cerradas(v4, H4, ahora)
    entrada, stop, obj, origen = _plan_de(a, v1c, v4c, ahora)
    lado = "COMPRA" if stop < entrada else "VENTA"
    mc = simular(v1c, entrada, stop, obj, v1c[-1]["t"] + H1, a.horas, a.recorridos, a.semilla,
                 fugas=fugas_de(m), moneda=m)
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
        "Veredicto: " + veredicto(mc), "",
        "Mismos %s recorridos, dos mundos:" % fmt(mc["recorridos"], 0),
        "| | Mundo ideal | Mundo real (fugas) |", "|---|---|---|",
        "| R medio | %s | %s |" % (fmt(mc["R_medio"], 3), fmt(mc["R_medio_real"], 3)),
        "| Recorridos que ganan | %s | %s |" % (pct(100 * mc["p_gana"], 1), pct(100 * (mc["p_gana_real"] or 0), 1)),
        "El mundo real resta diferencial (variable por hora), comisión, deslizamiento y swap con los "
        "supuestos del activo (ver `fugas`). El retraso no entra aquí: se simula desde la entrada.", ""]
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


def estudio(datos, horas=720, coste_pct=None, lado=None):
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
                cp = coste_pct if coste_pct is not None else coste_de(m)
                ops = [o for o in operaciones(v1, lista, horas, modo, r, cp, atrs) if o["ts"] >= t_ini]
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
                f["p2"]["R_medio"] > base["p2"]["R_medio"] + margen and f["total"].get("R_medio", 0) > 0):
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
    if a.coste is None:
        est["coste_pct"] = None
    if a.json:
        print(json.dumps(est, ensure_ascii=False, indent=1))
        return 0
    rm = lambda r: fmt(r["R_medio"], 2) if r.get("n") else "sin datos"
    out = ["Estudio de la regla «ruptura 20 + contexto 4h» · %d monedas · %s a %s (Madrid)" % (
        len(datos), hora(est["desde"]), hora(est["hasta"])),
        "Periodo 1: hasta %s · periodo 2: desde %s · coste %s ida y vuelta · máximo %d h por operación" % (
            hora(est["corte"]), hora(est["corte"]), texto_coste(est["coste_pct"]), est["horas"]),
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
    m = _monedas([a.moneda])[0]
    fijar_precision(m)
    v1, v4 = cargar(m, a.offline, a.dias * 24)
    v1, v4 = cerradas(v1, H1, ahora), cerradas(v4, H4, ahora)
    try:
        v1, v4 = preparar_historia(v1, v4)
    except Error as e:
        raise Error("%s: %s" % (m, e))
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
        ("%02d:00 (%s, volumen ×%s)" % (h, pct(rg), fmt(vr, 1)) if vr else "%02d:00 (%s)" % (h, pct(rg)))
        for h, (rg, vr) in top),
        "Horas más tranquilas: " + ", ".join("%02d:00 (%s)" % (h, pct(rg)) for h, (rg, vr) in low)]
    est = estudio_filtros(v1, v4, a.horas, a.coste if a.coste is not None else coste_de(m), moneda=m)
    c = est["cortes"]
    fecha = lambda t: a_madrid(t).strftime("%d/%m/%Y")
    out += ["", "Estudio de la regla con filtros · %s a %s (%s velas de 1h) · objetivo 2R · coste %s · máximo %d h" % (
        fecha(c[0]), fecha(v1[-1]["t"]), fmt(len(v1), 0), texto_coste(est["coste_pct"]), est["horas"]),
        "Periodos: P1 hasta %s · P2 hasta %s · P3 hasta hoy." % (fecha(c[1]), fecha(c[2])),
        "| Filtro | Stop | Ops | Aciertos | R P1 | R P2 | R P3 | R medio | Compras R | Ventas R |",
        "|---|---|---|---|---|---|---|---|---|---|"]
    rm = lambda x: fmt(x["R_medio"], 2) if x.get("n") else "-"
    for f in est["filas"]:
        t = f["total"]
        out.append("| %s%s | %s | %d | %s | %s | %s | %s | %s | %s | %s |" % (
            f["filtro"], " ✅" if f["robusto"] else " ↑" if f["mejora"] else "",
            "regla" if f["stop"] == "regla" else "1,5 ATR",
            t.get("n", 0), pct(t["acierto"], 0) if t.get("n") else "-", rm(f["partes"][0]), rm(f["partes"][1]),
            rm(f["partes"][2]), rm(t), rm(f["por_lado"]["COMPRA"]), rm(f["por_lado"]["VENTA"])))
    buenos = [f for f in est["filas"] if f["robusto"]]
    out.append("")
    out.append("Filtros: " + "; ".join("%s = %s" % (n, t) for n, t in FILTROS[1:]) + ".")
    if buenos:
        out.append("✅ = mejora a la regla en los 3 periodos, con margen y operaciones suficientes, y gana dinero. "
                   "Es una PROPUESTA: la regla no se cambia sin que lo decidas tú.")
    else:
        out.append("Ningún filtro mejora a la regla en los 3 periodos ganando dinero: no conviene añadir ninguno todavía.")
    if any(f["mejora"] and not f["robusto"] for f in est["filas"]):
        out.append("↑ = mejora a la regla en los 3 periodos, pero sigue perdiendo: no sirve para operar.")
    base = est["filas"][0]["total"]
    if base.get("n") and base["R_medio"] <= 0:
        out.append("⚠️ La regla tal cual NO gana en este activo (%s R por operación, con costes)." % fmt(base["R_medio"], 2))
    out += ["", "Un estudio del pasado no garantiza el futuro.", CIERRE]
    print("\n".join(out))
    return 0


def ventaja(v1, v4, horas=720, coste_pct=None, tramos=3, moneda=None):
    """Cómo le ha ido a la regla en esta moneda: total y último periodo, sin y con el filtro
    de horas. Sirve para ordenar oportunidades, no para cambiar la regla."""
    lista, atrs, extra = senales(v1, v4), atr(v1), datos_filtros(v1, moneda)
    coste_pct = coste_pct if coste_pct is not None else coste_de(moneda)
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
        fijar_precision(o["moneda"])
        if o.get("ahora") == "NO EVALUABLE":
            out.append("| %d | %s | NO EVALUABLE | | | | |" % (i, o["moneda"]))
            continue
        lado = o["lado"]
        disparo = "%s vela 1h %s %s" % (ICONO[lado] + " " + lado, ">" if lado == "COMPRA" else "<", fmt(o["nivel"]))
        dist = "%s (%s ATR)" % (pct(o["dist_pct"], 1), fmt(o["dist_atr"], 1) if o["dist_atr"] is not None else "-")
        v = o["ventaja"]["ninguno"]
        out.append("| %d | %s | %s | %s | %s | %s R | %s R |" % (
            i, o["moneda"], etiqueta_ahora(o["ahora"]), disparo, dist, rm(v[lado.lower()]), rm(v["ultimo"])))
    fijar_precision(None)
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


MIN_OPS_FIABLE = 60


def marca_real(r):
    """🟢 / ⚪ / 🔴 según el R medio en el mundo real; ⚠️ si hay pocas operaciones."""
    if not r.get("n") or r["n"] < MIN_OPS_FIABLE:
        return "⚠️"
    return "🟢" if r["R_medio"] > 0.02 else "🔴" if r["R_medio"] < -0.02 else "⚪"


def cmd_fugas(a):
    ahora = parse_ahora(a.ahora)
    monedas = _monedas(a.monedas)
    res, faltan = {}, []
    for m in monedas:
        try:
            v1, v4 = cargar(m, a.offline, a.dias * 24)
            v1, v4 = cerradas(v1, H1, ahora), cerradas(v4, H4, ahora)
            v1, v4 = preparar_historia(v1, v4)
            f = fugas_de(m)
            for k in ("spread", "comision", "desliz", "swap"):
                if getattr(a, k) is not None:
                    f[k] = getattr(a, k)
            res[m] = (fugas_moneda(v1, v4, m, a.horas, f), f, v1[0]["t"], v1[-1]["t"])
        except Error as e:
            faltan.append("%s (%s)" % (m, e))
    if not res:
        raise Error("no hay datos de ninguna moneda")
    rm = lambda r: fmt(r["R_medio"], 2) if r.get("n") else "-"
    fac = lambda r: fmt(r["factor"], 2) if r.get("factor") is not None else "-"
    out = ["Mismo estudio, dos mundos: de backtest a realidad · %s · %s a %s (Madrid)" % (
        ", ".join(res), a_madrid(min(x[2] for x in res.values())).strftime("%d/%m/%Y"),
        a_madrid(max(x[3] for x in res.values())).strftime("%d/%m/%Y")),
        "Regla del script tal cual (stop de 10 velas, objetivo 2R), sin solaparse, hasta stop u objetivo.", "",
        "| Paso | Operaciones | Aciertos | R medio | Factor | Resultado con 1 % por operación |",
        "|---|---|---|---|---|---|"]
    filas = {}
    for p, texto in PASOS_FUGAS:
        ops = [o for x in res.values() for o in x[0][p]]
        r = resumen(ops)
        filas[p] = r
        out.append("| %s | %d | %s | %s | %s | %s |" % (
            texto, r.get("n", 0), pct(r["acierto"], 0) if r.get("n") else "-", rm(r), fac(r),
            pct(r["R_total"], 1) if r.get("n") else "-"))
    if len(res) > 1:
        acept = cartera({m: x[0]["swap"] for m, x in res.items()}, a.max_abiertas, -a.tope_diario)
        r = resumen([o for _, o in acept])
        filas["cartera"] = r
        out.append("| + 06 límite de cartera: %d a la vez y −%s %% al día | %d | %s | %s | %s | %s |" % (
            a.max_abiertas, fmt(a.tope_diario, 0), r.get("n", 0), pct(r["acierto"], 0) if r.get("n") else "-",
            rm(r), fac(r), pct(r["R_total"], 1) if r.get("n") else "-"))
    ideal, fugado, real = filas["ideal"], filas["swap"], filas.get("cartera") or filas["swap"]
    out.append("")
    if ideal.get("n") and fugado.get("n"):
        out.append("Las fugas 01 a 05 se comen %s R por operación (de %s a %s)." % (
            fmt(ideal["R_medio"] - fugado["R_medio"], 2), rm(ideal), rm(fugado)))
    if filas.get("cartera", {}).get("n"):
        out.append("El límite de cartera (06) deja %d de %d operaciones y el R medio queda en %s: frena los días "
                   "malos, pero también deja pasar oportunidades." % (real["n"], fugado["n"], rm(real)))
    if ideal.get("n") and real.get("n"):
        out.append("Veredicto: %s" % ("🟢 la regla sigue ganando en el mundo real." if real["R_medio"] > 0.02 else
                                       "⚪ en el mundo real queda a la par: no da ventaja." if real["R_medio"] > -0.02 else
                                       "🔴 en el mundo real pierde: no conviene operarla así."))
    if len(res) > 1:
        out += ["", "Moneda a moneda, en el mundo real (todas las fugas menos el límite de cartera):",
                "| | Moneda | Operaciones | Aciertos | R medio | Ideal |", "|---|---|---|---|---|---|"]
        for m, x in sorted(res.items(), key=lambda kv: -(resumen(kv[1][0]["swap"]).get("R_medio") or -9)):
            r, i = resumen(x[0]["swap"]), resumen(x[0]["ideal"])
            out.append("| %s | %s | %d | %s | %s | %s |" % (
                marca_real(r), m, r.get("n", 0), pct(r["acierto"], 0) if r.get("n") else "-", rm(r), rm(i)))
        out.append("🟢 gana (más de +0,02 R) · ⚪ a la par · 🔴 pierde · ⚠️ menos de %d operaciones: pocos datos, "
                   "no fiable todavía." % MIN_OPS_FIABLE)
    etiqueta = lambda m: m if m in FUGAS else "acciones" if tipo_de(m) == "accion" else "cripto"
    supuestos = sorted({(etiqueta(m), "diferencial %s, comisión %s por lado, deslizamiento %s por lado, "
                         "swap %s por noche" % (pct(x[1]["spread"], 3), pct(x[1]["comision"], 3), pct(x[1]["desliz"], 3),
                                                pct(x[1]["swap"], 3))) for m, x in res.items()})
    out += ["", "Supuestos de costes (cámbialos con --spread, --comision, --desliz y --swap si tu bróker es distinto):"]
    out += ["  %s: %s" % (k, v) for k, v in supuestos]
    out += ["  Cripto sin apalancamiento no paga swap; con apalancamiento o CFD, ponlo con --swap.",
            "  El retraso se mide entrando en la apertura de la vela siguiente a la señal; si ya está fuera de la "
            "zona de entrada, la operación no se hace.", ""]
    for x in faltan:
        out.append("Sin datos de " + x)
    out += ["Un estudio del pasado no garantiza el futuro.", CIERRE]
    print("\n".join(out))
    return 0


# ---------------------------------------------------------------- validación dura: las 8 pruebas

VECINOS = [(n_r, n_s, N_EMA) for n_r in (15, 20, 25) for n_s in (8, 10, 12)] + [(N_RUPTURA, N_STOP, 40),
                                                                              (N_RUPTURA, N_STOP, 60)]
REGIMENES = ("TENDENCIA TRANQUILA", "LATERAL", "NERVIOSO", "DESPLOME")


def ops_reales(v1, v4, moneda, f=None, horas=720, n_ruptura=N_RUPTURA, n_stop=N_STOP, n_ema=N_EMA):
    """Operaciones en el mundo real (las 5 fugas de coste, retraso incluido)."""
    lista = senales(v1, v4, n_ruptura=n_ruptura, n_stop=n_stop, n_ema=n_ema)
    return operaciones_reales(v1, lista, horas, f or fugas_de(moneda), siguiente=True, moneda=moneda,
                              spread_variable=True)


def caida_maxima(Rs):
    """Mayor caída de la curva acumulada (en R; con 1 % por operación, en % del capital)."""
    pico = acum = peor = 0.0
    for r in Rs:
        acum += r
        pico = max(pico, acum)
        peor = max(peor, pico - acum)
    return peor


def sharpe(rets):
    """Sharpe anual de rentabilidades mensuales (sin tipo libre de riesgo)."""
    if len(rets) < 6:
        return None
    sd = statistics.pstdev(rets)
    return statistics.mean(rets) / sd * math.sqrt(12) if sd > 0 else None


def mes_de(ts):
    m = a_madrid(ts)
    return m.year * 12 + m.month - 1


def mensual_ops(ops, desde, hasta):
    """Resultado de cada mes en % del capital (1 % por operación), meses sin operaciones a 0."""
    meses = {k: 0.0 for k in range(mes_de(desde), mes_de(hasta) + 1)}
    for o in ops:
        k = mes_de(o["salida_ts"])
        if k in meses:
            meses[k] += o["R"]
    return [meses[k] for k in sorted(meses)]


def comprar_y_mantener(v1, desde, hasta):
    """Comprar al principio y no tocar: rentabilidad, caída máxima y Sharpe mensual."""
    tramo = [b for b in v1 if desde <= b["t"] <= hasta]
    if len(tramo) < 2:
        return None
    pico, peor, ultimo_mes, cierres_mes = tramo[0]["c"], 0.0, None, []
    for b in tramo:
        pico = max(pico, b["c"])
        peor = max(peor, 1 - b["c"] / pico)
        k = mes_de(b["t"])
        if k != ultimo_mes:
            cierres_mes.append(b["c"])
            ultimo_mes = k
        else:
            cierres_mes[-1] = b["c"]
    rets = [100 * (b / a - 1) for a, b in zip(cierres_mes, cierres_mes[1:])]
    return {"rent_pct": 100 * (tramo[-1]["c"] / tramo[0]["c"] - 1), "caida_pct": 100 * peor, "sharpe": sharpe(rets)}


def doble_coste(f):
    return {k: 2 * v for k, v in f.items()}


def trimestres(ops, desde, hasta):
    """R total de cada trimestre (por fecha de salida)."""
    q0, q1 = mes_de(desde) // 3, mes_de(hasta) // 3
    por = {q: 0.0 for q in range(q0, q1 + 1)}
    for o in ops:
        q = mes_de(o["salida_ts"]) // 3
        if q in por:
            por[q] += o["R"]
    return [por[q] for q in sorted(por)]


def walk_forward(por_variante, base, desde, hasta, ventana=4):
    """Prueba caminando hacia delante: cada trimestre se usa el ajuste vecino que mejor fue en
    los `ventana` trimestres anteriores, y se compara con la regla fija. Si elegir el «mejor»
    ajuste con el pasado no gana a la regla fija fuera de muestra, optimizar no sirve."""
    q_var = {v: trimestres(ops, desde, hasta) for v, ops in por_variante.items()}
    fija = q_var[base]
    elegido, fija_fuera = [], []
    for q in range(ventana, len(fija)):
        mejor = max(q_var, key=lambda v: sum(q_var[v][q - ventana:q]))
        elegido.append(q_var[mejor][q])
        fija_fuera.append(fija[q])
    return {"trimestres": len(fija), "positivos": sum(1 for x in fija if x > 0),
            "fuera": len(fija_fuera), "fija_R": sum(fija_fuera), "optimizada_R": sum(elegido)}


def regimen_diario(v1, moneda=None):
    """{inicio del día: régimen} con datos hasta ese día (sin mirar el futuro). Reglas simples:
    DESPLOME si en 7 días cae más de 2 desviaciones diarias × √7; NERVIOSO si la volatilidad de
    20 días está en su 20 % más alto del último año; TENDENCIA TRANQUILA si el precio, la EMA 20
    y la EMA 50 diarias están en orden y separadas al menos un 3 %; si no, LATERAL."""
    d = diarias_para(v1, moneda)
    cs = [b["c"] for b in d]
    e20, e50 = ema(cs, 20), ema(cs, 50)
    rets = [0.0] + [cs[i] / cs[i - 1] - 1 for i in range(1, len(cs))]
    vols, out = [], {}
    for i in range(len(cs)):
        vol = statistics.pstdev(rets[max(1, i - 19):i + 1]) if i >= 20 else None
        vols.append(vol)
        if vol is None or e50[i] is None or i < 7:
            continue
        hist = [v for v in vols[max(0, i - 365):i] if v is not None]
        pctl = sum(1 for v in hist if v < vol) / float(len(hist)) if hist else 0.5
        ret7 = cs[i] / cs[i - 7] - 1
        sep = abs(e20[i] - e50[i]) / e50[i]
        if ret7 < -2 * vol * math.sqrt(7):
            reg = "DESPLOME"
        elif pctl >= 0.8:
            reg = "NERVIOSO"
        elif sep >= 0.03 and ((cs[i] > e20[i] > e50[i]) or (cs[i] < e20[i] < e50[i])):
            reg = "TENDENCIA TRANQUILA"
        else:
            reg = "LATERAL"
        out[d[i]["t"]] = reg
    return out


def regimen_de(ts, reg, dias):
    """Régimen del último día cerrado antes de `ts`."""
    i = bisect.bisect_left(dias, ts - 86400) - 1
    return reg[dias[i]] if i >= 0 else None


def por_regimen(ops, reg):
    dias = sorted(reg)
    grupos = {r: [] for r in REGIMENES}
    for o in ops:
        r = regimen_de(o["entrada_ts"], reg, dias)
        if r:
            grupos[r].append(o)
    tiempo = {r: sum(1 for x in reg.values() if x == r) / float(len(reg) or 1) for r in REGIMENES}
    return {r: dict(resumen(g), tiempo=tiempo[r]) for r, g in grupos.items()}


def umbral_regla_rota(Rs, n=30, recorridos=3000, semilla=7):
    """Lo que la regla suele hacer en `n` operaciones: si las últimas `n` reales suman menos que
    el 5 % peor de los recorridos al azar, la regla se comporta peor de lo esperado (avisar)."""
    if len(Rs) < n:
        return None
    rng = random.Random(semilla)
    sumas = sorted(sum(rng.choice(Rs) for _ in range(n)) for _ in range(recorridos))
    caidas = sorted(caida_maxima([rng.choice(Rs) for _ in range(100)]) for _ in range(1000))
    return {"n": n, "p5": sumas[int(0.05 * recorridos)], "ultimas": sum(Rs[-n:]),
            "caida_p95": caidas[int(0.95 * len(caidas))]}


def validar_activo(m, v1, v4, horas=720):
    f = fugas_de(m)
    base = (N_RUPTURA, N_STOP, N_EMA)
    por_var = {v: ops_reales(v1, v4, m, f, horas, *v) for v in VECINOS}
    ops = por_var[base]
    if not ops:
        raise Error("%s: sin operaciones en la historia" % m)
    desde, hasta = v1[0]["t"], v1[-1]["t"]
    Rs = [o["R"] for o in sorted(ops, key=lambda o: o["salida_ts"])]
    real = resumen(ops)
    x2 = resumen(ops_reales(v1, v4, m, doble_coste(f), horas))
    vecinos = {v: resumen(o).get("R_medio") for v, o in por_var.items()}
    pos_vec = sum(1 for v, r in vecinos.items() if r is not None and r > 0)
    wf = walk_forward(por_var, base, desde, hasta)
    meses = mensual_ops(ops, desde, hasta)
    bh = comprar_y_mantener(v1, desde, hasta)
    reg = por_regimen(ops, regimen_diario(v1, m))
    rr = umbral_regla_rota(Rs)
    res = {"moneda": m, "real": real, "x2": x2, "vecinos": vecinos, "pos_vecinos": pos_vec, "wf": wf,
           "caida_R": caida_maxima(Rs), "sharpe": sharpe(meses), "rent_pct": sum(Rs), "bh": bh, "regimen": reg,
           "regla_rota": rr, "desde": desde, "hasta": hasta}
    ahora_reg = regimen_diario(v1, m)
    res["regimen_ahora"] = None
    if ahora_reg:
        rg = ahora_reg[max(ahora_reg)]
        d = diarias_para(v1, m)
        cs = [b["c"] for b in d]
        sube = cs[-1] > ema(cs, 50)[-1] if len(cs) >= 50 else None
        res["regimen_ahora"] = rg + ("" if sube is None or rg in ("NERVIOSO", "DESPLOME") else
                                     " (al alza)" if sube else " (a la baja)")
    res["veredicto"], res["fallos"] = veredicto_validacion(res)
    return res


def veredicto_validacion(r):
    fallos = []
    real, x2, wf, bh = r["real"], r["x2"], r["wf"], r["bh"]
    if not real.get("n") or real["R_medio"] <= 0.0:
        return "🔴 NO OPERAR", ["en el mundo real no gana"]
    if real["R_medio"] <= 0.02:
        fallos.append("en el mundo real gana muy poco")
    if not x2.get("n") or x2["R_medio"] <= 0:
        fallos.append("con el doble de costes deja de ganar")
    if r["pos_vecinos"] < 7:
        fallos.append("depende del ajuste exacto: solo %d de %d ajustes vecinos ganan" % (r["pos_vecinos"], len(VECINOS)))
    if wf["trimestres"] and wf["positivos"] / float(wf["trimestres"]) < 0.55:
        fallos.append("gana en pocos trimestres (%d de %d)" % (wf["positivos"], wf["trimestres"]))
    if bh and bh.get("sharpe") is not None and (r["sharpe"] or 0) <= bh["sharpe"]:
        fallos.append("comprar y mantener ha sido mejor en rentabilidad ajustada al riesgo")
    if real["n"] < 100:
        fallos.append("pocas operaciones (%d)" % real["n"])
    if r["caida_R"] > 15:
        fallos.append("caída máxima del %s con 1 %% por operación (tope 15 %%)" % pct(r["caida_R"], 0))
    rr = r["regla_rota"]
    if rr and rr["ultimas"] < rr["p5"]:
        fallos.append("REGLA ROTA: las últimas %d operaciones van peor que el 95 %% de lo esperado" % rr["n"])
    return ("🟢 SÓLIDA" if not fallos else "🟡 FRÁGIL"), fallos


def como_falla(r):
    """Puntos débiles, para el apartado «¿Cómo puede fallar?»."""
    out = ["Sesgo de supervivencia: solo se estudian activos que siguen existiendo hoy; los que se hundieron "
           "no están, así que el pasado parece algo mejor de lo que fue."]
    peor = min(((k, v) for k, v in r["regimen"].items() if v.get("n", 0) >= 15), key=lambda kv: kv[1]["R_medio"],
               default=None)
    if peor and peor[1]["R_medio"] < 0:
        out.append("Pierde en mercado %s (%s R por operación, %s del tiempo): si el mercado pasa a ese estado, "
                   "la ventaja desaparece." % (peor[0].lower(), fmt(peor[1]["R_medio"], 2), pct(100 * peor[1]["tiempo"], 0)))
    if not r["x2"].get("n") or r["x2"]["R_medio"] <= 0:
        out.append("Muy sensible a los costes: con el doble de diferencial y deslizamiento deja de ganar.")
    if r["pos_vecinos"] < 7:
        out.append("Frágil al ajuste: cambiar un poco las velas de ruptura, stop o media la hace perder.")
    if r["wf"]["fuera"] and r["wf"]["optimizada_R"] < r["wf"]["fija_R"]:
        out.append("Optimizar con el pasado no ayuda: el «mejor ajuste» elegido cada trimestre lo hizo peor que la "
                   "regla fija. Mantener la regla fija es lo correcto.")
    if tipo_de(r["moneda"]) == "cripto" and not es_materia(r["moneda"]):
        out.append("Precio de referencia: Bitstamp. Quantfury usa Binance o Coinbase; en momentos bruscos puede diferir.")
    if r["caida_R"] > 15:
        out.append("Racha mala larga: la caída máxima pasó del 15 %% con 1 %% por operación (%s)." % pct(r["caida_R"], 0))
    return out


def informe_validacion(r):
    rm = lambda x: fmt(x["R_medio"], 2) if x.get("n") else "-"
    bh = r["bh"] or {}
    fecha = lambda t: a_madrid(t).strftime("%d/%m/%Y")
    out = ["## %s · %s" % (r["moneda"], r["veredicto"]),
           "%s a %s · régimen de mercado ahora: %s" % (fecha(r["desde"]), fecha(r["hasta"]), (r["regimen_ahora"] or "sin dato").lower()),
           "", "| Prueba | Resultado |", "|---|---|",
           "| Mundo real (5 fugas) | %s R · %d operaciones · %s aciertos |" % (rm(r["real"]), r["real"].get("n", 0),
                                                                          pct(r["real"].get("acierto", 0), 0)),
           "| Con el doble de costes | %s R |" % rm(r["x2"]),
           "| Ajustes vecinos que ganan | %d de %d |" % (r["pos_vecinos"], len(VECINOS)),
           "| Trimestres que ganan | %d de %d |" % (r["wf"]["positivos"], r["wf"]["trimestres"]),
           "| Caminando hacia delante (%d trimestres) | regla fija %s R · ajuste «optimizado» %s R |" % (
               r["wf"]["fuera"], fmt(r["wf"]["fija_R"], 1), fmt(r["wf"]["optimizada_R"], 1)),
           "| Caída máxima (1 %% por operación) | %s |" % pct(r["caida_R"], 1),
           "| Sharpe anual: regla / comprar y mantener | %s / %s |" % (
               fmt(r["sharpe"], 2) if r["sharpe"] is not None else "-",
               fmt(bh.get("sharpe"), 2) if bh.get("sharpe") is not None else "-"),
           "| Comprar y mantener en el periodo | %s (caída máxima %s) |" % (
               pct(bh.get("rent_pct", 0), 0), pct(bh.get("caida_pct", 0), 0)),
           "| Regla con 1 %% por operación en el periodo | %s |" % pct(r["rent_pct"], 0)]
    rr = r["regla_rota"]
    if rr:
        out.append("| Señal de regla rota | últimas %d: %s R · umbral %s R · caída máx. esperable %s R |" % (
            rr["n"], fmt(rr["ultimas"], 1), fmt(rr["p5"], 1), fmt(rr["caida_p95"], 1)))
    out += ["", "Por tipo de mercado (régimen del día anterior a la entrada):",
            "| Régimen | Tiempo | Operaciones | R medio |", "|---|---|---|---|"]
    for k in REGIMENES:
        x = r["regimen"][k]
        out.append("| %s | %s | %d | %s |" % (k.capitalize(), pct(100 * x["tiempo"], 0), x.get("n", 0), rm(x)))
    if r["fallos"]:
        out += ["", "Por qué no es 🟢: " + "; ".join(r["fallos"]) + "."]
    out += ["", "¿Cómo puede fallar?"] + ["- " + x for x in como_falla(r)]
    return out


def cmd_validar(a):
    ahora = parse_ahora(a.ahora)
    res, faltan = [], []
    for m in _monedas(a.monedas or ["BTC", "ETH", "SOL", "DOGE"]):
        fijar_precision(m)
        try:
            v1, v4 = cargar(m, a.offline, a.dias * 24)
            v1, v4 = preparar_historia(cerradas(v1, H1, ahora), cerradas(v4, H4, ahora))
            res.append(validar_activo(m, v1, v4, a.horas))
        except Error as e:
            faltan.append("%s (%s)" % (m, e))
    fijar_precision(None)
    if not res:
        raise Error("no hay datos de ninguna moneda")
    out = ["Validación dura de la regla «ruptura 20 + contexto 4h» (mundo real, con las fugas)", "",
           "| Activo | Veredicto | R real | ×2 costes | Vecinos | Trimestres | Caída máx. | Sharpe regla/B&H | Últimas 30 |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(res, key=lambda r: -(r["real"].get("R_medio") or -9)):
        rr, bh = r["regla_rota"], r["bh"] or {}
        out.append("| %s | %s | %s | %s | %d/%d | %d/%d | %s | %s / %s | %s |" % (
            r["moneda"], r["veredicto"], fmt(r["real"].get("R_medio", 0), 2),
            fmt(r["x2"].get("R_medio", 0), 2) if r["x2"].get("n") else "-", r["pos_vecinos"], len(VECINOS),
            r["wf"]["positivos"], r["wf"]["trimestres"], pct(r["caida_R"], 0),
            fmt(r["sharpe"], 2) if r["sharpe"] is not None else "-",
            fmt(bh.get("sharpe"), 2) if bh.get("sharpe") is not None else "-",
            ("⚠️ " if rr and rr["ultimas"] < rr["p5"] else "") + (fmt(rr["ultimas"], 1) + " R" if rr else "-")))
    out += ["", "🟢 SÓLIDA: gana en el mundo real, aguanta el doble de costes, 7 o más ajustes vecinos ganan, gana en más "
            "de la mitad de los trimestres, mejor Sharpe que comprar y mantener, 100+ operaciones, caída < 15 % y sin "
            "señal de regla rota. 🟡 FRÁGIL: gana pero falla alguna. 🔴 NO OPERAR: no gana en el mundo real.", ""]
    for r in res:
        fijar_precision(r["moneda"])
        out += informe_validacion(r) + [""]
    fijar_precision(None)
    for x in faltan:
        out.append("Sin datos de " + x)
    out += ["Un estudio del pasado no garantiza el futuro.", CIERRE]
    print("\n".join(out))
    return 0


# ---------------------------------------------------------------- datos del panel visual

PANEL_ACTIVOS = ("BTC ETH SOL DOGE XRP HYPE ZEC LINK ADA XLM ORO PLATA EURUSD RUNE AVAX THETA DOT NEAR ARB "
                 "AAVE ATOM UNI INJ LTC FIL GBPUSD USDCAD USDJPY NZDUSD AUDUSD AAPL TSLA MSTR").split()
PANEL_PRINCIPALES = ["BTC", "ETH", "SOL", "DOGE"]
NOMBRE_PASO = {"ideal": "Backtest ideal", "costes": "01 Diferencial y 04 comisión", "desliz": "02 Deslizamiento",
               "retraso": "03 Retraso", "swap": "05 Swap"}


def fila_validacion(r):
    """Una fila de la tabla de validación del panel a partir de `validar_activo`."""
    bh = r["bh"] or {}
    rr = r["regla_rota"] or {}
    redondo = lambda x, n=2: None if x is None else round(x, n)
    return {"activo": r["moneda"], "veredicto": r["veredicto"], "r_real": redondo(r["real"].get("R_medio")),
            "r_x2": redondo(r["x2"].get("R_medio")) if r["x2"].get("n") else None,
            "vecinos": r["pos_vecinos"], "vecinos_total": len(VECINOS),
            "trimestres": r["wf"]["positivos"], "trimestres_total": r["wf"]["trimestres"],
            "caida_pct": round(r["caida_R"], 1), "sharpe": redondo(r["sharpe"]), "sharpe_bh": redondo(bh.get("sharpe")),
            "ultimas30_R": redondo(rr.get("ultimas"), 1), "regla_rota": bool(rr and rr["ultimas"] < rr["p5"]),
            "regimen_ahora": (r["regimen_ahora"] or "").lower(),
            "por_que": "; ".join(r["fallos"]) if r["veredicto"] != "🟢 SÓLIDA" else ""}


def datos_panel(cargados, recorridos=1000, n=200, muestra=24, semilla=19):
    """Los 6 conjuntos de datos del panel «Backtest vs mundo real», a partir de
    {moneda: (v1, v4)} ya preparados. Valida los activos que no pierden en el mundo real."""
    filas, ops_por, valid = [], {}, []
    for m, (v1, v4) in cargados.items():
        pasos = fugas_moneda(v1, v4, m, 720, fugas_de(m))
        ops_por[m] = pasos
        ideal, real = resumen(pasos["ideal"]), resumen(pasos["swap"])
        filas.append({"activo": m, "tipo": tipo_de(m), "marca": marca_real(real), "operaciones": real.get("n", 0),
                      "aciertos_pct": round(real.get("acierto", 0), 1), "r_real": round(real.get("R_medio", 0), 3),
                      "r_ideal": round(ideal.get("R_medio", 0), 3), "desde": a_madrid(v1[0]["t"]).strftime("%Y-%m-%d")})
        if real.get("n") and real["R_medio"] > -0.02:
            try:
                valid.append(fila_validacion(validar_activo(m, v1, v4)))
            except Error:
                pass
    filas.sort(key=lambda f: -f["r_real"])
    valid.sort(key=lambda f: -(f["r_real"] or -9))
    princ = [m for m in PANEL_PRINCIPALES if m in ops_por]
    pasos_rows = []
    for orden, (p, _) in enumerate(PASOS_FUGAS):
        r = resumen([o for m in princ for o in ops_por[m][p]])
        pasos_rows.append({"orden": orden + 1, "paso": NOMBRE_PASO[p], "clave": p, "operaciones": r.get("n", 0),
                           "aciertos_pct": round(r.get("acierto", 0), 1), "r_medio": round(r.get("R_medio", 0), 3),
                           "resultado_pct": round(r.get("R_total", 0), 1)})
    r = resumen([o for _, o in cartera({m: ops_por[m]["swap"] for m in princ})])
    pasos_rows.append({"orden": 6, "paso": "06 Límite de cartera", "clave": "cartera", "operaciones": r.get("n", 0),
                       "aciertos_pct": round(r.get("acierto", 0), 1), "r_medio": round(r.get("R_medio", 0), 3),
                       "resultado_pct": round(r.get("R_total", 0), 1)})
    rng = random.Random(semilla)
    bandas, caminos = [], []
    for mundo, clave in (("Backtest", "ideal"), ("Mundo real", "swap")):
        Rs = [o["R"] for m in princ for o in ops_por[m][clave]]
        if not Rs:
            continue
        curvas = []
        for _ in range(recorridos):
            eq, curva = 0.0, [0.0]
            for _ in range(n):
                eq += rng.choice(Rs)
                curva.append(eq)
            curvas.append(curva)
        for i in range(0, n + 1, 4):
            col = sorted(cv[i] for cv in curvas)
            q = lambda f: round(col[min(len(col) - 1, int(f * len(col)))], 2)
            bandas.append({"mundo": mundo, "operacion": i, "p05": q(.05), "p25": q(.25), "p50": q(.5),
                           "p75": q(.75), "p95": q(.95)})
        for k in range(muestra):
            for i in range(0, n + 1, 4):
                caminos.append({"mundo": mundo, "camino": k, "operacion": i, "resultado_pct": round(curvas[k][i], 2)})
    sup = [{"activo": k, "diferencial_pct": v["spread"], "comision_pct": v["comision"],
            "deslizamiento_pct": v["desliz"], "swap_noche_pct": v["swap"]}
           for k, v in (("Cripto", FUGAS_CRIPTO), ("Oro y plata", FUGAS["ORO"]),
                        ("EUR/USD y GBP/USD", FUGAS["EURUSD"]), ("Acciones", FUGAS_ACCION))]
    return {"activos": filas, "pasos": pasos_rows, "bandas": bandas, "caminos": caminos, "supuestos": sup,
            "validacion": valid}


def cmd_panel(a):
    """Escribe en --salida los archivos del panel (activos, pasos, bandas, caminos, supuestos,
    validacion .json) para subirlos al panel visual."""
    ahora = parse_ahora(a.ahora)
    cargados, faltan = {}, []
    for m in _monedas(a.monedas or PANEL_ACTIVOS):
        try:
            v1, v4 = cargar(m, a.offline, a.dias * 24)
            cargados[m] = preparar_historia(cerradas(v1, H1, ahora), cerradas(v4, H4, ahora))
        except Error as e:
            faltan.append("%s (%s)" % (m, e))
    if not cargados:
        raise Error("no hay datos de ninguna moneda")
    datos = datos_panel(cargados)
    os.makedirs(a.salida, exist_ok=True)
    for nombre, filas in datos.items():
        with open(os.path.join(a.salida, nombre + ".json"), "w", encoding="utf-8") as fh:
            json.dump(filas, fh, ensure_ascii=False)
    print("Panel: %d activos, %d validados · archivos en %s" % (len(datos["activos"]), len(datos["validacion"]), a.salida))
    for x in faltan:
        print("Sin datos de " + x)
    return 0


def cmd_tamano(a):
    if a.moneda:
        fijar_precision(_monedas([a.moneda])[0])
    t = tamano(a.capital, a.riesgo, a.entrada, a.stop, a.tope)
    lado = "COMPRA" if a.stop < a.entrada else "VENTA"
    obj = a.objetivo if a.objetivo is not None else a.entrada + (2 if lado == "COMPRA" else -2) * t["R"]
    print("%s %s · entrada %s · stop %s · objetivo %s" % (ICONO[lado], lado, fmt(a.entrada), fmt(a.stop), fmt(obj)))
    print("Cuenta: %s × %s = %s que se arriesgan. %s ÷ %s por unidad = %s unidades." % (
        fmt(a.capital, 0), pct(a.riesgo), fmt(t["riesgo_objetivo"], 2), fmt(t["riesgo_objetivo"], 2),
        fmt(t["R"]), fmt(t["unidades_riesgo"], t["decimales"])))
    print("| Unidades | Importe | Pierdes en el stop | Ganas en el objetivo |")
    print("|---|---|---|---|")
    print("| %s | %s | %s | %s |" % (fmt(t["unidades"], t["decimales"]), fmt(t["importe"], 2), fmt(t["perdida"], 2),
                                   fmt(t["unidades"] * abs(obj - a.entrada), 2)))
    if t["limite"] != "riesgo":
        print("Lo limita el capital: sin apalancamiento no se puede más. Con todo el capital arriesgas %s (%s)." % (
            fmt(t["perdida"], 2), pct(100 * t["perdida"] / a.capital)))
        print("Para arriesgar el %s harían falta %s unidades (importe %s): apalancamiento ×%s. "
              "Úsalo solo si tu regla lo permite." % (
                  pct(a.riesgo), fmt(t["unidades_riesgo"], t["decimales"]),
                  fmt(t["unidades_riesgo"] * a.entrada, 0), fmt(t["apalancamiento"], 1)))
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
        fijar_precision(m)
        if es_materia(m):
            try:
                doc = json.loads(_get(YAHOO_CHART % (urllib.request.quote(MATERIAS[m]["yahoo"]), "1d")).decode("utf-8"))
                meta = doc["chart"]["result"][0]["meta"]
                print("%s: %s · %s (Madrid) · %s (%s)" % (
                    m, fmt(float(meta["regularMarketPrice"])), hora(int(meta["regularMarketTime"])),
                    MATERIAS[m]["fuente"], "como %s, ±1-2 pips" % simbolo_tv(m) if MATERIAS[m].get("exacto")
                    else "en %s puede ser algo menor" % simbolo_tv(m)))
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
    fijar_precision(_monedas([a.moneda])[0])
    print(ficha(1, _monedas([a.moneda])[0], a.lado.upper(), a.nivel, a.marco, cond, caduca, a.texto or ""))
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
    s.add_argument("--coste", type=float, help="%% de coste ida y vuelta (por defecto, el del activo)")
    s.add_argument("--lado", choices=["compra", "venta"])
    s.add_argument("--json", action="store_true")
    comun(s)
    s.set_defaults(fn=cmd_estudiar)

    s = sub.add_parser("afondo", help="estudio completo de una moneda con años de datos")
    s.add_argument("moneda")
    s.add_argument("--dias", type=int, default=1095, help="días de historia de 1h (1095, unos 3 años)")
    s.add_argument("--horas", type=int, default=720,
                   help="horas máximas por operación (720 = 30 días: en la práctica, hasta stop u objetivo)")
    s.add_argument("--coste", type=float, help="%% de coste ida y vuelta (por defecto, el del activo)")
    comun(s)
    s.set_defaults(fn=cmd_afondo)

    s = sub.add_parser("oportunidades", help="las 10 monedas ordenadas por oportunidad")
    s.add_argument("monedas", nargs="*")
    s.add_argument("--dias", type=int, default=1095)
    comun(s)
    s.set_defaults(fn=cmd_oportunidades)

    s = sub.add_parser("fugas", help="de backtest a realidad: las 6 fugas, paso a paso")
    s.add_argument("monedas", nargs="*")
    s.add_argument("--dias", type=int, default=1095)
    s.add_argument("--horas", type=int, default=720)
    s.add_argument("--spread", type=float, help="%% de diferencial por operación")
    s.add_argument("--comision", type=float, help="%% de comisión por lado")
    s.add_argument("--desliz", type=float, help="%% de deslizamiento por lado")
    s.add_argument("--swap", type=float, help="%% de swap por noche")
    s.add_argument("--max-abiertas", type=int, default=3)
    s.add_argument("--tope-diario", type=float, default=2.0, help="%% de pérdida diaria máxima (con 1 %% por operación)")
    comun(s)
    s.set_defaults(fn=cmd_fugas)

    s = sub.add_parser("validar", help="las 8 pruebas duras: costes ×2, vecinos, trimestres, caída, Sharpe, régimen...")
    s.add_argument("monedas", nargs="*")
    s.add_argument("--dias", type=int, default=1095)
    s.add_argument("--horas", type=int, default=720)
    comun(s)
    s.set_defaults(fn=cmd_validar)

    s = sub.add_parser("panel", help="datos del panel visual «Backtest vs mundo real»")
    s.add_argument("monedas", nargs="*")
    s.add_argument("--salida", required=True, help="carpeta donde escribir los .json")
    s.add_argument("--dias", type=int, default=1095)
    comun(s)
    s.set_defaults(fn=cmd_panel)

    s = sub.add_parser("tamano", help="unidades para un % de riesgo")
    s.add_argument("--capital", type=float, required=True)
    s.add_argument("--riesgo", type=float, default=1.0, help="%% del capital (1)")
    s.add_argument("--entrada", type=float, required=True)
    s.add_argument("--stop", type=float, required=True)
    s.add_argument("--objetivo", type=float)
    s.add_argument("--tope", type=float, default=100.0, help="%% máximo del capital en la posición (100)")
    s.add_argument("--moneda", help="activo, para los decimales (p. ej. EURUSD)")
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
    finally:
        fijar_precision(None)


if __name__ == "__main__":
    sys.exit(main())
