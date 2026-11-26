import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import ROOT, load

cp = load("tv-estrategia", "comprobar")

# 26-11-2026 20:00 UTC = 21:00 en Madrid (CET, UTC+1)
T0 = 1795723200 - 60 * 3600   # inicio de la primera vela 1h


def barras(n, paso, inicio, ultimo_salto=0.0, pendiente=0.0):
    out = []
    for i in range(n):
        c = 100.0 + i * pendiente + (ultimo_salto if i == n - 1 else 0.0)
        out.append({"t": inicio + i * paso, "o": c - 0.05, "h": c + 0.05, "l": c - 0.1, "c": c, "v": 10})
    return out


class Madrid(unittest.TestCase):
    def test_invierno_y_verano(self):
        self.assertEqual(cp.madrid(1795723200), "26-11-2026 21:00")        # CET
        self.assertEqual(cp.madrid(1782907200), "01-07-2026 14:00")        # CEST, 12:00 UTC
        # cambio de hora: último domingo de octubre de 2026 (25-10), 01:00 UTC
        self.assertEqual(cp.madrid(1792890000 - 1), "25-10-2026 02:59")
        self.assertEqual(cp.madrid(1792890000), "25-10-2026 02:00")


class Comprobar(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.reglas = os.path.join(ROOT, "tv-estrategia", "reglas.example.json")

    def guardar(self, nombre, doc):
        p = os.path.join(self.dir, nombre)
        with open(p, "w") as fh:
            json.dump(doc, fh)
        return p

    def correr(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cp.main(list(args))
        return code, buf.getvalue()

    def datos(self, ultimo_salto=5.0, n1h=60):
        h1 = self.guardar("1h.json", {"bars": barras(n1h, 3600, T0, ultimo_salto)})
        h4 = self.guardar("4h.json", {"t": [T0 - 60 * 14400 + i * 14400 for i in range(60)],
                                      "o": [50 + i for i in range(60)], "h": [51 + i for i in range(60)],
                                      "l": [49 + i for i in range(60)], "c": [50 + i for i in range(60)],
                                      "v": [1] * 60})
        return ["--datos", "BITSTAMP:BTCUSD@1h=" + h1, "--datos", "BITSTAMP:BTCUSD@4h=" + h4]

    def test_senal_nueva_y_luego_ya_notificada(self):
        estado = os.path.join(self.dir, "estado.json")
        args = [self.reglas, "--ahora", "2026-11-26T20:05:00Z", "--estado", estado] + self.datos()
        code, out = self.correr(*args)
        self.assertEqual(code, 0)
        self.assertIn("BITSTAMP:BTCUSD · alcista · vela de 1h cerrada a las 26-11-2026 21:00 (Madrid): SEÑAL NUEVA", out)
        self.assertIn("Simulación: no se ha enviado ninguna orden.", out)
        code, out = self.correr(*args)
        self.assertEqual(code, 1)
        self.assertIn("YA NOTIFICADA", out)
        self.assertNotIn("SEÑAL NUEVA", out)

    def test_vela_abierta_no_cuenta(self):
        # a las 19:59 UTC la vela de las 19:00 sigue abierta: la última cerrada es la de las 18:00
        code, out = self.correr(self.reglas, "--ahora", "2026-11-26T19:59:00Z", *self.datos())
        self.assertIn("26-11-2026 20:00", out)
        self.assertEqual(code, 1)   # la vela con la ruptura no ha cerrado

    def test_dato_con_retraso_se_usa_y_se_indica(self):
        code, out = self.correr(self.reglas, "--ahora", "2026-11-26T23:10:00Z", *self.datos())
        self.assertEqual(code, 0)
        self.assertIn("dato con retraso de 3 h", out)
        self.assertIn("cerrada a las 26-11-2026 21:00", out)

    def test_retraso_excesivo_es_no_evaluable(self):
        code, out = self.correr(self.reglas, "--ahora", "2026-11-28T20:05:00Z", *self.datos())
        self.assertEqual(code, 1)
        self.assertIn("NO EVALUABLE", out)

    def test_simbolo_sin_datos_es_no_evaluable(self):
        code, out = self.correr(self.reglas, "--ahora", "2026-11-26T20:05:00Z", *self.datos())
        self.assertIn("BITSTAMP:ETHUSD: NO EVALUABLE", out)

    def test_cruces_y_rsi(self):
        b = barras(30, 3600, T0, pendiente=0.1)
        datos = {"1h": b}
        self.assertAlmostEqual(cp.valor("rsi(14)", datos, "1h"), 100.0)
        self.assertAlmostEqual(cp.valor("highest(20)[1]", datos, "1h"), b[-2]["h"])
        f = cp.condicion({"a": "close", "op": "cruza_arriba", "b": "highest(5)[1]"}, datos, "1h")
        self.assertFalse(f["pasa"])   # ya estaba por encima en la vela anterior

    def test_expresion_mala(self):
        with self.assertRaises(cp.Error):
            cp.valor("macd(1,2)", {"1h": []}, "1h")


if __name__ == "__main__":
    unittest.main()
