# Validación dura de los 33 activos · 28/11/2026

Regla «ruptura 20 + contexto 4h» (la del script de Pine, sin cambios), en el **mundo real**:
diferencial, deslizamiento, retraso de una vela, comisión y swap. Velas de 1h de Bitstamp
(cripto) y Yahoo (metales, divisas, acciones), unos 3 años hasta el 28/11/2026.
Objetivo 2R, hasta stop u objetivo con tope de 30 días, sin solaparse.

Hecho con `python3 trader-cripto/cripto.py validar <activos>` (10 pruebas, ver
`trader-cripto/SKILL.md`). Solo análisis y simulación: no se enviaron órdenes ni se
tocaron alertas.

**Resultado: 🟢 1 · 🟡 14 · 🔴 18**

| Activo | Veredicto | R real | ×2 costes | Vecinos | Trimestres | Caída máx. | Sharpe regla/B&H | Margen 95 % | vs azar | Últimas 30 |
|---|---|---|---|---|---|---|---|---|---|---|
| DOGE | 🟢 SÓLIDA | 0,20 | 0,16 | 11/11 | 10/12 | 6 % | 1,49 / 0,24 | 0,00 a 0,39 | mejor que el 98 % | 12,3 R |
| SOL | 🟡 FRÁGIL | 0,13 | 0,10 | 11/11 | 9/13 | 10 % | 0,98 / 0,46 | -0,05 a 0,31 | mejor que el 99 % | 4,4 R |
| AAVE | 🟡 FRÁGIL | 0,13 | 0,10 | 11/11 | 5/9 | 12 % | 0,96 / -0,11 | -0,09 a 0,35 | mejor que el 90 % | 2,4 R |
| BTC | 🟡 FRÁGIL | 0,12 | 0,06 | 11/11 | 10/13 | 10 % | 0,92 / 0,54 | -0,06 a 0,30 | mejor que el 100 % | -0,3 R |
| ETH | 🟡 FRÁGIL | 0,11 | 0,07 | 10/11 | 9/13 | 14 % | 0,78 / 0,25 | -0,08 a 0,33 | mejor que el 91 % | 5,5 R |
| RUNE | 🟡 FRÁGIL | 0,08 | 0,04 | 8/11 | 5/9 | 13 % | 0,59 / -0,97 | -0,16 a 0,31 | mejor que el 75 % | -1,4 R |
| ORO | 🟡 FRÁGIL | 0,07 | -0,02 | 11/11 | 6/10 | 12 % | 0,34 / 0,86 | -0,17 a 0,31 | mejor que el 88 % | -5,2 R |
| AVAX | 🟡 FRÁGIL | 0,06 | 0,03 | 11/11 | 9/13 | 15 % | 0,41 / 0,02 | -0,13 a 0,24 | mejor que el 84 % | 1,5 R |
| XLM | 🟡 FRÁGIL | 0,05 | 0,01 | 8/11 | 6/13 | 15 % | 0,36 / 0,46 | -0,11 a 0,23 | mejor que el 81 % | 1,7 R |
| THETA | 🟡 FRÁGIL | 0,05 | 0,02 | 10/11 | 4/9 | 11 % | 0,43 / -1,69 | -0,15 a 0,27 | mejor que el 60 % | 4,6 R |
| DOT | 🟡 FRÁGIL | 0,05 | 0,01 | 7/11 | 9/12 | 26 % | 0,32 / -0,52 | -0,14 a 0,23 | mejor que el 75 % | 4,3 R |
| ARB | 🟡 FRÁGIL | 0,04 | 0,01 | 9/11 | 5/7 | 17 % | 0,36 / -0,23 | -0,20 a 0,30 | mejor que el 72 % | 8,9 R |
| TSLA | 🟡 FRÁGIL | 0,03 | 0,02 | 4/11 | 5/12 | 9 % | 0,08 / 0,79 | -0,35 a 0,40 | mejor que el 52 % | -5,2 R |
| NEAR | 🟡 FRÁGIL | 0,02 | -0,01 | 3/11 | 5/13 | 19 % | 0,12 / 0,44 | -0,16 a 0,20 | mejor que el 68 % | -0,7 R |
| MSTR | 🟡 FRÁGIL | 0,01 | 0,00 | 9/11 | 5/12 | 14 % | 0,03 / 0,64 | -0,33 a 0,35 | mejor que el 47 % | 2,8 R |
| XRP | 🔴 NO OPERAR | -0,00 | -0,05 | 7/11 | 6/13 | 31 % | -0,00 / 0,47 | -0,16 a 0,16 | mejor que el 68 % | -1,6 R |
| LINK | 🔴 NO OPERAR | -0,01 | -0,05 | 9/11 | 6/13 | 29 % | -0,09 / 0,18 | -0,18 a 0,16 | mejor que el 62 % | 8,5 R |
| AAPL | 🔴 NO OPERAR | -0,02 | -0,03 | 1/11 | 4/12 | 6 % | -0,06 / 1,25 | -0,43 a 0,48 | mejor que el 50 % | -3,5 R |
| ATOM | 🔴 NO OPERAR | -0,04 | -0,08 | 6/11 | 5/9 | 22 % | -0,29 / -1,76 | -0,25 a 0,18 | mejor que el 35 % | -7,0 R |
| ZEC | 🔴 NO OPERAR | -0,05 | -0,08 | 1/11 | 1/3 | 10 % | -0,28 / - | -0,46 a 0,40 | mejor que el 57 % | -4,6 R |
| GBPUSD | 🔴 NO OPERAR | -0,05 | -0,14 | 2/11 | 4/12 | 28 % | -0,27 / 0,23 | -0,27 a 0,17 | mejor que el 54 % | 0,4 R |
| USDCAD | 🔴 NO OPERAR | -0,05 | -0,19 | 0/11 | 7/12 | 27 % | -0,23 / 0,33 | -0,26 a 0,17 | mejor que el 62 % | 13,2 R |
| UNI | 🔴 NO OPERAR | -0,06 | -0,09 | 1/11 | 4/12 | 21 % | -0,47 / 0,14 | -0,25 a 0,13 | mejor que el 27 % | 2,1 R |
| PLATA | 🔴 NO OPERAR | -0,07 | -0,12 | 2/11 | 6/10 | 33 % | -0,29 / 0,60 | -0,31 a 0,18 | mejor que el 37 % | 8,4 R |
| NZDUSD | 🔴 NO OPERAR | -0,07 | -0,15 | 0/11 | 5/12 | 18 % | -0,46 / -0,33 | -0,29 a 0,15 | mejor que el 46 % | -2,9 R |
| HYPE | 🔴 NO OPERAR | -0,08 | -0,12 | 0/11 | 1/5 | 12 % | -0,96 / 1,37 | -0,35 a 0,19 | mejor que el 40 % | 1,0 R |
| ADA | 🔴 NO OPERAR | -0,08 | -0,11 | 1/11 | 5/13 | 41 % | -0,49 / 0,20 | -0,25 a 0,09 | mejor que el 26 % | -3,8 R |
| AUDUSD | 🔴 NO OPERAR | -0,12 | -0,21 | 0/11 | 3/12 | 38 % | -0,68 / 0,14 | -0,31 a 0,08 | mejor que el 29 % | 4,8 R |
| USDJPY | 🔴 NO OPERAR | -0,15 | -0,22 | 0/11 | 5/12 | 28 % | -0,80 / 0,28 | -0,35 a 0,06 | mejor que el 29 % | -7,1 R |
| LTC | 🔴 NO OPERAR | -0,18 | -0,23 | 0/11 | 3/13 | 70 % | -1,56 / 0,03 | -0,33 a -0,02 | mejor que el 7 % | 7,4 R |
| EURUSD | 🔴 NO OPERAR | -0,21 | -0,30 | 0/11 | 2/12 | 44 % | -1,34 / 0,10 | -0,40 a -0,02 | mejor que el 7 % | -5,8 R |
| FIL | 🔴 NO OPERAR | -0,25 | -0,28 | 0/11 | 1/9 | 51 % | -1,63 / -1,62 | -0,45 a -0,05 | mejor que el 0 % | -3,9 R |
| INJ | 🔴 NO OPERAR | -0,34 | -0,36 | 0/11 | 1/3 | 33 % | -2,27 / 1,31 | -0,63 a -0,04 | mejor que el 3 % | -18,6 R |

