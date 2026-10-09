# Métricas y fórmulas

Notación para un periodo: **X** = exportaciones, **M** = importaciones (suma de `importe_eur` por flujo), en euros.
Todas las divisiones usan `NULLIF(denominador, 0)`: si el denominador es 0 (o no hay datos) el resultado es `NULL`, no un error ni un infinito.
Un test comprueba que **toda división** de `sql/analitica/*.sql` va protegida, porque SQLite/DuckDB devuelven `NULL` pero Spark en modo ANSI (Databricks) lanza un error.

## Indicadores básicos

| Métrica | Fórmula | Notas |
|---|---|---|
| Comercio total | X + M | |
| **Saldo** | X − M | Positivo = superávit, negativo = déficit |
| **Tasa de cobertura** | 100 · X / M | 100 % = equilibrio. `NULL` si M = 0 o si no hay datos; 0 % si X = 0 y M > 0 |
| Peso, unidades, nº de operaciones | sumas del periodo | |

## Ventanas temporales y variación interanual

El filtro de fechas (`desde`, `hasta`, en meses `AAAA-MM`) define el **periodo actual** A. El **periodo previo** P es el mismo rango desplazado 12 meses (`desde−12m … hasta−12m`).
Si el rango dura más de 12 meses, A y P se solapan; cada fila de gold se evalúa por separado contra ambas ventanas (un error de esta clase lo encontró la implementación de referencia y está cubierto por pruebas).

| Métrica | Fórmula |
|---|---|
| Variación interanual (%) de X, M o X+M | 100 · (V_A − V_P) / V_P |
| Variación del saldo | (X_A − M_A) − (X_P − M_P), **en euros** |

- Es `NULL` si el periodo previo no tiene datos (p. ej. 2018, el primer año, o un año ausente) o si V_P = 0.
- El saldo se compara en euros porque un porcentaje sobre un saldo negativo, nulo o cercano a cero es engañoso.

## Series

- **Mensual** (`/serie/mensual`): el calendario sale de `dim_mes`, así que un mes sin operaciones aparece con `n_operaciones = 0` e importes `NULL` (no `0 €`).
  - *Acumulado del año* (YTD): suma desde enero del año natural hasta el mes, independientemente de `desde`; un mes sin datos suma 0. También se calculan saldo y cobertura acumulados.
  - *Variación interanual del mes*: contra el mismo mes del año anterior; y variación del acumulado contra el acumulado del año anterior.
- **Anual** (`/serie/anual`): suma de los meses del año **que caen dentro del periodo filtrado**, comparada con **los mismos meses** del año anterior (comparación homogénea aunque el último año esté incompleto). `meses_en_periodo` y `meses_con_datos` indican la cobertura; un año sin datos devuelve importes `NULL` y `meses_con_datos = 0`.

## Cuotas y ranking por dimensión (`/tabla`)

Para cada elemento i (país, producto, sector, subsector o región) con operaciones en el periodo:

| Métrica | Fórmula |
|---|---|
| Cuota de exportaciones | 100 · X_i / Σ X |
| Cuota de importaciones | 100 · M_i / Σ M |
| Cuota de comercio | 100 · (X_i + M_i) / Σ (X + M) |
| Ranking | `RANK()` por comercio total descendente (los empates comparten puesto) |

Los totales Σ son los de los elementos que cumplen los filtros. Solo aparecen elementos con operaciones en el periodo actual. La ordenación y la paginación se hacen en SQL (`ORDER BY … NULLS LAST, clave LIMIT … OFFSET …`).

## Top N + «Resto» (`/top`)

Se ordenan los elementos por la medida elegida (`exportaciones`, `importaciones`, `comercio_total` o `saldo`; sentido `desc`/`asc`, desempate por clave). Se devuelven los N primeros y una fila **«Resto»** (`clave = RESTO`, `es_resto = 1`) con la suma del resto de elementos, solo si los hay.
**Top N + Resto = total del periodo**, para cualquier medida (probado también con el saldo). `cuota_pct = 100 · valor / total`; no se define para el saldo (puede ser negativo) y vale `NULL`.

## Contribución al crecimiento (`/contribucion`)

Para una medida V (X, M, X+M o saldo) y el periodo actual frente al previo:

```
contribución_i (pp) = 100 · (V_i,A − V_i,P) / |T_P|        con  T = Σ_i V_i
crecimiento total (%) = 100 · (T_A − T_P) / |T_P|          = Σ_i contribución_i
variación_i (%) = 100 · (V_i,A − V_i,P) / |V_i,P|
```

- Se incluyen los elementos que operaron en cualquiera de las dos ventanas (uno que solo existía en el periodo previo aporta una contribución negativa).
- Se muestran los N elementos de mayor |variación| y una fila «Resto»; la suma de todas las contribuciones iguala el crecimiento total.
- **Saldos negativos**: los denominadores usan valor absoluto, de modo que el signo sigue indicando si la situación mejora (+) o empeora (−). Ejemplo (probado): saldo previo −200, actual −400 → variación −100 % (empeora); el total pasa de −200 a −350 → −75 %.
- Si T_P = 0 o no existe, contribución y crecimiento son `NULL`.

## Ranking anual (`/ranking`)

Para cada año natural completo entre el año de `desde` y el de `hasta`: posición por la medida elegida (`ROW_NUMBER`, desempate por clave), cuota del año y `cambio_posicion = posición_año_anterior − posición` (positivo = sube; `NULL` si el elemento no estaba el año anterior). A diferencia de las series, el ranking usa años naturales completos.

## Casos límite resueltos explícitamente

| Caso | Tratamiento |
|---|---|
| Importaciones = 0 | cobertura `NULL` |
| Exportaciones = 0 e importaciones > 0 | cobertura 0 %, saldo negativo |
| Periodo previo sin datos / base 0 | variaciones `NULL` |
| Mes o año sin operaciones | fila presente con `n_operaciones = 0` e importes `NULL`; el acumulado suma 0 |
| Filtros sin resultados | indicadores `NULL`, `n_operaciones = 0`, tablas y rankings vacíos |
| Saldo negativo | `ABS` en denominadores; variación del saldo en euros; cuota del saldo no definida |
| N mayor que el nº de elementos | no hay fila «Resto» |
| Total del periodo 0 | cuotas `NULL` |
