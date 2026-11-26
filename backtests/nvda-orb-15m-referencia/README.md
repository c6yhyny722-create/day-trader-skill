# NVDA ORB 15 min · referencia

Prueba histórica en simulación. No se conectó ningún bróker ni se envió ninguna orden.
Es una prueba de una regla sobre datos pasados, no una recomendación.

## Datos

- Fuente: TradingView, `NASDAQ:NVDA`, velas de 5 minutos, solo sesión regular (9:30–16:00 ET),
  precios ajustados solo por splits. Descargadas el 26-nov-2026.
- Calendario de sesiones: NYSE, con los festivos y cierres anticipados de `trader-scanner/scan.py`.
- Una sesión cuenta como completa si tiene todas sus velas de 5 minutos desde las 9:30 hasta el cierre.
- Velas originales en `datos/`.

## Periodos

| Periodo | Sesiones | Uso |
|---|---|---|
| 2026-09-02 → 2026-11-25 | 60 de 60 completas | **Referencia** |
| 2026-06-08 → 2026-09-01 | 60 de 60 completas | Contraste: las 60 sesiones anteriores, sin fechas en común |

## Regla (igual en ambos periodos, sin ajustar)

1. Rango de apertura: velas de 9:30, 9:35 y 9:40 ET (los primeros 15 minutos). Máximo = el más alto
   de los máximos; mínimo = el más bajo de los mínimos.
2. Señal: la primera vela de 5 minutos que **cierra** por encima del máximo del rango (estrictamente mayor).
3. Entrada: precio de apertura de la vela siguiente.
4. Stop: punto medio del rango, redondeado hacia abajo al céntimo.
5. Objetivo: cierre de la vela de señal + 2 × (cierre de la vela de señal − stop).
6. Salida, lo primero que ocurra:
   - stop tocado: el mínimo de la vela es menor o igual que el stop; se sale en el stop;
   - objetivo tocado: el máximo de la vela es mayor o igual que el objetivo; se sale en el objetivo;
   - si una vela abre ya más allá del stop o del objetivo, se sale en esa apertura (no ocurrió);
   - por hora: apertura de la vela de 15:55 ET, o 5 minutos antes del cierre en sesiones reducidas
     (no hubo ninguna en estos periodos).
7. Si una vela toca el stop y el objetivo, el resultado es indeterminado y no cuenta en la media
   (no ocurrió).
8. Una operación por sesión como máximo. Solo largos.

## Costes

- Deslizamiento: 0,02 $ por acción en la entrada y otros 0,02 $ en la salida (0,04 $ por operación).
- Comisión: 0 $.
- Tasas SEC/FINRA en la venta: menos de 0,001 $ por acción; no se incluyen.

## Resultados (por acción, después de costes)

| | 2026-09-02 → 11-25 (referencia) | 2026-06-08 → 09-01 (contraste) |
|---|---|---|
| Sesiones evaluadas | 60 | 60 |
| Operaciones | 31 | 30 |
| Salidas por objetivo | 2 | 5 |
| Salidas por stop | 15 | 12 |
| Salidas por hora (15:55 ET) | 14 (8 con ganancia) | 13 (9 con ganancia) |
| Indeterminadas | 0 | 0 |
| Operaciones con ganancia | 10 | 14 |
| Resultado medio neto | **−0,53 $** (−0,28 R) | **+0,14 $** (+0,05 R) |
| Suma neta | −16,32 $ | +4,25 $ |

## Archivos

- `operaciones-2026-09-02_2026-11-25.csv`: las 31 operaciones del periodo de referencia.
- `operaciones-2026-06-08_2026-09-01.csv`: las 30 operaciones del periodo de contraste.
- `resultado-*.json`: el detalle de cada sesión, incluidas las que no tuvieron señal.
- `bt_orb.py`: el script. Para reproducir los resultados, descomprime primero el archivo de velas:
  `python3 bt_orb.py VELAS.json ../../trader-scanner/scan.py SALIDA.json [FECHA_FINAL]`.
  Sin `FECHA_FINAL`, toma las 60 sesiones hasta el 2026-11-25.

Columnas de los CSV: las horas son de apertura de la vela salvo `senal_confirmada_*` y `entrada_*`,
que son el cierre de la vela de señal (es decir, el momento de la entrada). `salida_vela_ET` es la
apertura de la vela en la que se tocó el nivel. Horas de Madrid calculadas con los cambios de horario
de cada país (del 26 al 30 de octubre la diferencia fue de 5 horas).
