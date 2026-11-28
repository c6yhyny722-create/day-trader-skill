import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import load

cr = load("trader-cripto", "cripto")

T0 = 1793750400          # 04-11-2026 00:00 UTC, múltiplo de 4 h
H1, H4 = 3600, 14400


def velas_1h(n, pendiente=0.01, salto=0.0, inicio=T0, base=100.0):
    out = []
    for i in range(n):
        c = base + i * pendiente + (salto if i == n - 1 else 0.0)
        o = c - pendiente
        out.append({"t": inicio + i * H1, "o": o, "h": max(o, c) + 0.05, "l": min(o, c) - 0.1, "c": c, "v": 10.0})
    return out


def a_4h(v1):
    cubos = {}
    for b in v1:
        cubos.setdefault(b["t"] // H4 * H4, []).append(b)
    out = []
    for t in sorted(cubos):
        bs = cubos[t]
        out.append({"t": t, "o": bs[0]["o"], "h": max(x["h"] for x in bs), "l": min(x["l"] for x in bs),
                    "c": bs[-1]["c"], "v": sum(x["v"] for x in bs)})
    return out


class Hora(unittest.TestCase):
    def test_invierno_verano_y_cambio(self):
        self.assertEqual(cr.hora(1795723200), "26/11 21:00")            # CET, 20:00 UTC
        self.assertEqual(cr.hora(1782907200), "01/07 14:00")            # CEST, 12:00 UTC
        self.assertEqual(cr.hora(1792890000 - 1), "25/10 02:59")
        self.assertEqual(cr.hora(1792890000), "25/10 02:00")

    def test_parse_ahora_es_hora_de_madrid(self):
        self.assertEqual(cr.parse_ahora("2026-11-26 21:00"), 1795723200)
        self.assertEqual(cr.parse_ahora("2026-07-01 14:00"), 1782907200)

    def test_fin_de_semana(self):
        self.assertTrue(cr.es_fin_de_semana(cr.parse_ahora("2026-11-28 10:00")))
        self.assertFalse(cr.es_fin_de_semana(cr.parse_ahora("2026-11-27 10:00")))


class Formato(unittest.TestCase):
    def test_numeros_en_espanol(self):
        self.assertEqual(cr.fmt(98400.4), "98.400")
        self.assertEqual(cr.fmt(9.30333), "9,303")
        self.assertEqual(cr.fmt(71.9), "71,90")
        self.assertEqual(cr.fmt(0.12345), "0,1235")
        self.assertEqual(cr.fmt(0.0577021), "0,057702")
        self.assertEqual(cr.fmt(None), "sin dato")

    def test_decimales_de_unidades(self):
        self.assertEqual(cr.unidades_dec(98000), 5)
        self.assertEqual(cr.unidades_dec(9.3), 1)
        self.assertEqual(cr.unidades_dec(0.2), 0)

    def test_velas_de_bitstamp(self):
        doc = {"data": {"pair": "LINK/USD", "ohlc": [
            {"timestamp": "7200", "open": "2", "high": "3", "low": "1", "close": "2.5", "volume": "4"},
            {"timestamp": "3600", "open": "1", "high": "2", "low": "1", "close": "1.5", "volume": "1"}]}}
        v = cr.normalizar(doc)
        self.assertEqual([b["t"] for b in v], [3600, 7200])
        self.assertEqual(v[1]["c"], 2.5)


class Regla(unittest.TestCase):
    def test_compra_con_contexto_alcista(self):
        v1 = velas_1h(300, salto=1.0)
        v4 = a_4h(v1)
        s = cr.senal_en(v1, len(v1) - 1, v4)
        self.assertEqual(s["lado"], "COMPRA")
        nivel = max(b["h"] for b in v1[-21:-1])
        stop = min(b["l"] for b in v1[-10:])
        self.assertAlmostEqual(s["nivel"], nivel)
        self.assertAlmostEqual(s["stop"], stop)
        R = v1[-1]["c"] - stop
        self.assertAlmostEqual(s["objetivo"], v1[-1]["c"] + 2 * R)
        self.assertAlmostEqual(s["zona"][1], nivel + 0.5 * R)
        self.assertEqual(s["cierre_ts"], v1[-1]["t"] + H1)

    def test_venta_con_contexto_bajista(self):
        v1 = velas_1h(300, pendiente=-0.01, salto=-1.0, base=200.0)
        s = cr.senal_en(v1, len(v1) - 1, a_4h(v1))
        self.assertEqual(s["lado"], "VENTA")
        self.assertGreater(s["stop"], s["entrada"])
        self.assertLess(s["objetivo"], s["entrada"])

    def test_sin_senal_contra_el_contexto(self):
        v1 = velas_1h(300, pendiente=-0.01, base=200.0)
        v1[-1]["c"] = max(b["h"] for b in v1[-21:-1]) + 0.5     # ruptura al alza con 4h bajista
        v1[-1]["h"] = v1[-1]["c"] + 0.05
        self.assertIsNone(cr.senal_en(v1, len(v1) - 1, a_4h(v1)))

    def test_contexto_es_la_vela_de_4h_anterior(self):
        v1 = velas_1h(300)
        v4 = a_4h(v1)
        c4, _ = cr.contexto(v4, v1[-1]["t"])
        cubo = v1[-1]["t"] // H4 * H4
        self.assertEqual(c4, [b for b in v4 if b["t"] == cubo - H4][0]["c"])

    def test_seguimiento_marca_la_invalidacion(self):
        v1 = velas_1h(300, salto=1.0)
        v4 = a_4h(v1)
        s = cr.senal_en(v1, len(v1) - 1, v4)
        t = v1[-1]["t"] + H1
        v1.append({"t": t, "o": s["entrada"], "h": s["entrada"], "l": s["stop"] - 0.01, "c": s["stop"], "v": 1})
        self.assertEqual(cr.seguir(s, v1)["estado"], "invalidada")

    def test_solo_velas_cerradas(self):
        v1 = velas_1h(300, salto=1.0)
        v4 = a_4h(v1)
        abierta = v1[-1]["t"] + H1 // 2              # la última vela aún no ha cerrado
        r = cr.estado_moneda("LINK", v1, v4, abierta)
        self.assertEqual(r["ahora"], "ESPERAR")
        cerrada = v1[-1]["t"] + H1 + 60
        r = cr.estado_moneda("LINK", v1, v4, cerrada)
        self.assertTrue(r["ahora"].startswith("COMPRA activada"))

    def test_senal_de_horas_antes_sigue_en_zona(self):
        v1 = velas_1h(300, salto=0.2)
        v4 = a_4h(v1)
        s = cr.senal_en(v1, len(v1) - 1, v4)
        self.assertTrue(s["en_zona"])
        c = (s["zona"][0] + s["zona"][1]) / 2           # el precio se queda dentro de la zona
        for k in range(1, 4):
            v1.append({"t": v1[-1]["t"] + H1, "o": c, "h": c + 0.01, "l": c - 0.01, "c": c, "v": 1.0})
        r = cr.estado_moneda("LINK", v1, a_4h(v1), v1[-1]["t"] + H1 + 60)
        self.assertTrue(r["ahora"].startswith("COMPRA en zona (señal de las"), r["ahora"])
        o = cr.oportunidad(dict(r, atr=1.0), None)
        self.assertEqual(o["orden"][0], 0)                # cuenta como activa en el ranking

    def test_sin_datos_no_evaluable(self):
        r = cr.estado_moneda("LINK", velas_1h(10), [], T0 + 10 * H1)
        self.assertEqual(r["ahora"], "NO EVALUABLE")


class TamanoYRiesgo(unittest.TestCase):
    def test_tamano_por_riesgo(self):
        t = cr.tamano(10000, 0.5, 9.694, 9.107)
        self.assertEqual(t["unidades"], 85.1)                 # 50 / 0,587 = 85,17 -> 85,1
        self.assertLessEqual(t["perdida"], 50.0)
        self.assertEqual(t["limite"], "riesgo")

    def test_tamano_limitado_por_capital(self):
        t = cr.tamano(1000, 1, 100.0, 99.99)
        self.assertLessEqual(t["importe"], 1000.0)
        self.assertNotEqual(t["limite"], "riesgo")

    def test_fin_de_semana_baja_el_riesgo(self):
        sab = cr.parse_ahora("2026-11-28 10:00")
        filas = cr.comprobar_riesgo(10000, 1.0, 10.0, 9.0, [12.0], "COMPRA", sab)
        self.assertIn("BLOQUEA", [f[0] for f in filas if "riesgo" in f[1]])
        filas = cr.comprobar_riesgo(10000, 0.75, 10.0, 9.0, [12.0], "COMPRA", sab)
        self.assertNotIn("BLOQUEA", [f[0] for f in filas])

    def test_beneficio_riesgo_minimo_por_objetivo(self):
        vie = cr.parse_ahora("2026-11-27 10:00")
        filas = cr.comprobar_riesgo(10000, 1.0, 10.0, 9.0, [11.0, 12.0], "COMPRA", vie)
        estados = [f[0] for f in filas if "objetivo" in f[1]]
        self.assertEqual(estados, ["BLOQUEA", "PASA"])

    def test_stop_mal_puesto_o_sin_stop(self):
        vie = cr.parse_ahora("2026-11-27 10:00")
        self.assertEqual(cr.comprobar_riesgo(10000, 1, 10.0, 11.0, [12.0], "COMPRA", vie)[0][0], "BLOQUEA")
        self.assertEqual(cr.comprobar_riesgo(10000, 1, 10.0, None, [12.0], "COMPRA", vie)[0][0], "BLOQUEA")

    def test_tope_de_posiciones_y_perdida_diaria(self):
        vie = cr.parse_ahora("2026-11-27 10:00")
        filas = cr.comprobar_riesgo(10000, 1, 10.0, 9.0, [12.0], "COMPRA", vie, abiertas=3, perdida_hoy_pct=2.5)
        self.assertEqual(sum(1 for f in filas if f[0] == "BLOQUEA"), 2)


class Simulacion(unittest.TestCase):
    def test_reproducible_y_suma_uno(self):
        v1 = velas_1h(24 * 30)
        a = cr.simular(v1, 107.0, 106.0, 109.0, v1[-1]["t"] + H1, horas=24, recorridos=500)
        b = cr.simular(v1, 107.0, 106.0, 109.0, v1[-1]["t"] + H1, horas=24, recorridos=500)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a["p_objetivo"] + a["p_stop"] + a["p_ninguno"], 1.0)
        self.assertEqual(a["r_objetivo"], 2.0)

    def test_pocos_datos_es_error(self):
        with self.assertRaises(cr.Error):
            cr.simular(velas_1h(100), 101, 100, 103, T0, recorridos=10)

    def test_veredicto(self):
        mc = {"p_objetivo": 0.5, "p_stop": 0.1, "r_objetivo": 2.0}
        self.assertTrue(cr.veredicto(mc).startswith("Claramente hacia el objetivo"))
        mc = {"p_objetivo": 0.12, "p_stop": 0.46, "r_objetivo": 2.0}
        self.assertTrue(cr.veredicto(mc).startswith("Se inclina hacia el stop"))

    def test_historial_cuenta_solo_senales_con_horas_completas(self):
        v1 = velas_1h(300, salto=1.0)
        self.assertEqual(cr.historial(v1, a_4h(v1), horas=48), [])   # la única señal es la última vela


