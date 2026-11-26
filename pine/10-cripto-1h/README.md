# 10 cripto 1h · ruptura 20 + contexto 4h

Copia del indicador Pine guardado en TradingView (`USER;c402a1494cd34107b5f62a34dd95f747`).
Solo simulación: no envía órdenes.

## v2.0 (26-11-2026)

- **Datos con retraso:** usa la última vela 1h cerrada disponible de cada moneda aunque
  no sea la misma hora que la del gráfico (antes se descartaba). Límite configurable:
  «Retraso máximo aceptado del dato (horas)», 24 por defecto. La línea indica
  «Dato con retraso de N h» cuando la vela es anterior al cierre del gráfico.
- **Hora real de cierre:** cada línea del aviso lleva la hora de cierre de la vela de
  esa moneda en Europe/Madrid (`dd-MM-yyyy HH:mm`); la cabecera, el cierre 1h del gráfico.
- **Sin repeticiones:** cada moneda recuerda la última vela que entró en un aviso y no
  vuelve a notificarla, aunque su dato retrasado siga apareciendo en horas siguientes.

Las alertas de TradingView guardan la versión del script con la que se crearon: hay que
volver a crearlas (o editarlas y guardarlas) para que usen la v2.0. Dos alertas sobre este
mismo indicador (p. ej. en gráficos de Bitstamp y Coinbase) envían el mismo aviso dos veces.
