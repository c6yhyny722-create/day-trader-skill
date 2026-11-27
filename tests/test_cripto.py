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
