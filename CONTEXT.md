# Asistente Comercial CISGE — Estado actual (2026-06-12)

## Lo que YA está funcionando

### Pipeline de texto (mensajes escritos)
- Asistente WhatsApp en producción: +51 940 587 545
- 4 etapas de búsqueda:
  - E1: código exacto
  - E2: prefijo de código + fallback token numérico + filtro de marca por alias
  - E3: GPT-4.1-mini parser → `_buscar_con_parsed()` → `buscar_por_tipo_medida_marca()`
    - Post-proceso: si GPT no extrae marca, se escanea el mensaje contra `_aliases_marcas` (word boundary)
  - E4: GPT-4.1-mini conversacional con tools (historial cargado solo aquí — lazy loading)
    - `tool_buscar_producto` usa `buscar_texto_libre()` (no `consultar()`) → evita E1+E2 redundantes
- 8737 productos, 44 marcas en memoria (Pandas DataFrame)
- Cotización múltiple con descuentos e IGV (18%)
- Historial por usuario via API REST externa (api.comercialcisgesac.com.pe)
- Split de mensajes WhatsApp largos (>4000 chars)
- Whitelist de números (4 vendedores/pruebas)
- Deduplicación de mensajes (set de IDs, max 1000)
- Keep-alive (ping cada 10 min al propio Render URL)

### Pipeline de imágenes (listas escaneadas o fotografiadas)
- Descarga de imagen desde WhatsApp Media API
- OCR con GPT-4o (Vision), max_tokens=4096 para evitar truncación
- Corrección pre-parser: `_corregir_codo_ocr` — si una línea tiene "codo" + tipo SAE (R1/R2/R12), lo reescribe como "casco"
- Parser de líneas OCR con GPT-4.1-mini (`_parsear_lineas_imagen`)
- Corrección post-parser: `_enriquecer_tipo_ferrula` — si `tipo=="FERRULA"` sin subtipo SAE pero `linea_original` lo tiene, inyecta el subtipo
- Corrección post-parser: `_corregir_medidas_ocr` — compara fracciones del texto original vs. lo que devolvió GPT; corrige redondeos (ej: 3/16 → 1/4 que GPT hace por sesgo de entrenamiento)
- Corrección post-parser: `_corregir_adaptador_ocr` — dos pasadas independientes:
  1. Si tipo empieza con ESPIGA y la línea contiene dos pares género+rosca (`_PAT_ADAP_GENDER`), reescribe como ADAP MACHO/HEMBRA X1 X MACHO/HEMBRA X2. Detecta "Ho." como error OCR de "H." (Hembra).
  2. Si tipo empieza con ADAP y no tiene ángulo, busca `(90)`, `(45)`, `90°`, `45°` en la línea original e inyecta el campo angulo.
- Búsqueda en motor para cada ítem parseado
- Generación de Excel en memoria (openpyxl):
  - Columnas: Línea Original | Código CISGE | Descripción | Cantidad | Precio Unit. USD | Subtotal USD | IGV (18%) | Total USD
  - Filas encontradas: blanco normal
  - Filas no encontradas: relleno amarillo (FFF9C4) + fuente itálica gris
  - Mantiene el orden original del OCR (encontrados + no encontrados)
  - Nota en columna Descripción: "Tamaño no disponible en catálogo" o "Producto no existe en el catálogo"
- Subida del Excel a WhatsApp Media API y envío como documento
- Solo envía Excel, sin texto adicional por WhatsApp
- Guard en main.py: `if respuesta:` — no envía texto vacío

