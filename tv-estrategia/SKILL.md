---
name: tv-estrategia
description: >-
  Estrategia con TradingView, de la idea a la alerta, solo en simulación. Convierte
  una estrategia (transcripción o capturas de un vídeo de YouTube, descripción del
  usuario o un script existente) en una ficha de reglas sin inventar nada, la escribe
  en Pine v6, la valida, la guarda y la prueba en TradingView con comisiones, en dos
  periodos y frente a comprar y mantener; comprueba cada condición sobre velas
  cerradas con su valor real (PASA / NO PASA) y propone la ficha de alerta con la
  hora de cierre en horario de Madrid y sin repetir velas ya notificadas. Nunca envía
  órdenes. Usar cuando el usuario diga "prepara la estrategia del vídeo", "pásalo a
  TradingView", "haz el backtest", "comprueba las condiciones", "¿hay señal?",
  "prepárame la alerta" o pegue una transcripción de trading.
argument-hint: "[transcripción | reglas.json | símbolo]"
---

# tv-estrategia

Flujo en español para llevar una estrategia hasta TradingView y probarla sin arriesgar
dinero. Reúne lo útil de los prompts de Claude Code que más circulan
(claude-tradingview-mcp-trading de Lewis Jackson, tradingview-mcp de tradesdontlie,
pinescript-agents de TradersPost) y quita lo que no encaja con este usuario: no hay
bróker, ni claves de exchange, ni bot 24/7 que opere solo.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill.

```bash
python3 "${CLAUDE_SKILL_DIR}/comprobar.py" reglas.json \
    --datos BITSTAMP:BTCUSD@1h=btc1h.json --datos BITSTAMP:BTCUSD@4h=btc4h.json \
    --estado estado-avisos.json          # PASA / NO PASA por condición, vela cerrada, hora de Madrid
```

Las 11 skills `trader-*` (acciones de EE. UU.) se cuadran con TradingView según
`MAPA-11-SKILLS.md`: `tv_a_yahoo.py` convierte velas de TradingView al formato que leen con
`--offline`; para cripto se usa `comprobar.py` (con `--capital` y `--riesgo-pct` da el plan
y el tamaño simulados).

## Reglas del usuario (siempre)

- Respuestas en español claro y horas en Europe/Madrid.
- Solo análisis y simulación. Nunca enviar órdenes ni tocar sus alertas sin que lo pida.
- Datos de TradingView (conector TradingView, herramientas `mcp-tv-*`). Si falta un
  dato decisivo, se marca **NO EVALUABLE**; no se rellena con suposiciones.
- Método: 4h para contexto, velas de 1h CERRADAS para confirmar. Las reglas se fijan
  antes de que ocurran y no se reajustan después de ver el resultado.
- Distinguir siempre: **ficha propuesta** (texto), **alerta configurada** (existe en su
  cuenta) y **entrada simulada** (operación de prueba).
- Las revisiones empiezan con una tabla para iPhone:
  activo | último cierre y hora | estado | condición sube | condición baja | caducidad.
- El cupo diario de llamadas a TradingView es limitado: pocas llamadas, bien elegidas.

## Pasos

1. **Fuente.** Transcripción pegada, capturas, descripción del usuario o un script suyo.
   No se puede ver un vídeo ni abrir YouTube desde la sesión: pedir la transcripción
   (YouTube → «más» → «Mostrar transcripción») o capturas.
2. **Extraer reglas** con `prompts/01-extraer-estrategia.md`. Lo que la fuente no dice
   es `NO DICHO`, nunca se inventa. Resultado: `reglas.json` (ver `reglas.example.json`).
3. **Preguntas antes del código.** Si falta algo decisivo (activo, temporalidad, stop,
   salida), preguntar al usuario. Una petición de una línea produce código que no es la
   estrategia.
4. **Pine v6.** `strategy()` para el backtest (solo las estrategias dan informe),
   comisión 0,1 % por lado y 2 ticks de deslizamiento salvo que la fuente diga otra cosa,
   ejecución en la apertura de la vela siguiente, `request.security` con `[1]` y
   `lookahead_on` para la temporalidad mayor (sin repintado). Plantilla:
   `backtests/video-claude-trading/estrategia.pine`.
5. **Validar y guardar.** `mcp-tv-validate-pine-script` → corregir → `mcp-tv-create-pine-script`
   (o `mcp-tv-update-pine-script`, que guarda una versión nueva y conserva las anteriores).
6. **Backtest.** `mcp-tv-run-pine-backtest` en dos periodos de la misma duración con las
   mismas reglas (referencia y contraste) y comprar y mantener con `mcp-tv-get-ohlcv`
   (`summary: true`). Informe: operaciones, % ganadoras, factor de beneficio, máximo
   drawdown, rendimiento neto y frente a comprar y mantener.
7. **Auditoría.** Repintado o `lookahead`, menos de 30 operaciones, un solo periodo bueno,
   parámetros afinados al resultado, costes ausentes. Lo que falle se dice.
8. **Comprobación en vivo** (el «safety check»). `mcp-tv-get-ohlcv` de 1h y 4h a archivo,
   luego `comprobar.py`. Solo velas cerradas; si el dato llega con retraso se usa y se
   indica; una vela ya notificada no se repite (`--estado`).
9. **Ficha de alerta propuesta**: símbolo, dirección, nivel, temporalidad, condición,
   tipo de alerta, caducidad y texto. Para avisos de un indicador, usar el patrón de
   `pine/10-cripto-1h/10-cripto-1h.pine` (hora de cierre en Madrid por línea, sin
   repetidos). El conector solo crea alertas de precio: las de indicador las crea el
   usuario en TradingView. Una sola alerta por indicador (dos alertas iguales duplican
   cada aviso).

## Lo que nunca hace

No envía órdenes, no pide claves de exchange, no despliega bots, no presenta un
resultado de backtest como promesa, no presenta reglas supuestas como las de la fuente
y no cambia las reglas después de ver el resultado.

## Seguridad

- Educación y herramientas, no asesoramiento financiero (not financial advice).
- La mayoría de los backtests de los vídeos virales no se sostienen: costes reales,
  sobreajuste y repintado. Se dice con números.
- Ningún paso de esta skill coloca una orden. Si algún día el usuario quiere operar,
  eso pasa por `/trader-risk` y `/trader-broker`, con su sí explícito para cada orden.
