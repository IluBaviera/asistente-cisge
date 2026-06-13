# REVISIÓN TÉCNICA — asistente-cisge

**Fecha:** 2026-06-12
**Alcance:** `app/main.py`, `app/agente.py`, `app/motor.py`, `app/db.py`, `app/tools.py`, infraestructura del repo.
**Regla:** esta revisión NO modifica código — solo analiza y propone.

---

## 1. ARQUITECTURA GENERAL

### Lo que funciona bien

- **Pipeline de etapas E1→E4 con costo creciente**: código exacto (gratis) → prefijo (gratis) → GPT parser (1 llamada) → GPT conversacional con tools (N llamadas). Diseño correcto: la mayoría de consultas se resuelven sin tocar OpenAI.
- **Separación OCR/parser** en el pipeline de imágenes: permite cambiar el modelo de visión sin tocar el parser (decisión documentada en CONTEXT.md).
- **Correctores deterministas post-GPT** (`_corregir_medidas_ocr`, `_corregir_adaptador_ocr`, `_enriquecer_tipo_ferrula`): patrón sano — el código Python corrige los sesgos conocidos del modelo en lugar de pelear con el prompt.
- **Caché del catálogo en memoria con refresh** cada 10 min y reintento agresivo (30 s) si arrancó vacío.
- **Webhook responde 200 inmediato** y procesa en background (`asyncio.create_task`) — correcto para los timeouts de Meta.

### Debilidades estructurales

| # | Problema | Detalle |
|---|---|---|
| A1 | **Pipeline duplicado completo** | `motor.consultar()` (E1+E2+E3+saludos, ~220 líneas) y `agente._agente_cisge_impl()` (E1+E2+parser+E3+E4) implementan el mismo flujo dos veces con divergencias sutiles. `consultar()` solo lo usan `/consultar` (REST) y `cotizar_multiple` re-implementa una tercera variante del mismo flujo. Tres copias de la lógica E1/E2/E3 = tres lugares donde arreglar cada bug. |
| A2 | **Trabajo de red en import del módulo** | `motor.py` líneas 411-418: al importar el módulo se hace `httpx.get` sincrónico con 3 reintentos (hasta ~50 s bloqueado). Esto hace imposible importar `motor` en tests sin red, alarga el cold start de Render, y acopla el orden de imports al estado de la API. |
| A3 | **Referencias stale entre módulos** | `agente.py` línea 21-24 importa `df as motor_df` y `_aliases_marcas` **por valor de referencia**. Cuando `refresh_stock_loop()` hace `df = _build_df_from_api(data)` (rebinding del global), `motor_df` en agente.py sigue apuntando al DataFrame **del arranque para siempre**. Afecta: filtro de marca en E2 (línea 439), `_validar_subfamilias`, `_grupos_disponibles` y el post-proceso de aliases de marcas (líneas 482-487, que usa los aliases del arranque aunque se refresquen cada 10 min). Las funciones de búsqueda (`buscar_por_codigo`, etc.) NO están afectadas porque viven en motor.py y leen su propio global. |
| A4 | **Vocabulario de prompts congelado al arranque** | `_tipos_manguera_str` y `_tipos_otros_str` se calculan una vez al importar agente.py. Si se agrega un grupo nuevo en Navasoft (ej: el caso real "UNION HEMBRA NPT"), el prompt no lo ve hasta el siguiente deploy, aunque el catálogo sí se refresque. |
| A5 | **Estado en memoria sin persistencia** | `mensajes_procesados` (dedup) y `log_consultas` se pierden en cada restart de Render. Aceptable para la fase actual, pero documentarlo. |

---

## 2. BUGS Y RIESGOS

### B1 — CRÍTICO: `NameError` latente en `buscar_por_tipo_medida_marca` (motor.py:676)

`tipo_up` se asigna **solo dentro** del bloque `if tipo:` (líneas 611 y 625), pero la línea 676 lo usa fuera de ese bloque:

```python
if tipo_up == "MANG SILICONA":   # línea 676 — NameError si tipo es None
```

