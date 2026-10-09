# Proyecto EBSA — Consumo de energía por cliente

> Para entender cómo funciona todo por dentro (flujo de datos, cada notebook, los cortes por zona, y cómo se evalúa: backtest, seguimiento en vivo y simulación), leer **`GUIA_TECNICA.md`**. Los comandos del día a día están en **`COMANDOS.md`**.

Análisis, agrupamiento, detección de caída y pronóstico del consumo eléctrico de los clientes de la Empresa de Energía de Boyacá (EBSA).

- **Clientes:** ~592.000 NIU.
- **Historia:** enero 2022 → abril 2026 (52 meses) en la extracción actual; crece un mes con cada archivo nuevo de la empresa.
- **Fuente:** los archivos mensuales XLSX/CSV que entrega la empresa (formato TC2), en `Datos_Ebsa\00_formato_TC2\`, y el archivo de usuarios atendidos por otros comercializadores, en `Datos_Ebsa\00_otros_comercializadores\`. **Nunca se modifican**: el pipeline los lee tal cual llegan.
- **Glosario:** los códigos del TC2 (ciclo, clase de servicio, tipo de medidor, tipo de lectura, tipo de factura) se traducen a texto con `utilidades_glosario.py` (tomado de `GLOSARIO_EBSA.xlsx`), y los perfiles técnicos P0–P4 se muestran como **grupos de consumo**: Intermitente, Pequeño (< 500 kWh/mes), Mediano (500–5.000), Grande (≥ 5.000) y Sin historia suficiente.

---

## 1. Qué entrega el proyecto (los tres productos)

El proyecto termina en **tres productos independientes**. Cada uno tiene su propio modelo final y sus propias salidas.

| Producto | Pregunta que responde | Notebooks | Salida principal |
|---|---|---|---|
| **A. Gestión de caída de consumo** | ¿Qué clientes están dejando de consumir, cuánto vale esa pérdida, en qué ciclo de lectura están y por dónde empieza la cuadrilla? Incluye, por cliente, si el modelo prevé que el **próximo mes** siga cayendo o se recupere. | 9 → 10 → 11 | `07_gestion_caida\gestion_caida_operativa.csv` y `gestion_caida_gerencial.csv` |
| **B. Pronóstico de consumo a 6 meses** | ¿Cuánto va a consumir cada cliente en cada uno de los próximos 6 meses? | 1 → 8 (el modelo se entrena en el 8) | `04_pronostico\modelo_final\predicciones_segmentadas_optimizadas_6_meses.parquet` |
| **C. Riesgo de fuga a otro comercializador** | ¿Qué clientes tienen más probabilidad de irse a otro comercializador en los próximos 6 meses, cuánto facturan hoy y quiénes ya se fueron? Aprende de los usuarios que la empresa reporta atendidos por otros comercializadores. | 14 | `10_riesgo_fuga\riesgo_fuga_clientes.csv` y `lista_riesgo_fuga_gerencial.csv` |

Los tres se entregan también **por grupo de consumo**, con nombres de negocio y las columnas del glosario, en `11_exportes_negocio\` (paso 15), que es lo que descarga la página.

El producto A **usa** una columna del producto B (`pred_1m_kwh`, el pronóstico del mes siguiente) para la trayectoria, por eso el notebook 8 se corre antes que el 11.

Alrededor de los dos productos hay tres piezas que los mantienen honestos mes a mes: el **seguimiento** (notebook 12: cada pronóstico y cada lista anteriores contra lo que realmente pasó), la **retroalimentación de campo** (notebook 13: lo que encontraron las cuadrillas contra la lista) y la **compuerta de calidad** del archivo entrante (notebook 2). Todo se corre con un solo comando (`pipeline_mensual.py`, §7) y se consulta en una página web (`app_ebsa.py`, §10).

---

## 2. Rutas principales

Dos carpetas, separadas a propósito: el **código** en GitHub y los **datos** en Documentos. Son carpetas nuevas: el proyecto anterior (`Datos Ebsa` y la raíz de `GitHub\ProyectoEBSA`) queda intacto y los dos no se mezclan.

| Qué | Ruta | Dónde se define |
|---|---|---|
| **Código** (15 notebooks, `utilidades_borde.py`, `utilidades_calidad.py`, `utilidades_glosario.py`, `pipeline_mensual.py`, `app_ebsa.py`, `preparar_carpeta_datos.py`) | `C:\Users\Home\Documents\GitHub\ProyectoEBSA\Pipeline_Ebsa` | Es donde se abren los notebooks y desde donde se corren los scripts. Los tres `utilidades_*.py` **deben estar en esta misma carpeta** para que el `import` funcione. |
| **Datos** (archivos de la empresa, intermedios, modelos, salidas) | `C:\Users\Home\Documents\Datos_Ebsa` | Variable `BASE_DIR` (o `DATA_DIR` en Exploración) en la primera celda de cada notebook, y `DATOS_POR_DEFECTO` en los scripts. Todos la leen primero de la variable de entorno `EBSA_DATOS` y, si no existe, usan esta ruta. |

Estructura completa de la carpeta de datos:

```
C:\Users\Home\Documents\Datos_Ebsa\
│
├── 00_formato_TC2\                ← los XLSX/CSV mensuales de la empresa (formato TC2). NO SE TOCAN. Entrada del paso 1.
├── 00_otros_comercializadores\    ← el XLSX de la empresa con los usuarios atendidos por otros comercializadores. NO SE TOCA. Entrada del paso 14.
├── 01_historico_procesado\        ← Paso 1 (Exploración): historico_2022.parquet ... historico_2026.parquet
│   └── detalle_mensual\              (detalle factura a factura, por archivo; solo auditoría)
├── 02_serie_reconstruida\         ← Paso 2 (Reconstrucción rural) + control_calidad_mes_entrante.csv
│   └── copia_historicos\             (copia de trabajo de los historico_YYYY)
├── 03_serie_modelado\             ← Paso 3 (Preprocesamiento)   ★ ENTRADA DE TODOS LOS MODELOS
├── 04_pronostico\
│   ├── desarrollo_01_modelo_unico\   ← Notebook 4 (primer modelo, sin segmentar) — referencia
│   ├── desarrollo_02_segmentado\     ← Notebook 5 (modelo segmentado v1) — referencia
│   └── modelo_final\                 ← Notebooks 6, 7 y 8   ★ MODELO FINAL DE PRONÓSTICO
│       └── historial_pronosticos\       (una copia del pronóstico por fecha de corte)
├── 05_segmentos_clientes\         ← Paso 9    ★ MODELO FINAL DE AGRUPAMIENTO
├── 06_estudio_caida\              ← Paso 10   ★ CRITERIOS FINALES DE CAÍDA
├── 07_gestion_caida\              ← Paso 11   ★ LISTAS FINALES PARA GESTIÓN
│   ├── historial\                    (una copia de la lista operativa por corte)
│   └── retroalimentacion\            (plantilla y resultados de las visitas; Paso 13)
├── 08_seguimiento\                ← Paso 12   ★ PRECISIÓN EN VIVO Y QUÉ PASÓ CON LAS LISTAS
├── 09_registro_corridas\          ← pipeline_mensual.py: un registro por corrida (notebooks ejecutados + resumen)
├── 10_riesgo_fuga\                ← Paso 14   ★ RIESGO DE FUGA A OTRO COMERCIALIZADOR (modelo, listas, seguimiento)
│   └── historial\                   (una copia de la lista de riesgo por corte)
└── 11_exportes_negocio\           ← Paso 15   ★ ARCHIVOS POR GRUPO DE CONSUMO PARA DESCARGAR (pronóstico, caída, fuga)
    ├── pronostico_6_meses\
    ├── lista_caida\
    └── riesgo_fuga\

C:\Users\Home\Documents\GitHub\ProyectoEBSA\
└── Pipeline_Ebsa\                 ← EL CÓDIGO: 15 notebooks, utilidades_*.py, pipeline_mensual.py, app_ebsa.py (página original),
                                     app_ebsa_v2.py + componentes_v2.py + recursos_v2\ (página con interfaz nueva)
