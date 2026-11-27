---
name: trader-cripto
description: >-
  Las habilidades del paquete de day trading, adaptadas a cripto, solo en simulación.
  Con velas públicas de Bitstamp (el mismo mercado que las alertas de TradingView del
  usuario) aplica la regla del script «10 cripto 1h · ruptura 20 + contexto 4h» a BTC,
  ETH, XRP, SOL, HYPE, ZEC, DOGE, LINK, ADA y XLM: escanea las 10 monedas (como
  trader-scanner), da la señal con zona, invalidación y objetivo 2R (trader-entry y
  trader-exit), simula 10.000 recorridos y repasa cada señal pasada (trader-timemachine),
  calcula unidades fraccionarias para un % del capital (trader-budget), da PASA / BLOQUEA
  con los límites del usuario (trader-risk), propone fichas de alerta y lee el último
  precio (trader-alerts) y trae titulares por moneda (trader-news). Siempre dice COMPRA,
  VENTA o ESPERAR. Nunca envía órdenes ni crea alertas. Usar cuando el usuario diga
  "escanea las cripto", "¿hay señal en LINK?", "simula esta operación", "¿cuánto compro?",
  "¿cumple mis reglas?", "prepárame la ficha", "noticias de bitcoin" o pida estudiar
  cripto con las 11 habilidades.
argument-hint: "[escanear | senal MONEDA | simular MONEDA | tamano | riesgo | precio | ficha | noticias]"
---

# trader-cripto

Las 11 habilidades del paquete están hechas para acciones de EE. UU.: horario de la bolsa
de Nueva York, rango de apertura y acciones enteras. Esta habilidad lleva a cripto las que
tienen sentido allí, con el método del usuario: **4h para el contexto, velas de 1h cerradas
para confirmar, horas de Madrid**. Es para estudio e investigación con capital simulado.

`${CLAUDE_SKILL_DIR}` es la carpeta de esta skill.

## Equivalencias

| Paquete de acciones | En cripto | Comando |
| --- | --- | --- |
| trader-scanner | Las 10 monedas del script, con estado y niveles | `escanear` |
| trader-entry + trader-exit | Señal de la regla, zona de entrada, invalidación y objetivo 2R | `senal MONEDA` |
| trader-timemachine | 10.000 recorridos de las próximas horas y cada señal pasada | `simular MONEDA` |
| (nuevo) | Compara stops y objetivos en dos periodos, con costes | `estudiar` |
| (nuevo) | Estudio a fondo de una moneda con 3 años: diario, niveles, horas, regla y filtros | `afondo MONEDA` |
| trader-budget | Unidades fraccionarias para un % de riesgo, enseñando la cuenta | `tamano` |
| trader-risk | PASA / BLOQUEA con los límites del método | `riesgo` |
| trader-alerts | Último precio de Bitstamp y ficha de alerta propuesta | `precio`, `ficha` |
| trader-news | Titulares de Yahoo Finance por moneda, en hora de Madrid | `noticias` |
| trader-broker | **No se adapta**: el usuario no quiere órdenes | |
| trader-analyst, trader-pelosi | **No aplican**: no hay resultados trimestrales ni declaraciones del Congreso en cripto | |

## La regla (la del script de Pine, sin cambios)

- **🟢 COMPRA**: el cierre de la vela de 4h anterior está por encima de su EMA 50 y la vela de
  1h cierra por encima del máximo de las 20 velas anteriores.
- **🔴 VENTA**: el cierre de la vela de 4h anterior está por debajo de su EMA 50 y la vela de
  1h cierra por debajo del mínimo de las 20 velas anteriores.
- **Invalidación**: mínimo (compra) o máximo (venta) de las 10 últimas velas de 1h.
- **Zona de entrada**: desde el nivel roto hasta 0,5R. Fuera de ella no se persigue.
- **Objetivo**: 2R.

Comprobado con la alerta real del 26/11: LINK, vela cerrada a las 22:00, cierre 9,303,
🟢 COMPRA en zona. Sale igual que el aviso de TradingView.

## Comandos

```bash
python3 "${CLAUDE_SKILL_DIR}/cripto.py" escanear                 # tabla de las 10 monedas
python3 "${CLAUDE_SKILL_DIR}/cripto.py" escanear LINK BTC        # solo esas
python3 "${CLAUDE_SKILL_DIR}/cripto.py" senal LINK               # señal, plan y fichas
python3 "${CLAUDE_SKILL_DIR}/cripto.py" simular LINK             # 10.000 recorridos, 48 h
python3 "${CLAUDE_SKILL_DIR}/cripto.py" simular LINK --entrada 9.694 --stop 9.107 --horas 24
python3 "${CLAUDE_SKILL_DIR}/cripto.py" afondo BTC               # 3 años de BTC: lo más fiable
python3 "${CLAUDE_SKILL_DIR}/cripto.py" estudiar                 # las 10 monedas, 83 días, coste 0,1 %
python3 "${CLAUDE_SKILL_DIR}/cripto.py" estudiar LINK SOL --lado compra --coste 0.2
python3 "${CLAUDE_SKILL_DIR}/cripto.py" tamano --capital 10000 --riesgo 0.5 --entrada 9.694 --stop 9.107
python3 "${CLAUDE_SKILL_DIR}/cripto.py" riesgo --capital 10000 --riesgo 1 --entrada 9.694 --stop 9.107 \
    --abiertas 1 --perdida-hoy 0.5
python3 "${CLAUDE_SKILL_DIR}/cripto.py" precio LINK BTC
python3 "${CLAUDE_SKILL_DIR}/cripto.py" ficha LINK compra 9.694 --caduca "2026-11-28 20:00"
python3 "${CLAUDE_SKILL_DIR}/cripto.py" noticias BTC ETH --horas 12
```