**Verificado por análisis AST**: asignaciones en [611, 625], uso en 676 a nivel de función.
Cualquier búsqueda **sin tipo** (solo marca: "QF", solo medida, solo subfamilia) lanza `NameError`. En el pipeline de agente el `try/except` global lo enmascara como "problemas técnicos"; en `/consultar` y en `motor.consultar()` produce un 500. También rompe `_tipo_existe_en_catalogo("")` → no, ese pasa tipo; pero cualquier llamada `buscar_por_tipo_medida_marca(marca=...)` sin tipo crashea.

**Fix:** inicializar `tipo_up = ""` antes del `if tipo:`. Esfuerzo: 1 línea.

### B2 — ALTO: caracteres invisibles literales en el fix de encoding (motor.py:316)

```python
"grupo": str(p.get("grupo", "")).replace(" ", " ").replace("�", "°").strip().upper(),
```

El primer `replace` contiene un **NBSP literal (U+00A0)** y el segundo un **U+FFFD literal** — invisibles en el editor. Este es el fix que resuelve TODOS los matches de adaptadores angulares. Riesgo: cualquier formateador, editor con "normalize whitespace", o copy-paste lo rompe **silenciosamente** y el bug del catálogo regresa sin pista alguna. Verificado: al intentar imprimir la línea, el propio Python falla con `UnicodeEncodeError ... '�'`.

**Fix:** usar escapes explícitos `.replace("\xa0", " ").replace("�", "°")` + comentario. Comportamiento idéntico, robustez total. Esfuerzo: 1 línea.

### B3 — ALTO: regex de ángulo sin anclas en `_corregir_adaptador_ocr` (agente.py:183)

```python
ang = re.search(r'\(?(90|45)°?\)?', linea)
```

Sin word boundaries, matchea "90" o "45" **en cualquier parte**: `"= 90 und"` (cantidad 90 → ángulo 90), `"090-06-06"` (código de catálogo → ángulo 90), `"1990"`, `"45 mts"`. Como esta corrección solo corre cuando GPT no extrajo ángulo, el daño es acotado pero real: un pedido de 90 unidades de adaptador recto se convertiría en adaptador 90°.

**Fix:** exigir paréntesis o símbolo de grado o boundary: `r'(?:\((90|45)°?\)|(?<![\d-])(90|45)°)'`. Necesita prueba con las listas reales de los vendedores. **[RESUELTO — commit ecb475d, Fase 2]**

### B12 — ALTO (hallazgo nuevo, 2026-06-13): normalización MACHO-primero solo cubría ESPIGA en `_corregir_adaptador_ocr`

La reconstrucción de tipo en forma canónica MACHO-primero estaba encerrada en `if tipo_up.startswith("ESPIGA")`. Cuando GPT ya clasificaba la línea como ADAP pero con el género en el orden del texto (ej: "Ho. JIC 12 - M. JIC 12" → `ADAP HEMBRA JIC X MACHO JIC`), el catálogo usa MACHO-primero, ese grupo no existía, y `_tipo_existe_en_catalogo` devolvía False → "Producto no existe en el catálogo" para un producto que sí está. No detectado en la revisión estática original; surgió al rastrear el flujo de una línea concreta en producción.

**Fix:** ampliar la condición de la Corrección 1 a `startswith("ESPIGA") or startswith("ADAP")`. La reconstrucción es idempotente sobre tipos ya correctos. **[RESUELTO — commit f2aa777, Fase 2]**

### B4 — MEDIO: tasks de asyncio sin referencia (main.py:103, 34-35)

```python
asyncio.create_task(_procesar_mensaje(data))
```

Documentado en la stdlib: el event loop guarda solo una referencia débil; un task sin referencia fuerte **puede ser recolectado por GC a mitad de ejecución**. Es raro pero no teórico — el síntoma sería "un mensaje de WhatsApp ocasionalmente nunca obtiene respuesta", indistinguible de cualquier otro fallo. Aplica también a los dos tasks del startup.

