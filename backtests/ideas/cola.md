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
| 28/11/2026 | Filtro de *funding* (tasa de financiación de los perpetuos): no comprar con *funding* muy alto, no vender con *funding* muy negativo | Lista «awesome-mcp-servers», sección Finanzas (foto «20 repos de Claude») | Sin probar: Binance, Bybit y OKX no responden desde este entorno. Hace falta su historial de 3 años | ⏳ pendiente |
| 28/11/2026 | Filtro de interés abierto y liquidaciones: ¿la ruptura sale mejor si sube el interés abierto o tras una ola de liquidaciones? | idem | Sin probar, por lo mismo. Ojo: el historial de liquidaciones gratis suele ser corto | ⏳ pendiente |

## Lo descartado de la misma guía, y por qué

- Los 6 agentes (escáner, investigador, toro, oso, riesgo, backtest): ya los tenemos como `escanear`/`oportunidades`, `noticias`, `riesgo` (reglas en código, con pruebas), `fugas` y `validar` (costes, deslizamiento, fuera de muestra, comparación con comprar y mantener y con el azar).
- Controles de datos (precios mal formados, velas repetidas o que faltan): ya los hace `revisar_velas` y `normalizar`.
- BTCC: enlace de afiliado. No aporta nada al estudio; Rodrigo opera en Quantfury.

## Foto «20 repos de GitHub de Claude» (28/11/2026)

Revisados los 20. Casi todos son programas para programar (Cline, Aider, Continue, Open Interpreter,
OpenDevin, Claude Engineer, Task Master, Swarm, SuperClaude, router de modelos, instaladores de MCP).
Hacen lo mismo que Claude Code, que ya usamos. No mejoran las señales.

- Útil: «awesome-mcp-servers», sección Finanzas. Da la idea de probar *funding*, interés abierto y
  liquidaciones (arriba, ⏳). No se instala ningún servidor de terceros: los datos se bajarían
  directamente de las API públicas, como ya hacemos con Bitstamp.
- «awesome-claude-code»: sin nada de trading. Los ganchos útiles (pruebas tras cada cambio,
  confirmar órdenes) ya están en `.claude/settings.json`.
- Descartados los servidores con órdenes reales o pago por consulta (x402): no encajan con «solo simulación».
