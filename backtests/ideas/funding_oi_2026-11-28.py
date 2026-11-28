"""Idea de la foto «20 repos de Claude» (lista awesome-mcp-servers, Finanzas): ¿el funding,
el interés abierto, las liquidaciones o la posición de la multitud separan las señales buenas
de las malas? Mundo real (fugas, entrada en la vela siguiente), 5 monedas, 3 años.

Datos: archivo público de Binance (data.binance.vision), futuros USDT:
  fundingRate mensual y metrics diario (interés abierto cada 5 min, ratio largos/cortos,
  ratio de compradores/vendedores agresivos). Solo se usa lo publicado ANTES del cierre de la señal.
Uso: python3 backtests/ideas/funding_oi_2026-11-28.py <carpeta con f/ y m/>
"""
import sys, os, io, csv, zipfile, time, bisect, datetime as dt
sys.path.insert(0, "trader-cripto"); import cripto as cr

CARPETA = sys.argv[1]


def leer_zip(ruta):
    with zipfile.ZipFile(ruta) as z:
        nombre = z.namelist()[0]
        return list(csv.reader(io.TextIOWrapper(z.open(nombre))))


def funding(sim):
    filas = []
    for f in sorted(os.listdir(f"{CARPETA}/f")):
        if f.startswith(sim + "-"):
            for r in leer_zip(f"{CARPETA}/f/{f}")[1:]:
                filas.append((int(r[0]) // 1000, float(r[2])))
    filas.sort(); return filas


def metricas(sim):
    filas = []
    for f in sorted(os.listdir(f"{CARPETA}/m")):
        if f.startswith(sim + "-"):
            for r in leer_zip(f"{CARPETA}/m/{f}")[1:]:
                try:
                    ts = int(dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp())
                    if float(r[3]) > 0:
                        filas.append((ts, float(r[3]), float(r[6] or 0), float(r[7] or 0)))
                except (ValueError, IndexError):
                    pass
    filas.sort(); return filas


def antes(serie, tss, ts):
    """Índice del último dato con marca <= ts (o -1)."""
    return bisect.bisect_right(tss, ts) - 1


def percentil(valor, previos):
    if len(previos) < 30: return None
    return 100 * sum(1 for x in previos if x < valor) / len(previos)


res = []
ahora = int(time.time())
for m in ["BTC", "ETH", "SOL", "DOGE", "XLM"]:
    sim = m + "USDT"
    fu = funding(sim); fts = [x[0] for x in fu]
    me = metricas(sim); mts = [x[0] for x in me]
    v1, v4 = cr.cargar(m, None, 1095 * 24)
    v1, v4 = cr.preparar_historia(cr.cerradas(v1, cr.H1, ahora), cr.cerradas(v4, cr.H4, ahora))
    lista = cr.senales(v1, v4); por_ts = {s["cierre_ts"]: s for s in lista}
    ops = cr.operaciones_reales(v1, lista, 720, cr.fugas_de(m), siguiente=True, moneda=m, spread_variable=True)
    for o in ops:
        s = por_ts[o["ts"]]; ts = s["cierre_ts"]; compra = s["lado"] == "COMPRA"
        x = {"m": m, "ts": ts, "R": o["R"]}
        i = antes(fu, fts, ts)
        if i >= 0 and ts - fts[i] < 9 * 3600:
            p = percentil(fu[i][1], [v for t, v in fu[max(0, i - 270):i]])  # 90 días previos
            if p is not None:
                x["funding_multitud_igual"] = (compra and p >= 80) or ((not compra) and p <= 20)
                x["funding_multitud_contra"] = (compra and p <= 20) or ((not compra) and p >= 80)
        k = antes(me, mts, ts)
        if k >= 0 and ts - mts[k] <= 600:
            k24 = antes(me, mts, ts - 86400); k1 = antes(me, mts, ts - 3600)
            if k24 >= 0 and ts - 86400 - mts[k24] <= 600:
                ch24 = me[k][1] / me[k24][1] - 1
                x["oi_24h_sube_3"] = ch24 > 0.03
                x["oi_24h_baja_3"] = ch24 < -0.03
            if k1 >= 0 and ts - 3600 - mts[k1] <= 600:
                ch1 = me[k][1] / me[k1][1] - 1
                x["_ch1"] = ch1
                x["barrida_1h_oi_-1,5"] = ch1 < -0.015   # caída brusca del interés abierto ≈ liquidaciones
            previos = [r[2] for r in me[max(0, k - 288 * 30):k:12]]  # ratio largos/cortos, 30 días, cada hora
            p = percentil(me[k][2], previos)
            if p is not None:
                x["_ls_p"] = p if compra else 100 - p
                x["ls_multitud_igual"] = (compra and p >= 80) or ((not compra) and p <= 20)
            ult = [r[3] for r in me[max(0, k - 11):k + 1] if r[3] > 0]
            if ult:
                tk = sum(ult) / len(ult)
                x["_tk"] = tk if compra else 1 / tk
                x["agresores_a_favor"] = (compra and tk > 1.05) or ((not compra) and tk < 0.95)
        res.append(x)

res.sort(key=lambda x: x["ts"])
n = len(res); t1, t2 = res[n // 3]["ts"], res[2 * n // 3]["ts"]
per = lambda x: 0 if x["ts"] < t1 else 1 if x["ts"] < t2 else 2
media = lambda xs: sum(xs) / len(xs) if xs else float("nan")
print(f"operaciones {n}  R medio {media([x['R'] for x in res]):+.3f}")
claves = ["funding_multitud_igual", "funding_multitud_contra", "oi_24h_sube_3", "oi_24h_baja_3",
          "barrida_1h_oi_-1,5", "ls_multitud_igual", "agresores_a_favor"]
for c in claves:
    con = [x for x in res if x.get(c) is True]; sin = [x for x in res if x.get(c) is False]
    linea = f"{c:24s} con {media([x['R'] for x in con]):+.3f} (n={len(con)}) sin {media([x['R'] for x in sin]):+.3f} (n={len(sin)}) |"
    for p in range(3):
        a = [x["R"] for x in con if per(x) == p]; b = [x["R"] for x in sin if per(x) == p]
        linea += f" P{p+1} {media(a):+.2f}({len(a)}) vs {media(b):+.2f}"
    ic = cr.intervalo_R([x["R"] for x in con]) if len(con) >= 20 else None
    print(linea, "| IC con", ic and (round(ic["bajo"], 2), round(ic["alto"], 2)))

print("\nAjustes vecinos (con / sin, y P1 P2 P3 de 'con' menos 'sin'):")
def barrer(nombre, campo, umbrales, cond):
    for u in umbrales:
        con = [x for x in res if campo in x and cond(x[campo], u)]; sin = [x for x in res if campo in x and not cond(x[campo], u)]
        d = []
        for p in range(3):
            d.append(media([x["R"] for x in con if per(x) == p]) - media([x["R"] for x in sin if per(x) == p]))
        print(f"  {nombre} {u}: con {media([x['R'] for x in con]):+.3f} (n={len(con)}) sin {media([x['R'] for x in sin]):+.3f}  dif P {' '.join(f'{v:+.2f}' for v in d)}")
barrer("largos/cortos percentil >=", "_ls_p", [70, 75, 80, 85, 90], lambda v, u: v >= u)
barrer("caída interés abierto 1h <", "_ch1", [-0.01, -0.0125, -0.015, -0.02, -0.025], lambda v, u: v < u)
barrer("agresores a favor >", "_tk", [1.0, 1.03, 1.05, 1.08, 1.10], lambda v, u: v > u)
todo = [x["R"] for x in res]
filtrado = [x["R"] for x in res if not x.get("ls_multitud_igual") and not x.get("barrida_1h_oi_-1,5")]
print(f"\nSin filtro: {media(todo):+.3f} R, {len(todo)} ops, total {sum(todo):+.0f} R")
print(f"Quitando multitud igual + barrida: {media(filtrado):+.3f} R, {len(filtrado)} ops, total {sum(filtrado):+.0f} R")
solo_ag = [x["R"] for x in res if x.get("agresores_a_favor")]
print(f"Solo con agresores a favor: {media(solo_ag):+.3f} R, {len(solo_ag)} ops, total {sum(solo_ag):+.0f} R")
