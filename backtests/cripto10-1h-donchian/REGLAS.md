# 10 criptomonedas · 1h · ruptura de 20 velas con contexto de 4h: reglas fijadas antes de la prueba

Escritas el 2026-11-26, antes de calcular ningún resultado de estas monedas. No se ajustan después.
La señal es la misma que en `../btcusd-1h-donchian/REGLAS.md`. Lo único nuevo es la zona de entrada.

## Selección de monedas (TradingView, 2026-11-26 ~13:00 UTC)
1. Ranking por capitalización: screener de TradingView, mercado `coin`, columna `market_cap_calc`.
2. Fuera las monedas estables (USDT, USDC, USDS, USDe, DAI, USDT0, RWUSD…).
3. Fuera las versiones duplicadas de otro activo (WBTC, cbBTC, stETH, wstETH, WBETH, WETH…).
4. Exchange: Bitstamp, el mismo de la prueba de BTC. Hace falta un par contra USD con liquidez:
   - al menos 0,5 M$ de volumen diario medio en los últimos 30 días (volumen × cierre de las velas de 1h);
   - al menos el 99 % de las velas de 1h de esos 30 días.
5. Las 10 primeras que lo cumplen, por orden de capitalización.

## Señal (por moneda, al cierre confirmado de cada vela de 1h)
- Contexto 4h: la última vela de 4h ya cerrada antes de que abra la vela de 1h. Alcista si su cierre > EMA 50
  de 4h; bajista si su cierre < EMA 50.
- Alcista: contexto alcista Y cierre > máximo más alto de las 20 velas de 1h anteriores de esa moneda.
- Bajista: contexto bajista Y cierre < mínimo más bajo de las 20 velas de 1h anteriores.
- Invalidación: alcista, mínimo más bajo de las 10 últimas velas, incluida la de señal; bajista, máximo más alto
  de las 10 últimas velas.
- Riesgo R = |cierre de señal − invalidación|. Objetivo: 2R desde el cierre de señal.
- Las velas son las de la propia moneda: si le falta una hora, se cuentan sus velas, no las horas del reloj.

## Zona de entrada (nueva)
- Alcista: desde el nivel roto hasta el nivel roto + 0,5R.
- Bajista: desde el nivel roto − 0,5R hasta el nivel roto.
- Si el cierre de señal queda fuera de esa zona (demasiado lejos del nivel roto): «Señal confirmada · Fuera
  de zona de entrada». El 0,5 se ha elegido de antemano, no se ha optimizado.

## Ejecución simulada (igual que BTC)
- Entrada en la apertura de la vela siguiente. Salida por stop, por objetivo o por tiempo (cierre de la vela 48).
- Una vela que toca stop y objetivo: indeterminado, fuera de la media.
- Una operación abierta a la vez por moneda y dirección.
- Costes: 0,10 % por lado (0,05 % comisión + 0,05 % deslizamiento). Sin financiación (funding).
- Se publican dos cuentas: todas las señales (como en BTC) y solo las que estaban dentro de zona.
