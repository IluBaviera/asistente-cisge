# Asistente Comercial CISGE

## Descripción
Asistente de WhatsApp para CISGE, distribuidora de mangueras hidráulicas en Perú.
Permite a vendedores cotizar productos por WhatsApp en tiempo real.

## Stack
- Backend: FastAPI + Uvicorn
- Deploy: Render (https://asistente-cisge.onrender.com)
- Repo: GitHub (IluBaviera/asistente-cisge)
- Python 3.14

## Estructura
```
app/
├── main.py      # FastAPI + webhook WhatsApp (Meta API)
├── motor.py     # Lógica de búsqueda y cotización
└── data/
    └── mangueras_precios.xlsx  # 771 productos
```

## Flujo
1. Cliente escribe en WhatsApp al +51 940 587 545
2. Meta envía webhook POST a /webhook en Render
3. main.py recibe y llama a motor.py
4. motor.py busca en el Excel y retorna respuesta
5. main.py envía respuesta vía WhatsApp API

## Motor de búsqueda (motor.py)
Estrategias en orden de prioridad:
1. Código exacto (ej: QF-R1-1/2")
2. Código parcial único
3. Tipo + medida + marca + color + línea + presión
4. Palabras clave en descripción

### Tipos SAE hidráulicos soportados
R1, R2, R3, R4, R5, R6, R7, R9, R12, R13, R15, 4SH, 4SP

### Marcas en BD
- QF / QINGFLEX
- JDEFLEX (JDE)
- VITILLO (VT)
- AF (mangueras industriales)
- MACTUBI
- RUNNINGFLEX (RSY)
- SWAGGER (SW)
- HYP

### Líneas premium (exclusivas por marca)
- exactflex / exact flex → JDEFLEX (aplica a R12, R15, 4SH, 4SP)
- everest → VITILLO TSER (isobárica 4000/5000/6000 PSI)
- impulmax / ip → QF R2IP (R2 premium)
- no conductiva → MACTUBI R7
- alto rendimiento → MACTUBI R7
- twin / doble → MACTUBI R7

### Mapeos especiales en BD
- R15 → tipo_cod R15 (JDE/QF) o TSR15xx (VITILLO)
- R12 → tipo_cod R12 o TSR12xx (VITILLO)
- R13 → TSR13xx (VITILLO)
- 4SH → tipo_cod 4SH o TS (VITILLO Teknospir)
- Everest → tipo_cod TSER (VITILLO, isobárica)
- HT → alta temperatura QF, subtipos 1SN (R1) y 2SN (R2)

### Variables de entorno (Render)
- WHATSAPP_TOKEN
- VERIFY_TOKEN
- PHONE_NUMBER_ID = 1051785754692564

## Estado actual
- 771 SKUs de mangueras hidráulicas e industriales
- Cotización múltiple (varias líneas)
- Descuentos por producto (ej: r1 1/2 x10 20%)
- Próximamente: 4500 SKUs totales (espigas, ferrulas, adaptadores, etc.)
- Próximamente: fotos de productos
- Futuro: IA como parser de consultas

## Problemas conocidos / pendientes
- Encoding CRLF al copiar archivos desde Downloads — editar siempre directo en VSCode
- El vendedor comienza pruebas hoy
- Configurar UptimeRobot para evitar cold start de Render