class CalidadYEstudio(unittest.TestCase):
    def test_hueco_en_las_velas_es_no_evaluable(self):
        v1 = velas_1h(300, salto=1.0)
        v4 = a_4h(v1)
        del v1[-5]
        r = cr.estado_moneda("LINK", v1, v4, v1[-1]["t"] + H1 + 60)
        self.assertEqual(r["ahora"], "NO EVALUABLE")
        self.assertIn("falta la vela", r["motivo"])

    def test_vela_imposible_es_no_evaluable(self):
        v1 = velas_1h(300)
        v1[-3]["h"] = v1[-3]["l"] - 1
        self.assertTrue(cr.revisar_velas(v1, H1, 10))
        self.assertEqual(cr.revisar_velas(velas_1h(300), H1, 50), [])

    def _con_senales_seguidas(self):
        # tendencia que rompe máximos varias horas seguidas y luego se queda plana
        v1 = velas_1h(300)
        for k in range(1, 6):
            b = v1[-60 + k]
            b["c"] += 0.5 * k
            b["h"] = b["c"] + 0.05
        for b in v1[-60 + 6:]:
            b["c"] = v1[-60 + 5]["c"]
            b["o"], b["h"], b["l"] = b["c"], b["c"] + 0.01, b["c"] - 0.01
        return v1

    def test_senales_seguidas_cuentan_una_vez(self):
        v1 = self._con_senales_seguidas()
        v4 = a_4h(v1)
        lista = cr.senales(v1, v4, solo_zona=False)
        ops = cr.operaciones(v1, lista, horas=24)
        self.assertGreater(len(lista), len(ops))
        for a, b in zip(ops, ops[1:]):
            self.assertGreater(b["ts"], a["ts"])

    def test_coste_resta_en_r(self):
        v1 = self._con_senales_seguidas()
        lista = cr.senales(v1, a_4h(v1), solo_zona=False)
        sin = cr.operaciones(v1, lista, horas=24)
        con = cr.operaciones(v1, lista, horas=24, coste_pct=0.1)
        self.assertEqual(len(sin), len(con))
        for a, b in zip(sin, con):
            self.assertLess(b["R"], a["R"])

    def test_conclusion_no_propone_lo_que_pierde(self):
        r = lambda m, n=40: {"n": n, "R_medio": m}
        est = {"filas": [
            {"stop": "regla", "objetivo_R": 2.0, "p1": r(-0.5), "p2": r(-0.5), "total": r(-0.5)},
            {"stop": "atr15", "objetivo_R": 2.0, "p1": r(-0.2), "p2": r(-0.2), "total": r(-0.2)},
        ]}
        self.assertEqual(cr.conclusion(est)[1], [])

    def test_conclusion_exige_ganar_en_los_dos_periodos(self):
        r = lambda m, n=40: {"n": n, "R_medio": m}
        est = {"filas": [
            {"stop": "regla", "objetivo_R": 2.0, "p1": r(0.0), "p2": r(0.0), "total": r(0.0)},
            {"stop": "atr15", "objetivo_R": 2.0, "p1": r(0.3), "p2": r(-0.1), "total": r(0.1)},   # solo gana en uno
            {"stop": "min20", "objetivo_R": 2.0, "p1": r(0.2, 10), "p2": r(0.2, 10), "total": r(0.2, 20)},  # pocas
        ]}
        self.assertEqual(cr.conclusion(est)[1], [])
        est["filas"].append({"stop": "colchon", "objetivo_R": 2.0, "p1": r(0.1), "p2": r(0.1), "total": r(0.1)})
        self.assertEqual(cr.conclusion(est)[1][0]["stop"], "colchon")

    def test_nota_stop(self):
        self.assertIn("muy cerca", cr.nota_stop(0.5, 1.0))
        self.assertIn("muy lejos", cr.nota_stop(5.0, 1.0))
        self.assertEqual(cr.nota_stop(2.0, 1.0), "stop a 2,0 ATR")
        self.assertEqual(cr.nota_stop(2.0, None), "")

    def test_stop_atr(self):
        v1 = velas_1h(300, salto=1.0)
        s = cr.senal_en(v1, len(v1) - 1, a_4h(v1))
        atrs = cr.atr(v1)
        self.assertAlmostEqual(cr.stop_variante("atr15", s, v1, atrs), s["entrada"] - 1.5 * atrs[-1])
        self.assertLess(cr.stop_variante("colchon", s, v1, atrs), s["stop"])


