# Consumo desde herramientas de BI

La API no tiene autenticación ni TLS: es una demostración local. **No la expongas fuera de tu máquina sin añadir ambas.**

## Qué se ha probado y qué no

| | Estado |
|---|---|
| Los endpoints JSON devuelven listas de registros **planos y con las mismas columnas** (lo que necesita `Table.FromRecords`) | **Probado** (`test_json_plano_y_uniforme_apto_para_power_bi`) |
| El CSV (`/export/*.csv`) es UTF-8 con BOM, se lee con `pandas.read_csv` con tipos correctos y coincide con el JSON; `sep=;` y `bom=false` funcionan | **Probado** |
| Paginación, ordenación y filtros desde cliente HTTP (curl, `urllib`, navegador) | **Probado** |
| Conexión real desde **Power BI Desktop / Service** | **No probado** (no hay Power BI en este entorno) |
| Conexión desde **Report Builder / SSRS** | **No probado** |
| *Gateway*, actualización programada, credenciales, privacidad de datos | **No probado** |

Todo lo que sigue son **propuestas**.

## Power BI Desktop

### Opción A — API JSON (Conector Web)

*Obtener datos → Web → Avanzado*, o consulta en blanco con el editor avanzado:

```m
let
    Fuente = Json.Document(Web.Contents("http://localhost:8000/api/v1/serie/mensual",
                [Query = [desde = "2022-01", hasta = "2025-12", pais = "DE,FR"]])),
    Tabla  = Table.FromRecords(Fuente[datos]),
    Tipos  = Table.TransformColumnTypes(Tabla, {{"mes_inicio", type date}, {"exportaciones_eur", type number},
                                                {"importaciones_eur", type number}, {"saldo_eur", type number}})
in
    Tipos
```

Para `/tabla` hay paginación (máx. 500 filas por página); para traerlo todo usa el CSV.

### Opción B — CSV completo

```m
let
    Fuente = Csv.Document(Web.Contents("http://localhost:8000/api/v1/export/tabla.csv",
                [Query = [dimension = "pais", desde = "2024-01", hasta = "2024-12"]]),
                [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Cabecera = Table.PromoteHeaders(Fuente, [PromoteAllScalars = true])
in
    Cabecera
```

Los números llevan punto decimal; si tu configuración regional espera coma, indica la cultura al convertir tipos (`Table.TransformColumnTypes(..., "en-US")`).

### Opción C — Directo a Databricks (recomendada para uso real)

Con las tablas gold en Databricks (ver `docs/databricks.md`), el conector nativo *Databricks* de Power BI permite *DirectQuery* o importación sobre `hechos_mensual` y las dimensiones, y modelar las medidas en DAX o en un modelo semántico.

### Actualización en el Servicio de Power BI

Una URL `localhost` no es alcanzable desde el Servicio: haría falta una *puerta de enlace de datos local* o publicar la API en un servidor accesible (con autenticación). Con las opciones A y B habría que usar `RelativePath`/`Query` con una URL base fija para que la actualización programada funcione.

## Report Builder (informes paginados)

Report Builder no tiene un origen de datos JSON/REST nativo. Opciones propuestas:

1. **ODBC a un SQL Warehouse de Databricks** (controlador ODBC de Databricks): origen de datos *ODBC* y conjuntos de datos con las consultas de `sql/databricks/`. Es la vía más directa para informes paginados sobre estos datos.
2. **Conjunto de datos de Power BI** (informes paginados del Servicio de Power BI): construir primero el modelo semántico (opción C) y usarlo como origen.
3. **CSV intermedio**: descargar `/export/*.csv` y cargarlo en SQL Server/Excel para usarlo como origen. Manual y sin refresco automático.
4. El origen *XML* de Report Builder admite una URL, pero esta API no devuelve XML; habría que añadir un formato de salida XML.
