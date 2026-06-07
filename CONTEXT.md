# Asistente Comercial CISGE — Estado actual (2026-06-07)

## Lo que YA está funcionando

### Pipeline de texto (mensajes escritos)
- Asistente WhatsApp en producción: +51 940 587 545
- 4 etapas de búsqueda:
  - E1: código exacto
  - E2: prefijo de código
  - E3: GPT-4.1-mini parser → motor Python
  - E4: GPT-4.1-mini conversacional con tools (historial cargado solo aquí — lazy loading)
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
- Búsqueda en motor para cada ítem parseado
- Generación de Excel en memoria (openpyxl):
  - Columnas: Línea Original | Código CISGE | Descripción | Cantidad | Precio Unit. USD | Subtotal USD | IGV (18%) | Total USD
  - Filas encontradas: blanco normal
  - Filas no encontradas: relleno amarillo (FFF9C4) + fuente itálica gris
  - Mantiene el orden original del OCR (encontrados + no encontrados)
- Subida del Excel a WhatsApp Media API y envío como documento
- Solo envía Excel, sin texto adicional por WhatsApp
- Guard en main.py: `if respuesta:` — no envía texto vacío

### Motor (app/motor.py)
- Aliases de tipos: casco/casquillo → FERRULA, gir/girat → GIRATORIO, etc.
- Aliases de marcas: JDE → JDEFLEX, VITI → VITILLO, etc.
- Aliases de colores: A=Amarillo, N=Negro, R=Rojo
- Mapeos SAE especiales (4SH, 4SP, HT, MP, TSER, etc.)
- Búsqueda por palabra de frontera (word boundary): evita R1 → R12 falso positivo
- Medidas nominales: 08→1/2, 12→3/4, 16→1, 20→1¼, 24→1½, etc.
- `IGV = 0.18`, `_stock_total(fila)` exportados para agente.py

## Estructura de archivos

```
asistente-cisge/
├── app/
│   ├── agente.py      # Core: pipeline texto + imagen, prompts GPT, helpers OCR/Excel
│   ├── motor.py       # Motor búsqueda: 4 estrategias, aliases, formateo resultados
│   ├── db.py          # Historial via API REST (api.comercialcisgesac.com.pe)
│   ├── tools.py       # Tool functions para E4: buscar_producto, ver_stock, cotizar
│   ├── main.py        # FastAPI: webhook Meta, envío WhatsApp, keep-alive
│   └── data/          # Catálogo CSV, stocks
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

## Decisiones diferidas (con razón)

| Tema | Estado | Razón |
|---|---|---|
| Merge OCR+parser (un solo GPT-4o) | Diferido | Mantener separados para poder comparar modelos OCR alternativos sin tocar el parser |
| Truncación de historial | Diferido | Medir primero cuánto historial es óptimo antes de fijar el límite |
| Historial lazy loading | **Implementado** | Solo se carga en E4 (GPT conversacional). E1/E2/E3 no hacen llamada a historial API |

## Principio de bug fixing

1. Primero robustecer motor.py (código Python determinista, sin hardcodear en prompts)
2. Después propagar mejora a los parsers (_PARSER_PROMPT y _PARSEAR_LINEAS_PROMPT)