class AFondo(unittest.TestCase):
    def test_diarias_solo_dias_completos(self):
        v1 = velas_1h(24 * 5 + 7)
        d = cr.diarias_de(v1)
        self.assertEqual(len(d), 5)
        self.assertEqual(d[0]["c"], v1[23]["c"])
        self.assertEqual(d[0]["h"], max(b["h"] for b in v1[:24]))

    def test_filtro_de_horas_en_hora_de_madrid(self):
        t = cr.parse_ahora("2026-11-27 16:00")              # cierre de la vela, Madrid
        s = {"lado": "COMPRA", "j": 0, "t": t - H1, "cierre_ts": t}
        self.assertTrue(cr.pasa_filtro("horas", s, [], {}))
        s["cierre_ts"] = cr.parse_ahora("2026-11-27 12:00")
        self.assertFalse(cr.pasa_filtro("horas", s, [], {}))

    def test_filtro_diario_y_extremo(self):
        t = 86400 * 20000
        extra = {"dia": {t - 86400: (100.0, 90.0, 25.0)}, "vmed": [None]}
        compra = {"lado": "COMPRA", "j": 0, "t": t + 3600, "cierre_ts": t + 7200}
        venta = dict(compra, lado="VENTA")
        self.assertTrue(cr.pasa_filtro("diario", compra, [], extra))
        self.assertFalse(cr.pasa_filtro("diario", venta, [], extra))
        self.assertTrue(cr.pasa_filtro("extremo", compra, [], extra))
        self.assertFalse(cr.pasa_filtro("extremo", venta, [], extra))   # RSI 25: no vender

    def test_estudio_filtros_estructura(self):
        v1 = velas_1h(24 * 40)
        est = cr.estudio_filtros(v1, a_4h(v1), horas=24)
        self.assertEqual(len(est["filas"]), 2 * len(cr.FILTROS))
        self.assertFalse(est["filas"][0]["robusto"])            # la base nunca se marca
        for f in est["filas"]:
            self.assertEqual(len(f["partes"]), 3)

    def test_giros(self):
        v4 = a_4h(velas_1h(24 * 10))
        v4[20]["h"] += 50
        self.assertIn(("resistencia", v4[20]["h"], v4[20]["t"]), cr.giros(v4, cuantos=50))

    def test_perfil_horario_24_horas(self):
        self.assertEqual(sorted(cr.perfil_horario(velas_1h(24 * 3))), list(range(24)))


