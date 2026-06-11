# Asistente Comercial CISGE — Estado actual (2026-06-09)

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
- Corrección pre-parser: `_corregir_codo_ocr` — si una línea tiene "codo" + tipo SAE (R1/R2/R12), lo reescribe como "casco" (los cascos llevan subtipo SAE, los codos no)
- Parser de líneas OCR con GPT-4.1-mini (`_parsear_lineas_imagen`)
- Corrección post-parser: `_enriquecer_tipo_ferrula` — si `tipo=="FERRULA"` sin subtipo SAE pero `linea_original` lo tiene, inyecta el subtipo
- Corrección post-parser: `_corregir_medidas_ocr` — compara fracciones del texto original vs. lo que devolvió GPT; corrige redondeos (ej: 3/16 → 1/4 que GPT hace por sesgo de entrenamiento)
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
- **Soporte mangueras silicona RUBBERFLEX**:
  - TIPO_ALIAS: silicona recta/codo 90/codo 45/corrugada/radiador/J20/U/reduccion → grupos MANG SILICONA*
  - MARCA_ALIAS: rubberflex/rubber → RUBBERFLEX
  - Medida mm: extractor explícito `\b(\d{2,3})\s*mm\b` + fallback mm directo para nominales no-ISO
  - Para tipos silicona/PU, el extractor nominal NO aplica MEDIDA_NOMINAL (16mm no se convierte a 1")
  - `medida_cod` prefix match: "38" matchea "38 38 X10L" para grupos codo/recta silicona
  - Silicona genérica sin ángulo (`tipo == "MANG SILICONA"`) → excluye CODO por defecto (recto implícito)
  - Guard ángulo en `buscar_por_tipo_medida_marca`: no reinyectar ángulo si ya está en el nombre del tipo
  - E3 `_PARSER_PROMPT` + `_buscar_con_parsed`: medida mm normalizada (GPT extrae "19", no "19mm")
- **SAE base type fallback (tier 4)** en `interpretar_linea`: "espiga hembra jic" → tipo "ESPIGA HEMBRA JIC" que luego hace prefix-match con "ESPIGA HEMBRA JIC R2", etc.

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

## Plan mediano plazo — Silicona y catálogo enriquecido

### Opción preferida: campos custom en Navasoft
- La BD Navasoft permite agregar características custom a productos (string); salen en el API actual.
- Plan: agregar campo `diametro_mm` a los productos silicona RUBBERFLEX (~200 SKUs, llenado manual).
- Cuando esté disponible: el motor filtra por `diametro_mm` en lugar de parsear `medida_cod`.
- Beneficio: elimina toda la lógica de prefix match y resuelve codos de reducción (diámetros distintos, ej: `30 38 X10L`).
- **No hacer todavía**: esperar a que los campos estén poblados antes de cambiar el motor.

### Descartado: diccionario mm↔pulgadas para silicona
- Silicona usa mm (19, 25, 38...) que no corresponden a los códigos nominales hidráulicos.
- Los vendedores que trabajan con silicona conocen los mm directamente.
- Agregar solo si en producción se detecta que vendedores escriben "silicona 3/4" en vez de "silicona 19mm".

### Descartado: BD cisge-rollos como fuente de catálogo
- Requeriría sincronización con Navasoft para precio/stock (fuente de verdad).
- Más complejidad que los campos custom en Navasoft para el mismo resultado.

## Decisiones diferidas (con razón)

| Tema | Estado | Razón |
|---|---|---|
| Merge OCR+parser (un solo GPT-4o) | Diferido | Mantener separados para poder comparar modelos OCR alternativos sin tocar el parser |
| Truncación de historial | Diferido | Medir primero cuánto historial es óptimo antes de fijar el límite |
| Historial lazy loading | **Implementado** | Solo se carga en E4 (GPT conversacional). E1/E2/E3 no hacen llamada a historial API |
| Medidas métricas en medida_cod (Opción A) | Diferido | Actualmente MM LIVIANA/PESADA busca M12/M14 por descripción (Opción B). Opción A requeriría que `_extraer_medidas_lista` distinga cuándo un segmento de código (`-12-`) es hilo métrico vs tamaño de manguera (`12→3/4"`), lo cual depende de la familia de producto. Más preciso pero requiere refactorizar el extractor de medidas por familia. |
| Reemplazar GPT parser E3 con `interpretar_linea` | **Descartado** | `interpretar_linea` requiere coincidencia exacta con grupos del catálogo. Falla con lenguaje natural (ej: "espiga hembra jic" no matchea porque en el catálogo todos los grupos incluyen el subtipo SAE: "ESPIGA HEMBRA JIC R2"). Mantener alias manualmente no escala. GPT es la elección correcta para E3. |
| Diccionario mm↔pulgadas para silicona | **Diferido** | Los vendedores que manejan silicona conocen mm directamente. Agregar solo si en producción se ve "silicona 3/4" en vez de "silicona 19mm". |
| Campos diametro_mm custom en Navasoft | **Pendiente llenado manual** | BD ya soporta el campo; cuando esté poblado, el motor puede filtrar directamente sin parsear medida_cod. |

## Principio de bug fixing

1. Primero robustecer motor.py (código Python determinista, sin hardcodear en prompts)
2. Después propagar mejora a los parsers (_PARSER_PROMPT y _PARSEAR_LINEAS_PROMPT)

## Lecciones aprendidas (arquitectura)

- **`interpretar_linea` vs GPT parser**: `interpretar_linea` es buena para inputs estructurados (códigos, texto limpio con términos exactos del catálogo). GPT parser es necesario para lenguaje natural de vendedores. No son intercambiables en E3.
- **Redundancia E1/E2 en E4**: cuando `tool_buscar_producto` llamaba `consultar()`, re-corría E1+E2 que ya habían fallado en `agente_cisge`. Resuelto: la tool ahora usa `buscar_texto_libre()` que va directo a `interpretar_linea()` + motor.
- **Fallthrough silencioso en motor**: patrón de bug recurrente — si un filtro (marca, medidas) no encuentra resultados, el código original continuaba sin el filtro y devolvía resultados de otras marcas/medidas. Ahora cualquier filtro especificado que no tiene match retorna vacío (strict filter).
- **GPT sesgo de redondeo en medidas**: GPT convierte 3/16 → 1/4 por sesgo de entrenamiento. Solución determinista: `_corregir_medidas_ocr()` post-parser compara fracciones regex del texto original vs. lo que devolvió GPT y corrige posición a posición.
