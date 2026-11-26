# BTCUSD 1h · ruptura de 20 velas con contexto de 4h — reglas fijadas antes de la prueba

Escritas el 2026-11-26, antes de calcular ningún resultado. No se ajustan después.

- Datos: TradingView BITSTAMP:BTCUSD, velas de 1 hora (UTC). Velas de 4 h construidas con las de 1 h,
  alineadas a 00, 04, 08, 12, 16 y 20 UTC. Solo velas cerradas; la vela en formación se descarta.
- Contexto de 4 h: la última vela de 4 h ya cerrada antes de que abra la vela de 1 h de señal.
  Alcista si su cierre > EMA 50 de cierres de 4 h; bajista si su cierre < EMA 50.

## Señal alcista (largo)
- Confirmación al cierre de la vela de 1 h: contexto 4 h alcista Y cierre > máximo más alto
  de las 20 velas de 1 h anteriores (sin contar la de señal).
- Invalidación (stop): mínimo más bajo de las 10 últimas velas de 1 h, incluida la de señal.
- Objetivo: cierre de señal + 2 × (cierre de señal − stop).

## Señal bajista (corto)
- Confirmación al cierre: contexto 4 h bajista Y cierre < mínimo más bajo de las 20 velas
  de 1 h anteriores.
- Invalidación (stop): máximo más alto de las 10 últimas velas de 1 h, incluida la de señal.
- Objetivo: cierre de señal − 2 × (stop − cierre de señal).

## Ejecución simulada
- Entrada en la apertura de la vela de 1 h siguiente a la señal.
- Salida: stop, objetivo, o por tiempo al cierre de la vela 48 tras la entrada (48 h).
- Si la apertura ya está más allá del stop o del objetivo, la salida es en esa apertura.
- Si una vela toca stop y objetivo, resultado indeterminado (fuera de la media).
- Una sola operación abierta a la vez por dirección; las señales durante una operación abierta
  de la misma dirección se ignoran.
- Costes: 0,10 % por lado (0,05 % comisión + 0,05 % deslizamiento), 0,20 % por operación.
  Sin financiación (funding) ni intereses.
- Resultado en % del precio de entrada y en R (riesgo = |entrada − stop|).