```

`python preparar_carpeta_datos.py` (desde `Pipeline_Ebsa`) crea las carpetas vacías de `Datos_Ebsa` y dice qué copiar del proyecto anterior (§7.0).

---

## 3. Modelos y archivos finales para la página web

Esto es lo que una aplicación web debe **leer**. Todo lo demás del proyecto es intermedio o de auditoría.

### 3.1 Producto A — Gestión de caída (lo que se muestra)

Carpeta: `Datos_Ebsa\07_gestion_caida\`

| Archivo | Para qué sirve en la página |
|---|---|
| `gestion_caida_operativa.csv` | **Vista por ciclo.** Un cliente por fila, ordenado por ciclo (00–99) y, dentro del ciclo, por valor en riesgo. Es la lista que usa una cuadrilla. |
| `gestion_caida_gerencial.csv` | **Vista gerencial.** Los mismos clientes ordenados por valor en riesgo de mayor a menor, con `ranking` global. |
| `resumen_gestion_por_ciclo.csv` | Total de clientes, kWh y pesos en riesgo por ciclo, con % acumulado. Sirve para el gráfico "qué ciclos concentran el riesgo". |
| `resumen_gestion_por_corte.csv` | Los mismos totales por `estrato`, `clase_servicio`, `tramo_consumo` y `zona`. |
| `diagnostico_sesgo_pronostico.csv` | Explica si la trayectoria se calculó también para rurales (brecha de sesgo rural vs urbano). |
| `auditoria_tarifa.csv` | Cuántos clientes tienen tarifa real y cuántos no. |
| `clientes_cero_sostenido.csv` | Los clientes en cero o casi cero sostenido que se retiraron de la lista (regla de §3.2b-bis): `consumo_reciente_kwh`, `consumo_max_mes_ventana_kwh` (el mes más alto de su ventana), `umbral_casi_cero_kwh`, `consumo_referencia_kwh` y `valor_facturaba_antes_mes` (lo que consumían y facturaban antes), `ultimo_mes_con_consumo`, `meses_en_cero` y `motivo` (cero exacto o casi cero). Alimenta la sección *Clientes sin consumo* de la página. |
| `clientes_excluidos_de_gestion.csv` | Los clientes de clases sin gestión (AC, AU, RI, PR) retirados de la lista. |
| `resumen_entradas_salidas_lista.csv` | Una fila por corte: cuántos clientes permanecen, salieron y entraron frente al corte anterior. |
| `historial\gestion_caida_operativa_corte_AAAA-MM.csv` | La lista operativa de cada corte, tal como se entregó. No se sobreescribe. |
| `retroalimentacion\resultado_gestion_plantilla.csv` | Plantilla para que la empresa registre las visitas (§9). |
| `retroalimentacion\evaluacion_retroalimentacion_resumen.csv` | Precisión de la lista por corte, severidad, trayectoria, estado, tramo, zona, segmento y ciclo (cuando hay visitas registradas). |

Columnas de las listas operativa y gerencial (las que la página debe interpretar):

| Columna | Significado |
|---|---|
| `ciclo_etiqueta`, `orden_en_ciclo` | Ciclo de lectura (00–99, `SIN_CICLO` si no se conoce) y posición del cliente dentro de su ciclo. |
| `NIU` | Identificador del cliente. |
| `zona`, `clase_servicio`, `estrato`, `tramo_consumo` | Urbano/Rural, tipo de servicio, estrato, tamaño (`BAJO` <30 kWh, `MEDIO` 30–99, `ALTO` 100–299, `GRANDE` ≥300). |
| `cluster_id` | Segmento de negocio al que pertenece (ver §5.6). |
| `veredicto` | `CAIDA_CONFIRMADA` (cae vs. periodo anterior **y** vs. año pasado) o `CAIDA_SOSTENIDA` (venía cayendo y sigue). Solo estos dos entran a gestión. |
| `severidad` | `CRITICA` / `FUERTE` / `MODERADA`, relativa a lo normal de su segmento. |
| `consumo_anterior_kwh`, `consumo_reciente_kwh`, `perdida_kwh_mes` | Consumo medio mensual antes, ahora, y la diferencia. |
| `tarifa_kwh`, `tiene_tarifa` | **Tarifa real** ($/kWh) aplicada a ese cliente en su última factura. Nunca se estima: si no hay, `tiene_tarifa = False`. |
| `valor_riesgo_mes` | `perdida_kwh_mes × tarifa_kwh`, en pesos/mes. **Vacío** si no hay tarifa (no se inventa). Desde el 2026-10-08 `perdida_kwh_mes` es coherente con el veredicto: contra el año pasado en `CAIDA_SOSTENIDA`, y la **menor** de las dos referencias en `CAIDA_CONFIRMADA` (antes era siempre la mayor de las dos, lo que inflaba el valor con acumulados o refacturaciones de hace un año). El estudio de caída conserva la mayor en `perdida_maxima_kwh_mes` y marca `referencia_anio_muy_superior` cuando el año pasado triplica al periodo anterior. |
| `valor_orden` | Solo para ordenar (los sin tarifa no se hunden al fondo). No mostrarlo como valor. |
| `variacion_vs_anterior_pct`, `variacion_vs_anio_pct` | Variación % del consumo reciente contra el periodo anterior y contra el mismo periodo del año pasado. |
| `meses_ventana` | 3 (lectura mensual) o 6 (lectura trimestral/rural). |
| `trayectoria` | Qué prevé el modelo para el **mes siguiente**: `CAIDA_ACELERANDO` (seguirá bajando más allá del error del modelo), `SIN_RECUPERACION_PREVISTA` (se queda donde está), `RECUPERACION_PREVISTA` (sube más que el error del modelo **y** el pronóstico lo devuelve al menos a la mitad de lo que consumía antes de caer, con un mínimo de 10 kWh; una subida que no llega a ese nivel queda `SIN_RECUPERACION_PREVISTA`), `NO_EVALUABLE_RURAL` (rural excluido por sesgo), `SIN_PRONOSTICO` (el cliente no tiene predicción). |
| `pred_1m_kwh`, `variacion_proyectada_pct`, `wape_aplicable_pct` | Pronóstico del próximo mes, su variación contra el consumo reciente, y el error del modelo (WAPE h=1 de su perfil) usado como umbral. |
| `estado_en_lista` | `NUEVO` (primera vez en la lista), `PERSISTENTE` (también estaba en el corte anterior), `REINCIDENTE` (estuvo en algún corte de los últimos 12 meses, pero no en el anterior). Sale de cruzar con `historial\`; la racha se cuenta sobre los cortes que existen (en operación mensual, el mes anterior). |
| `meses_consecutivos_en_lista`, `veces_en_lista_12m` | Cuántos meses seguidos lleva en la lista (1 = solo este) y cuántas veces apareció en los últimos 12 cortes. |
| `fecha_corte` | Mes de corte de la lista (fin de la ventana del estudio de caída). Es la clave para el historial y para la retroalimentación. |

### 3.2 Producto B — Pronóstico a 6 meses (lo que se muestra)

Carpeta: `Datos_Ebsa\04_pronostico\modelo_final\`

| Archivo | Contenido |
|---|---|
| `predicciones_segmentadas_optimizadas_6_meses.parquet` | **Una fila por cliente**, con `pred_1m_kwh` … `pred_6m_kwh` y sus fechas `fecha_pred_1m` … `fecha_pred_6m`, `promedio_pred_3m_kwh`, `promedio_pred_6m_kwh`, `perfil`, `modelo_Xm` (algoritmo usado), `alpha_ml_Xm` (peso del ML vs. la línea base), `fecha_corte`, `regimen_actual` (`observado` = leído ese mes; `reconstruido` = viene de una lectura trimestral repartida). |
| `predicciones_segmentadas_optimizadas_3_meses.parquet` | Igual, solo horizontes 1–3. |
| `metricas_sistema_por_perfil_horizonte_optimizado.csv` | Error esperado (WAPE %) por perfil y horizonte. **Lo que se debe mostrar como "precisión" del pronóstico.** |
| `metricas_sistema_ganador_backtest_optimizado.csv` | Error global por horizonte en el backtest. |
| `real_vs_pronosticado_sistema_optimizado_backtest.parquet` | Real vs. pronosticado del backtest, para gráficas de "cómo le fue al modelo". |

### 3.2b Producto C — Riesgo de fuga a otro comercializador (lo que se muestra)

Carpeta `10_riesgo_fuga\` (notebook 14). Todo con corte en el último mes consolidado, el mismo de la lista de caída.

| Archivo | Qué es |
|---|---|
| `riesgo_fuga_clientes.csv` | Todos los clientes puntuados: `prob_fuga_6m` (probabilidad de fuga en los próximos 6 meses, calibrada con lo observado en validación y con tope en el máximo comprobado), `puntaje_modelo` (el puntaje que ordena y define los niveles; desempata a los clientes que comparten el tope de probabilidad), `nivel_riesgo` (ALTO / MEDIO / BAJO), `valor_en_riesgo_mes` (consumo promedio 6 meses × tarifa **real**; sin tarifa queda vacío), `valor_esperado_perdida_mes` (probabilidad × valor; es el orden del `ranking`), `senales` (en texto: caída reciente, meses en cero, zona con más salidas, tamaño), zona y clase en texto, grupo de consumo, tipo de medidor y de lectura, promedio semestral, recurrencia frente a cortes anteriores (`estado_en_lista`). |
| `lista_riesgo_fuga_gerencial.csv` | Solo ALTO y MEDIO, ordenados por pérdida esperada. `lista_riesgo_fuga_por_zona.csv`: los mismos, por zona y probabilidad. |
| `clientes_con_otro_comercializador.csv` | Los NIU del archivo de la empresa, con su estado (`CON OTRO COMERCIALIZADOR`, `REGRESÓ A EBSA`, `SIN HISTORIA EN TC2`), comercializador, municipio, mes de salida y de dónde se dedujo, y lo que facturaban antes de irse. |
| `vigilancia_mercado_no_regulado.csv` | Ciclo 33 (USUARIOS NO REGULADOS), clase IR o consumo ≥ 55.000 kWh/mes: por tamaño pueden negociar con cualquier comercializador. **Se puntúan aparte y no entran al ranking ni a las listas** (decisión 2026-10-02): traen `motivo`, `estado` (PUNTUADO fuera del ranking / YA CON OTRO COMERCIALIZADOR / SIN PUNTUAR), `nivel_riesgo` (solo por probabilidad) y `prob_fuga_6m`. |
| `perfil_clientes_que_se_fueron.csv` | Cómo son los que se fueron: por clase, zona, tamaño, comercializador y municipio. |
| `resumen_riesgo_fuga_por_zona.csv`, `resumen_riesgo_fuga_por_grupo.csv` | Cuántos ALTO/MEDIO y cuánta pérdida esperada por zona y por grupo de consumo. |
| `metricas_modelo_fuga.csv`, `importancia_variables_fuga.csv`, `hiperparametros_fuga.json`, `optuna_ensayos_fuga.csv` | Calidad del modelo evaluada por cortes en el tiempo (AUC, precisión y *lift* en el top 50/100/200/500), con las filas del modelo (parámetros fijos conservadores), de la referencia "ordenar por consumo de 12 meses" y por cliente distinto; qué variables pesan; los parámetros usados; y los 30 ensayos de Optuna, que desde el 2026-10-08 son solo un análisis de sensibilidad y no eligen el modelo. |
| `seguimiento_riesgo_fuga.csv` | Para cada corte anterior: de los señalados ALTO/MEDIO, qué % efectivamente se fue en sus 6 meses, frente a la tasa base. |
| `historial\riesgo_fuga_corte_AAAA-MM.csv` | Copia de cada corte (no se sobreescribe). |

**Población.** Se puntúan las clases de servicio que aparecen entre los que ya se fueron (hoy comercial, industrial, oficial, acueductos y no regulados), sin alumbrado público, provisionales, ciclos internos (15, 90, 91, 94, 96, 98, 99) ni autogeneradores (ciclo 50 **actual**). Si el archivo trae algún día un residencial, la población se amplía sola. Los que ya están con otro comercializador o en cero sostenido no se puntúan: van en `clientes_con_otro_comercializador.csv`. El mercado no regulado (ciclo 33, clase IR o ≥ 55.000 kWh/mes) se puntúa con el mismo modelo pero queda **fuera de `riesgo_fuga_clientes.csv`, del ranking, de las listas, de los resúmenes y de los exportes**: solo aparece en `vigilancia_mercado_no_regulado.csv`, porque su seguimiento es comercial y no de cuadrilla.

**Cómo se ve una salida en TC2.** En los datos reales, el cliente que se cambia **no desaparece**: sigue apareciendo con 0 kWh y solo meses después deja de estar en el archivo. Por eso el mes de salida es el más temprano entre su primer mes en el archivo de otros comercializadores, su primer mes de consumo cero sostenido (≥ 3 meses) y el mes siguiente a su última fila; y si algún día el TC2 trae el ciclo 97 (OTROS COMERCIALIZADORES), cuenta automáticamente.

**Cambios del 2026-10-09 (segunda ronda de revisión).** (1) *Redacción*: la página habla de **probabilidad de fuga**, nunca de clientes que "se van a ir"; la sección de Comercial se llama *Clientes con probabilidad de fuga* y la columna de señales, *Señales observadas*. (2) *Recurrencia en fuga*: PERSISTENTE se cuenta sobre los cortes guardados que existen (misma regla que la lista de caída); antes salía siempre 0. (3) `riesgo_fuga_clientes.csv` guarda `puntaje_modelo`. (4) *Paso 13*: una visita de un cliente rural (cuyo `fecha_corte` es el de su zona, no el de la corrida) ya no detiene el pipeline. (5) *Proyección anual*: la etiqueta CONFIABLE / ORIENTATIVO de cada escenario usa el error de su propio modelo (la página además la recalcula, así que vale aunque el archivo sea anterior). (6) *Página, memoria*: las tablas se guardan una sola vez en caché y cada pantalla recibe una vista liviana; en la prueba con un usuario, la memoria del servidor pasó de superar 6 GB tras unas 15 secciones (y caerse) a mantenerse entre 0,7 y 1,5 GB en las 24 secciones. La sección *Descargas* lee solo el archivo que se elige. (7) *Página, textos*: cabecera de Panorama con el total y lo que hay para gestionar ahora; mensaje claro cuando el NIU no existe o un filtro deja la lista vacía; se acepta un NIU pegado desde Excel con ".0"; un cliente estacional muestra "Estacional" en vez de gravedad; la clave de ejemplo "CAMBIAR" no abre sesión; tabla del modelo frente a pronósticos simples en *Pronóstico 6 meses*.

**Correcciones del 2026-10-08 (revisión independiente).** (1) *Parámetros fijos y conservadores* (`PARAMS_CONSERVADORES`: 200 árboles, 7 hojas, hojas de al menos 100 clientes): con ~80 clientes que se fueron, elegir hiperparámetros con Optuna sobre la misma validación que se reporta daba una cifra optimista (el "mejor de 30 ensayos" movía la precisión del top 100 entre 0 % y 12 % según la corrida). Optuna se conserva solo como análisis de sensibilidad (`optuna_ensayos_fuga.csv`). (2) *Cada cliente que se fue pesa lo mismo* (`pesar_positivos_por_niu`): antes cada uno aparecía en 4–5 filas casi idénticas y el modelo los memorizaba. (3) *Probabilidad calibrada*: el puntaje del modelo ordena, pero no es una probabilidad; un calibrador ajustado con predicciones fuera de muestra lo lleva a la fracción que realmente se fue en validación (queda guardado en el `.joblib`). Es una curva logística continua: la primera versión era isotónica y, con tan pocos casos, daba tres o cuatro escalones (todos los clientes de un tramo mostraban la misma cifra). Tiene un tope: un puntaje mayor que el máximo visto en validación recibe la probabilidad de ese máximo, porque más allá no hay casos observados. (4) *Niveles por cupo*: ALTO = el 1 % con mayor puntaje, MEDIO = hasta el 5 %, siempre con probabilidad ≥ tasa base. (5) *Líneas base en `metricas_modelo_fuga.csv`*: "ordenar por consumo de 12 meses" (por fila, por cliente distinto y solo entre clientes ≥ 500 kWh/mes) y métricas por cliente distinto. **Lectura honesta:** el modelo **no ordena mejor** que listar a los clientes por tamaño (AUC 0,961 del modelo contra 0,979 de ordenar por consumo de 12 meses; por cliente distinto, precisión promedio 0,038 contra 0,040); sirve como lista de clientes grandes con señales para priorizar contactos, no para predecir quién se va. Por eso la página habla de *probabilidad de fuga* y nunca de clientes que "se van a ir", y la pérdida esperada se presenta como orden de magnitud. (6) *Clientes con sus tres últimos meses en cero* ya no se puntúan (`es_activo`). (7) *Seguimiento*: cuando la lista es posterior al último mes del archivo de otros comercializadores, `seguimiento_riesgo_fuga.csv` dice `observable = NO` y deja vacías las salidas, en vez de escribir 0 %.

**Validación (2026-10-06).** El modelo se evalúa por cortes en el tiempo; desde esta fecha los cortes de validación entran **sin submuestreo de negativos** (antes iban al ~17 %, lo que inflaba la precisión y el *lift* del top 100), y la variable `tasa_salida_zona` se calcula **en cada corte** solo con las salidas conocidas hasta ese mes (antes era una sola tasa con todo el archivo, igual en todos los cortes).

**Niveles (por cupo, desde el 2026-10-08).** ALTO: el 1 % con mayor puntaje del modelo; MEDIO: hasta el 5 %; en ambos casos solo clientes con probabilidad al menos igual a la tasa base. Así siempre hay una lista corta y de tamaño estable para trabajar. En la vigilancia de no regulados (fuera del ranking) el nivel se asigna solo por probabilidad.

### 3.2b-bis Reglas de negocio de las listas (experto de negocio, 2026-10-02; ajuste del equipo, 2026-10-07)

- **Clases sin gestión**: área común (AC), autoconsumos EBSA (AU), distritos de riego (RI) y provisionales (PR) no entran a la lista de caída ni al riesgo de fuga (`CLASES_SIN_GESTION` en `utilidades_glosario.py`). Siguen en la serie y en el pronóstico. El notebook 11 deja los retirados en `07_gestion_caida\clientes_excluidos_de_gestion.csv`.
- **Cero sostenido (cero o casi cero)**: un cliente cuyo consumo no pasa, en **ningún mes** de su ventana reciente (3 meses los de lectura mensual, 6 los rurales de lectura trimestral), del mayor entre **10 kWh** y el **5 % de lo que consumía** (la mayor referencia entre el periodo anterior y el mismo periodo del año pasado) ya no consume (retiro, suspensión, predio desocupado) y no es una caída para revisar; el notebook 11 lo saca de la lista y lo deja en `07_gestion_caida\clientes_cero_sostenido.csv` con lo que facturaba antes (referencia conservadora, ver más abajo), y la página lo muestra en *Clientes sin consumo*. La condición es mes a mes, no sobre el promedio de la ventana: un cliente con dos meses en 0 y uno en 25 kWh sigue en la lista. La ventana termina en el corte de la zona de cada cliente, así que el mes provisional de los rurales no cuenta. El umbral es el mismo de la regla de cero sostenido del pronóstico (§3.2d). Hasta el 2026-10-06 la regla exigía consumo exactamente 0, y un industrial que pasó de 7.000 a 2–3 kWh seguía en la lista como caída con "recuperación prevista"; el ajuste del 2026-10-07 lo corrige. En el corte 2026-04 son 8.390 clientes (2.758 en cero exacto y 5.632 en casi cero) que facturaban $602,5 M/mes con la referencia actual (antes del cambio de referencia del 2026-10-08 esa cifra era $1.249 M/mes) y que inflaban la "facturación en riesgo"; la lista queda en 29.057 clientes. **El modelo de riesgo de fuga no cambia**: su etiqueta de salida sigue usando el cero exacto sostenido (≥ 3 meses), porque ahí se busca el momento en que el cliente dejó de ser facturado, no una caída sin gestión.
- **Estacionales**: un cliente que en los últimos 24 meses, **antes de la ventana de su caída actual**, ya estuvo en cero (≤ 10 % de su mediana) y volvió a consumir, es estacional si además se cumple una de tres cosas: el pronóstico prevé recuperación al mes siguiente, el pronóstico prevé el repunte en alguno de los 6 meses siguientes (al menos la mitad del nivel previo y 10 kWh), o los mismos meses del año pasado también fueron bajos (al menos 2 de cada 3 casi en cero). Su "caída" es temporada baja; el motivo queda en la columna `motivo_estacional` (desde el 2026-10-07 la caída actual no puede ser su propia prueba de estacionalidad; la segunda y la tercera condición se añadieron el 2026-10-08 porque exigir la recuperación al mes siguiente dejaba como urgentes a clientes de temporada). Sigue en la lista con `prioridad_gestion = VIGILAR: estacional` (y `VIGILAR: se espera recuperación` para los no estacionales con recuperación prevista), al final de su ciclo y del ranking; la página los muestra con esa prioridad y las visitas por ciclo los ocultan por defecto. Columnas `estacional`, `prioridad_gestion` (`GESTIONAR`, `SEGUIMIENTO: caída antigua`, `VIGILAR: se espera recuperación`, `VIGILAR: estacional`).
- **Caídas antiguas en seguimiento** (2026-10-07): un cliente con veredicto `CAIDA_SOSTENIDA` no cae frente a su periodo anterior; cayó hace meses frente al año pasado y se quedó en ese nivel (por ejemplo, de 8.500 a 1.800 kWh hace medio año). La pérdida es real y se sigue contando en la facturación que se está perdiendo, pero no es urgente: queda con `prioridad_gestion = SEGUIMIENTO: caída antigua`, detrás de `GESTIONAR` y antes de los `VIGILAR` en el orden de cada ciclo y en el ranking. Desde el 2026-10-08 esto vale para todas las caídas antiguas, también las que el pronóstico ve seguir bajando (columna `caida_antigua_sigue_bajando`): `GESTIONAR` queda solo para caídas recientes. En la página, una caída antigua tampoco se muestra como "Grave": su gravedad aparece como "Antigua (lleva meses así)" y "Grave" queda para caídas recientes (la severidad original sigue en el archivo y en la vista técnica). Las cifras por prioridad de cada corte están en `resumen_gestion_por_corte.csv` y en la salida del paso 11. En la página, *Consumía* y *Caída* se muestran frente a la referencia con la que se midió la pérdida (la mayor entre el periodo anterior y el mismo periodo del año pasado), hay columna y filtro *Tipo de caída* (Reciente / Lleva meses así) y las listas muestran por defecto solo `GESTIONAR`.
- **"Se prevé que baje más" (`CAIDA_ACELERANDO`), corregido el 2026-10-09 (revisión, ronda 2).** Antes se marcaba cuando el pronóstico del mes siguiente quedaba por debajo del **promedio de la ventana reciente** en más que el error del modelo; en un cliente que ya venía bajando dentro de la ventana, su último mes está por debajo de ese promedio, así que un pronóstico igual o mayor que su último mes salía como "sigue bajando". Ahora exige que el pronóstico quede por debajo del **último mes consolidado** (columna nueva `consumo_ultimo_mes_kwh`; la variación queda en `variacion_vs_ultimo_mes_pct`) en más que el error del modelo. La recuperación prevista se evalúa primero y no cambia, así que **no cambian ni el tamaño de la lista ni las prioridades**; solo baja el número de clientes con esa tendencia (el paso 11 imprime cuántos eran con la regla anterior y cuántos con la actual). El seguimiento (paso 12) usa la misma base para `SIGUE_CAYENDO` en las listas generadas desde esa fecha; las listas guardadas anteriores no traen el último mes y se siguen midiendo contra el promedio de su ventana.
- **"Facturaba antes" de los clientes sin consumo.** Es la referencia con la que se midió la caída según el veredicto (en una caída confirmada, la menor entre el periodo anterior y el año pasado), no el máximo que el cliente llegó a facturar; el umbral de "casi cero" sí usa la mayor de las dos. Es una cifra conservadora.
- **Niveles de fuga**: el "top 1 % / 5 %" solo aplica a clientes con probabilidad ≥ tasa base; nadie por debajo del riesgo promedio queda en ALTO o MEDIO (antes, con el ranking plano, un cliente con 0,004 % podía salir MEDIO). La página muestra la probabilidad con decimales útiles y llama "factura promedio 6 meses" a lo que antes decía "factura hoy".
- **Autogeneradores** (ciclo 50 actual): fuera de todo el universo (sección 5.3).
- **Zona regional**: columna `zona_regional` en todas las listas (`ZONA_REGIONAL_POR_CICLO`): CENTRO = ciclos 0, 9, 10, 19; TUNDAMA = 1, 11; SUGAMUXI = 2, 12; OCCIDENTE = 3, 22; ORIENTE = 4, 13; NORTE = 5, 21; RICAURTE = 6, 23; PUERTO BOYACÁ = 7, 38. Es la dirección regional que decide las acciones en terreno; el ciclo detallado se conserva para las cuadrillas. La página filtra y resume por zona regional.
- `verificar_corrida.py` marca ERROR si alguna clase sin gestión o un autogenerador aparece en las listas, o un no regulado en el ranking de fuga.

### 3.2c Exportes por grupo de consumo (lo que descarga la página)

Carpeta `11_exportes_negocio\` (notebook 15): `pronostico_6_meses\pronostico_6_meses_<grupo>.csv`, `lista_caida\lista_caida_<grupo>.csv`, `riesgo_fuga\riesgo_fuga_alto_y_medio_<grupo>.csv` y `riesgo_fuga_todos_los_puntuados_<grupo>.csv`, más uno `_todos_los_grupos` por producto, e `indice_exportes.csv` con archivo, grupo, filas y corte. Los grupos son: Intermitente (mediana 12 meses ≤ 10 kWh o ≥ 50 % de meses en cero), Pequeño (10–500 kWh/mes), Mediano (500–5.000), Grande (≥ 5.000) y Sin historia suficiente (< 6 meses válidos). Todas las listas traen `zona_nombre`, `clase_servicio_nombre`, `grupo_consumo`, `tipo_medidor_nombre`, `tipo_lectura_nombre`, `consumo_promedio_semestral_kwh`, `valor_facturado_mes` y `valor_facturado_origen` (dato del TC2, columna Q, cuando el histórico lo trae; si no, consumo × tarifa real del cliente — nunca una tarifa imputada).

### 3.2d Regla de cero sostenido en el pronóstico

Un cliente no intermitente (mediana de 12 meses ≥ 100 kWh) con sus **dos últimos meses consolidados por debajo del 5 % de su mediana** no tiene evidencia de recuperación; la línea base estacional y el modelo de los grandes tendían a "resucitarlo" porque hace un año consumía. Para esos clientes el pronóstico de los 6 meses es persistencia del último valor y la columna `modelo_Nm` dice `REGLA_CERO_SOSTENIDO`. Se aplica también en el backtest (las métricas la reflejan), no aplica a intermitentes ni a meses rurales provisionales, y deja de aplicar sola el mes que vuelva a haber consumo. Efecto en la lista de caída: esos clientes ya no salen como "RECUPERACION_PREVISTA".

### 3.2e Versiones de los modelos (`12_versiones_modelos\`)

Cada reentrenamiento guarda una copia del modelo con el corte en el nombre (`pronostico_corte_AAAA-MM.joblib`, `agrupamiento_...`, `criterios_caida_...`, `riesgo_fuga_...`) y una fila en `registro_versiones.csv`; cada corrida anota en `registro_uso.csv` qué versión usó para qué corte. `pipeline_mensual.py --modo aplicar --version-modelo AAAA-MM` corre con una versión concreta (para volver atrás o para comparar). El seguimiento (`08_seguimiento`) trae `fecha_corte_modelo` y `meses_desde_entrenamiento` en cada fila, que es lo que permite ver el deterioro por versión.

### 3.3 Seguimiento — precisión en vivo (lo que se muestra)

Carpeta: `Datos_Ebsa\08_seguimiento\` (notebook 12). Se llena mes a mes: solo puede evaluar meses que ya quedaron consolidados, así que en la primera corrida está vacío.

| Archivo | Contenido |
|---|---|
| `seguimiento_pronostico_global.csv` | Por fecha de corte y horizonte: `WAPE_pct` (error real del pronóstico contra lo que pasó), `sesgo_pct` (+ = pronosticó de más), `n`. **Es la precisión en vivo**, distinta del backtest. |
| `seguimiento_pronostico_por_perfil.csv` | Lo mismo por perfil, con `WAPE_backtest_pct` y `dif_vs_backtest_pp` al lado: si esa diferencia es claramente positiva varios meses seguidos, toca reentrenar. |
| `seguimiento_pronostico_por_zona.csv` | Lo mismo por rural / urbano. |
| `seguimiento_lista_gestion.csv` | Qué pasó con los clientes de cada lista en los meses siguientes: `RECUPERADO` (volvió al 90 % del nivel contra el que se midió su caída: periodo anterior o mismo periodo del año pasado, el que originó el veredicto), `ESTABLE_BAJO` (se quedó en el nivel caído), `SIGUE_CAYENDO` (bajó del 90 % del promedio de su ventana reciente). Por trayectoria, veredicto, severidad y zona. Desde el 2026-10-08 cada lista de zona y cada pronóstico se cuentan una sola vez (antes los rurales entraban dos veces cuando su corte no avanzaba) y la recuperación ya no se mide contra el periodo anterior, que en una caída sostenida es casi igual al reciente. No hay grupo de control: son porcentajes descriptivos; lo que sí muestran es que la trayectoria ordena bien (los `CAIDA_ACELERANDO` siguen cayendo mucho más que los demás). |

### 3.4 Modelos entrenados (lo que la página carga si necesita **volver a predecir**)

Si la página solo muestra las salidas ya calculadas, no necesita cargar modelos. Los necesita si va a puntuar clientes nuevos o el mes nuevo sin correr los notebooks.

| Modelo | Ruta | Qué contiene | Cómo se usa |
|---|---|---|---|
| **Pronóstico (final)** | `04_pronostico\modelo_final\modelos_ganadores_optimizados_final.joblib` | Diccionario con `modelos[(perfil, h)]` (un modelo por perfil × horizonte 1–6, LightGBM/XGBoost/CatBoost), `mapa_seleccion_optimizado` (qué algoritmo y qué `alpha_ml` usa cada grupo), `hiperparametros`, `features` (lista y orden exacto de columnas de entrada), `config_perfiles` (umbrales para clasificar clientes en P0–P4), `fecha_corte`, `horizontes`. | `import joblib; b = joblib.load(ruta); b["modelos"][("P1_REGULAR", 1)]`. Las features se construyen igual que en el notebook 8 (funciones `calcular_perfiles`, `crear_features`, `baseline_hibrido`); el pronóstico final es `alpha_ml × pred_ml + (1 − alpha_ml) × baseline`. |
| Pronóstico — hiperparámetros | `...\hiperparametros_optimos_por_grupo.json` | Los mismos hiperparámetros, legibles. | Auditoría / reentrenar. |
| Pronóstico — selección | `...\seleccion_modelo_por_perfil_horizonte_optimizada.csv` | Qué algoritmo ganó en cada perfil × horizonte y con qué `alpha_ml`. | Mostrar "qué modelo se usa para cada grupo". |
| **Agrupamiento (final)** | `05_segmentos_clientes\modelo_agrupamiento.joblib` | Diccionario con, por zona (`URBANO`, `RURAL`): `modelo` (clustering), `scaler` (RobustScaler), `limites_winsor` (recorte p1–p99), `mapa_segmentos` (cluster → nombre de negocio). Además `columnas_clustering` (orden exacto), `catalogo_segmentos` (nombre → acción y prioridad), `tramos_consumo`, `umbrales_negocio`, `semilla`, `ventana`. | Para un cliente nuevo: construir las mismas features de 12 meses → winsorizar con `limites_winsor` → `scaler.transform` → `modelo.predict` → `mapa_segmentos` → nombre `ZONA_SEGMENTO_TRAMO`. |
| **Criterios de caída (final)** | `06_estudio_caida\criterios_caida_por_segmento.joblib` (copia legible: `.csv`) | Umbrales de caída **por segmento** (`umbrales_vs_anterior`, `umbrales_vs_anio`), con el criterio usado (`PORCENTAJE` o `KWH`), y los parámetros (`K_DESVIACIONES`, banda [−60, −10] %, `UMBRAL_MINIMO_PERDIDA_KWH = 10`). | Reaplicar exactamente la misma regla en el mes siguiente sin recalcular umbrales, para que dos meses sean comparables. |
| **Detector del borde provisional** | `Pipeline_Ebsa\utilidades_borde.py` | Función `ultimo_periodo_consolidado(serie)` → último mes que se puede usar. | Lo llaman los notebooks 8, 9, 10 y 12 antes de entrenar, agrupar, evaluar o comparar (ver §6). |
| **Compuerta de calidad** | `Pipeline_Ebsa\utilidades_calidad.py` | Función `validar_mes_entrante(historico)` → reporte por chequeo; lanza error si el archivo del mes llegó mal. | La llama el notebook 2 antes de reconstruir (§7). |

> **En modo aplicar (§8) los tres modelos se cargan y se usan sin reentrenar.** Un mes normal no toca ningún `.joblib`; solo la corrida en modo reentrenar los sobreescribe.

> Los archivos `modelos_ganadores_segmentados.joblib` (notebook 6) y `modelos_ganadores_optimizados.joblib` (notebook 7) también existen en la misma carpeta, pero son **versiones anteriores**. El final es `modelos_ganadores_optimizados_final.joblib`.

---

## 4. Orden de ejecución

Todos los notebooks se corren de arriba abajo, con **kernel reiniciado**, en este orden. Cada uno lee lo que escribió el anterior.

| # | Notebook | Qué hace | Necesita | Produce en |
|---|---|---|---|---|
| 1 | `Exploracion_inicial.ipynb` | Lee los XLSX/CSV de `00_formato_TC2\` (el año-mes sale del nombre del archivo), unifica encabezados (esquema canónico + alias), guarda el detalle y un resumen NIU × mes por archivo, y **anualiza**: cada mes entra a su `historico_YYYY.parquet` conservando los meses que ya estaban; si un mes ya existía y vuelve a llegar, se reemplaza y lo avisa. Los archivos ya procesados en corridas anteriores no se vuelven a leer (caché en `resumen_por_archivo\`). Termina con la cobertura del histórico completo (clientes por mes, huecos). | `00_formato_TC2\` | `01_historico_procesado\historico_YYYY.parquet`, `detalle_mensual\`, `resumen_por_archivo\` |
| 2 | `Reconstruccion_serie_tiempo_consumo_rural.ipynb` | Une los `historico_YYYY`, detecta lecturas largas (75–129 días = trimestrales, rurales) y reparte ese consumo en los meses que cubre. Deja una serie **mensual** por cliente. Valida que el consumo total se conserva. | Salida de 1 | `02_serie_reconstruida\` |
| 3 | `Preprocesamiento_serie_tiempo_para_modelado.ipynb` | Excluye alumbrado público (ciclo 15 + clase AP) y autogeneradores (ciclo 50, decisión de la empresa: consumen menos de la red por diseño; lista en `nius_autogeneradores_excluidos.parquet`), marca ciclos rurales (10, 11, 12, 13, 19, 21, 22, 23, 38), deja la serie lista para modelar con `es_rural`, `consumo_kwh_mensual`, `regimen`, etc. Guarda el ciclo de cada NIU. **Calcula el corte por zona** (`cortes_por_zona.csv`) y marca cada fila con `estado_mes` CONSOLIDADO / PROVISIONAL (§6). | Salida de 2 | `03_serie_modelado\` ★ |
| 4 | `Modelado_prediccion_consumo_3_6_meses.ipynb` | **Primer modelo** (un solo modelo para todos los clientes, muestra de 50.000). Sirvió para demostrar que hacía falta segmentar. Se conserva como referencia; **no alimenta nada posterior**. | Salida de 3 | `04_pronostico\desarrollo_01_modelo_unico\` |
| 5 | `Modelado_prediccion_consumo_segmentado_3_6_meses.ipynb` | Introduce los **perfiles** (P0 intermitente, P1 regular, P2 alto, P3 grande, P4 insuficiente), un modelo por perfil × horizonte, y el blend ML + línea base. Solo LightGBM. **Tampoco alimenta nada posterior.** | Salida de 3 | `04_pronostico\desarrollo_02_segmentado\` |
| 6 | `Modelado_segmentado_comparacion_modelos_3_6_meses.ipynb` | Compara LightGBM, XGBoost y CatBoost por perfil × horizonte, elige ganador, hace backtest y pronóstico. **Sus CSV de backtest los lee el notebook 8** para la comparación original vs optimizado. | Salida de 3 | `04_pronostico\modelo_final\` (`seleccion_modelo_por_perfil_horizonte.csv`, `metricas_sistema_*.csv`, `modelos_ganadores_segmentados.joblib`) |
| 7 | `Optimizacion_hiperparametros_modelos_finales.ipynb` | Optuna sobre los ganadores del 6. Guarda los mejores hiperparámetros y la selección optimizada. | Salida de 3 y 6 | `04_pronostico\modelo_final\`: `hiperparametros_optimos_por_grupo.json`, `seleccion_modelo_por_perfil_horizonte_optimizada.csv`, `optuna_estudios.sqlite3` |
| 8 | `Backtest_y_reentrenamiento_final_optimizado.ipynb` | **Modelo final de pronóstico.** Modo *reentrenar*: backtest con corte 2025-07 (examen contra meses ya ocurridos, excluyendo de las métricas los meses provisionales), reentrenamiento con toda la historia consolidada y pronóstico a 6 meses; celda 32: diagnóstico del tope de muestra (opcional, lento). Modo *aplicar*: carga el `.joblib` guardado, verifica que el contrato de features y umbrales sea el mismo, avisa si lleva más de 6 meses sin reentrenar, y pronostica. En ambos modos guarda una copia del pronóstico por corte en `historial_pronosticos\`. | Salida de 3, 6, 7 + `utilidades_borde.py` | `modelos_ganadores_optimizados_final.joblib`, `predicciones_segmentadas_optimizadas_3/6_meses.parquet`, `metricas_*_optimizado.csv`, `comparacion_backtest_original_vs_optimizado.csv`, `historial_pronosticos\` |
| 9 | `Agrupamiento_clientes_consumo.ipynb` | **Modelo final de agrupamiento.** Features de 12 meses por cliente (ventana que termina en el último mes consolidado, detectado con `utilidades_borde`), separación de grupos estructurales por regla, winsor + RobustScaler. Modo *reentrenar*: comparación de algoritmos con Optuna (semilla fija) y nombres de negocio. Modo *aplicar*: carga el `.joblib` y asigna a cada cliente su cluster y su nombre guardado, sin reagrupar; avisa si el perfil de algún cluster ya no corresponde a su nombre. | Salida de 3 (+ perfil de periodicidad de 2) | `05_segmentos_clientes\` |
| 10 | `Estudio_caida_consumo.ipynb` | **Criterios de caída.** Ventana de 3 meses (mensual) o 6 (rural) que termina en el último mes consolidado, comparación vs. periodo anterior y vs. año pasado, veredicto y severidad. Modo *reentrenar*: calcula los umbrales por segmento y los guarda. Modo *aplicar*: usa los guardados (misma regla que el mes anterior), los recalcula solo para medir la deriva (`deriva_criterios_caida.csv`) y avisa cuando conviene reentrenar. | Salida de 3 y 9 | `06_estudio_caida\` |
| 11 | `Priorizacion_gestion_caida.ipynb` | **Listas de gestión.** Cruza la caída con ciclo, tarifa real, estrato, clase y tramo; calcula valor en riesgo; añade trayectoria con `pred_1m_kwh` del 8; cruza con `historial\` para saber si cada cliente es nuevo o lleva meses en la lista; guarda la copia del corte. | Salida de 3, 8, 9, 10 + `01_historico_procesado\` (tarifa) | `07_gestion_caida\` |
| 12 | `Seguimiento_pronostico_mensual.ipynb` | **Precisión en vivo.** Toma cada pronóstico de `historial_pronosticos\` y cada lista de `07_gestion_caida\historial\`, y los compara con el consumo real de los meses que ya quedaron consolidados. No entrena nada; recalcula todo en cada corrida. | Salida de 3, 8, 11 | `08_seguimiento\` |
| 13 | `Evaluacion_retroalimentacion_gestion.ipynb` | **Resultados de campo.** Lee los `resultado_gestion*.csv` que llene la empresa, los cruza con la lista de la que salió cada cliente y mide la precisión de la lista. Si no hay archivos, lo dice y termina sin error. | Salida de 11 + archivos de visitas | `07_gestion_caida\retroalimentacion\` |
| 14 | `Riesgo_fuga_comercializador.ipynb` | **Riesgo de fuga.** Lee `00_otros_comercializadores\`, ubica el mes de salida de cada cliente que se fue, define la población elegible, calcula variables de consumo y atributos en cada corte histórico y entrena LightGBM con parámetros fijos conservadores y evaluación por cortes en el tiempo, calibra la probabilidad con predicciones fuera de muestra (modo *reentrenar*, semilla fija; Optuna queda como análisis de sensibilidad; con menos de 20 ejemplos usa un puntaje de similitud). Modo *aplicar*: carga `modelo_riesgo_fuga.joblib` y puntúa. Listas, recurrencia, vigilancia de no regulados y seguimiento de cortes anteriores. | Salida de 1, 3, 6 (corte) y 8 (perfiles) + archivo de otros comercializadores | `10_riesgo_fuga\` |
| 15 | `Exportes_negocio.ipynb` | **Exportes por grupo.** Parte el pronóstico, la lista de caída y la de fuga por grupo de consumo, con las columnas del glosario, y escribe el índice. No calcula nada nuevo. | Salida de 8, 11 y 14 | `11_exportes_negocio\` |
| — | `utilidades_borde.py` | Módulo Python (no es notebook). Detecta el borde provisional y calcula el corte por zona (`cortes_por_zona`, `leer_cortes_por_zona`). Lo importan 3, 8, 9, 10, 12 y 14. | — | — |
| — | `utilidades_glosario.py` | Módulo Python (no es notebook). Traduce ciclo → zona, clase de servicio, tipo de medidor/lectura/factura y perfil → grupo de consumo; calcula el valor facturado. Lo importan 11, 14, 15 y la página. | — | — |
| — | `utilidades_versiones.py` | Módulo Python. Guarda y resuelve versiones de los modelos (`12_versiones_modelos`). Lo importan 8, 9, 10 y 14. | — | — |
| — | `simular_meses.py`, `comparar_modelos.py` | Simulación mes a mes con `--corte-max` (entrenar en un corte, aplicar mes a mes, reentrenar, comparar) y lectura del deterioro / mejora. Procedimiento completo en `COMANDOS.md` §4b. | — | — |
| — | `verificar_corrida.py` | Verificador de la corrida (solo lee): consistencia de cortes, pronóstico, listas, exportes y registro. Correr después de cada `pipeline_mensual.py`. | — | — |
| — | `estado_modelos.py` | ¿Toca reentrenar? Un veredicto por modelo (MANTENER / REVISAR / REENTRENAR) leyendo la antigüedad, el seguimiento en vivo y la deriva de criterios; imprime el comando exacto. Solo lee. | — | — |
| — | `diagnostico_fuga.py`, `diagnostico_cruce_fuga.py` | Scripts de solo lectura con los que se estudió cómo se ven en TC2 los clientes que se fueron (no forman parte de la corrida). | — | — |
| — | `utilidades_calidad.py` | Módulo Python (no es notebook). Compuerta de calidad del archivo entrante. Lo importa el 2. | — | — |
| — | `pipeline_mensual.py` | Script que corre los notebooks en orden con kernel limpio (§7). | — | `09_registro_corridas\` |
| — | `app_ebsa.py` | Página web (Streamlit) que muestra las salidas (§10). | — | — |
| — | `app_ebsa_v2.py`, `componentes_v2.py`, `recursos_v2\` | La misma página con interfaz nueva (§10.1). Mismas cifras y reglas que `app_ebsa.py`; se abren por separado. | — | — |
| — | `empaquetar_app.py` | Arma la carpeta para compartir las dos páginas sin el pipeline (§10.1). | Salidas del pipeline | `EBSA_app_para_compartir\` |
| — | `requirements.txt`, `generar_lock_entorno.py` | Dependencias del entorno (§11). | — | — |
| — | `preparar_carpeta_datos.py` | Crea la estructura de carpetas y dice qué copiar del proyecto anterior (§7.0). | — | — |

**Dependencias resumidas:**

```
1 → 2 → 3 ─┬─→ 4 (referencia, termina ahí)
           ├─→ 5 (referencia, termina ahí)
           ├─→ 6 → 7 → 8 ──────────────┐   Producto B (pronóstico 6 meses)
           └─→ 9 → 10 → 11 ←───────────┘   Producto A (gestión de caída; el 11 lee pred_1m_kwh del 8)
                          └─→ 12 → 13      Seguimiento y retroalimentación (leen los historiales de 8 y 11)