## Todos juntos (los que ganan, por grupo de ejecución)

- Todas juntas (BTC, ETH, SOL, DOGE, 905 operaciones): R medio 0,14, margen 95 % de 0,05 a 0,24 R. Juntas, la ventaja no parece suerte.
- Todas juntas (XLM, ORO, 399 operaciones): R medio 0,06, margen 95 % de -0,08 a 0,21 R. Ni juntas se puede descartar que sea suerte.
- Todas juntas (RUNE, AVAX, THETA, DOT, NEAR, 1048 operaciones): R medio 0,05, margen 95 % de -0,04 a 0,13 R. Ni juntas se puede descartar que sea suerte.
- Todas juntas (ARB, AAVE, 281 operaciones): R medio 0,09, margen 95 % de -0,08 a 0,25 R. Ni juntas se puede descartar que sea suerte.
- Todas juntas (TSLA, MSTR, 114 operaciones): R medio 0,02, margen 95 % de -0,24 a 0,29 R. Ni juntas se puede descartar que sea suerte.

Los grupos son solo cómo se repartió el cálculo (6 a la vez). La cifra que importa: BTC, ETH,
SOL y DOGE juntos, 905 operaciones, +0,14 R con margen de +0,05 a +0,24 R.

## Cómo leerlo

- 🟢 SÓLIDA: pasa las 10 pruebas. 🟡 FRÁGIL: gana pero falla alguna. 🔴 NO OPERAR: no gana
  en el mundo real.
- **Margen 95 %**: dónde está de verdad el R medio. Si cruza el 0, la ganancia puede ser suerte.
- **vs azar**: % de las 100 pruebas de entrada al azar (misma dirección, riesgo y objetivo)
  que la regla supera. Hace falta 90 % o más para decir que el momento de la ruptura aporta.
- **Últimas 30**: R de las 30 últimas operaciones; ⚠️ si van peor que el 95 % de lo esperado.

## Conclusiones

1. Solo DOGE es 🟢.
2. SOL, BTC y ETH solo fallan por el margen de error y superan al azar en el 91-100 %:
   juntos con DOGE, la ventaja es real.
3. AAVE gana +0,13 R pero solo en 5 de 9 trimestres.
4. LINK, XRP, ZEC y HYPE (del script de 10 monedas) salen 🔴.
5. LTC, EUR/USD, FIL e INJ pierden con todo el margen por debajo de 0.

Sirve de línea base para las revisiones semanales. Para repetirlo:
`python3 trader-cripto/cripto.py validar BTC ETH SOL DOGE ...` (unos 2-3 minutos por cada 6 activos).

El detalle de cada activo (régimen de mercado, caminando hacia delante, cómo puede fallar)
está en `detalle.md`; la tabla en `resumen.csv`.