### Motor (app/motor.py)
- Aliases de tipos: casco/casquillo → FERRULA, gir/girat → GIRATORIO, etc.
- Aliases de marcas: JDE → JDEFLEX, VITI → VITILLO, etc. + `_aliases_marcas` dinámico desde API ERP
- Aliases de colores: A=Amarillo, N=Negro, R=Rojo
- Mapeos SAE especiales (4SH, 4SP, HT, MP, TSER, etc.)
- Búsqueda por palabra de frontera (word boundary): evita R1 → R12 falso positivo
- Medidas nominales: 08→1/2, 12→3/4, 16→1, 20→1¼, 24→1½, etc.
- `IGV = 0.18`, `_stock_total(fila)` exportados para agente.py
- **Strict brand filter**: si se especifica marca y no existe en catálogo → retorna vacío (no fallthrough)
- **Strict medidas filter**: si se especifican medidas múltiples y no hay match exacto → retorna vacío
- **Ferrula T/M default**: `ferrula_tm=""` → aplica T/M; `ferrula_tm="no"` → solo lisa
- **Guard descripción**: en `consultar()`, si hay marca especificada y E3 devolvió vacío → no cae a búsqueda por palabras clave (evita resultados de otras marcas)
- **`buscar_texto_libre(texto, cantidad, descuento)`**: nueva función — `interpretar_linea()` + `buscar_por_tipo_medida_marca()` sin E1/E2/descripción. Usada por `tool_buscar_producto` en E4.
- **Encoding fix en `_build_df_from_api`**: el campo `grupo` llega de la API con U+FFFD (°) por mismatch Latin-1→UTF-8 en Navasoft, y con `\xa0` (non-breaking space). Ambos se normalizan: `.replace("\xa0", " ").replace("°", "°").strip().upper()`. Sin esto, los adaptadores angulares (grupo="ADAP 90° ...") nunca matcheaban.
- **Ángulo injection en `buscar_por_tipo_medida_marca`**: tipo="ADAP MACHO JIC X HEMBRA JIC" + angulo="90" → busca grupo "ADAP 90° MACHO JIC X HEMBRA JIC". Guard: no reinyectar si el ángulo ya está en el nombre del tipo.
- **`_es_metrica` block con strict hose filter**: para espigas MM LIVIANA/PESADA, si medida=M16 (hilo métrico), se filtra descripción por `\bM16\b`; luego si hay medidas=["3/8"] (tamaño de manguera), se aplica filtro estricto en `medidas_cod` — si no existe ese tamaño, retorna vacío en lugar de devolver todos los M16.
- **Collapse fix en `_buscar_fila_imagen` y `_buscar_con_parsed`**: si medidas tiene un solo elemento, solo colapsa a medida cuando medida está vacío o es el mismo valor. Si medida="M16" y medidas=["3/8"], se conservan ambos (hilo métrico + tamaño de manguera).
- **SAE base type fallback (tier 4)** en `interpretar_linea`: "espiga hembra jic" → tipo "ESPIGA HEMBRA JIC" que luego hace prefix-match con "ESPIGA HEMBRA JIC R2", etc.
- **Soporte mangueras silicona RUBBERFLEX**:
  - TIPO_ALIAS: silicona recta/codo 90/codo 45/corrugada/radiador/J20/U/reduccion → grupos MANG SILICONA*
  - MARCA_ALIAS: rubberflex/rubber → RUBBERFLEX
  - Medida mm: extractor explícito `\b(\d{2,3})\s*mm\b` + fallback mm directo para nominales no-ISO
  - Para tipos silicona/PU, el extractor nominal NO aplica MEDIDA_NOMINAL (16mm no se convierte a 1")
  - `medida_cod` prefix match: "38" matchea "38 38 X10L" para grupos codo/recta silicona
  - Silicona genérica sin ángulo (`tipo == "MANG SILICONA"`) → excluye CODO por defecto (recto implícito)

### Prompts GPT (agente.py)

#### _PARSER_PROMPT (E3, texto libre)
- Regla ADAPTADOR: si el tipo de rosca aparece DOS VECES en el texto → ADAP (no ESPIGA). Convención de género: MACHO siempre primero en el nombre.
- Regla ángulo: "90", "(90)", "90°", "(90°)", "(45)", "(45°)", "45°" = ángulo válido. "(12)", "(6)", "(10)" NO son ángulos.
- Medidas dash: "- 6 - 6", "- 8 - 10" en productos NO-espiga → medidas=["3/8","3/8"] / ["1/2","5/8"]. Aplica tabla SAE 4→1/4, 6→3/8, 8→1/2, 10→5/8, 12→3/4, 16→1.
- Alias: `union hembra npt = UNION HEMBRA NPT` (explícitamente NO es ESPIGA)

#### _PARSEAR_LINEAS_PROMPT (imagen/OCR)
- Aliases conocidos OCR: "Ho." = "H." (error OCR frecuente de "H. JIC")
- Sección "MEDIDAS DASH PARA PRODUCTOS NO-ESPIGA": cubre uniones, niples, camlock, union hembra npt con ejemplos de mismo tamaño y reducción
- Alias: `union hembra npt = UNION HEMBRA NPT` (NO ESPIGA) + ejemplo en sección tipos_otros
- Regla ángulo: lista explícita de patrones válidos (90°, (90°), (90), 45°, (45°), (45)) e inválidos ((12), (6), (10))
- Los ángulos pueden aparecer DESPUÉS de la cantidad

### Inteligencia comercial
- Demandas no encontradas se registran en `app/data/demandas_no_catalogo.jsonl`
- Campos: fecha, motivo (tamaño/producto), tipo, medida, cantidad, linea_original, numero_wa (últimos 4 dígitos)
- Endpoint `/demandas` en main.py para consultar el registro
- Distingue "Tamaño no disponible en catálogo" vs "Producto no existe en el catálogo"

### Fichas técnicas
- Directorio: `app/data/fichas/{grupo_prefix}.docx`
- Intención detectada por regex `_INTENT_FICHA`
- Flujo: upload a WhatsApp Media API → envío como documento .docx

## Estructura de archivos

```
asistente-cisge/
├── app/
│   ├── agente.py      # Core: pipeline texto + imagen, prompts GPT, helpers OCR/Excel
│   ├── motor.py       # Motor búsqueda: buscar_texto_libre, consultar, interpretar_linea, aliases
│   ├── db.py          # Historial via API REST (api.comercialcisgesac.com.pe)
│   ├── tools.py       # Tool functions para E4: buscar_producto (usa buscar_texto_libre), ver_stock, cotizar
│   ├── main.py        # FastAPI: webhook Meta, envío WhatsApp, keep-alive, /demandas
│   └── data/          # Catálogo CSV, stocks, fichas/*.docx, demandas_no_catalogo.jsonl
├── requirements.txt   # fastapi, uvicorn, pandas, openpyxl, openai, httpx, python-dotenv
├── runtime.txt        # Python version para Render
├── start.sh           # Entrypoint Render
└── CONTEXT.md         # Este archivo
```

## Variables de entorno (Render)

| Variable | Descripción |
|---|---|
| `OPENAI_API_KEY` | Clave OpenAI (GPT-4.1-mini + GPT-4o) |
| `WHATSAPP_TOKEN` | Bearer token Meta Graph API |
| `VERIFY_TOKEN` | Token verificación webhook Meta |
| `PHONE_NUMBER_ID` | ID del número WhatsApp Business |
| `RENDER_EXTERNAL_URL` | URL pública Render (para keep-alive) |

## Infraestructura

- Deploy: Render (https://asistente-cisge.onrender.com)
- Modelos: GPT-4.1-mini (parser + conversacional), GPT-4o (OCR/Vision)
- Historial: API REST externa en api.comercialcisgesac.com.pe
- Servidor CISGE: 192.168.2.13 (Windows Server 2012, SQL Server 2014)
- Cloudflare Tunnel: cisge-servidor (Healthy, falta dominio CISGE)
- Tablas stock: prd0101(Lima Centro), prd0108(Colonial), prd0112(San Luis 1), prd0118(San Luis 2)
- Repo: IluBaviera/asistente-cisge

## Pendiente inmediato

1. **Dominio CISGE en Cloudflare** → activar API stock directa (reemplaza sync periódico)
2. **Evaluar tamaño óptimo de historial** → implementar truncación a N mensajes más recientes
3. **Backend real para cisge-rollos** → FastAPI en servidor CISGE (repo: IluBaviera/cisge-rollos)
4. **Ampliar pruebas con vendedores** → monitorear aciertos del OCR en listas reales
5. **Optimizar pipeline de imágenes** → latencia >1 min; cuello de botella es GPT-4o OCR (max_tokens=4096). Opciones: comprimir imagen antes de enviar, evaluar si max_tokens puede reducirse.
6. **Verificar Union Escamada "- 6 - 6"** → fix de medidas dash fue deployed pero no confirmado por el usuario

## Plan mediano plazo — Silicona y catálogo enriquecido

### Opción preferida: campos custom en Navasoft
- La BD Navasoft permite agregar características custom a productos (string); salen en el API actual.
- Plan: agregar campo `diametro_mm` a los productos silicona RUBBERFLEX (~200 SKUs, llenado manual).
- Cuando esté disponible: el motor filtra por `diametro_mm` en lugar de parsear `medida_cod`.
- Beneficio: elimina toda la lógica de prefix match y resuelve codos de reducción (diámetros distintos, ej: `30 38 X10L`).
- **No hacer todavía**: esperar a que los campos estén poblados antes de cambiar el motor.
- También pendiente: campo `modelo` para mangueras (SHIELD FLEX = estándar, EXACTFLEX = premium).

### Descartado: diccionario mm↔pulgadas para silicona
- Silicona usa mm (19, 25, 38...) que no corresponden a los códigos nominales hidráulicos.
- Los vendedores que trabajan con silicona conocen los mm directamente.

## Decisiones diferidas (con razón)

| Tema | Estado | Razón |
|---|---|---|
| Merge OCR+parser (un solo GPT-4o) | Diferido | Mantener separados para poder comparar modelos OCR alternativos sin tocar el parser |
| Truncación de historial | Diferido | Medir primero cuánto historial es óptimo antes de fijar el límite |
| Historial lazy loading | **Implementado** | Solo se carga en E4 (GPT conversacional). E1/E2/E3 no hacen llamada a historial API |
| Medidas métricas en medida_cod (Opción A) | Diferido | Actualmente MM LIVIANA/PESADA busca M12/M14 por descripción (Opción B). Opción A requeriría distinguir hilo métrico vs tamaño de manguera en el extractor. |
| Reemplazar GPT parser E3 con `interpretar_linea` | **Descartado** | `interpretar_linea` requiere coincidencia exacta con grupos del catálogo. Falla con lenguaje natural. GPT es la elección correcta para E3. |
| Diccionario mm↔pulgadas para silicona | **Diferido** | Los vendedores que manejan silicona conocen mm directamente. |
| Campos custom en Navasoft (modelo, diametro_mm) | **Pendiente llenado manual** | BD ya soporta el campo; cuando estén poblados, el motor puede filtrar directamente sin parsear medida_cod. |
| Fine-tuning GPT-4o Vision para OCR | **Descartado** | No disponible por API. La alternativa es mejorar prompt OCR + corrector post-parser + preprocesamiento de imagen. |

## Principio de bug fixing

1. Primero robustecer motor.py (código Python determinista, sin hardcodear en prompts)
2. Después propagar mejora a los parsers (_PARSER_PROMPT y _PARSEAR_LINEAS_PROMPT)

## Lecciones aprendidas (arquitectura)

- **`interpretar_linea` vs GPT parser**: `interpretar_linea` es buena para inputs estructurados (códigos, texto limpio con términos exactos del catálogo). GPT parser es necesario para lenguaje natural de vendedores. No son intercambiables en E3.
- **Redundancia E1/E2 en E4**: cuando `tool_buscar_producto` llamaba `consultar()`, re-corría E1+E2 que ya habían fallado en `agente_cisge`. Resuelto: la tool ahora usa `buscar_texto_libre()`.
- **Fallthrough silencioso en motor**: patrón de bug recurrente — si un filtro (marca, medidas) no encuentra resultados, el código original continuaba sin el filtro y devolvía resultados de otras marcas/medidas. Ahora cualquier filtro especificado que no tiene match retorna vacío (strict filter).
- **GPT sesgo de redondeo en medidas**: GPT convierte 3/16 → 1/4 por sesgo de entrenamiento. Solución determinista: `_corregir_medidas_ocr()` post-parser compara fracciones regex del texto original vs. lo que devolvió GPT y corrige posición a posición.
- **Encoding U+FFFD en campo grupo**: la API Navasoft devuelve el símbolo ° (U+00B0) codificado como U+FFFD cuando hay mismatch Latin-1→UTF-8. Sin normalizar este campo en `_build_df_from_api`, todos los grupos con ángulo ("ADAP 90°...") nunca matcheaban. Fix: `.replace("°", "°")` (U+FFFD → U+00B0) al construir el DataFrame.
- **`\xa0` non-breaking space**: Python `.strip()` no elimina `\xa0`. Los grupos "ADAP MACHO JIC X HEMBRA JIC\xa0" no matcheaban con la versión sin espacio. Fix: `.replace("\xa0", " ")` antes de `.strip()`.
- **Prompts OCR demasiado restrictivos**: una regla "NUNCA inferir X" mal redactada puede bloquear incluso los casos explícitos. Mejor dar una lista de patrones válidos e inválidos concretos en lugar de prohibiciones absolutas.
- **OCR M↔H en manuscrito**: GPT-4o puede confundir "M." (Macho) con "H." (Hembra) en escritura manual de baja calidad. Las alternativas viables son: (1) contexto de dominio en el prompt OCR, (2) corrector post-OCR determinista, (3) preprocesamiento de imagen. Fine-tuning de GPT-4o Vision no está disponible por API.
