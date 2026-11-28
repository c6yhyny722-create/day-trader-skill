# Cola de ideas para mejorar la regla

Cada idea: qué es, de dónde sale, fecha, resultado y estado. La llena la búsqueda nocturna;
la revisión del domingo instala solo las ✅ que cumplen todas las garantías.
Monedas operables: BTC, ETH, SOL, DOGE y XLM. Métrica: R medio en el mundo real (con fugas).

| Fecha | Idea | Fuente | Resultado (mundo real, 5 monedas, 3 años) | Estado |
|---|---|---|---|---|
| 28/11/2026 | Margen de error del R medio y comparación con entrar al azar | Jakeschincariol/day-trader-skill, PR 53 | Instalado en `validar` (no cambia señales) | ✅ instalado |
| 28/11/2026 | Diario de operaciones reales con deslizamiento | Jakeschincariol/day-trader-skill, PR 78 | Instalado como `diario` (no cambia señales) | ✅ instalado |
| 28/11/2026 | «Analista bajista»: no operar una señal con pegas (stop > 3 ATR, RSI 1h agotado, volumen < 50 % de su media, 4h a menos del 0,2 % de su EMA 50, fin de semana) | Guía «Claude Trading Desk» de 6 agentes (vídeo/carrusel de Prosper AI) | Ninguna pega predice pérdidas: todas siguen ganando. Stop lejos +0,10 R (sin la pega +0,19); RSI agotado +0,14 (sin +0,11); volumen bajo +0,07 (81 ops); 4h casi gira +0,12 (55 ops); fin de semana +0,18 (sin +0,11). Ninguna es peor en los 3 periodos. 1.167 operaciones. Script: `pegas_2026-11-28.py` | ❌ descartada como filtro |
| 28/11/2026 | Vigilar «stop > 3 ATR»: peor en 2 de 3 periodos (P1 +0,09 frente a +0,17; P3 +0,10 frente a +0,29), pero sigue ganando | idem | Pendiente de ver si se repite en las próximas semanas | 👀 en observación |
| 28/11/2026 | *Funding* a favor de la multitud (percentil ≥ 80 al comprar, ≤ 20 al vender) | Lista «awesome-mcp-servers», sección Finanzas (foto «20 repos de Claude») | +0,06 frente a +0,14, pero solo peor en 2 de 3 periodos (P3 +0,15 frente a +0,13). 332 ops | ❌ descartada |
| 28/11/2026 | **No operar si la multitud ya está del mismo lado** (ratio largos/cortos de Binance en el percentil ≥ 80 de 30 días al comprar; ≤ 20 al vender) | idem | **−0,11 frente a +0,15**. Peor en los 3 periodos (−0,21, −0,36, −0,23) y con los umbrales vecinos 75 y 85. 117 ops | ⭐ candidata, semana 1 de 2; aguanta costes al doble |
| 28/11/2026 | No operar tras una «barrida» (el interés abierto cae más de un 1,5 % en la última hora; aproxima liquidaciones) | idem | −0,04 frente a +0,16, peor en P1 y P2, igual en P3. Con umbral −2 % es mejor en P3: no es firme. 208 ops | 👀 en observación |
| 28/11/2026 | Operar solo si los compradores agresivos van a favor (ratio comprador/vendedor de la última hora > 1,05 al comprar, < 0,95 al vender) | idem | +0,18 frente a +0,05, mejor en los 3 periodos y con todos los umbrales vecinos. IC +0,07 a +0,29. Pero quita casi la mitad de las operaciones y el R total baja (117 frente a 141) | 👀 en observación |
| 28/11/2026 | Interés abierto 24 h (sube o baja más de un 3 %) | idem | Sin efecto claro: cambia de signo según el periodo | ❌ descartada |

## Lo descartado de la misma guía, y por qué

- Los 6 agentes (escáner, investigador, toro, oso, riesgo, backtest): ya los tenemos como `escanear`/`oportunidades`, `noticias`, `riesgo` (reglas en código, con pruebas), `fugas` y `validar` (costes, deslizamiento, fuera de muestra, comparación con comprar y mantener y con el azar).
- Controles de datos (precios mal formados, velas repetidas o que faltan): ya los hace `revisar_velas` y `normalizar`.
- BTCC: enlace de afiliado. No aporta nada al estudio; Rodrigo opera en Quantfury.

## Foto «20 repos de GitHub de Claude» (28/11/2026)

Revisados los 20. Casi todos son programas para programar (Cline, Aider, Continue, Open Interpreter,
OpenDevin, Claude Engineer, Task Master, Swarm, SuperClaude, router de modelos, instaladores de MCP).
Hacen lo mismo que Claude Code, que ya usamos. No mejoran las señales.

- Útil: «awesome-mcp-servers», sección Finanzas. Da la idea de probar *funding*, interés abierto y
  liquidaciones (arriba). No se instala ningún servidor de terceros: los datos se bajarían
  directamente de las API públicas, como ya hacemos con Bitstamp.
- «awesome-claude-code»: sin nada de trading. Los ganchos útiles (pruebas tras cada cambio,
  confirmar órdenes) ya están en `.claude/settings.json`.
- Descartados los servidores con órdenes reales o pago por consulta (x402): no encajan con «solo simulación».

### Prueba del 28/11/2026 (`funding_oi_2026-11-28.py`)

- Datos: archivo público de Binance (`data.binance.vision`): *funding* y métricas cada 5 min, de oct-2023 a nov-2026.
  Binance y Bybit en directo bloquean este servidor por país; OKX solo guarda 3 meses.
- 1.167 operaciones reales (fugas, entrada en la vela siguiente). Sin filtro: +0,12 R.
- Quitando «multitud del mismo lado» y «barrida»: +0,19 R con 856 operaciones (R total +160 frente a +141).
- **Costes al doble** (28/11/2026, `... x2`): la regla sola baja a +0,08 R (IC −0,01 a +0,16).
  Sin «multitud igual»: +0,10 R (IC +0,02 a +0,19); sin «multitud igual» ni «barrida»: +0,14 R
  (IC +0,04 a +0,23). «Multitud igual» sigue peor en los 3 periodos (−0,13, −0,25, −0,10). ✅ Aguanta.
- Caída máxima (suma de R en fila, 5 monedas): normal −23,6 R sin filtro, −21,2 sin «multitud igual»,
  −23,8 con los dos filtros; al doble de costes −28,3, −25,0 y −26,7. El filtro no la empeora.
- Falta antes de instalar: ✅ otra semana y **una fuente en directo**:
  el archivo de Binance se publica con un día de retraso. Opciones: el mismo ratio de OKX
  (`/api/v5/rubik/stat/contracts/long-short-account-ratio`, distinto mercado: habría que reprobar)
  o que Rodrigo lo mire en TradingView/Binance antes de entrar.
- Para repetir: bajar a una carpeta `f/` los `fundingRate` mensuales y a `m/` los `metrics` diarios
  de BTC, ETH, SOL, DOGE y XLM (USDT, futuros `um`), y ejecutar el script con esa carpeta.