**Fix:** set global `_tasks` con `task.add_done_callback(_tasks.discard)`. Esfuerzo: 5 líneas.

### B5 — MEDIO: llamadas HTTP sincrónicas bloquean el event loop

- `db.py`: `cargar_historial`/`guardar_mensajes` usan `httpx.post` **sincrónico** con timeout 5 s, llamados desde código async (`agente_cisge`, `_gpt_conversacional`). Cada guardado puede congelar el servidor entero hasta 5 s — ningún otro mensaje de WhatsApp se procesa mientras tanto.
- `tools.py`: `tool_ver_stock` (httpx sync, 5 s) y `tool_buscar_producto` (pandas pesado) corren dentro del loop async de `_llamar_gpt`.

**Fix:** `httpx.AsyncClient` en db.py, o envolver en `asyncio.to_thread(...)`. Esfuerzo: mediano (tocar firmas).

### B6 — MEDIO: dedup de mensajes se vacía de golpe (main.py:124-125)

```python
if len(mensajes_procesados) > MAX_IDS:
    mensajes_procesados.clear()
```

Al llegar a 1000 IDs se borra TODO, incluyendo los más recientes. Si Meta reintenta un mensaje justo después del clear, se procesa (y cobra GPT) dos veces y el vendedor recibe respuesta duplicada. **Fix:** `collections.OrderedDict` como LRU o `deque` paralelo. Esfuerzo: pequeño.

### B7 — BAJO: `log_consultas` crece sin límite (motor.py:21)

Se appendea en cada consulta y nunca se trunca → fuga de memoria lenta en un servicio que (por el keep-alive) nunca duerme. **Fix:** `collections.deque(maxlen=500)`. 1 línea.

### B8 — BAJO: `verificar_webhook` puede lanzar excepción (main.py:97)

`int(params["hub.challenge"])` → `KeyError`/`ValueError` con query malformada → 500. Cosmético (solo afecta la verificación de Meta), pero trivial de blindar.

### B9 — BAJO: patrón `'resultados' in locals()` (motor.py:1329)

Funciona pero es frágil: cualquier refactor que renombre la variable lo rompe en silencio (la condición se vuelve `False` y cae a E4 en vez de dar el mensaje de marca). Inicializar `resultados = pd.DataFrame()` arriba.

### B10 — BAJO: doble búsqueda por ítem en pipeline de imagen (agente.py:854-855)

```python
if _buscar_con_parsed(parsed, imagen_cantidad=cantidad) or parsed.get("codigo"):
    fila_motor = _buscar_fila_imagen(parsed, cantidad)
```

Cada ítem ejecuta el filtrado pandas completo **dos veces** (una para saber si hay resultado, otra para elegir fila). Además de duplicar latencia, son dos implementaciones que pueden divergir (ya tienen lógica de colapso de medidas copiada-pegada en ambas). Riesgo de inconsistencia: el primero encuentra y el segundo no → fila `None` con nota equivocada.

### B11 — INFRAESTRUCTURA: `runtime.txt` vacío y dependencias sin pin

- `runtime.txt` tiene **0 bytes** — la versión de Python en Render no está fijada; un upgrade de plataforma puede cambiar el runtime sin aviso (localmente ya corre 3.14).
- `requirements.txt` deja `httpx`, `openai`, `openpyxl`, `python-dotenv` **sin versión**. Un deploy cualquiera puede traer un major de `openai` con breaking changes y tumbar producción sin que haya cambiado el código.
- `app/__pycache__/*.pyc` están **commiteados** en git (aparecen como modified en cada `git status` y ensucian los diffs) a pesar de que `.gitignore` los excluye (entraron antes).
- Archivos basura en raíz: `1`, `12`, `test_output.txt`, `test_dg.py` (7 líneas), `test_multi_marca.py` sin trackear.

---

## 3. SEGURIDAD

### S1 — ALTO: webhook sin verificación de firma