class Oportunidades(unittest.TestCase):
    def _r(self, ahora, compra=None, venta=None, cierre=100.0, atr_=1.0):
        return {"moneda": "X", "ahora": ahora, "cierre": cierre, "compra_si": compra, "venta_si": venta, "atr": atr_}

    def _v(self, rc, rv):
        res = lambda r: {"n": 30, "R_medio": r}
        return {"ninguno": {"compra": res(rc), "venta": res(rv), "total": res(0), "ultimo": res(0)},
                "horas": {"total": res(0)}}

    def test_orden_activa_cerca_lejos_sin_ventaja(self):
        activa = cr.oportunidad(self._r("COMPRA activada", compra=101), self._v(0.1, 0.1))
        cerca = cr.oportunidad(self._r("ESPERAR", compra=101), self._v(0.1, 0.1))
        lejos = cr.oportunidad(self._r("ESPERAR", compra=105), self._v(0.1, 0.1))
        sin = cr.oportunidad(self._r("ESPERAR", compra=100.5), self._v(-0.2, 0.1))
        orden = sorted([sin, lejos, cerca, activa], key=lambda o: o["orden"])
        self.assertEqual(orden, [activa, cerca, lejos, sin])

    def test_distancia_y_lado(self):
        o = cr.oportunidad(self._r("ESPERAR", venta=98, atr_=0.5), self._v(0.1, -0.1))
        self.assertEqual(o["lado"], "VENTA")
        self.assertAlmostEqual(o["dist_pct"], 2.0)
        self.assertAlmostEqual(o["dist_atr"], 4.0)
        self.assertEqual(o["r_lado"], -0.1)

    def test_no_evaluable_al_final(self):
        o = cr.oportunidad({"moneda": "X", "ahora": "NO EVALUABLE"}, None)
        self.assertEqual(o["orden"][0], 3)

    def test_ventaja_devuelve_los_dos_filtros(self):
        v1 = velas_1h(24 * 40)
        v = cr.ventaja(v1, a_4h(v1), horas=24)
        self.assertEqual(sorted(v), ["horas", "ninguno"])
        self.assertIn("ultimo", v["ninguno"])


class OroYPlata(unittest.TestCase):
    def _sesiones(self, dias=40):
        """Velas de 1h de lunes a viernes, con la pausa diaria de 22:00 a 23:00 UTC."""
        out, t, c = [], 1793664000, 3000.0     # 03-11-2026, martes 00:00 UTC
        while len(out) < dias * 23:
            d = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=t)
            abierto = d.weekday() < 4 or (d.weekday() == 4 and d.hour < 22) or (d.weekday() == 6 and d.hour >= 23)
            if abierto and d.hour != 22:
                c += 0.5
                out.append({"t": t, "o": c - 0.5, "h": c + 0.3, "l": c - 0.8, "c": c, "v": 100.0})
            t += H1
        return out

    def test_alias_y_simbolos(self):
        self.assertEqual(cr._monedas(["gold", "TVC:SILVER", "xauusd", "btcusd"]), ["ORO", "PLATA", "ORO", "BTC"])
        self.assertEqual(cr.simbolo_tv("ORO"), "TVC:GOLD")
        self.assertEqual(cr.simbolo_tv("BTC"), "BITSTAMP:BTCUSD")
        self.assertEqual(cr.par("ORO"), "oro")

    def test_cierres_de_mercado_no_son_datos_dudosos(self):
        v1 = self._sesiones()
        v4 = cr.agrupar_4h(v1)
        r = cr.estado_moneda("ORO", v1, v4, v1[-1]["t"] + H1 + 60)
        self.assertNotEqual(r["ahora"], "NO EVALUABLE", r.get("motivo"))
        r = cr.estado_moneda("BTC", v1, v4, v1[-1]["t"] + H1 + 60)        # en cripto, un hueco sí lo es
        self.assertEqual(r["ahora"], "NO EVALUABLE")

    def test_fin_de_semana_no_caduca_el_dato(self):
        v1 = self._sesiones()
        lunes = v1[-1]["t"] + 50 * H1
        r = cr.estado_moneda("ORO", v1, cr.agrupar_4h(v1), lunes)
        self.assertNotEqual(r["ahora"], "NO EVALUABLE", r.get("motivo"))

    def test_contexto_salta_el_cierre(self):
        v1 = self._sesiones()
        v4 = cr.agrupar_4h(v1)
        mapa = cr.mapa_contexto(v4)
        lunes = [b for b in v1 if (datetime.datetime(1970, 1, 1) +
                                   datetime.timedelta(seconds=b["t"])).weekday() == 0][-1]
        c4, e4 = cr.contexto(v4, lunes["t"], mapa)
        anterior = [b for b in v4 if b["t"] < lunes["t"] // H4 * H4][-1]
        self.assertEqual(c4, anterior["c"])

    def test_diarias_por_sesion(self):
        d = cr.diarias_de(self._sesiones(), cr.DESFASE_SESION, 20)
        self.assertTrue(d)
        for b in d:
            self.assertLess((datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=b["t"])).weekday(), 5)

    def test_ficha_con_simbolo_de_tradingview(self):
        f = cr.ficha(1, "ORO", "VENTA", 3454, "1h", "Cierre por debajo", cr.parse_ahora("2026-11-30 20:00"))
        self.assertIn("Símbolo:     TVC:GOLD", f)
        self.assertIn("Comprueba el nivel", cr.aviso_materia("ORO", None))
        self.assertEqual(cr.aviso_materia("ORO", "carpeta"), "")
        self.assertEqual(cr.aviso_materia("BTC", None), "")


class EuroDolar(unittest.TestCase):
    def tearDown(self):
        cr.fijar_precision(None)

    def test_nombres(self):
        self.assertEqual(cr._monedas(["EUR/USD", "FX:EURUSD", "oanda:eurusd", "eur"]), ["EURUSD"] * 4)
        self.assertEqual(cr.simbolo_tv("EURUSD"), "FX:EURUSD")

    def test_cinco_decimales_solo_en_divisas(self):
        cr.fijar_precision("EURUSD")
        self.assertEqual(cr.fmt(1.093487), "1,09349")
        self.assertEqual(cr.fmt(1.5, 2), "1,50")                    # los decimales pedidos mandan
        f = cr.ficha(1, "EURUSD", "VENTA", 1.093487, "1h", "Cierre por debajo", cr.parse_ahora("2026-11-30 20:00"))
        self.assertIn("Nivel:       1,09349", f)
        cr.fijar_precision("BTC")
        self.assertEqual(cr.fmt(9.30333), "9,303")

    def test_informe_no_borra_la_precision(self):
        cr.fijar_precision("EURUSD")
        cr.informe([{"moneda": "EURUSD", "ahora": "NO EVALUABLE", "motivo": "x"}])
        self.assertEqual(cr.fmt(1.093487), "1,09349")

    def test_sin_aviso_de_contado(self):
        self.assertEqual(cr.aviso_materia("EURUSD", None), "")

    def test_coste_por_activo(self):
        self.assertEqual(cr.coste_de("EURUSD"), 0.02)
        self.assertEqual(cr.coste_de("ORO"), 0.05)
        self.assertEqual(cr.coste_de("BTC"), 0.1)

    def test_apalancamiento_necesario(self):
        t = cr.tamano(10000, 1, 1.09349, 1.09733)
        self.assertNotEqual(t["limite"], "riesgo")
        self.assertLessEqual(t["importe"], 10000.0)
        self.assertAlmostEqual(t["apalancamiento"], 100 / 0.00384 * 1.09349 / 10000, places=2)


