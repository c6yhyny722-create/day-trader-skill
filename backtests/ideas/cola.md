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

## Lo descartado de la misma guía, y por qué

- Los 6 agentes (escáner, investigador, toro, oso, riesgo, backtest): ya los tenemos como `escanear`/`oportunidades`, `noticias`, `riesgo` (reglas en código, con pruebas), `fugas` y `validar` (costes, deslizamiento, fuera de muestra, comparación con comprar y mantener y con el azar).
- Controles de datos (precios mal formados, velas repetidas o que faltan): ya los hace `revisar_velas` y `normalizar`.
- BTCC: enlace de afiliado. No aporta nada al estudio; Rodrigo opera en Quantfury.