`POST /webhook` acepta **cualquier JSON** de cualquier origen. Meta firma cada payload con `X-Hub-Signature-256` (HMAC con el App Secret) y el código no la valida. Hoy la única defensa es la whitelist de números — pero el número viene **dentro del payload atacante-controlado**: cualquiera que conozca la URL (es adivinable: `asistente-cisge.onrender.com`) y un número de la whitelist puede inyectar mensajes falsos, gastar tokens de OpenAI, y contaminar el historial de un vendedor real.

**Fix:** validar HMAC del header con `META_APP_SECRET` antes de procesar. Esfuerzo: pequeño (15 líneas + 1 env var).

### S2 — ALTO: endpoints internos públicos sin autenticación

- `GET /logs` — expone las últimas 20 consultas de los vendedores (qué cotizan, cuánto).
- `GET /demandas` — expone la inteligencia comercial completa (demanda insatisfecha + últimos 4 dígitos de números de WhatsApp).
- `POST /consultar` — permite a **cualquiera** (incluida la competencia) consultar el catálogo completo de precios CISGE sin límite ni autenticación.

**Fix:** header `X-API-Key` contra env var, o eliminarlos si no se usan. Esfuerzo: pequeño.

### S3 — MEDIO: whitelist hardcodeada en el código

Los números de los vendedores están en `main.py` (commiteados a GitHub). Agregar un vendedor = deploy. **Fix:** env var `NUMEROS_PERMITIDOS` separada por comas. Pequeño.

### S4 — BAJO: log de respuestas completas de la API de Meta

`enviar_whatsapp` loggea `r.text` completo en INFO — incluye message IDs y metadata. En Render los logs son visibles para cualquiera con acceso al dashboard. Bajar a DEBUG o loggear solo el status code.

### S5 — OK (verificado)

- Secretos via env vars, `.env` en `.gitignore` y no trackeado. ✔
- No hay SQL (todo pandas en memoria). ✔
- `_registrar_demanda` anonimiza el número (últimos 4 dígitos). ✔

---

## 4. MOTOR DE BÚSQUEDA (motor.py)

### Correcto y bien resuelto

- Filtros estrictos para marca y medidas múltiples (sin fallthrough silencioso) — lección aprendida y aplicada de forma consistente.
- Equivalencia BSP↔BSPP, inyección de ángulo con guard, tabla `MEDIDA_NOMINAL` con correcciones de errores de BD documentadas en comentarios.
- Match de grupo exacto-o-prefijo-con-espacio que evita el clásico falso positivo R1→R12.

### Problemas

| # | Problema | Detalle |
|---|---|---|
| M1 | **`buscar_por_tipo_medida_marca`: 230 líneas, 14 parámetros posicionales** | Es la función más crítica del sistema y la más difícil de tocar sin romper. Los call sites la llaman posicionalmente (`buscar_por_tipo_medida_marca(tipo, medida_busq, marca, presion, linea, subtipo_ht, superficie, subfamilias, medidas)`) — un parámetro nuevo en medio rompería todos en silencio. El patrón interno se repite 12 veces: `r_x = r[filtro]; if not r_x.empty: r = r_x` (filtro suave) vs `return vacío` (estricto), sin que se distinga visualmente cuál es cuál. |
| M2 | **`interpretar_linea` recalcula listas en cada llamada** | Línea 918: `sorted(df["grupo"].dropna().unique().tolist(), ...)` + un `re.search` por cada grupo (~300+) **en cada mensaje**. Lo mismo con `tipo_cod` (línea 932) y los tipos base (fallback 4, líneas 942-953 — reconstruye y reordena todo). Con el catálogo refrescándose cada 10 min, esto se puede precalcular en `_build_df_from_api` y reusar. No es bug, pero es costo por mensaje innecesario. |
| M3 | **Colapso de medidas duplicado 2 veces** | La lógica "si medidas tiene un elemento, colapsar a medida salvo conflicto métrico" está copiada idéntica en `_buscar_fila_imagen` (agente.py:607-613) y `_buscar_con_parsed` (agente.py:656-662). Ya divergieron una vez (el bug M16 de esta semana se arregló en ambas por separado). |
| M4 | **`medida=None` reasignado a mitad de función** | En el bloque `_es_metrica` (línea 764) se hace `medida = None` para "consumirla" — funciona, pero significa que el orden de los bloques de filtro importa de formas no obvias. Síntoma del problema M1. |
| M5 | **`consultar()` y `cotizar_multiple` duplican E1/E2/E3** | Ver A1. `cotizar_multiple` además tiene `fila = None` dos veces seguidas (líneas 1377-1379, copy-paste visible). |
| M6 | **`buscar_por_codigo_prefijo` es O(n) por mensaje** | `.str.upper().str.startswith(...)` sobre 8737 filas en cada consulta E2. Aceptable hoy (<10 ms), pero si el catálogo crece 10x conviene un índice ordenado. No urgente. |