class Fugas(unittest.TestCase):
    def _senal(self):
        v1 = velas_1h(300, salto=0.2)
        v4 = a_4h(v1)
        s = cr.senal_en(v1, len(v1) - 1, v4)
        return v1, s

    def _sigue(self, v1, precios):
        for o, h, l, c in precios:
            v1.append({"t": v1[-1]["t"] + H1, "o": o, "h": h, "l": l, "c": c, "v": 1.0})

    def test_ideal_es_la_regla_sin_costes(self):
        v1, s = self._senal()
        self._sigue(v1, [(s["entrada"], s["objetivo"] + 0.01, s["entrada"] - 0.01, s["objetivo"])])
        o = cr.operaciones_reales(v1, [s])[0]
        self.assertEqual(o["fin"], "objetivo")
        self.assertAlmostEqual(o["R"], 2.0)

    def test_costes_y_deslizamiento_restan(self):
        v1, s = self._senal()
        self._sigue(v1, [(s["entrada"], s["entrada"] + 0.01, s["stop"] - 0.01, s["stop"])])
        ideal = cr.operaciones_reales(v1, [s])[0]["R"]
        real = cr.operaciones_reales(v1, [s], fugas={"spread": 0.1, "desliz": 0.05})[0]["R"]
        self.assertAlmostEqual(ideal, -1.0)
        self.assertLess(real, ideal)

    def test_retraso_no_persigue(self):
        v1, s = self._senal()
        fuera = s["zona"][1] + 0.5                       # la siguiente vela abre por encima de la zona
        self._sigue(v1, [(fuera, fuera + 5, fuera - 0.01, fuera + 4)])
        self.assertEqual(cr.operaciones_reales(v1, [s], siguiente=True), [])
        self.assertEqual(len(cr.operaciones_reales(v1, [s], siguiente=False)), 1)

    def test_retraso_entra_en_la_apertura_siguiente(self):
        v1, s = self._senal()
        e = (s["zona"][0] + s["zona"][1]) / 2
        self._sigue(v1, [(e, s["objetivo"] + 0.01, e - 0.01, s["objetivo"])])
        o = cr.operaciones_reales(v1, [s], siguiente=True)[0]
        self.assertEqual(o["entrada_ts"], v1[-1]["t"])
        self.assertAlmostEqual(o["R"], (s["objetivo"] - e) / (e - s["stop"]))

    def test_noches(self):
        t = 86400 * 20000 + 12 * 3600                  # mediodía UTC
        self.assertEqual(cr.noches(t, t + 3600), 0)
        self.assertEqual(cr.noches(t, t + 12 * 3600), 1)  # cruza las 22:00 UTC
        self.assertEqual(cr.noches(t, t + 3 * 86400), 3)

    def test_swap_resta_por_noche(self):
        v1, s = self._senal()
        larga = [(s["entrada"], s["entrada"] + 0.01, s["entrada"] - 0.01, s["entrada"])] * 30
        self._sigue(v1, larga + [(s["entrada"], s["objetivo"] + 0.01, s["entrada"], s["objetivo"])])
        sin = cr.operaciones_reales(v1, [s])[0]["R"]
        con = cr.operaciones_reales(v1, [s], fugas={"swap": 0.05})[0]["R"]
        self.assertLess(con, sin)

    def test_cartera_tres_a_la_vez_y_tope_diario(self):
        base = cr.parse_ahora("2026-11-25 10:00")
        op = lambda h, dur, r: {"entrada_ts": base + h * H1, "salida_ts": base + (h + dur) * H1, "R": r}
        por = {"A": [op(0, 10, 1)], "B": [op(0, 10, 1)], "C": [op(0, 10, 1)], "D": [op(1, 2, 1)]}
        self.assertEqual(len(cr.cartera(por)), 3)                 # la cuarta no cabe
        por = {"A": [op(0, 1, -1), op(3, 1, 1)], "B": [op(0, 1, -1)], "C": [op(2, 1, 1)]}
        self.assertEqual(len(cr.cartera(por)), 2)                 # tras −2R en el día, no abre más

    def test_diferencial_variable_por_hora(self):
        dia = cr.parse_ahora("2026-11-25 16:00")          # miércoles por la tarde
        noche = cr.parse_ahora("2026-11-25 03:00")
        finde = cr.parse_ahora("2026-11-28 16:00")        # sábado
        self.assertEqual(cr.factor_spread(dia, "BTC"), 1.0)
        self.assertAlmostEqual(cr.factor_spread(noche, "BTC"), 1.3)
        self.assertAlmostEqual(cr.factor_spread(finde, "BTC"), 1.5)
        rollover = 86400 * 20000 + 21 * 3600              # 21:00 UTC
        self.assertEqual(cr.factor_spread(rollover, "EURUSD"), 3.0)
        self.assertEqual(cr.factor_spread(dia, "ORO"), 1.0)

    def test_diferencial_variable_cuesta_mas_de_noche(self):
        v1, s = self._senal()
        self._sigue(v1, [(s["entrada"], s["entrada"] + 0.01, s["stop"] - 0.01, s["stop"])])
        fijo = cr.operaciones_reales(v1, [s], fugas={"spread": 0.1})[0]["R"]
        var = cr.operaciones_reales(v1, [s], fugas={"spread": 0.1}, moneda="BTC", spread_variable=True)[0]["R"]
        horas = [cr.a_madrid(x).hour for x in (s["cierre_ts"], v1[-1]["t"] + H1)]
        if any(h < 7 for h in horas):
            self.assertLess(var, fijo)
        else:
            self.assertLessEqual(var, fijo)

    def test_montecarlo_dos_mundos(self):
        v1 = velas_1h(24 * 30)
        ideal = cr.simular(v1, 107.0, 106.0, 109.0, v1[-1]["t"] + H1, horas=24, recorridos=300)
        dos = cr.simular(v1, 107.0, 106.0, 109.0, v1[-1]["t"] + H1, horas=24, recorridos=300,
                         fugas={"spread": 0.1, "desliz": 0.05, "swap": 0.02}, moneda="BTC")
        self.assertIsNone(ideal["R_medio_real"])
        self.assertEqual(dos["R_medio"], ideal["R_medio"])     # los mismos caminos
        self.assertLess(dos["R_medio_real"], dos["R_medio"])   # el mundo real resta
        self.assertLessEqual(dos["p_gana_real"], dos["p_gana"])

    def test_marca_del_mundo_real(self):
        self.assertEqual(cr.marca_real({"n": 100, "R_medio": 0.1}), "🟢")
        self.assertEqual(cr.marca_real({"n": 100, "R_medio": 0.0}), "⚪")
        self.assertEqual(cr.marca_real({"n": 100, "R_medio": -0.1}), "🔴")
        self.assertEqual(cr.marca_real({"n": 10, "R_medio": 0.5}), "⚠️")
        self.assertEqual(cr.marca_real({"n": 0}), "⚠️")

    def test_par_sin_negociacion_no_evaluable(self):
        v1 = velas_1h(300, salto=1.0)
        for b in v1[-200:]:
            b["o"] = b["h"] = b["l"] = b["c"] = v1[-201]["c"]
        self.assertGreater(cr.planas(v1), 0.5)
        r = cr.estado_moneda("LINK", v1, a_4h(v1), v1[-1]["t"] + H1 + 60)
        self.assertEqual(r["ahora"], "NO EVALUABLE")
        self.assertIn("casi no se negocia", r["motivo"])
        self.assertEqual(cr.sin_negociacion(velas_1h(300)), "")
        self.assertEqual(cr.tipo_de("ATOM"), "cripto")
        self.assertEqual(cr.MATERIAS["ATOM"]["yahoo"], "ATOM-USD")

    def test_recorta_el_inicio_sin_negociacion(self):
        v1 = velas_1h(1500)
        for b in v1[:600]:                     # recién listado: 600 velas planas al principio
            b["o"] = b["h"] = b["l"] = b["c"] = 100.0
        util = cr.recortar_inicio_sin_negociacion(v1)
        self.assertLess(len(util), len(v1))
        self.assertLessEqual(cr.planas(util), cr.MAX_PLANAS)
        v1b, v4b = cr.preparar_historia(v1, a_4h(v1))
        self.assertEqual(v1b[0]["t"], util[0]["t"])

    def test_sin_negociacion_ahora_es_error(self):
        v1 = velas_1h(1500)
        for b in v1[-600:]:
            b["o"] = b["h"] = b["l"] = b["c"] = 100.0
        with self.assertRaises(cr.Error):
            cr.preparar_historia(v1, a_4h(v1))

    def test_fugas_por_activo(self):
        self.assertEqual(cr.fugas_de("BTC")["swap"], 0.0)
        self.assertGreater(cr.fugas_de("ORO")["swap"], 0)
        f = cr.fugas_de("EURUSD")
        self.assertAlmostEqual(f["spread"] + 2 * f["desliz"], cr.coste_de("EURUSD"))


