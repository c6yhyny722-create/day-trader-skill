# Estrategia del vídeo «Cómo Usar CLAUDE Para Hacer Trading» · preparación

Solo simulación: nada aquí envía órdenes.

## Estado (26-11-2026)

- [x] Plantilla Pine v6 de backtest (`estrategia.pine`) con módulos de entrada, filtro, stop, objetivo,
      comisión, deslizamiento y periodo. **Sin validar en TradingView** (cupo diario agotado).
- [x] Ficha de reglas (`FICHA.md`) para rellenar.
- [ ] Reglas del vídeo: faltan. Pegar la transcripción de YouTube («Ver más» → «Mostrar transcripción»)
      o capturas de las reglas / del código / del probador de estrategias.
- [ ] Validar y guardar el script en TradingView.
- [ ] Backtests (abajo).

Los valores por defecto de la plantilla (cruce EMA 9/21 con filtro EMA 200, stop 2 ATR, objetivo 2R)
son una **hipótesis de prueba**, no las reglas del vídeo. Ningún resultado con ellos se presenta como
«la estrategia del vídeo».

## Plan en TradingView cuando haya cupo

1. `validate-pine-script` con `estrategia.pine` (con las reglas de la ficha ya puestas).
2. `create-pine-script` → guardar el `script_id` aquí.
3. `run-pine-backtest` en el activo y temporalidad de la ficha:
   - Referencia: el periodo del vídeo (o los últimos 2 años si no lo dice).
   - Contraste: el periodo anterior de la misma duración.
   - Mismas reglas en ambos; no se reajustan parámetros entre uno y otro.
4. Comparar con comprar y mantener en el mismo periodo y con «10 cripto 1h» si el activo es cripto.
5. Informe: operaciones, % ganadoras, factor de beneficio, máximo drawdown, rendimiento neto,
   rendimiento vs comprar y mantener; qué se sostiene en los dos periodos y qué no.
6. Solo si aguanta: ficha de alerta propuesta (símbolo, dirección, nivel, temporalidad, condición,
   tipo de alerta, caducidad, texto). No se crea ninguna alerta sin permiso.

## Pendiente de tus alertas (relacionado)

- Una única alerta «10 cripto 1h» v2.0 sobre BITSTAMP:BTCUSD en 1 h (crearla en TradingView: la conexión
  no crea alertas de indicador).
- Pausar/borrar la alerta de COINBASE:BTCUSD (id 6158574788) y la antigua v1.0 de Bitstamp (id 6158577302)
  cuando la nueva esté activa.

## Herramientas relacionadas

- Skill `tv-estrategia/`: flujo completo en español (ficha → Pine → backtest → comprobación → alerta).
- `tv-estrategia/prompts/01-extraer-estrategia.md`: pegar aquí la transcripción del vídeo.
