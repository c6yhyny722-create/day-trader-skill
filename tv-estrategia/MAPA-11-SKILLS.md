# Las 11 skills, cuadradas con TradingView (acciones de EE. UU. y cripto)

El paquete de 11 skills que circula («Day Trader Skill», Jake Schincariol) es el que hay en
este repositorio. Está hecho para acciones de EE. UU., con datos gratuitos de Yahoo y hora
de Nueva York. Esta tabla dice cómo usar cada una con la cuenta de TradingView y qué
equivale en cripto. Solo análisis y simulación: ninguna fila envía órdenes.

| Skill | Acciones EE. UU. con TradingView | Cripto con TradingView | Herramientas TradingView |
| --- | --- | --- | --- |
| trader-scanner | Escáner de TradingView (mercado america) en lugar de los 5.900 gráficos de Yahoo; o velas 5m convertidas para `scan.py --offline` | Escáner de TradingView (mercado crypto), por volumen y cambio; luego `comprobar.py` en los candidatos | `mcp-tv-run-screener`, `mcp-tv-get-screener-columns` |
| trader-news | Noticias de TradingView por símbolo, además de los 8-K de la SEC | Noticias de TradingView por símbolo y calendario económico (IPC, Fed) | `mcp-tv-get-news`, `mcp-tv-get-news-story`, `mcp-tv-get-economic-calendar` |
| trader-entry | `entry.py --offline` con velas de TradingView convertidas por `tv_a_yahoo.py` (ORB de 15 min) | `comprobar.py`: 4h de contexto, vela de 1h cerrada, hora de Madrid, sin repetidos | `mcp-tv-get-ohlcv` |
| trader-exit | `exit.py --offline` con velas convertidas | Plan de `comprobar.py`: invalidación, R, zona de entrada y objetivo en R | `mcp-tv-get-ohlcv` |
| trader-timemachine | `timemachine.py --offline` con 60 días de velas 5m convertidas | Backtest de la estrategia Pine en TradingView, en dos periodos y frente a comprar y mantener | `mcp-tv-run-pine-backtest`, `mcp-tv-get-ohlcv` |
| trader-budget | Igual (acciones enteras) | Tamaño de `comprobar.py --capital --riesgo-pct` (unidades fraccionarias, sin apalancamiento) | ninguna |
| trader-risk | Igual | Mismos límites: pérdida máxima por operación, tope diario, sin apalancamiento salvo permiso | ninguna |
| trader-broker | **No se usa**: el usuario no quiere órdenes | **No se usa** | ninguna |
| trader-alerts | Alertas de precio en TradingView (fichas propuestas; se crean solo con permiso) | Igual, y alertas de indicador con `alert()` (patrón de `pine/10-cripto-1h`) que crea el usuario | `mcp-tv-create-alert`, `mcp-tv-list-alerts`, `mcp-tv-get-alerts-log` |
| trader-analyst | Igual (SEC EDGAR); datos de símbolo de TradingView como apoyo | No aplica (no hay 10-Q); se sustituye por noticias y calendario | `mcp-tv-get-symbol-data` |
| trader-pelosi | Igual | No aplica | ninguna |

## Sin TradingView: `trader-cripto`

Cuando el cupo de TradingView se agota (o en tareas programadas sin conector), la skill
`trader-cripto` hace lo mismo con velas públicas de Bitstamp: escáner de las 10 monedas,
señal con zona e invalidación, 10.000 recorridos, tamaño, riesgo, fichas y noticias.

## Cómo pasar velas de TradingView a las skills de acciones

```bash
# 1. Claude guarda la respuesta de mcp-tv-get-ohlcv (NASDAQ:TSLA, 5m) en tsla5m.json
python3 tv-estrategia/tv_a_yahoo.py tsla5m.json --simbolo NASDAQ:TSLA --intervalo 5m -o datos/TSLA.json
python3 trader-entry/entry.py check TSLA --offline datos/ --now "2026-10-19 10:15"
```

Probado: con las velas de TSLA del 19-10-2026 convertidas, `trader-entry` da el mismo disparo
(10:15 AM a 364,18) que con los datos de Yahoo.

## Cripto: la comprobación de cada hora

```bash
# Claude guarda 1h y 4h de mcp-tv-get-ohlcv para cada moneda
python3 tv-estrategia/comprobar.py tv-estrategia/reglas.example.json \
    --datos BITSTAMP:BTCUSD@1h=btc1h.json --datos BITSTAMP:BTCUSD@4h=btc4h.json \
    --estado estado-avisos.json --capital 1000 --riesgo-pct 1
```

## Límites que conviene saber

- Las skills de acciones siguen usando el calendario de la NYSE (festivos, cierres a la 1:00 p. m.).
- El conector de TradingView crea alertas de precio, no de indicador.
- El cupo diario de llamadas a TradingView es limitado: un escáner y unas pocas velas por revisión.
- Los paquetes de cripto que circulan (Claude-Crypto-Skill, crypto-trading-skills,
  ultimate-claude-code-trading-skills) conectan exchanges con claves para operar. Aquí no se
  usa esa parte; de ellos se toma la idea de una sola librería para análisis, backtest y avisos.
