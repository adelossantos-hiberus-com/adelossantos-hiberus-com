# Análisis de comercio exterior — demo para Databricks (datos ficticios)

Proyecto de demostración con Python y SQL: genera 50.000 registros ficticios de exportaciones e importaciones (2022–2025) por país, producto y sector, los valida y calcula métricas de comercio exterior con SQL.

> **Todos los datos son inventados.** Los nombres de países son solo etiquetas; los importes, pesos y fechas no proceden de ninguna estadística real. El proyecto no usa servicios externos ni credenciales.

## Estructura

```
comercio_exterior/
├── src/comercio_exterior/
│   ├── generador.py      # Genera los 50.000 registros (reproducible con semilla)
│   ├── consultas.py      # Carga las plantillas SQL y las ejecuta (SQLite local)
│   ├── validaciones.py   # Calidad de datos y coherencia de totales
│   └── demo.py           # Ejecución completa local
├── sql/                  # Consultas (válidas en SQLite y Spark SQL / Databricks)
│   ├── 01_metricas_anuales.sql
│   ├── 02_variacion_interanual.sql
│   ├── 03_top_paises.sql
│   └── 04_metricas_por_sector.sql
├── notebooks/demo_databricks.py   # Notebook de Databricks (formato fuente)
├── scripts/verificar_spark_local.py   # Opcional: contrasta SQL en Spark vs SQLite
└── tests/                # Pruebas con pytest
```

## Cómo ejecutarlo en local

Requiere Python ≥ 3.10.

```bash
cd comercio_exterior
pip install -r requirements.txt

python -m pytest                              # 56 pruebas
PYTHONPATH=src python -m comercio_exterior.demo   # genera, valida y muestra las métricas
PYTHONPATH=src python -m comercio_exterior.generador --salida datos/comercio_exterior.csv   # solo el CSV
```

`demo` termina con código de salida 1 si alguna validación falla.

## Cómo ejecutarlo en Databricks

1. Importa el repositorio como *Git folder* (o copia la carpeta `comercio_exterior`).
2. Abre `notebooks/demo_databricks.py` y ejecútalo en un clúster o *serverless*.
3. Ajusta los widgets `catalogo` y `esquema` (por defecto `main.comercio_exterior_demo`). El notebook crea la tabla Delta `<catalogo>.<esquema>.comercio`, ejecuta las validaciones y muestra las cuatro consultas con `display()`.

Necesitas permiso para crear esquemas/tablas en el catálogo elegido.

## Datos

Tabla `comercio` (una fila por operación):

| Columna | Descripción |
|---|---|
| `id_registro` | Identificador único |
| `fecha`, `anio` | Fecha de la operación y su año (2022–2025) |
| `pais` | 30 países |
| `sector`, `producto` | 8 sectores × 5 productos |
| `flujo` | `EXPORTACION` o `IMPORTACION` |
| `importe_eur` | Importe en euros |
| `peso_kg` | Peso en kilogramos |

Con la semilla por defecto (42) el resultado es siempre el mismo.

## Métricas

Los importes están en euros. Todas las divisiones usan `NULLIF(denominador, 0)`: si el denominador es cero el resultado es `NULL` (no un error ni un infinito).

| Métrica | Definición | Notas |
|---|---|---|
| **Exportaciones** | Suma de `importe_eur` con flujo `EXPORTACION` | |
| **Importaciones** | Suma de `importe_eur` con flujo `IMPORTACION` | |
| **Saldo comercial** | Exportaciones − Importaciones | Positivo = superávit; negativo = déficit |
| **Tasa de cobertura** | Exportaciones / Importaciones × 100 | 100 % = equilibrio; >100 % las exportaciones cubren las importaciones. `NULL` si no hay importaciones |
| **Variación interanual** | (Valor del año − valor del año anterior) / valor del año anterior × 100 | Calculada para exportaciones, importaciones y comercio total (exp. + imp.). `NULL` si falta el año anterior, no tiene datos o vale 0 |
| **Variación del saldo** | Saldo del año − saldo del año anterior (en euros) | Es absoluta: un porcentaje sobre un saldo negativo o cercano a cero sería engañoso |
| **Top 10 países** | Los 10 países con mayor comercio total (exp. + imp.) de cada año | Incluye saldo, cobertura y `cuota_pct` (peso sobre el comercio total del año). Los empates se desempatan por nombre |

**Años sin datos.** Las consultas parten de un calendario explícito de años (`ANIOS`, por defecto 2022–2025). Un año del calendario sin registros aparece con `num_registros = 0` y métricas `NULL`, que no es lo mismo que «0 euros». La variación interanual compara siempre con el año inmediatamente anterior: si ese año no tiene datos, la variación es `NULL` (no se compara con el último año disponible).

## Validaciones (`validaciones.py`)

Se hacen sobre un DataFrame de pandas, así que funcionan igual en local y en Databricks.

**Calidad** (`validar_calidad`): esquema completo; `id_registro` sin duplicados; sin filas idénticas salvo el id; sin nulos ni textos vacíos en ninguna columna; sin importes ni pesos negativos (un importe 0 es válido); `flujo` solo con valores permitidos; `anio` coincide con el año de `fecha`; todos los años esperados tienen datos.

**Coherencia de totales** (`validar_coherencia`): los totales anuales calculados por SQL coinciden con un recálculo independiente en pandas; saldo = exportaciones − importaciones y cobertura = exp./imp.×100; la suma de los años iguala el total general; la suma agrupada por país, producto y sector iguala el total (detecta filas con clave nula que se perderían); el ranking de países está ordenado y no supera el total del año.

## Pruebas (`tests/`)

- **Generador**: 50.000 registros, esquema, años, flujos, sector↔producto, sin nulos/duplicados/negativos, reproducibilidad.
- **Consultas** con datos mínimos calculados a mano: exportaciones, importaciones, saldo (positivo y negativo), cobertura, **división por cero** (importaciones = 0, base interanual = 0, comercio total = 0), **años sin datos** (año final, año intermedio, tabla vacía), top N (menos de 10 países, empates, independencia por año, cuotas que suman 100 %) y validación de parámetros.
- **Validaciones**: un caso que falla por cada comprobación, más totales manipulados a propósito.
- **Estática**: toda división de los ficheros `.sql` debe ir protegida por `NULLIF`.

### Por qué existe la prueba estática de `NULLIF`

SQLite devuelve `NULL` al dividir por cero, pero Spark/Databricks en modo ANSI (el predeterminado en versiones recientes) lanza un error. Los tests en SQLite por sí solos no detectarían una división sin proteger, por eso se revisa el SQL de forma estática. Además, `scripts/verificar_spark_local.py` (opcional, requiere `pip install pyspark` y Java) ejecuta las mismas consultas en Spark local con ANSI activado y compara los resultados con SQLite, incluidos los casos límite.

## Limitaciones

- El notebook de Databricks se ha probado simulando su lógica en Spark local, pero no en un workspace real.
- `consultas.crear_conexion` usa SQLite en memoria: es solo para ejecución local y tests.
- Los importes ficticios no están calibrados con ninguna fuente real.
