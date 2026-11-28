#!/usr/bin/env python3
"""Convierte velas de TradingView (mcp-tv-get-ohlcv) al formato de gráfico de Yahoo
que leen las 11 skills trader-* con --offline. Así trader-entry, trader-exit,
trader-timemachine y el resto trabajan con los datos de la cuenta de TradingView en
lugar de los gratuitos de Yahoo.

    python3 tv_a_yahoo.py tsla5m.json --simbolo NASDAQ:TSLA --intervalo 5m -o TSLA.json
    python3 ../trader-entry/entry.py check TSLA --offline TSLA.json --now "2026-10-19 10:15"

Solo acciones de EE. UU.: las skills trader-* usan el horario de la NYSE. Para cripto,
usar comprobar.py, que no depende de sesiones.
"""

import argparse
import json
import os
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comprobar import Error, leer_barras  # noqa: E402

INTERVALOS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "60m", "1D": "1d", "1d": "1d"}


def yahoo_simbolo(tv):
    """NASDAQ:TSLA -> TSLA, NYSE:BRK.B -> BRK-B."""
    return tv.split(":")[-1].upper().replace(".", "-")


def convertir(barras, simbolo_tv, intervalo, cierre_anterior=None, hora_datos=None):
    if intervalo not in INTERVALOS:
        raise Error("intervalo %r no soportado (usa %s)" % (intervalo, ", ".join(INTERVALOS)))
    if not barras:
        raise Error("no hay velas que convertir")
    sym = yahoo_simbolo(simbolo_tv)
    meta = {"symbol": sym, "dataGranularity": INTERVALOS[intervalo],
            "exchangeName": simbolo_tv.split(":")[0] if ":" in simbolo_tv else "",
            "exchangeTimezoneName": "America/New_York", "currency": "USD",
            "regularMarketPrice": barras[-1]["c"],
            "regularMarketTime": int(hora_datos if hora_datos is not None else barras[-1]["t"]),
            "fuente": "TradingView (%s)" % simbolo_tv}
    if cierre_anterior is not None:
        meta["previousClose"] = meta["chartPreviousClose"] = float(cierre_anterior)
    q = {k: [b[c] for b in barras] for k, c in (("open", "o"), ("high", "h"), ("low", "l"),
                                                 ("close", "c"), ("volume", "v"))}
    q["volume"] = [int(v) for v in q["volume"]]
    return {"chart": {"result": [{"meta": meta, "timestamp": [b["t"] for b in barras],
                                  "indicators": {"quote": [q]}}], "error": None}}


def main(argv=None):
    p = argparse.ArgumentParser(description="Velas de TradingView -> JSON de gráfico de Yahoo.")
    p.add_argument("entrada", help="respuesta de mcp-tv-get-ohlcv guardada en un archivo")
    p.add_argument("--simbolo", required=True, help="EXCHANGE:TICKER de TradingView, p. ej. NASDAQ:TSLA")
    p.add_argument("--intervalo", required=True, help=", ".join(INTERVALOS))
    p.add_argument("--cierre-anterior", type=float, help="cierre de la sesión anterior (opcional)")
    p.add_argument("--hora-datos", type=int, help="segundos Unix del último dato (por defecto, la última vela)")
    p.add_argument("-o", "--salida", required=True)
    a = p.parse_args(argv)
    try:
        doc = convertir(leer_barras(a.entrada), a.simbolo, a.intervalo, a.cierre_anterior, a.hora_datos)
    except Error as e:
        print("ERROR: %s" % e, file=sys.stderr)
        return 2
    with open(a.salida, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    print("%s: %d velas de %s guardadas en %s" % (yahoo_simbolo(a.simbolo), len(doc["chart"]["result"][0]["timestamp"]),
                                                   a.intervalo, a.salida))
    return 0


if __name__ == "__main__":
    sys.exit(main())