class ListaDeSeguimiento(unittest.TestCase):
    def test_nombres_con_usdt_y_pares(self):
        self.assertEqual(cr._monedas(["BTC/USDT", "FIL/USDT", "dot", "USD/JPY", "AUDUSD", "aapl"]),
                         ["BTC", "FIL", "DOT", "USDJPY", "AUDUSD", "AAPL"])

    def test_tipos_y_simbolos(self):
        self.assertEqual(cr.tipo_de("BTC"), "cripto")
        self.assertEqual(cr.tipo_de("FIL"), "cripto")
        self.assertEqual(cr.tipo_de("USDJPY"), "divisa")
        self.assertEqual(cr.tipo_de("TSLA"), "accion")
        self.assertEqual(cr.tipo_de("ORO"), "metal")
        self.assertFalse(cr.con_cierres("FIL"))
        self.assertTrue(cr.con_cierres("AAPL"))
        self.assertEqual(cr.simbolo_tv("FIL"), "BINANCE:FILUSDT")
        self.assertEqual(cr.simbolo_tv("AAPL"), "NASDAQ:AAPL")
        self.assertEqual(cr.simbolo_tv("USDJPY"), "FX:USDJPY")

    def test_yen_con_tres_decimales(self):
        cr.fijar_precision("USDJPY")
        try:
            self.assertEqual(cr.fmt(159.5234), "159,523")
        finally:
            cr.fijar_precision(None)

    def test_costes_de_acciones(self):
        f = cr.fugas_de("AAPL")
        self.assertEqual(f["swap"], 0.0)
        self.assertAlmostEqual(f["spread"] + 2 * f["desliz"], cr.coste_de("AAPL"))
        apertura = 86400 * 20000 + 14 * 3600 + 1800        # 14:30 UTC
        self.assertEqual(cr.factor_spread(apertura, "AAPL"), 1.5)
        self.assertEqual(cr.factor_spread(apertura + 3 * H1, "AAPL"), 1.0)

    def test_acciones_dias_cortos_y_fin_de_semana(self):
        # sesiones de 7 velas a las y media, de lunes a viernes
        v1, t = [], 1793712600      # 03-11-2026 14:30 UTC (martes)
        c = 100.0
        while len(v1) < 7 * 60:
            d = cr.EPOCH + __import__("datetime").timedelta(seconds=t)
            if d.weekday() < 5 and (d.hour, d.minute) >= (14, 30) and d.hour < 21:
                c += 0.1
                v1.append({"t": t, "o": c - 0.1, "h": c + 0.05, "l": c - 0.2, "c": c, "v": 1000.0})
            t += H1
        self.assertGreater(len(cr.diarias_para(v1, "AAPL")), 50)
        lunes = v1[-1]["t"] + 64 * H1                     # de viernes por la tarde al lunes
        r = cr.estado_moneda("AAPL", v1, cr.agrupar_4h(v1), lunes)
        self.assertNotEqual(r["ahora"], "NO EVALUABLE", r.get("motivo"))


