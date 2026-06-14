# Esquema de campos personalizados (Navasoft) — medidas estructuradas

Especificación para llenar los **atributos personalizados** de los productos en
Navasoft ("Más información"), de modo que el motor del asistente deje de
adivinar las medidas desde el código (fuente de los bugs C1/C2, reductores
falsos en férrulas, métricas que no calzaban) y las lea de forma fiable.

> **Regla de oro:** estos campos guardan **solo medidas**. La familia, el tipo de
> rosca (JIC/NPT/…), el género (MACHO/HEMBRA), el ángulo y la cola (R2/R12) ya
> están en el campo `grupo` y funcionan bien — **no se duplican aquí**.

---

## 1. Mapeo de campos (nombre físico fijo ↔ rol)

Navasoft no deja renombrar el campo físico (`Usr_001`, `Usr_002`, …); lo que
les da significado es la **Descripción**. Mantener SIEMPRE este orden y
descripción en todos los productos:

| Campo físico | Descripción (poner tal cual) | Tipo | Long. | Rol |
|---|---|---|---|---|
| `Usr_001` | `med_manguera` | Texto | 15 | Tamaño de manguera en pulgadas (lado que recibe la manguera) |
| `Usr_002` | `med_rosca_1` | Texto | 15 | Medida de la 1ª rosca (pulgadas o hilo métrico) |
| `Usr_003` | `med_rosca_2` | Texto | 15 | Medida de la 2ª rosca (solo productos de dos roscas) |
| `Usr_004` | `med_tubo` | Texto | 15 | Serie de tubo DIN para milimétricas (`6L`, `8S`, …) |

- **Tipo = Texto** en los cuatro (las fracciones y los códigos métricos NO son
  numéricos; `3/8` como número se interpretaría como 0.375).
- **Longitud 15** da margen (el valor más largo realista, `M22x1.5`, son 7).

---

## 2. Por qué por ROL y no por posición

El problema de fondo era mezclar "medida de la manguera" con "medida de la
rosca" en una lista posicional ambigua extraída del código. Separar por **rol**
elimina la ambigüedad:

- Una espiga 1/4" × 3/16" → `med_rosca_1=1/4`, `med_manguera=3/16`. Si un
  vendedor pide "3/16 × 3/16", el motor exige rosca=3/16 **y** manguera=3/16;
  esta espiga (rosca 1/4) queda descartada correctamente — sin heurísticas.
- Un reductor se detecta trivial y fiable: `med_rosca_1 != med_rosca_2`.

---

## 3. Reglas de formato canónico (CRÍTICO con texto libre)

Como es texto sin validación, el match depende de escribir **siempre igual**:

1. **Pulgadas = fracción canónica**, con **espacio** en compuestas:
   `3/8`, `1/2`, `1`, `1 1/4`, `1 1/2`, `2`.
   - NUNCA: `0.375`, `3/8"`, `3/8 pulg`, `1-1/4`, `11/4`.
2. **Métrico = `M` + número**, paso pegado con `x` si aplica:
   `M22`, `M22x1.5`, `M42x2.0`.
3. **Tubo DIN = número + letra de serie** (L = liviana, S = pesada):
   `6L`, `8L`, `10L`, `12L`, `15L`, `18L`, `22L`, `28L`, `35L`, `42L`,
   `6S`, `8S`, `10S`, `12S`, `14S`, `16S`, `20S`, `25S`, `30S`, `38S`.
4. **Vacío = no aplica.** No escribir `N/A`, `-`, `0`, `x`. Vacío de verdad.
5. **Un solo valor por campo.** Nada de `3/4 x 1/2` dentro de un campo.

### Fracciones válidas (lista cerrada)

```
1/8 · 3/16 · 1/4 · 5/16 · 3/8 · 1/2 · 5/8 · 3/4 · 7/8 · 1 · 1 1/4 · 1 1/2 · 2 · 2 1/2 · 3 · 3 1/2
```

### Hilos métricos comunes

```
M10 · M12 · M14 · M16 · M18 · M20 · M22 · M24 · M27 · M30 · M36 · M42 · M48 · M52
```

---

## 4. Cómo llenar cada familia (ejemplos)

| Producto | med_manguera | med_rosca_1 | med_rosca_2 | med_tubo |
|---|---|---|---|---|
| Espiga JIC 1/4" × manguera 3/16" | `3/16` | `1/4` | — | — |
| Espiga uniforme JIC 3/4 | `3/4` | `3/4` | — | — |
| Férrula R2 1/2 | `1/2` | — | — | — |
| Adaptador M JIC 3/4 × M NPT 1/2 (reductor) | — | `3/4` | `1/2` | — |
| Adaptador 90° JIC×JIC 3/4 | — | `3/4` | `3/4` | — |
| Manguera R1 1/2 | `1/2` | — | — | — |
| Espiga métrica pesada M42 × manguera 1 1/4 | `1 1/4` | `M42` | — | — |
| Terminal cabina M12 tubo 6L | — | `M12x1.5` | — | `6L` |
| Unión escamada 3/8 | `3/8` | — | — | — |

Resumen por familia:
- **Espigas / casquillos**: `med_manguera` + `med_rosca_1`.
- **Férrulas / mangueras / uniones de 1 rosca**: solo `med_manguera`.
- **Adaptadores / uniones de 2 roscas**: `med_rosca_1` + `med_rosca_2` (sin manguera).
- **Métricas**: igual que arriba pero la rosca va como `M..`, y si es de tubo DIN, llenar `med_tubo`.

---

## 5. Cómo lo consumirá el motor

Reemplaza la extracción frágil (`_extraer_medidas_lista` sobre el código):

```
reductor       = med_rosca_1 y med_rosca_2 llenos y distintos     (fiable)
match espiga   = med_manguera == pedido_manguera AND med_rosca_1 == pedido_rosca
match métrico  = med_rosca_1 == "M42" AND med_manguera == "1 1/4"
match tubo     = med_tubo == "6L"
```

Con esto desaparecen C1, C2, el reductor falso en férrulas, y las métricas con
tubo — todas de una, sin parsear códigos.

### ⚠️ Pendiente de verificar antes de cablear el motor

**Cómo expone el API estos campos.** El nombre físico es `Usr_002` pero la
descripción es `med_rosca_1`. Hay que confirmar en la respuesta de
`api.comercialcisgesac.com.pe/stock` si los custom fields llegan:
- por descripción (`"med_rosca_1": "1/4"`), o
- por nombre físico (`"Usr_002": "1/4"`), o
- dentro de una sub-estructura (ej. `"atributos": {...}`).

De eso depende cómo `_build_df_from_api` los mapee a columnas del DataFrame.

---

## 6. Plan de migración (sin big-bang)

1. **Familia piloto: `ESPIGA 90° HEMBRA JIC`** (la de la fila 6) — llenar
   `med_manguera` + `med_rosca_1` en todos sus SKUs.
2. Verificar el punto del §5 (cómo llegan por API).
3. Adaptar el motor para que: **si los campos están presentes, los use; si
   están vacíos, caiga al comportamiento actual** (`medidas_cod`). Así las
   familias migran de a poco sin romper lo que hoy funciona.
4. Ir poblando familia por familia; cada una que se llena, se vuelve fiable.
5. Cuando todas estén pobladas, retirar la lógica vieja de `medidas_cod`.

---

*Referencia para el llenado manual en Navasoft. Mantener el formato canónico
del §3 a rajatabla: con texto libre, la consistencia es lo único que garantiza
que el match funcione.*
