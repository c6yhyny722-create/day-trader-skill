# 10 criptomonedas · 1h · ruptura de 20 velas con contexto de 4h

Prueba histórica e indicador en simulación (2026-11-26). No se conectó ningún bróker ni se envió ninguna orden.
Las reglas se fijaron antes de la prueba: ver `REGLAS.md`.

## Monedas elegidas (Bitstamp, par contra USD)

Ranking por capitalización del screener de TradingView (`market_cap_calc`) a las 13:00 UTC del 2026-11-26.
Liquidez medida con las velas de 1h de Bitstamp de los últimos 30 días.

| # | Símbolo exacto | Volumen diario medio (30 d) | Velas de 1h (30 d) |
|---|---|---|---|
| 1 | `BITSTAMP:BTCUSD` | 118,2 M$ | 719/719 |
| 2 | `BITSTAMP:ETHUSD` | 24,1 M$ | 719/719 |
| 3 | `BITSTAMP:XRPUSD` | 16,2 M$ | 719/719 |
| 4 | `BITSTAMP:SOLUSD` | 15,3 M$ | 719/719 |
| 5 | `BITSTAMP:HYPEUSD` | 3,6 M$ | 719/719 |
| 6 | `BITSTAMP:ZECUSD` | 3,5 M$ | 715/719 |
| 7 | `BITSTAMP:DOGEUSD` | 5,8 M$ | 719/719 |
| 8 | `BITSTAMP:LINKUSD` | 0,74 M$ | 715/719 |
| 9 | `BITSTAMP:ADAUSD` | 1,6 M$ | 719/719 |
| 10 | `BITSTAMP:XLMUSD` | 1,3 M$ | 719/719 |

Descartadas:
- Monedas estables: USDT, USDC, USDS, USDe, DAI, USDT0 y RWUSD.
- Versiones duplicadas de otro activo: stETH, wstETH, WBTC, WBETH, cbBTC y WETH.
- Sin liquidez suficiente en Bitstamp:
  - BNB: unos 0,14 M$ al día, según el promedio de 10 días de TradingView.
  - TRX: 0,02 M$ al día y faltan 425 de 719 velas.
- Sin par en Bitstamp: XMR, LEO y WBT.
- Siguientes de la lista: NEAR (2,8 M$) sería la primera suplente. BCH (0,44 M$) no llega al mínimo de liquidez.

## Resultados por moneda (2026-05-02 → 2026-11-26, velas de 1h, después de costes)

Costes: 0,10 % por lado, 0,20 % por operación. «En zona» son las operaciones cuyo cierre de señal estaba dentro de la zona de entrada.

| Moneda | Alcista: ops · obj/stop/48h · media | Bajista: ops · obj/stop/48h · media |
|---|---|---|
| BTCUSD | 43 · 9/23/11 · −0,20 % | 51 · 8/21/22 · +0,01 % |
| ETHUSD | 36 · 10/17/9 · −0,14 % | 44 · 6/12/26 · +0,32 % |
| XRPUSD | 33 · 7/13/12 (1 ind.) · −0,64 % | 57 · 16/20/21 · +0,64 % |
| SOLUSD | 38 · 9/13/16 · +0,55 % | 47 · 11/12/24 · +0,57 % |
| HYPEUSD | 51 · 10/26/15 · −0,12 % | 50 · 8/24/17 (1 abierta) · −0,39 % |
| ZECUSD* | 37 · 6/14/16 (1 ind.) · +0,35 % | 29 · 7/12/10 · +0,47 % |
| DOGEUSD | 28 · 7/11/10 · −0,19 % | 54 · 14/17/23 · +0,61 % |
| LINKUSD | 45 · 7/24/13 (1 abierta) · −0,38 % | 49 · 13/21/15 · +0,18 % |
| ADAUSD | 31 · 7/13/11 · +0,83 % | 58 · 11/21/26 · +0,52 % |
| XLMUSD | 34 · 6/19/9 · +0,34 % | 61 · 12/25/24 · +0,22 % |
| **Total** | **376 · 78/173/122 · +0,02 %** (en zona: 366, +0,01 %) | **500 · 106/185/208 · +0,31 %** (en zona: 489, +0,38 %) |

\* ZECUSD empieza el 2026-05-23 y tiene 85 huecos de una o más horas en todo el periodo.
HYPEUSD y LINKUSD tienen 1 y 8 huecos.

Fuera de zona solo quedaron 10 señales alcistas y 11 bajistas: con 0,5R, la zona casi no filtra.

## Comprobaciones

- **Pine = Python.** El indicador se ejecutó en TradingView sobre `BITSTAMP:BTCUSD` 1h, entre la vela que
  abre el 2026-10-15 22:00 UTC y la que cierra el 2026-11-26 12:00 UTC (999 velas cerradas).
  Para cada moneda se comparó el número de señales alcistas, el de bajistas y una suma de control
  (hora × tipo de señal × dentro o fuera de zona): los 30 valores coinciden con la prueba en Python.
  El bloque usado está en `comprobacion_bloque.pine`.
- **Señales simultáneas.** En cada vela, el número de líneas del aviso coincide con el número de señales,
  también en las 7 horas en que las 10 monedas dieron señal a la vez, como el 25-11-2026 a las 15:00 de Madrid.
  En todo el periodo hubo 1.290 horas con alguna señal, 571 de ellas con dos monedas o más.
  Ejemplo reconstruido en `ejemplo_aviso.txt`.
- **BTC:** 43 señales alcistas frente a las 42 de la prueba anterior. Aquí la primera vela de 4h incompleta
  entra en la EMA, igual que en TradingView. En la prueba anterior se descartaba.

## Archivos

- `indicador_10cripto.pine`: el indicador (Pine v6), con la lista editable de monedas, un único aviso por cierre de 1h y una tabla con cada símbolo, su exchange y su estado.
- `REGLAS.md`: reglas y criterios de selección, fijados antes de la prueba.
- `bt_multi.py`: la prueba. Uso: `python3 bt_multi.py CARPETA_VELAS SALIDA EPOCH_AHORA`.
- `operaciones.csv`, `resumen_por_moneda.csv` y `senales_todas.json`: los resultados.
- `datos/`: las velas originales de TradingView.

## Activar el aviso en el iPhone

1. En el iPhone, instala la app de TradingView e inicia sesión con tu cuenta.
   En Ajustes → Notificaciones → TradingView, permite las notificaciones.
2. En tradingview.com, desde el ordenador, abre un gráfico de `BITSTAMP:BTCUSD` en **1 hora**.
3. Abre el **Editor de Pine**, pega `indicador_10cripto.pine`, pulsa **Guardar** y después **Añadir al gráfico**.
   Revisa la lista de monedas en los ajustes del indicador antes del paso 4.
4. Crea la alerta con el icono del reloj o con Alt + A:
   - Condición: «10 cripto 1h · ruptura 20 + contexto 4h» → **«Cualquier llamada a la función alert()»**.
   - Vencimiento: la fecha que quieras; depende de tu plan de TradingView.
   - Notificaciones: marca **«Notificar en la app»**.
   - Nombre: por ejemplo, «10 cripto 1h · simulación». Pulsa **Crear**.
5. La alerta se calcula en los servidores de TradingView, así que el ordenador puede estar apagado.
   El texto completo de cada aviso queda en el registro de alertas de la app.
6. Si cambias la lista de monedas o un parámetro, borra la alerta y créala de nuevo:
   la alerta guarda los ajustes que tenía el indicador cuando la creaste.