- `--ahora "AAAA-MM-DD HH:MM"` (hora de Madrid) repite el análisis como si fuera esa hora.
- `--offline CARPETA` lee `linkusd-1h.json` y `linkusd-4h.json` (formato de Bitstamp, de
  `mcp-tv-get-ohlcv` o una lista de velas) en lugar de bajarlos.
- `--json` en `escanear` y `simular` da los datos completos.

## Controles contra errores

- **Solo velas cerradas.** La vela en curso nunca confirma.
- **Datos dudosos = NO EVALUABLE.** Si falta una vela de 1h o de 4h en el tramo que usa la
  regla, o hay una vela imposible (máximo por debajo del mínimo), la moneda sale NO EVALUABLE
  con el motivo. Igual si el último dato tiene más de 24 h de retraso.
- **Distancia del stop en ATR.** Cada plan dice a cuántos ATR de 1h está el stop y avisa si
  está a menos de 1 ATR (lo puede tocar el movimiento normal) o a más de 4 (sale muy pequeña).
- **La historia no cuenta dos veces la misma operación.** Si salen señales varias horas
  seguidas, solo cuenta la primera mientras siga abierta, como en la práctica.

## Ajustar entradas y stops sin engañarse: `estudiar`

Compara el stop de la regla con tres alternativas (colchón de 0,25 ATR, 1,5 ATR desde la
entrada, mínimo de 20 velas) y objetivos de 1,5R, 2R y 3R, con coste por operación.

- Parte el periodo en dos mitades. **Una variante solo se propone si gana a la regla en las
  dos**, con un margen de 0,05R y al menos 30 operaciones en cada mitad. Lo que mejora en una
  mitad y no en la otra suele ser casualidad.
- Al probar 12 combinaciones, alguna puede ganar por suerte. Una propuesta hay que volver a
  comprobarla con datos nuevos antes de usarla.
- **Nunca cambia la regla por su cuenta.** La regla se fija antes; cambiarla lo decide el usuario.

## Estudio a fondo: `afondo MONEDA`

Con unos 3 años de velas de 1h (26.000 velas, un minuto de descarga) da: estado y fichas,
tendencia diaria (EMA 20/50/200, RSI, ATR, cambios a 7, 30, 90 y 365 días) con aviso si el
RSI diario está por debajo de 30 o por encima de 70, niveles de giro en 4h, horas de más y
menos movimiento en hora de Madrid, y la regla con cuatro filtros decididos de antemano
(horas con Nueva York abierta, volumen, tendencia diaria, RSI diario extremo) y dos stops,
en tres periodos de un año. Un filtro solo se marca ✅ si mejora a la regla en los tres.

Lecciones ya aprendidas (BTC, 29/11/2023 a 27/11/2026):
- **83 días engañan.** Con 83 días la regla en BTC parecía perder (−0,10 R); con 3 años gana
  +0,12 R por operación, con 40 % de aciertos y positiva en los tres años, en línea con la
  prueba de referencia de TradingView (41 %, factor 1,20).
- **No cerrar por tiempo.** Las operaciones se miden hasta el stop o el objetivo (como el
  script), con un tope de 30 días. Cortarlas a las 48 h empeoraba mucho el resultado.
- El stop de 1,5 ATR que parecía mejor en 83 días no mejora en 3 años. Ningún filtro
  mejora a la regla en los tres años: por ahora, la regla se queda como está.

## Revisión continua

Cada semana conviene: pasar las pruebas (`python3 -m unittest discover -s tests`), lanzar
`estudiar` y comparar con la semana anterior, comprobar que Bitstamp sigue respondiendo y que
la alerta real más reciente coincide con lo que da `escanear --ahora`. Cualquier cambio de
código va en una rama con su petición de unión; el usuario decide si se une.

## Cómo presentar el resultado

1. Empieza por la tabla para iPhone: `Activo | Último cierre (hora) | Ahora | 🟢 COMPRA si |
   🔴 VENTA si | Caducidad`. «Ahora» es `🟢 COMPRA activada`, `🔴 VENTA activada`,
   `⏸️ ESPERAR` o `NO EVALUABLE`.
2. Toda señal, ficha y escenario dice **COMPRA, VENTA o ESPERAR** en la primera palabra.
3. Español sencillo, frases cortas. Horas de Madrid. Indica qué vela cerrada se ha usado.
4. Si falta un dato decisivo, **NO EVALUABLE** y qué falta. No se estima.
5. Distingue **ficha propuesta** (texto), **alerta configurada** (existe en TradingView,
   compruébalo con list-alerts) y **entrada simulada** (anotada en el registro).
6. Termina con: «Análisis y simulación. No se han enviado órdenes ni modificado alertas.»

## Límites de riesgo que comprueba `riesgo`

- Stop obligatorio y del lado correcto.
- Beneficio/riesgo de al menos 2 a 1 **por cada objetivo**.
- Riesgo máximo del 1 % del capital; 0,75 % en fin de semana (hora de Madrid).
- Máximo 3 posiciones abiertas y tope de pérdida diaria del 2 %.
- Sin apalancamiento: el importe no puede pasar del capital.

## Qué no hace

- No envía órdenes, no conecta con ningún exchange ni bróker, no pide claves.
- No crea, cambia ni borra alertas de TradingView: solo propone fichas.
- La simulación usa el pasado (unos 83 días de velas de 1h): no garantiza el futuro, y con
  pocas señales en la historia el resultado puede deberse a la suerte.
- Bitstamp es la referencia. Si el precio de Quantfury es muy distinto, pídelo y recalcula.

No es asesoramiento financiero. Solo análisis y simulación.