class ValidacionDura(unittest.TestCase):
    def test_caida_maxima(self):
        self.assertEqual(cr.caida_maxima([1, 1, -1, -2, 3]), 3)
        self.assertEqual(cr.caida_maxima([1, 2, 3]), 0)

    def test_sharpe(self):
        self.assertIsNone(cr.sharpe([1, 2]))
        self.assertIsNone(cr.sharpe([1.0] * 12))                     # sin variación
        self.assertGreater(cr.sharpe([1, 2, 1, 2, 1, 2, 1, 2]), 0)

    def test_comprar_y_mantener(self):
        v1 = velas_1h(24 * 70, pendiente=0.05)
        bh = cr.comprar_y_mantener(v1, v1[0]["t"], v1[-1]["t"])
        self.assertGreater(bh["rent_pct"], 0)
        self.assertGreaterEqual(bh["caida_pct"], 0)

    def test_vecinos_incluyen_la_regla(self):
        self.assertIn((cr.N_RUPTURA, cr.N_STOP, cr.N_EMA), cr.VECINOS)
        self.assertEqual(len(cr.VECINOS), 11)

    def test_doble_coste(self):
        self.assertEqual(cr.doble_coste({"spread": 0.1, "swap": 0.0}), {"spread": 0.2, "swap": 0.0})

    def test_walk_forward_elige_con_el_pasado(self):
        base = (20, 10, 50)
        t0 = cr.parse_ahora("2025-01-15 10:00")
        def ops(rs):   # una operación a mitad de cada trimestre
            return [{"salida_ts": t0 + q * 91 * 86400, "R": r} for q, r in enumerate(rs)]
        por = {base: ops([1, 1, 1, 1, 1, 1]), (15, 8, 50): ops([2, 2, 2, 2, -5, -5])}
        wf = cr.walk_forward(por, base, t0, t0 + 5 * 91 * 86400)
        self.assertEqual(wf["fuera"], 2)
        self.assertEqual(wf["fija_R"], 2)
        self.assertEqual(wf["optimizada_R"], -4)               # -5 (eligió la otra) + 1 (vuelve a la fija)

    def test_regimen_diario_tendencia_y_desplome(self):
        sube = velas_1h(24 * 120, pendiente=0.05)
        reg = cr.regimen_diario(sube)
        self.assertEqual(reg[max(reg)], "TENDENCIA TRANQUILA")
        cae = velas_1h(24 * 120, pendiente=0.0)
        for i, b in enumerate(cae[-24 * 5:]):                 # caída fuerte en los últimos 5 días
            c = 100 - (i + 1) * 0.3
            b["o"], b["c"], b["h"], b["l"] = c + 0.3, c, c + 0.35, c - 0.05
        reg = cr.regimen_diario(cae)
        self.assertIn(reg[max(reg)], ("DESPLOME", "NERVIOSO"))

    def test_umbral_regla_rota(self):
        Rs = [2, -1, -1] * 20
        u = cr.umbral_regla_rota(Rs)
        self.assertLess(u["p5"], 0 + 2 * 30)
        self.assertEqual(u["ultimas"], sum(Rs[-30:]))
        self.assertIsNone(cr.umbral_regla_rota([1] * 10))

    def test_veredicto(self):
        bueno = {"real": {"n": 200, "R_medio": 0.12}, "x2": {"n": 200, "R_medio": 0.06}, "pos_vecinos": 11,
                 "wf": {"trimestres": 12, "positivos": 9}, "bh": {"sharpe": 0.5}, "sharpe": 0.9, "caida_R": 10,
                 "regla_rota": {"n": 30, "ultimas": 0, "p5": -8}}
        self.assertEqual(cr.veredicto_validacion(bueno)[0], "🟢 SÓLIDA")
        fragil = dict(bueno, pos_vecinos=4)
        v, fallos = cr.veredicto_validacion(fragil)
        self.assertEqual(v, "🟡 FRÁGIL")
        self.assertTrue(any("ajuste exacto" in f for f in fallos))
        rota = dict(bueno, regla_rota={"n": 30, "ultimas": -12, "p5": -8})
        self.assertTrue(any("REGLA ROTA" in f for f in cr.veredicto_validacion(rota)[1]))
        malo = dict(bueno, real={"n": 200, "R_medio": -0.1})
        self.assertEqual(cr.veredicto_validacion(malo)[0], "🔴 NO OPERAR")

    def test_margen_de_error(self):
        self.assertIsNone(cr.intervalo_R([1.0] * 10))
        ic = cr.intervalo_R([2, -1, -1] * 40)                  # media 0: el margen cruza el 0
        self.assertLess(ic["bajo"], 0)
        self.assertGreater(ic["alto"], 0)
        ic = cr.intervalo_R([2, 2, -1] * 40)                   # media +1: claramente positiva
        self.assertGreater(ic["bajo"], 0)

    def test_veredicto_con_margen_y_azar(self):
        bueno = {"real": {"n": 200, "R_medio": 0.12}, "x2": {"n": 200, "R_medio": 0.06}, "pos_vecinos": 11,
                 "wf": {"trimestres": 12, "positivos": 9}, "bh": {"sharpe": 0.5}, "sharpe": 0.9, "caida_R": 10,
                 "regla_rota": None, "ic": {"bajo": 0.03, "alto": 0.2},
                 "azar": {"regla_R": 0.12, "azar_R": 0.0, "percentil": 97.0, "recorridos": 100}}
        self.assertEqual(cr.veredicto_validacion(bueno)[0], "🟢 SÓLIDA")
        suerte = dict(bueno, ic={"bajo": -0.05, "alto": 0.29})
        v, fallos = cr.veredicto_validacion(suerte)
        self.assertEqual(v, "🟡 FRÁGIL")
        self.assertTrue(any("suerte" in x for x in fallos))
        azar = dict(bueno, azar={"regla_R": 0.12, "azar_R": 0.11, "percentil": 60.0, "recorridos": 100})
        self.assertTrue(any("al azar" in x for x in cr.veredicto_validacion(azar)[1]))

    def test_entradas_al_azar_copian_riesgo_y_direccion(self):
        import random
        v1 = velas_1h(500, pendiente=0.01)
        s = {"lado": "COMPRA", "entrada": 100.0, "stop": 98.0, "zona": (99.0, 100.5), "j": 10}
        x = cr.entradas_al_azar(v1, [s], random.Random(1))[0]
        self.assertEqual(x["lado"], "COMPRA")
        self.assertAlmostEqual((x["entrada"] - x["stop"]) / x["entrada"], 0.02)
        self.assertAlmostEqual(x["objetivo"], x["entrada"] + cr.OBJETIVO_R * x["R"])

    def test_contra_azar_sin_red(self):
        v1 = velas_1h(24 * 60, pendiente=0.01)
        for i in range(0, len(v1), 37):
            v1[i]["c"] += 0.8
            v1[i]["h"] = max(v1[i]["h"], v1[i]["c"] + 0.05)
        az = cr.contra_azar(v1, a_4h(v1), "BTC", recorridos=10)
        if az:                                                 # puede no haber operaciones cerradas
            self.assertTrue(0 <= az["percentil"] <= 100)
            self.assertEqual(az["recorridos"], 10)

    def test_filtro_de_regimen(self):
        extra = {"reg": {86400 * 20000: "NERVIOSO", 86400 * 20001: "LATERAL"}}
        extra["reg_dias"] = sorted(extra["reg"])
        s = {"lado": "COMPRA", "j": 0, "t": 86400 * 20002 + 3600, "cierre_ts": 0}
        self.assertTrue(cr.pasa_filtro("regimen", s, [], extra))       # día anterior: lateral
        s["t"] = 86400 * 20001 + 3600
        self.assertFalse(cr.pasa_filtro("regimen", s, [], extra))      # día anterior: nervioso

    def test_senal_con_ajustes_vecinos(self):
        v1 = velas_1h(300, salto=1.0)
        v4 = a_4h(v1)
        base = cr.senal_en(v1, len(v1) - 1, v4)
        otra = cr.senal_en(v1, len(v1) - 1, v4, None, 25, 12)
        self.assertEqual(base["lado"], otra["lado"])
        self.assertLessEqual(otra["stop"], base["stop"])            # 12 velas de stop: mínimo más bajo o igual