1 + 3 + 8 + 10 ──→ 14 ──→ 15               Producto C (riesgo de fuga) y exportes por grupo (el 15 lee 8, 11 y 14)
```

**Corrida mensual:** 1 → 2 → 3 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15, en modo *aplicar*. Es exactamente lo que hace `python pipeline_mensual.py --modo aplicar` (§7). Los notebooks 4, 5, 6 y 7 son de desarrollo y solo se repiten si se quiere volver a elegir algoritmos o hiperparámetros.

---

## 5. Qué hay en cada carpeta y cómo leerlo

### 5.1 `01_historico_procesado\` (notebook 1)

- `historico_YYYY.parquet` — una fila por NIU × mes del año, con `consumo_kwh_raw`, `dias_facturados_max`, `fecha_lectura_anterior/actual`, `tarifa_aplicada_kwh`, `estrato`, `ciclo`, `clase_servicio`, `tipo_lectura`, `tipo_medidor`, `tipo_factura`, `consumo_promedio_semestral_kwh` y, desde esta versión, `valor_facturado_consumo` (columna Q del TC2, "Valor Facturación por Consumo Usuario ($)", sumada por NIU-mes). Un histórico generado con la versión anterior del notebook 1 no trae esa columna: las listas muestran entonces `valor_facturado_mes` = consumo × tarifa real (y lo dicen en `valor_facturado_origen`) hasta que se vuelva a correr el paso 1 desde los XLSX. Es el resumen "tal como lo dice la empresa", **sin repartir** las lecturas trimestrales. De aquí sale la **tarifa real** que usa el notebook 11.
- `detalle_mensual\` — el detalle factura por factura de cada archivo original. Solo para auditar.
- `resumen_por_archivo\` — el resumen NIU × mes de cada archivo TC2 ya procesado. Es la caché del notebook 1: si el archivo no cambió, no se vuelve a leer. Borrar esta carpeta obliga a releer todos los XLSX que estén en `00_formato_TC2\`.
- `historico_temporal.pkl` — respaldo de la versión anterior del notebook 1; ya no se usa y se puede borrar.

### 5.2 `02_serie_reconstruida\` (notebook 2)

- `serie_mensual_consumo_reconstruida.parquet` — serie mensual por cliente con las lecturas trimestrales ya repartidas en sus meses.
- `perfil_periodicidad_clientes.parquet` — por NIU: si su lectura es mensual o trimestral, cuántas lecturas largas tiene, etc.
- `validacion_conservacion_consumo.parquet` — prueba de que la suma de consumo antes y después de repartir es la misma.
- `aportes_lecturas_trimestrales.parquet` — trazabilidad: qué lectura larga aportó cuánto a qué mes.

### 5.3 `03_serie_modelado\` (notebook 3) ★

- `serie_mensual_modelado_preprocesada.parquet` — **la entrada de todos los modelos** (notebooks 4–11). Columnas clave: `NIU`, `periodo`, `consumo_kwh_mensual`, `es_rural`, `regimen` (observado / reconstruido), `ciclo`, `estrato`, `clase_servicio`.
- `niu_ciclo.parquet` — ciclo de lectura (0–99) de cada NIU: `ciclo` (el más frecuente en su historia; define urbano/rural) y `ciclo_actual` (el último conocido; es la ruta de hoy y el que usa el 11 para etiquetar la lista operativa y el 9c para excluir autogeneradores).
- `nius_alumbrado_publico_excluidos.parquet` — los NIU de alumbrado público que se sacaron.
- `nius_autogeneradores_excluidos.parquet` — los NIU cuyo **ciclo actual** es 50 (AUTOGENERADORES). Se excluyen del universo completo (serie, pronóstico, segmentación, caída y fuga): generan parte de su energía, así que su consumo de la red cae por diseño y una "caída" en ellos no es gestionable. Se usa el ciclo actual y no el más frecuente porque el caso típico es un cliente que llevaba años en un ciclo normal y acaba de pasar a autogenerador (decisión 2026-10-02); si vuelve a un ciclo normal, reingresa en la corrida siguiente.
- `auditoria_preprocesamiento_modelado.csv`, `auditoria_cobertura_mensual.csv` — cuántos clientes y cuánto consumo quedó por mes después de cada filtro.

En `02_serie_reconstruida\` queda además `control_calidad_mes_entrante.csv` (notebook 2): un chequeo por fila (columnas esenciales, clientes vs. previos, **clientes con lectura frente al mes anterior y ciclos urbanos sin leer** — añadidos el 2026-10-06 tras el archivo de prueba de mayo, que traía filas pero no el consumo del mes para parte de los urbanos; ERROR si los urbanos con dato caen más de 5 % —, consumo total, tarifa, ciclos nuevos, duplicados, fechas de lectura) con `resultado` OK / ERROR / AVISO y el detalle. Los umbrales están documentados en `utilidades_calidad.py`.

### 5.4 `04_pronostico\desarrollo_01_modelo_unico\` (notebook 4) y `04_pronostico\desarrollo_02_segmentado\` (notebook 5) — referencia

Resultados de las dos primeras versiones del pronóstico (`modelo_consumo_ganador.joblib`, `modelos_segmentados_consumo.joblib`, `predicciones_*`, `metricas_*`). Sirven para contar la evolución del proyecto (un modelo → modelos por perfil → comparación de algoritmos → optimización). **Nada posterior los lee.**

### 5.5 `04_pronostico\modelo_final\` (notebooks 6, 7, 8)

Del 6 (sistema original): `comparacion_modelos_validacion.csv` (LGBM vs XGB vs CatBoost por grupo), `seleccion_modelo_por_perfil_horizonte.csv`, `metricas_sistema_por_perfil_horizonte.csv`, `metricas_sistema_ganador_backtest.csv`, `modelos_ganadores_segmentados.joblib`, `predicciones_segmentadas_ganadoras_*.parquet`, `perfiles_consumidores_corte_final.parquet` (perfil P0–P4 de cada cliente), `grandes_consumidores_corte_final.parquet`.

Del 7: `hiperparametros_optimos_por_grupo.json`, `seleccion_modelo_por_perfil_horizonte_optimizada.csv`, `modelos_ganadores_optimizados.joblib` (entrenados hasta el corte de validación, no el final), `optuna_estudios.sqlite3` (historial de la búsqueda; se puede borrar sin perder nada).

Del 8 (sistema final): todo lo que termina en `_optimizado` o `_optimizadas` (ver §3.2 y §3.4), más:
- `comparacion_backtest_original_vs_optimizado.csv` — WAPE del sistema del 6 vs. el del 8 por perfil y horizonte, con columna `comparable` (`False` cuando el mes objetivo era provisional y la comparación no es justa).
- `diagnostico_tope_muestra.csv` — resultado de la celda 32: WAPE con tope 60k / 120k / sin tope. Concluyó que el tope cuesta ~0,1 punto, por eso se mantiene.
- `historial_pronosticos\predicciones_6_meses_corte_AAAA-MM.parquet` — el pronóstico de cada corte, con `modo` y `fecha_corte_modelo` (con qué corte se entrenó el modelo que lo produjo). Los lee el notebook 12.

**Cómo leer las métricas:** `WAPE_final_pct` es el error porcentual ponderado; 25 % significa que, sumando todos los clientes del grupo, el pronóstico se desvía un 25 % del real. `WAPE_baseline_pct` es la línea base del notebook 8: **el mismo mes del año anterior** (no "repetir el consumo reciente", como decía este README hasta el 2026-10-08). Para saber cuánto aporta el modelo hay que compararlo además con los ingenuos de corto plazo (repetir el último mes, media de 3 y de 12 meses): eso lo hace `python evaluar_ingenuos_backtest.py`, que deja `comparacion_ingenuos_backtest.csv` (por zona, perfil y horizonte) y `error_por_cliente_backtest.csv`. En el backtest vigente el modelo le gana a la línea base estacional por 5–17 puntos, pero al mejor ingenuo de corto plazo solo por 0–2 puntos, y en algunos perfiles y horizontes no le gana. El backtest rural a 1–2 meses es optimista (las lecturas trimestrales se reparten entre meses y pueden cerrar después del corte): para rurales vale el seguimiento en vivo. Los perfiles: `P0_INTERMITENTE` (muchos ceros), `P1_REGULAR` (la mayoría), `P2_ALTO`, `P3_GRANDE`, `P4_INSUFICIENTE` (sin historia suficiente, solo línea base).

### 5.6 `05_segmentos_clientes\` (notebook 9)

- `clientes_clusters_consumo.parquet` — **un cliente por fila** con `cluster_id` (nombre de negocio), `zona`, `tramo_consumo`, `segmento_negocio`, `accion`, `prioridad` y las features de 12 meses.
- `catalogo_segmentos_negocio.csv` — el diccionario: para cada segmento, qué significa, qué acción se recomienda y su prioridad.
- `perfil_clusters_resumen.csv` — tamaño y consumo medio de cada segmento.
- `comparacion_algoritmos_clustering.csv` — qué algoritmo y parámetros ganaron por zona.
- `features_clientes_consumo.parquet` — las features antes de agrupar (auditoría).
- `auditoria_promedio_semestral.csv` — cruce contra el promedio semestral que reporta la empresa.

**Cómo leer un nombre de segmento:** `ZONA_SEGMENTO_TRAMO`, p. ej. `URBANO_BASE_ESTABLE_MEDIO` = cliente urbano, consumo estable, entre 30 y 99 kWh/mes. Segmentos:

| Segmento | Qué es | Acción | Prioridad |
|---|---|---|---|
| `CAIDA_SEVERA` | Caída fuerte y sostenida frente a su propio historial. | Revisión prioritaria: medidor, predio y facturación. | 1 – Crítica |
| `EN_COLAPSO` | Consumo casi nulo y cayendo hacia cero. | Inspección en terreno: predio desocupado o medidor con falla. | 1 – Crítica |
| `INTERMITENTE_CRITICO` | Más de un tercio del año sin consumo y muy volátil. | Verificar continuidad del servicio y confiabilidad de la lectura. | 2 – Alta |
| `SIN_CONSUMO` | Cero consumo en los 12 meses, pero sigue registrado. | Depuración de catastro. | 2 – Alta |
| `BASE_EN_DESCENSO` | Consumo regular con tendencia sostenida a la baja. | Vigilar; entrada principal del estudio de caída. | 3 – Media |
| `EN_REACTIVACION` | Consumo creciendo con fuerza desde niveles casi nulos. | Confirmar reconexión o nuevo ocupante. | 4 – Informativa |
| `BASE_ESTABLE` | Consumo regular y predecible. La mayoría. | Monitoreo estándar. | 5 – Baja |
| `NUEVO_O_SIN_DATOS` | Menos de 6 meses de historia válida en la ventana. | Esperar historia; excluir de análisis de tendencia. | 5 – Baja |

Estas columnas (`accion`, `prioridad`) ya vienen en `clientes_clusters_consumo.parquet` y en `catalogo_segmentos_negocio.csv`; la página puede mostrarlas directamente.

Tramos: `BAJO` < 30 kWh/mes, `MEDIO` 30–99, `ALTO` 100–299, `GRANDE` ≥ 300.

### 5.7 `06_estudio_caida\` (notebook 10)

- `estudio_caida_consumo.parquet` — **todos** los clientes evaluados, con `veredicto`, `severidad`, `tipo_hallazgo`, consumos y variaciones.
- `resumen_caida_por_segmento.csv` — por segmento: cuántos clientes marcados, % del segmento, kWh perdidos (solo de los marcados).
- `clientes_caida_prioritarios.csv` — lista corta ordenada por kWh perdidos y concentración.
- `criterios_caida_por_segmento.csv` / `.joblib` — los umbrales aplicados (ver §3.4).
- `diagnostico_borde_ventana.csv` — nivel del último mes vs. lo normal, por zona; justifica el retroceso de la ventana.
- `deriva_criterios_caida.csv` — solo en modo aplicar: umbral guardado vs. umbral recalculado con el mes actual, por segmento. Señal para decidir cuándo reentrenar.

**Veredictos:** `CAIDA_CONFIRMADA` (cae vs. periodo anterior y vs. año pasado), `CAIDA_RECIENTE` (solo vs. anterior), `CAIDA_SOSTENIDA` (solo vs. año pasado: ya venía bajo), `SIN_CAIDA`, `SIN_BASE_COMPARABLE` (no hay periodo anterior), `NO_APLICA` (segmentos sin consumo o sin datos), `NO_EVALUADO` (no alcanzó a evaluarse en la ventana). **Severidad:** cuántas "escalas" (desviaciones robustas de su segmento) supera el umbral: ≥ 2 `CRITICA`, ≥ 1 `FUERTE`, resto `MODERADA`. **Tipo de hallazgo:** `DESCUBRIMIENTO` (cae un cliente de un segmento estable: es noticia) vs. `CONFIRMACION` (cae uno de un segmento que ya era de caída).

### 5.8 `07_gestion_caida\` (notebook 11)

Descrito completo en §3.1.

---

## 6. El mes provisional y el corte por zona (importante para cualquier corrida futura)

Los clientes rurales se leen cada tres meses. En cualquier extracción, a los **últimos meses** solo les ha llegado la lectura de una parte de ellos, así que aparecen con una fracción del consumo normal (en la extracción de enero 2026: 47,9 % en rurales); y un archivo mensual puede llegar **sin ninguna fila rural** (febrero 2026 llegó solo con urbanos). No es un error: se completa hacia arriba cuando llegan las lecturas siguientes. Los urbanos, en cambio, se leen todos los meses y su último mes está completo.

Por eso el proyecto trabaja con **un corte por zona**: `utilidades_borde.cortes_por_zona` detecta, en cada corrida y por separado, el último mes consolidado de los urbanos (normalmente el último del archivo) y el de los rurales (el último trimestre cerrado). Mira dos cosas de cada mes y zona: el **nivel** (consumo promedio de los clientes con fila: detecta lecturas parciales) y la **cobertura** (cuántos clientes tienen fila: detecta clientes enteros que faltan; en febrero 2026 solo 89 de ~219.000 rurales tenían fila y su promedio era normal, así que sin esta prueba febrero pasaba por consolidado y los rurales se quedaban sin pronóstico). Cada una se compara contra la mediana de los 12 meses previos **y** contra el mismo mes del año anterior, para no confundir estacionalidad con borde; el registro del paso 3 dice por cuál prueba cayó cada mes. `verificar_corrida.py` además comprueba que cada zona tenga pronóstico para la mayoría de sus clientes. El notebook 3 los escribe en `03_serie_modelado\cortes_por_zona.csv` y marca cada fila de la serie con `estado_mes` = CONSOLIDADO / PROVISIONAL. A partir de ahí:

- **Pronóstico (8):** los meses posteriores al corte de cada zona se enmascaran en la matriz (ni entrenan ni se evalúan); cada cliente se pronostica desde el corte de su zona. Un rural con corte diciembre recibe pronóstico para enero–junio: sus primeros meses ya pasaron pero aún no tienen lectura, y en la página y en los exportes se muestran como **"pronosticado, a la espera de la lectura trimestral"** hasta que llegue la real. La serie nunca mezcla real con pronosticado.
- **Agrupamiento (9), caída (10), listas (11), riesgo de fuga (14):** las ventanas de cada cliente terminan en el corte de su zona. Toda fila lleva su `fecha_corte`; los archivos del mes se nombran por el corte urbano (el mes de la corrida).
- **Seguimiento (12):** cada pronóstico y cada lista se evalúan contra un mes solo cuando ese mes ya está consolidado para la zona del cliente. Así el seguimiento urbano avanza cada mes aunque los rurales esperen.
- **Compuerta de calidad (2):** compara urbanos contra urbanos y rurales contra rurales; una caída de clientes urbanos es ERROR, un mes sin filas rurales es solo AVISO.

Cuando llegue el archivo de marzo: los urbanos avanzan a marzo; los rurales avanzan cuando sus lecturas cierren el trimestre. **No hay que cambiar ningún número a mano.** Si el detector quiere retroceder más de 3 meses en urbanos o más de 4 en rurales, se detiene con error: la extracción llegó mal y hay que revisarla antes de seguir.

---

## 7. Procedimiento cuando llega un mes nuevo

1. Copiar el archivo TC2 nuevo de la empresa a `Datos_Ebsa\00_formato_TC2\` sin editarlo. El nombre debe traer el año y el mes (`formato_tc2_202602.xlsx`, `..._20262.xlsx`), porque de ahí sale el periodo. No hace falta tener ahí los meses anteriores: el paso 1 agrega el mes nuevo al `historico_YYYY.parquet` de su año y conserva los que ya estaban (si el mes ya existía, lo reemplaza y avisa). Si se dejan todos los archivos en la carpeta, tampoco pasa nada: los ya procesados se reutilizan sin releerlos. Si la empresa entregó una versión nueva del archivo de usuarios de otros comercializadores, copiarla a `Datos_Ebsa\00_otros_comercializadores\` (se pueden dejar varias: el paso 14 quita las filas repetidas NIU-mes).
2. Abrir una consola en `C:\Users\Home\Documents\GitHub\ProyectoEBSA\Pipeline_Ebsa` y correr:

   ```
   python pipeline_mensual.py --modo aplicar
   ```

   Esto ejecuta 1 → 2 → 3 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 con kernel limpio. Al terminar, el registro del paso 3 dice los dos cortes de la corrida (urbano y rural) y la página los muestra en la barra lateral, usando los modelos guardados (sin reentrenar). Tarda minutos. Cada notebook ejecutado, con sus salidas, queda en `Datos_Ebsa\09_registro_corridas\<fecha-hora>_aplicar\` como registro, junto a `resumen_corrida.txt`. Los notebooks originales no se tocan.
3. Si un paso falla, el pipeline se detiene, muestra el error y dice con qué comando reanudar (`--desde N`). Los dos fallos "buenos" (los que protegen las salidas) son: la **compuerta de calidad** del notebook 2, cuando el archivo llegó con menos clientes, tarifas en cero o un ciclo desconocido; y el **detector del borde**, cuando quiere retroceder más de 3 meses. En ambos casos hay que mirar el archivo, no forzar la corrida.
4. Revisar tres cosas en el registro: el bloque `CONTROL DE CALIDAD DEL MES ENTRANTE` (notebook 2), el bloque `CORTES POR ZONA` (notebook 3: qué mes quedó consolidado para urbanos y para rurales) y el bloque de sesgo rural (notebook 11). Son los controles que dicen si el mes entró bien.
5. Abrir la página (`streamlit run app_ebsa.py`, §10) o leer directamente `07_gestion_caida\`, `04_pronostico\modelo_final\`, `08_seguimiento\`, `10_riesgo_fuga\` y, para repartir a negocio, `11_exportes_negocio\`.

Otros usos del script:

```
python pipeline_mensual.py --lista                          # ver los pasos
python pipeline_mensual.py --modo aplicar --desde 9         # reanudar desde el 9
python pipeline_mensual.py --modo aplicar --solo 11,12,13   # solo esos pasos
python pipeline_mensual.py --modo reentrenar --solo 14,15   # reentrenar solo el riesgo de fuga (minutos) y rehacer los exportes
python pipeline_mensual.py --modo reentrenar                # corrida de reentrenamiento (§8)
python pipeline_mensual.py --modo aplicar --datos "D:\otra\Datos_Ebsa"   # solo si los datos no están en Documentos\Datos_Ebsa
```

## 8. Modo aplicar y modo reentrenar

Los notebooks 8, 9, 10 y 14 leen la variable de entorno `EBSA_MODO` (la fija `pipeline_mensual.py`; si se abren a mano en Jupyter, vale el valor por defecto de la primera celda, `reentrenar`).

| | `aplicar` (cada mes) | `reentrenar` (una vez al año, o cuando `estado_modelos.py` lo pida) |
|---|---|---|
| Pronóstico (8) | Carga `modelos_ganadores_optimizados_final.joblib`, verifica el contrato y pronostica desde el último mes consolidado. No hace backtest. | Backtest + reentrenamiento con toda la historia + pronóstico. Sobreescribe el `.joblib`. Horas. |
| Agrupamiento (9) | Carga `modelo_agrupamiento.joblib` y asigna cluster y nombre guardados. Los segmentos no cambian de nombre entre meses. | Comparación de algoritmos con Optuna y nuevos nombres. Sobreescribe el `.joblib`. |
| Caída (10) | Usa `criterios_caida_por_segmento.joblib`: la misma regla que el mes anterior. Guarda la deriva en `deriva_criterios_caida.csv`. | Recalcula los umbrales y los guarda. |
| Riesgo de fuga (14) | Carga `modelo_riesgo_fuga.joblib` y puntúa el corte nuevo; avisa si la población elegible cambió o el modelo lleva más de 12 meses. | Rearma el conjunto de entrenamiento con todos los cortes, evalúa en los últimos 6 cortes con ventana completa, entrena con todo y guarda el `.joblib`. Minutos, no horas: se puede reentrenar cada mes con `--solo 14,15`. |

**Cuándo toca reentrenar.** La política acordada por el equipo (evaluada con la simulación de once cortes: la edad del modelo no explica el error y reentrenar a los ocho meses movió 0,1 puntos de WAPE) es **pronóstico y agrupamiento una vez al año**, para que el modelo incorpore un ciclo estacional completo más, y antes solo si `estado_modelos.py` lo pide por alguna de estas señales: el notebook 8 avisa que el modelo lleva más de 12 meses sin reentrenar (`MESES_MAX = 12`); en `seguimiento_pronostico_por_perfil.csv` la columna `dif_vs_backtest_pp` es claramente positiva varios meses seguidos; el notebook 9 avisa que el perfil de un cluster ya no corresponde a su nombre; el notebook 10 avisa que algún segmento cambiaría de criterio o que los umbrales se movieron más de 10 puntos; el notebook 14 avisa que la población elegible cambió (una clase nueva en el archivo de otros comercializadores) o que en `seguimiento_riesgo_fuga.csv` los señalados ALTO no se van más que la tasa base. Antes de reentrenar conviene correr también 6 y 7 si se quiere revisar la elección de algoritmos e hiperparámetros; si no, el 8 reutiliza los que están.

## 9. Retroalimentación de campo

La lista dice *quién* parece estar dejando de consumir; solo la visita dice *por qué*. Para cerrar ese ciclo:

1. Copiar `07_gestion_caida\retroalimentacion\resultado_gestion_plantilla.csv` como `resultado_gestion_<mes>.csv` en esa misma carpeta (la crea el notebook 13 la primera vez que corre).
2. Una fila por cliente visitado: `NIU`, `fecha_corte_lista` (el `fecha_corte` de la lista de donde salió, formato AAAA-MM), `fecha_visita`, `hallazgo`, `accion`, `observaciones`.
3. `hallazgo` toma un valor del catálogo, agrupado así: **con causa gestionable** (`MEDIDOR_DANADO`, `MEDIDOR_MANIPULADO_O_FRAUDE`, `ERROR_DE_LECTURA_O_FACTURACION`, `ACOMETIDA_O_RED_CON_FALLA`, `CONEXION_IRREGULAR`), **caída real sin gestión** (`PREDIO_DESOCUPADO`, `CAMBIO_DE_ACTIVIDAD_O_HABITO`, `AUTOGENERACION`, `CLIENTE_RETIRADO`), **sin novedad** (`SIN_NOVEDAD`: falso positivo) y **no verificado** (`NO_UBICADO`, `PENDIENTE`). El catálogo se puede ampliar en la primera celda del notebook 13.
4. El notebook 13 (lo corre el pipeline) produce `evaluacion_retroalimentacion_resumen.csv`: cobertura de la lista, precisión gestionable y precisión de caída real por severidad, trayectoria, estado en lista, tramo, zona, segmento y ciclo. Si un cruce muestra precisión baja de forma sostenida, ese grupo debe bajar en el orden de la lista; ese ajuste se hace en el notebook 11.

## 9b. Ubicación de los clientes y mapa (formato TC1) — paso aparte

El TC1 de la empresa (`00_formato_TC1\TC1_MMAAAA.csv`, una fila por NIU, separado por `;`) trae el código DANE del municipio (columna N, 8 dígitos: 5 del municipio + 3 del centro poblado), la dirección, la ubicación SUI, el estrato/sector, el nivel de tensión, el circuito, el transformador y las **coordenadas** de cada cliente. Junto con `Código DANE.xls` (código → municipio, departamento y provincia) permite poner municipio a cualquier lista y dibujar el mapa.

```
python cruzar_ubicacion_tc1.py
```

Es un script independiente del pipeline mensual: no toca ningún notebook ni ninguna salida existente; se corre una vez y se repite solo cuando llegue un TC1 nuevo (toma el más reciente por el periodo del nombre). Deja la carpeta `13_ubicacion_clientes\`:

| Archivo | Qué es |
|---|---|
| `ubicacion_clientes.parquet` | Una fila por NIU: `codigo_dane`, `codigo_municipio`, `municipio`, `provincia`, `departamento`, `zona_mapa` (una de las 8 zonas del mapa de la empresa, por el ciclo actual del cliente), `direccion`, `ubicacion_sui`, `estrato_sector`, `nivel_tension`, `circuito`, `transformador`, `latitud`, `longitud`, `altitud`, `coordenadas_validas` (dentro de la caja de Boyacá y vecinos), `autogenerador_tc1`, `periodo_tc1`. |
| `municipios_zona.csv` | Una fila por municipio: `zona_ebsa` (la zona de los ciclos de sus clientes; en los datos de agosto 2026 cada municipio cae 100 % en una sola zona, así que la tabla municipio → zona sale de los datos, no del dibujo), `pct_zona`, `clientes_tc1`, `clientes_en_serie`, `coordenadas_validas`, `lat_centro` / `lon_centro` (mediana de las coordenadas de sus clientes, donde se dibuja el círculo). |
| `auditoria_cruce_tc1.csv` | Cifras del cruce: filas, duplicados, códigos sin municipio, clientes fuera de Boyacá (municipios vecinos de Santander, Cundinamarca y Casanare), coordenadas sin dato o fuera de rango, autogeneradores según el TC1, clientes de la serie sin TC1. |

Con eso la página muestra el municipio en Gestión por ciclo, Ranking gerencial, Riesgo de fuga (lista y vigilancia) y Buscar cliente (con un filtro por municipio en cada una), y la sección **Mapa** dibuja los municipios de Boyacá como círculos sobre el mapa (tamaño = cifra elegida: clientes, lista de caída, críticos, valor en riesgo, riesgo de fuga, pérdida esperada; color = zona EBSA con la paleta del mapa de la empresa), con tablas por zona y por municipio y la opción de ver los clientes de una lista como puntos. El mapa usa plotly (`pip install plotly`); sin plotly dibuja un mapa básico sin nombres al pasar el mouse. El contorno de las zonas no es un polígono oficial: es la agrupación de municipios por ciclo; si se quisiera un mapa coloreado por polígono habría que traer los límites municipales del DANE (Marco Geoestadístico Nacional) y disolverlos con `municipios_zona.csv`.

Nota sobre `ubicacion_sui`: en los datos, el código 1 coincide casi exactamente con los ciclos rurales del glosario y el 2 con los urbanos; se guarda el código tal cual y la zona urbano/rural del proyecto sigue saliendo del ciclo, no de esta columna, hasta que la empresa confirme el significado.

## 9c. Proyección de consumo por zona para la compra de energía — paso aparte

```
pip install statsmodels
python proyeccion_anual_consumo.py            # 36 meses, umbral de confianza 5 %
```

Independiente del pipeline mensual. Toma la serie consolidada (`03_serie_modelado`, solo meses CONSOLIDADO, sin alumbrado ni ciclos internos), la agrega por **zona regional** y **TOTAL BOYACÁ** (GWh y clientes por mes), y **cada zona pasa por todos los candidatos**: la línea base estacional (mismo mes del año anterior, la referencia que hay que superar), seis variantes de Holt-Winters/ETS (tendencia aditiva, amortiguada o sin tendencia × estacionalidad aditiva o multiplicativa; sus parámetros de suavizado se estiman por máxima verosimilitud en cada ajuste) y SARIMA con **búsqueda de hiperparámetros**: 72 órdenes (p,d,q)(P,1,Q)₁₂ con p,q ∈ {0,1,2}, d ∈ {0,1}, P,Q ∈ {0,1}, de los que los 3 de menor AIC pasan al backtest. Gana el de menor WAPE a 1 año en un **backtest de orígenes móviles** (desde el mes 24 hasta el penúltimo, pronosticando hasta 24 meses adelante). **Verificación** de cada candidato: WAPE año 1 y año 2, sesgo (error medio con signo), cobertura real de la banda del 80 % (debe acercarse a 80 %) y, para el elegido, Ljung-Box sobre los residuos (p > 0,05 = sin estructura que el modelo haya dejado por fuera); se avisa si el ganador no supera la línea base. Todo queda en `comparacion_modelos_por_zona.csv` y en la página (expander "Ver todos los candidatos probados por zona"). `--rapido` usa uno de cada dos orígenes. Además del ganador (escenario **BASE**) se proyecta un escenario **ALTERNATIVO**: si el ganador no tiene tendencia, el mejor candidato con tendencia (qué pasa si el crecimiento de los primeros años continúa); si la tiene, el mejor sin tendencia (qué pasa si el consumo se estanca). Ambos salen con su error medido; para compra de energía lo usual es tomar el mayor como techo. En los datos reales de abril 2026 el total de Boyacá creció 3,5 % anual en 2022–2024 y quedó plano en 2024–2026, por lo que el backtest eligió un modelo sin tendencia y el escenario alternativo es el de crecimiento. Proyecta 36 meses con bandas del 80 % y 95 % (intervalos del modelo; en Holt-Winters por simulación) y suma por año calendario.

Salidas en `14_proyeccion_anual\`: `serie_mensual_por_zona.csv`, `proyeccion_mensual_por_zona.csv` (real + proyección + bandas), `proyeccion_anual_por_zona.csv` (por año: meses reales/proyectados, total, bandas, **confiabilidad**, error del backtest, modelo), `error_backtest_por_zona.csv`, `comparacion_modelos_por_zona.csv` y, si existe el pronóstico a 6 meses, `comparacion_pronostico_individual.csv` (suma de los 580.000 pronósticos individuales vs. el modelo agregado del total, mes a mes).

**Cuántos años mostrar.** Un año es `CONFIABLE` si el WAPE del backtest a ese horizonte es ≤ umbral (5 % por defecto, `--umbral`). Las bandas se **calibran** con el backtest: si la banda del 80 % cubrió menos del 80 % de los meses reales, se ensancha por el factor medido (`factor_calibracion_banda`), `ORIENTATIVO` si es mayor y `NO VERIFICABLE` si la historia no alcanza a probar ese horizonte (con 52 meses: el año 3). La sección *Proyección de consumo (compra de energía)* de la vista Comercial muestra el consumo mes a mes por zona, la proyección con bandas, la tabla por año con la confiabilidad y la frase "para esta zona se pueden usar los años …". La banda anual suma las mensuales (conservadora). Limitaciones declaradas: 52 meses = 4 ciclos anuales; no modela crecimiento de clientes ni tarifas ni clima; el año en curso mezcla real y proyección.

## 10. Página web

Hay **dos versiones de la página** y las dos se mantienen: `app_ebsa.py` (la original) y `app_ebsa_v2.py` (interfaz nueva). Son aplicaciones Streamlit que **solo leen** las salidas del pipeline (no entrenan ni recalculan nada), usan la misma carpeta de datos y el mismo archivo de usuarios, y muestran las mismas cifras. Para abrirlas:

```
pip install streamlit plotly              # una sola vez
python -m streamlit run app_ebsa.py       # página original, http://localhost:8501
python -m streamlit run app_ebsa_v2.py    # interfaz nueva
```

### 10.1 Las dos versiones: en qué se diferencian y cómo conviven

| | `app_ebsa.py` (original) | `app_ebsa_v2.py` (interfaz nueva) |
|---|---|---|
| Archivos que necesita | `app_ebsa.py`, `utilidades_glosario.py` | `app_ebsa_v2.py`, `componentes_v2.py`, la carpeta `recursos_v2\` y `utilidades_glosario.py` |
| Cifras, reglas, permisos, descargas | Las de siempre | Las mismas: comparadas en 113 escenarios (indicadores y archivos de descarga idénticos) |
| Navegación | Barra lateral con dos listas (vista y sección) | Pestañas de vista arriba, menú lateral agrupado y, en celular, menú inferior |
| Tablas | Tabla completa con desplazamiento | Búsqueda, orden, páginas de 25 filas y columnas prioritarias; la descarga trae todas las filas |
| Filtros | Sueltos sobre cada lista | Un bloque por lista con **Restablecer filtros**; el filtro de municipio solo ofrece los de la zona elegida |
| Mapa | Círculos sobre un fondo que se descarga de internet | Límites de los 123 municipios (DANE), sin internet |
| Buscar cliente (Administrador) | Arma siempre la tabla de ejemplos | La arma solo al pedirla (más rápida y con menos memoria) |
| Extras | — | "Ocultar NIU y direcciones" para presentar; avisos de limitaciones destacados |
| Streamlit | 1.35 o superior | 1.40 o superior (ver `GUIA_TECNICA.md` §3.9) |

**Las dos a la vez.** Cada una en su consola y en un puerto distinto:

```
python -m streamlit run app_ebsa.py    --server.port 8501
python -m streamlit run app_ebsa_v2.py --server.port 8502
```

**Regla para mantenerlas.** Ninguna reemplaza a la otra. Si se cambia un cálculo o una regla de negocio en una página, hay que hacer el mismo cambio en la otra; lo visual de la V2 vive en `componentes_v2.py`. Los datos se actualizan igual para las dos: se corre el pipeline por consola (sección 7) y las dos páginas leen los archivos nuevos solas, sin reiniciarlas.

**Si la V2 no se ve bien.** Barra superior o menú sin estilos, o mapa de círculos en vez de municipios: falta `componentes_v2.py` o la carpeta `recursos_v2\` junto a `app_ebsa_v2.py`. Después de cambiar cualquier archivo de la V2 hay que detener la página (Ctrl+C) y volver a abrirla; recargar el navegador no basta. Más casos en `GUIA_TECNICA.md` §3.9.

**Usuarios.** La página pide usuario y clave al abrir. Los usuarios están en `.streamlit\secrets.toml` (junto a `app_ebsa.py`; ese archivo está en `.gitignore`, así que se copia a mano a cada máquina a partir de `secrets.toml.ejemplo`): `comercial` abre solo la vista Comercial; `soporte` abre Soporte y Comercial; `admin` abre las tres y es el único que puede cambiar la carpeta de datos. Un mes nuevo no se incorpora desde la página: se corre el pipeline por consola (sección 7) y la página solo lee el resultado. Para cambiar una clave o agregar un usuario se edita ese archivo (cada usuario tiene `nombre`, `clave` y `vistas`) y se vuelve a abrir la página. *Cerrar sesión* está en la barra lateral.

**Para compartir solo la página.** `python empaquetar_app.py` arma una carpeta autónoma con **las dos páginas** (`app_ebsa.py`, `app_ebsa_v2.py`, `componentes_v2.py`, `recursos_v2\`, `utilidades_glosario.py`), `INICIAR_APP.bat` (original, puerto 8501), `INICIAR_APP_V2.bat` (interfaz nueva, puerto 8502), `LEEME.txt`, `requirements_app.txt` y `datos\` con únicamente las salidas que las páginas leen (sin archivos de la empresa, sin modelos `.joblib` y sin notebooks). **El paquete no lleva claves**: incluye `secrets.toml.ejemplo` y quien lo recibe crea su `.streamlit\secrets.toml`; `--incluir-claves` copia el de esta máquina, como hacía antes. La carpeta `datos\` sí lleva información de clientes (NIU, dirección, consumo): es para el equipo, no para publicar. Cada página toma la carpeta `datos\` que esté junto a ella si existe, luego `EBSA_DATOS`, y si no la ruta de siempre.

La página tiene **tres vistas** (barra lateral), una por público:

- **Comercial** (lenguaje de negocio): *Panorama* (clientes con caída para revisar, facturación que se está perdiendo, clientes con riesgo de irse y pérdida esperada, caídas graves, nuevos en la lista, ya con otro comercializador, grandes clientes en vigilancia; mapa de Boyacá por municipio con la cifra elegida; de qué clases y tamaños viene el valor; qué cambió frente al mes anterior), *Clientes con riesgo de irse* (prioridad, municipio, factura hoy, probabilidad, por qué, situación; y aparte los grandes clientes no regulados), *Caídas de consumo* (consumía / consume ahora / caída / facturación que se pierde / gravedad / tendencia; arriba avisa cuántos clientes en cero o casi cero hay aparte), *Clientes sin consumo* (los de cero o casi cero sostenido: situación, consumía / consume ahora, lo que facturaban, último mes con consumo, meses sin consumo y una acción sugerida según el tiempo que llevan así; filtros por zona regional, municipio, situación, tiempo y tamaño), *Clientes que ya se fueron* (solo los que están con otro comercializador) y *Descargas*.
- En todas las listas (Comercial, Soporte y Administrador) **un clic en una fila abre debajo la ficha del cliente**, con un botón para ir a *Consultar un cliente* / *Buscar cliente*. La gráfica de consumo muestra 18 meses reales y los 6 pronosticados. Las cifras van en formato colombiano (punto de miles, coma decimal) y los CSV se descargan con `;` y coma decimal para Excel en español; cada lista dice "Se muestran N de M".
- **Soporte** (atención al cliente y campo): *Consultar un cliente* (ficha en lenguaje simple: dónde está, clase y tamaño, qué le pasa al consumo, riesgo de irse, avisos de autogenerador / no regulado / ya con otro comercializador, **qué revisar o qué decirle**, y la gráfica de consumo y pronóstico; con buscador por municipio, gravedad y tendencia), *Visitas por ciclo* (ruta de visita con municipio y dirección del TC1, orden por facturación perdida, filtros y mapa de los clientes del ciclo) y *Registrar resultado de visitas*.
- **Administrador del modelo** (todo lo técnico): Resumen (cifras del corte, riesgo de fuga, trayectoria, estado en lista, valor por ciclo, severidad), Gestión por ciclo (lista operativa por ciclo con el nombre de la zona, filtrable por grupo de consumo y descargable), Ranking gerencial, **Riesgo de fuga** (lista filtrable por nivel, zona, grupo, clase y municipio; resumen por zona y grupo; los que ya están con otro comercializador y su perfil; vigilancia del mercado no regulado, que es donde viven los no regulados, fuera del ranking; calidad del modelo; seguimiento), Cortes (clase, estrato, zona, tramo), **Mapa** (municipios de Boyacá, sección 9b), Buscar cliente (ubicación, segmento, caída, posición en la lista, riesgo de fuga y pronóstico a 6 meses de un NIU, con aviso si es autogenerador o de mercado no regulado; el buscador de ejemplos muestra ciclo, zona y municipio de **todos** los clientes y la situación de cada uno en caída y en fuga, filtrable por grupo, segmento, ciclo, municipio, situación en caída y riesgo de fuga), Pronóstico 6 meses (totales proyectados y precisión por grupo de consumo), **Descargas por grupo** (los archivos de `11_exportes_negocio\`), Seguimiento, Retroalimentación y Estado del pipeline. Todas las tablas muestran zona, clase de servicio, tipo de medidor y de lectura, promedio semestral y valor facturado con los nombres del glosario. La carpeta de datos se toma de `EBSA_DATOS` o se cambia en la barra lateral.

## 11. Entorno

Python 3.10+ con las dependencias de `requirements.txt` (`pip install -r requirements.txt`). Los `.joblib` de LightGBM, XGBoost, CatBoost y scikit-learn dependen de la versión instalada: para dejar constancia de las versiones exactas de la máquina que entrenó los modelos, correr una vez `python generar_lock_entorno.py`, que escribe `requirements-lock.txt`; otra máquina reproduce el entorno con `pip install -r requirements-lock.txt`. Si un `.joblib` no carga por cambio de versión, la salida es una corrida en modo reentrenar.

Los notebooks se abren desde `C:\Users\Home\Documents\GitHub\ProyectoEBSA\Pipeline_Ebsa` con `utilidades_borde.py`, `utilidades_calidad.py` y `utilidades_glosario.py` en esa misma carpeta. La búsqueda de hiperparámetros del notebook 7 lleva semilla (`TPESampler(seed=...)`), igual que la del 9, así que una misma serie produce los mismos resultados.
