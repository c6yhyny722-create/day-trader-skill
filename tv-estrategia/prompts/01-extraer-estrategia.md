# Extraer la estrategia de una transcripción

Adaptado de `prompts/01-extract-strategy.md` (claude-tradingview-mcp-trading). Pega la
transcripción o las capturas debajo de la línea y ejecútalo en Claude Code.

---

Abajo está la transcripción (o capturas) de un vídeo de trading. Extrae la estrategia en
forma estructurada. Responde con precisión y **no inventes nada que no esté en la fuente**:
lo que no se diga es `NO DICHO`. Cita el minuto de la transcripción de cada regla.

1. **Activo, exchange y temporalidades.** ¿Cuál marca el contexto y cuál la entrada?
2. **Indicadores.** Cada uno con sus parámetros (si se dicen) y para qué lo usa.
3. **Entrada.** Qué tiene que cumplirse, por separado para largos y cortos. ¿Al cierre
   de la vela o durante la vela?
4. **Cuándo no entrar.** Filtros y señales de alarma que menciona.
5. **Riesgo.** Stop, objetivo, salida por tiempo, tamaño de posición.
6. **Resultado que declara.** Rendimiento, periodo, nº de operaciones, drawdown, comisiones.
   Si el título y el contenido no coinciden, dilo.
7. **Huecos.** Lista de lo que falta para poder programarla sin suponer.

Después escribe `reglas.json` con esta estructura (la de `tv-estrategia/reglas.example.json`):

```json
{
  "estrategia": "nombre",
  "fuente": "autor, título del vídeo, fecha",
  "simbolos": ["EXCHANGE:TICKER"],
  "temporalidad_contexto": "4h",
  "temporalidad_confirmacion": "1h",
  "retraso_maximo_horas": 24,
  "senales": {
    "alcista": [{"a": "close", "op": ">", "b": "ema(50)", "texto": "regla en palabras (min 12:40)"}],
    "bajista": []
  },
  "invalidacion": {"alcista": "...", "bajista": "..."},
  "riesgo": ["..."],
  "no_dicho": ["..."],
  "resultado_declarado": "...",
  "notas": ""
}
```

Expresiones válidas en `a` y `b`: `close`, `open`, `high`, `low`, `volume`, un número,
`ema(N)`, `sma(N)`, `rsi(N)`, `atr(N)`, `highest(N)`, `lowest(N)`, con `[K]` para velas
anteriores y `@4h` para otra temporalidad. Operadores: `>`, `<`, `>=`, `<=`,
`cruza_arriba`, `cruza_abajo`. Si una regla no se puede expresar así (patrones de velas,
soportes dibujados a mano, Fibonacci), déjala en `notas` como texto y márcala para Pine.

No escribas código hasta que el usuario confirme la ficha.

---

[PEGA LA TRANSCRIPCIÓN O LAS CAPTURAS DEBAJO DE ESTA LÍNEA]