### Recomendación de refactor (cuando haya tests)

Convertir `buscar_por_tipo_medida_marca` en una cadena de filtros nombrados:

```python
FILTROS = [filtro_tipo, filtro_subfamilia, filtro_cola, filtro_hex, ...]
# cada filtro: (df, params) -> df | declara si es estricto o suave
```

Esto hace testeable cada filtro por separado y elimina la clase de bugs B1/M4 (variables que cruzan bloques). **No hacerlo antes de tener la suite de pytest** — es exactamente el tipo de refactor que rompe casos de borde no documentados.

---

## 5. CALIDAD Y MANTENIBILIDAD

### Código duplicado (resumen)

1. Pipeline E1/E2/E3 × 3 (A1/M5) — el más caro de mantener.
2. Colapso de medidas × 2 (M3).
3. Bloque "mostrar alternativas del tipo" (`No hay *{tipo}* en *{medida}*...`) × 2: `buscar_texto_libre` (1086-1105) y `consultar` (1275-1293), casi carácter por carácter.
4. Detección `sae_subtipo` HT/R1/R2 × 2 (1052-1058 y 1228-1233).
5. Fallback VITILLO letra de color × 2 (motor 1204-1210, agente 418-426).
6. `_norm_medida` (agente) vs `normalizar_medida_texto` + `MEDIDA_NOMINAL` (motor) — dos normalizadores de medida con reglas parcialmente solapadas.

### Funciones demasiado largas

- `buscar_por_tipo_medida_marca` — 230 líneas (M1).
- `consultar` — 220 líneas.
- `_agente_cisge_impl` — 150 líneas (E2 con el fallback de tokens merece función propia).
- `procesar_imagen_whatsapp` — 115 líneas, 7 pasos que serían 7 funciones.
- `interpretar_linea` — 190 líneas que devuelven una **tupla posicional de 10 elementos** (`return marca, tipo, medida, medidas, color, cantidad, presion, linea, superficie, subfamilias_detectadas`) — cada call site debe recordar el orden exacto; un `dataclass` o `dict` eliminaría esa clase de error.

### Nombres confusos

- `linea` significa "línea de texto" en unos contextos y "línea premium de producto" (ExactFlex) en otros — dentro del mismo archivo (`cotizar_multiple` usa `linea` y `linea_prem` para distinguir; `buscar_por_tipo_medida_marca` recibe `linea=` que es la premium).
- `subtipo` en la firma de `buscar_por_tipo_medida_marca` solo se usa para HT-color — el nombre no lo dice.
- `df` como global mutable compartido entre módulos (ver A3).

### Logging — ¿se puede diagnosticar producción en Render con lo actual?

**Parcialmente sí.** Lo bueno:

- El pipeline de texto tiene trazas por etapa con `[{numero_wa}]`: se puede seguir un mensaje desde E1 hasta E4.
- `_buscar_con_parsed` loggea los parámetros exactos que recibe el motor y cuántas filas devolvió — esto fue clave para los bugs de esta semana.
- El OCR loggea el texto extraído (primeros 200 chars) y el conteo de líneas/ítems.

Lo que falta para diagnosticar sin reproducir:

