# BTCUSD 1h · ruptura de 20 velas con contexto de 4h

Prueba histórica en simulación (2026-11-26). No se conectó ningún bróker ni se envió ninguna orden.
Las reglas se fijaron antes de calcular los resultados: ver `REGLAS.md`.

- Datos: TradingView `BITSTAMP:BTCUSD` (mercado al contado de Bitstamp), velas de 1 hora.
  4.999 velas cerradas, del 2026-05-02 06:00 al 2026-11-26 13:00 UTC, sin huecos.
  Las primeras señales posibles son del 2026-05-10 16:00 UTC: la EMA 50 de 4 h necesita 50 velas de 4 h para estar lista.
- Costes: 0,10 % por lado (0,05 % comisión + 0,05 % deslizamiento), 0,20 % por operación. Sin financiación (funding).

## Resultados (después de costes)

| | Alcista (largo) | Bajista (corto) |
|---|---|---|
| Señales / operaciones | 42 | 51 |
| Objetivo 2R | 9 | 8 |
| Stop | 22 | 21 |
| Salida por tiempo (48 h) | 11 | 22 |
| Indeterminadas / abiertas | 0 / 0 | 0 / 0 |
| Ganadoras | 15 | 21 |
| Resultado medio neto | −0,18 % | +0,01 % |
| Resultado medio bruto | +0,02 % | +0,21 % |
| Resultado medio neto en R | −0,20 R | −0,14 R |
| 1.ª mitad (hasta 2026-08-14) | 18 ops, −0,97 % | 26 ops, −0,02 % |
| 2.ª mitad | 24 ops, +0,41 % | 25 ops, +0,05 % |

## Archivos

- `REGLAS.md`: las reglas fijadas antes de la prueba.
- `operaciones.csv`: una fila por operación (horas de la señal en UTC y en Madrid).
- `bt_btc.py`: el script. Uso: `python3 bt_btc.py VELAS.json SALIDA.csv EPOCH_AHORA`.
- `indicador.pine`: indicador de TradingView (Pine v6), con selector Alcista / Bajista / Ambas.
  El compilador de TradingView lo ha validado sin errores, pero no se ha guardado en ninguna cuenta.
  Marca todas las señales, también las que la prueba ignora por tener ya una operación abierta.
- `datos/`: las velas originales.