class Panel(unittest.TestCase):
    def test_datos_del_panel_sin_red(self):
        v1 = velas_1h(24 * 120, pendiente=0.01)
        for i in range(0, len(v1), 37):                 # algún salto para que haya señales
            v1[i]["c"] += 0.8
            v1[i]["h"] = max(v1[i]["h"], v1[i]["c"] + 0.05)
        datos = cr.datos_panel({"BTC": (v1, a_4h(v1))}, recorridos=50, n=20, muestra=3)
        self.assertEqual(sorted(datos), ["activos", "bandas", "caminos", "pasos", "supuestos", "validacion"])
        self.assertEqual(datos["activos"][0]["activo"], "BTC")
        self.assertEqual([p["clave"] for p in datos["pasos"]], ["ideal", "costes", "desliz", "retraso", "swap", "cartera"])
        self.assertEqual(len(datos["supuestos"]), 4)
        json.dumps(datos)                                 # se puede guardar tal cual

    def test_fila_validacion(self):
        r = {"moneda": "BTC", "veredicto": "🟡 FRÁGIL", "real": {"n": 200, "R_medio": 0.1234},
             "x2": {"n": 200, "R_medio": 0.05}, "pos_vecinos": 9, "wf": {"positivos": 8, "trimestres": 12},
             "caida_R": 12.34, "sharpe": 0.9, "bh": {"sharpe": 0.5}, "regla_rota": {"ultimas": -9, "p5": -8},
             "regimen_ahora": "LATERAL", "fallos": ["algo"]}
        f = cr.fila_validacion(r)
        self.assertEqual(f["r_real"], 0.12)
        self.assertTrue(f["regla_rota"])
        self.assertEqual(f["regimen_ahora"], "lateral")
        self.assertEqual(f["por_que"], "algo")


class FichasYNoticias(unittest.TestCase):
    def test_ficha_con_los_ocho_campos(self):
        f = cr.ficha(1, "LINK", "COMPRA", 9.694, "1h", "Cierre por encima", cr.parse_ahora("2026-11-28 20:00"))
        for campo in ("Símbolo:     BITSTAMP:LINKUSD", "Operación:   🟢 COMPRA (abrir largo)", "Nivel:       9,694",
                      "Marco:       1h", "Condición:   Cierre por encima", "Tipo:        Una vez por cierre de barra",
                      "Caducidad:   28/11 20:00 (Madrid)", 'Texto:       "🟢 COMPRA LINK'):
            self.assertIn(campo, f)
        self.assertTrue(f.startswith("FICHA 1"))
        self.assertNotIn("\u2014", f)

    def test_ficha_de_venta(self):
        f = cr.ficha(2, "BTC", "VENTA", 58719, "1h", "Cierre por debajo", cr.parse_ahora("2026-11-28 20:00"))
        self.assertIn("🔴 VENTA (abrir corto)", f)
        self.assertIn("cierra < 58.719", f)

    def test_noticias_con_etiquetas(self):
        rss = (b'<?xml version="1.0"?><rss><channel>'
               b'<item><title>SEC approves new ETF</title><link>https://x/1</link>'
               b'<pubDate>Fri, 27 Nov 2026 18:30:00 +0000</pubDate></item>'
               b'<item><title>Sin fecha</title><link>https://x/2</link></item>'
               b'</channel></rss>')
        items = cr.parse_noticias(rss, "BTC")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["etiquetas"], ["regulación", "ETF"])


class Comandos(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        v1 = velas_1h(300, salto=1.0)
        for nombre, velas in (("linkusd-1h.json", v1), ("linkusd-4h.json", a_4h(v1))):
            with open(os.path.join(self.dir, nombre), "w") as fh:
                json.dump(velas, fh)
        self.ahora = v1[-1]["t"] + H1 + 60

    def correr(self, argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cr.main(argv)
        return code, out.getvalue()

    def test_escanear_sin_red(self):
        code, out = self.correr(["escanear", "LINK", "--offline", self.dir, "--ahora",
                                 "2026-11-16 12:01"])
        self.assertEqual(code, 0)
        self.assertIn("| Activo | Último cierre (hora) | Ahora |", out)
        self.assertIn("| LINK |", out)
        self.assertTrue(out.rstrip().endswith(cr.CIERRE))

    def test_senal_sin_red_da_fichas(self):
        ahora = cr.a_madrid(self.ahora).strftime("%Y-%m-%d %H:%M")
        code, out = self.correr(["senal", "LINK", "--offline", self.dir, "--ahora", ahora])
        self.assertEqual(code, 0)
        self.assertIn("🟢 COMPRA activada", out)
        self.assertIn("FICHA 1", out)
        self.assertIn("FICHA 2", out)

    def test_moneda_sin_datos_no_evaluable(self):
        code, out = self.correr(["escanear", "BTC", "--offline", self.dir])
        self.assertIn("NO EVALUABLE", out)

    def test_tamano_y_riesgo(self):
        code, out = self.correr(["tamano", "--capital", "10000", "--riesgo", "0.5", "--entrada", "9.694",
                                 "--stop", "9.107"])
        self.assertIn("85,1", out)
        code, out = self.correr(["riesgo", "--capital", "10000", "--riesgo", "1", "--entrada", "9.694",
                                 "--stop", "9.107", "--ahora", "2026-11-28 10:00"])
        self.assertEqual(code, 1)
        self.assertIn("BLOQUEA", out)


if __name__ == "__main__":
    unittest.main()