1. **motor.py no sabe quién pregunta**: los logs del motor no llevan `numero_wa`, así que con 2 vendedores simultáneos las líneas se entrelazan sin poder atribuirlas. Fix barato: pasar un `request_id` corto o usar `contextvars`.
2. **`FileHandler("cisge_consultas.log")` es inútil en Render**: disco efímero (se pierde en cada deploy/restart) y sin rotación (el archivo local ya pesa 200 KB y crecerá indefinidamente en dev). Render ya captura stdout — eliminar el FileHandler.
3. **`logging.basicConfig` vive en motor.py**: configurar logging es responsabilidad del entrypoint (main.py). Hoy el formato depende de qué módulo se importa primero.
4. **Sin métricas de latencia**: el problema conocido "pipeline de imagen >1 min" no se puede descomponer con los logs actuales (¿OCR? ¿parser? ¿motor × N ítems? ¿upload?). Agregar `t0 = time.monotonic()` y loggear duración por paso costaría 10 líneas.
5. **Los ítems no encontrados de imagen** se loggean solo al jsonl de demandas, no al log — para depurar "por qué no encontró X" hay que correlacionar dos fuentes.

### Tests automatizados — qué agregar (pytest), priorizando motor.py

Estado actual: `test_parser.py` y `test_imagen_pipeline.py` son **scripts manuales** que llaman a la API real de OpenAI — no son ejecutables en CI ni deterministas. `test_dg.py` (7 líneas) y `test_multi_marca.py` son restos sueltos.

**Prerrequisito (pequeño pero clave):** mover la carga API del import de motor.py a una función `init_catalogo()` llamada desde main.py, para poder importar motor con un DataFrame sintético. Sin esto, todo test necesita mockear red en tiempo de import.

Suite mínima en orden de valor:

| Prioridad | Test | Qué protege |
|---|---|---|
| 1 | `test_buscar_por_tipo_medida_marca` con fixture de DataFrame sintético (~30 filas representativas: espigas, adaptadores con °, métricas, ferrulas T/M, multi-marca) | El corazón del negocio. Casos: tipo exacto, prefijo, BSP↔BSPP, marca inexistente→vacío, medidas estrictas→vacío, ángulo inyectado, **tipo=None+marca (detectaría B1 hoy)**, métrica M16+manguera 3/8 |
| 2 | `test_build_df_from_api` con payload sintético que incluya grupo con `�` y `\xa0`, TSER, VITILLO TH1SN, HYP sin tipo | Las correcciones de encoding (B2) y las normalizaciones por marca — hoy invisibles e intesteadas |
| 3 | `test_interpretar_linea` — tabla de ~20 entradas reales de vendedores → tupla esperada | Todo el parsing determinista de texto libre |
| 4 | `test_correcciones_ocr` — `_corregir_adaptador_ocr`, `_corregir_medidas_ocr`, `_enriquecer_tipo_ferrula`, `_corregir_codo_ocr` (funciones puras, triviales de testear) | Los bugs de esta semana ("Ho. JIC", "(90)", redondeo 3/16→1/4) tendrían regression tests |
| 5 | `test_normalizar_medida_texto` + `_norm_medida` + `extraer_cantidad/descuento` | Tabla nominal y variantes de escritura |
| 6 | `test_cotizar_multiple` con df sintético | Totales, descuento global, ítem no encontrado, agotado |
| 7 | `test_dividir_mensaje` (main.py) | Corte de mensajes largos en límites de línea |

Los prompts de GPT no se testean unitariamente — para eso sirve un set de regresión de mensajes reales contra el parser (manual, mensual), que es lo que `test_parser.py` ya intenta ser: formalizarlo como script de smoke separado de pytest.

---

## 6. PLAN DE ACCIÓN

### Fase 1 — Inmediato, seguro de aplicar sin pruebas con ventas

(no cambian el comportamiento observable; arreglan crashes o blindan)

| Orden | Cambio | Esfuerzo | Riesgo |
|---|---|---|---|
| 1 | **B1**: inicializar `tipo_up = ""` (fix del NameError) | pequeño | nulo — solo convierte un crash en búsqueda normal |
| 2 | **B2**: escapes explícitos `\xa0`/`�` en línea 316 | pequeño | nulo — bytes idénticos |
| 3 | **S2**: API key en `/logs`, `/demandas`, `/consultar` | pequeño | nulo para WhatsApp |
| 4 | **S1**: validación HMAC `X-Hub-Signature-256` en webhook | pequeño | bajo — probar con un mensaje real tras el deploy |
| 5 | **B7**: `log_consultas` → `deque(maxlen=500)` | pequeño | nulo |
| 6 | **B4**: guardar referencias de `asyncio.create_task` | pequeño | nulo |
| 7 | **B6**: dedup LRU en lugar de `clear()` | pequeño | nulo |
| 8 | **B11**: pin de `openai/httpx/openpyxl`, `runtime.txt` con versión, `git rm --cached` de los `.pyc`, borrar archivos `1`, `12`, `test_output.txt` | pequeño | nulo (pinear a las versiones HOY desplegadas en Render) |
| 9 | **S3**: whitelist → env var | pequeño | nulo |

### Fase 2 — Corto plazo, requiere validación ligera

| Orden | Cambio | Esfuerzo | Validación necesaria |
|---|---|---|---|
| 10 | **B3**: endurecer regex de ángulo en `_corregir_adaptador_ocr` | pequeño | re-correr las imágenes de prueba de esta semana (H. JIC, Ho. JIC, adaptadores rectos con (12)) |
| 11 | **Logging**: quitar FileHandler, mover basicConfig a main.py, agregar timing por paso del pipeline de imagen, `numero_wa` en logs de motor | mediano | solo revisar logs en Render tras deploy |
| 12 | **B5**: db.py async (`httpx.AsyncClient`) y tools via `asyncio.to_thread` | mediano | smoke test de historial y E4 |
| 13 | **A2 + prerrequisito de tests**: `init_catalogo()` en vez de carga en import | pequeño-mediano | smoke de arranque en Render |
| 14 | **Suite pytest fases 1-4** de la tabla de tests | mediano | n/a — son los tests |

### Fase 3 — Mediano plazo, NECESITA pruebas con el equipo de ventas antes de producción

| Orden | Cambio | Esfuerzo | Por qué necesita ventas |
|---|---|---|---|
| 15 | **A3/A4**: eliminar imports por referencia (`motor_df`, `_aliases_marcas`); recalcular vocabulario de prompts en cada refresh | mediano | cambia qué ve el prompt → el comportamiento del parser puede variar con catálogo vivo; probar con las listas reales |
| 16 | **B10/M3**: unificar `_buscar_fila_imagen`/`_buscar_con_parsed` en una sola función que devuelva (fila, formato) | mediano | afecta qué producto se elige en los Excel de imagen |
| 17 | **M1**: refactor de `buscar_por_tipo_medida_marca` a cadena de filtros + kwargs obligatorios | grande | es el corazón; solo después de que la suite pytest esté verde y con período de prueba paralelo |
| 18 | **A1/M5**: unificar los 3 pipelines E1/E2/E3 en una sola implementación | grande | ídem — cada divergencia actual podría ser un comportamiento del que los vendedores dependen |
| 19 | **M2**: precalcular listas de grupos/tipos en `_build_df_from_api` | pequeño | bajo riesgo, pero verificar que el matching no cambie |

### Regla transversal

Del propio CONTEXT.md: *"Primero robustecer motor.py (código determinista), después propagar a los parsers"*. Este plan la respeta: las fases 1-2 son determinismo y blindaje; los refactors grandes (fase 3) solo después de tener la red de seguridad de pytest (ítem 14).

---

*Informe generado por revisión estática completa de los 5 módulos de `app/` + infraestructura del repo. Bugs B1 y B2 verificados con análisis AST e inspección de bytes respectivamente; el resto por lectura de código.*
