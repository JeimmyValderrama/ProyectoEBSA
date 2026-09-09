# Proyecto EBSA — Consumo de energía por cliente

Análisis, agrupamiento, detección de caída y pronóstico del consumo eléctrico de los clientes de la Empresa de Energía de Boyacá (EBSA).

- **Clientes:** ~592.000 NIU.
- **Historia:** enero 2022 → enero 2026 (49 meses) en la extracción actual; crece un mes con cada archivo nuevo de la empresa.
- **Fuente:** los archivos mensuales XLSX/CSV que entrega la empresa (formato TC2), en `Datos_Ebsa\00_formato_TC2\`. **Nunca se modifican**: el pipeline los lee tal cual llegan.

---

## 1. Qué entrega el proyecto (los dos productos)

El proyecto termina en **dos productos independientes**. Cada uno tiene su propio modelo final y sus propias salidas.

| Producto | Pregunta que responde | Notebooks | Salida principal |
|---|---|---|---|
| **A. Gestión de caída de consumo** | ¿Qué clientes están dejando de consumir, cuánto vale esa pérdida, en qué ciclo de lectura están y por dónde empieza la cuadrilla? Incluye, por cliente, si el modelo prevé que el **próximo mes** siga cayendo o se recupere. | 9 → 10 → 11 | `07_gestion_caida\gestion_caida_operativa.csv` y `gestion_caida_gerencial.csv` |
| **B. Pronóstico de consumo a 6 meses** | ¿Cuánto va a consumir cada cliente en cada uno de los próximos 6 meses? | 1 → 8 (el modelo se entrena en el 8) | `04_pronostico\modelo_final\predicciones_segmentadas_optimizadas_6_meses.parquet` |

El producto A **usa** una columna del producto B (`pred_1m_kwh`, el pronóstico del mes siguiente) para la trayectoria, por eso el notebook 8 se corre antes que el 11.

Alrededor de los dos productos hay tres piezas que los mantienen honestos mes a mes: el **seguimiento** (notebook 12: cada pronóstico y cada lista anteriores contra lo que realmente pasó), la **retroalimentación de campo** (notebook 13: lo que encontraron las cuadrillas contra la lista) y la **compuerta de calidad** del archivo entrante (notebook 2). Todo se corre con un solo comando (`pipeline_mensual.py`, §7) y se consulta en una página web (`app_ebsa.py`, §10).

---

## 2. Rutas principales

Dos carpetas, separadas a propósito: el **código** en GitHub y los **datos** en Documentos. Son carpetas nuevas: el proyecto anterior (`Datos Ebsa` y la raíz de `GitHub\ProyectoEBSA`) queda intacto y los dos no se mezclan.

| Qué | Ruta | Dónde se define |
|---|---|---|
| **Código** (13 notebooks, `utilidades_borde.py`, `utilidades_calidad.py`, `pipeline_mensual.py`, `app_ebsa.py`, `preparar_carpeta_datos.py`) | `C:\Users\Home\Documents\GitHub\ProyectoEBSA\Pipeline_Ebsa` | Es donde se abren los notebooks y desde donde se corren los scripts. Los dos `utilidades_*.py` **deben estar en esta misma carpeta** para que el `import` funcione. |
| **Datos** (archivos de la empresa, intermedios, modelos, salidas) | `C:\Users\Home\Documents\Datos_Ebsa` | Variable `BASE_DIR` (o `DATA_DIR` en Exploración) en la primera celda de cada notebook, y `DATOS_POR_DEFECTO` en los scripts. Todos la leen primero de la variable de entorno `EBSA_DATOS` y, si no existe, usan esta ruta. |

Estructura completa de la carpeta de datos:

```
C:\Users\Home\Documents\Datos_Ebsa\
│
├── 00_formato_TC2\                ← los XLSX/CSV mensuales de la empresa (formato TC2). NO SE TOCAN. Entrada del paso 1.
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
└── 09_registro_corridas\          ← pipeline_mensual.py: un registro por corrida (notebooks ejecutados + resumen)

C:\Users\Home\Documents\GitHub\ProyectoEBSA\
└── Pipeline_Ebsa\                 ← EL CÓDIGO: 13 notebooks, utilidades_*.py, pipeline_mensual.py, app_ebsa.py
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
| `valor_riesgo_mes` | `perdida_kwh_mes × tarifa_kwh`, en pesos/mes. **Vacío** si no hay tarifa (no se inventa). |
| `valor_orden` | Solo para ordenar (los sin tarifa no se hunden al fondo). No mostrarlo como valor. |
| `variacion_vs_anterior_pct`, `variacion_vs_anio_pct` | Variación % del consumo reciente contra el periodo anterior y contra el mismo periodo del año pasado. |
| `meses_ventana` | 3 (lectura mensual) o 6 (lectura trimestral/rural). |
| `trayectoria` | Qué prevé el modelo para el **mes siguiente**: `CAIDA_ACELERANDO` (seguirá bajando más allá del error del modelo), `SIN_RECUPERACION_PREVISTA` (se queda donde está), `RECUPERACION_PREVISTA` (sube), `NO_EVALUABLE_RURAL` (rural excluido por sesgo), `SIN_PRONOSTICO` (el cliente no tiene predicción). |
| `pred_1m_kwh`, `variacion_proyectada_pct`, `wape_aplicable_pct` | Pronóstico del próximo mes, su variación contra el consumo reciente, y el error del modelo (WAPE h=1 de su perfil) usado como umbral. |
| `estado_en_lista` | `NUEVO` (primera vez en la lista), `PERSISTENTE` (también estaba el mes pasado), `REINCIDENTE` (estuvo en algún corte de los últimos 12 meses, pero no el pasado). Sale de cruzar con `historial\`. |
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

### 3.3 Seguimiento — precisión en vivo (lo que se muestra)

Carpeta: `Datos_Ebsa\08_seguimiento\` (notebook 12). Se llena mes a mes: solo puede evaluar meses que ya quedaron consolidados, así que en la primera corrida está vacío.

| Archivo | Contenido |
|---|---|
| `seguimiento_pronostico_global.csv` | Por fecha de corte y horizonte: `WAPE_pct` (error real del pronóstico contra lo que pasó), `sesgo_pct` (+ = pronosticó de más), `n`. **Es la precisión en vivo**, distinta del backtest. |
| `seguimiento_pronostico_por_perfil.csv` | Lo mismo por perfil, con `WAPE_backtest_pct` y `dif_vs_backtest_pp` al lado: si esa diferencia es claramente positiva varios meses seguidos, toca reentrenar. |
| `seguimiento_pronostico_por_zona.csv` | Lo mismo por rural / urbano. |
| `seguimiento_lista_gestion.csv` | Qué pasó con los clientes de cada lista en los meses siguientes: `RECUPERADO` (volvió al 90 % de lo que consumía antes de caer), `ESTABLE_BAJO` (se quedó en el nivel caído), `SIGUE_CAYENDO` (bajó del 90 % de su consumo reciente). Por trayectoria, severidad y zona: es la prueba de que las etiquetas discriminan. |

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
| 1 | `Exploracion_inicial.ipynb` | Lee todos los XLSX/CSV de `00_formato_TC2\`, unifica encabezados (esquema canónico + alias), guarda el detalle y un resumen NIU × mes por año. Analiza presencia mensual y periodicidad. | `00_formato_TC2\` | `01_historico_procesado\historico_YYYY.parquet`, `01_historico_procesado\detalle_mensual\` |
| 2 | `Reconstruccion_serie_tiempo_consumo_rural.ipynb` | Une los `historico_YYYY`, detecta lecturas largas (75–129 días = trimestrales, rurales) y reparte ese consumo en los meses que cubre. Deja una serie **mensual** por cliente. Valida que el consumo total se conserva. | Salida de 1 | `02_serie_reconstruida\` |
| 3 | `Preprocesamiento_serie_tiempo_para_modelado.ipynb` | Excluye alumbrado público (ciclo 15 + clase AP), marca ciclos rurales (10, 11, 12, 13, 19, 21, 22, 23, 38), deja la serie lista para modelar con `es_rural`, `consumo_kwh_mensual`, `regimen`, etc. Guarda el ciclo de cada NIU. | Salida de 2 | `03_serie_modelado\` ★ |
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
| — | `utilidades_borde.py` | Módulo Python (no es notebook). Detecta el borde provisional. Lo importan 8, 9, 10 y 12. | — | — |
| — | `utilidades_calidad.py` | Módulo Python (no es notebook). Compuerta de calidad del archivo entrante. Lo importa el 2. | — | — |
| — | `pipeline_mensual.py` | Script que corre los notebooks en orden con kernel limpio (§7). | — | `09_registro_corridas\` |
| — | `app_ebsa.py` | Página web (Streamlit) que muestra las salidas (§10). | — | — |
| — | `requirements.txt`, `generar_lock_entorno.py` | Dependencias del entorno (§11). | — | — |
| — | `preparar_carpeta_datos.py` | Crea la estructura de carpetas y dice qué copiar del proyecto anterior (§7.0). | — | — |

**Dependencias resumidas:**

```
1 → 2 → 3 ─┬─→ 4 (referencia, termina ahí)
           ├─→ 5 (referencia, termina ahí)
           ├─→ 6 → 7 → 8 ──────────────┐   Producto B (pronóstico 6 meses)
           └─→ 9 → 10 → 11 ←───────────┘   Producto A (gestión de caída; el 11 lee pred_1m_kwh del 8)
                          └─→ 12 → 13      Seguimiento y retroalimentación (leen los historiales de 8 y 11)
```

**Corrida mensual:** 1 → 2 → 3 → 8 → 9 → 10 → 11 → 12 → 13, en modo *aplicar*. Es exactamente lo que hace `python pipeline_mensual.py --modo aplicar` (§7). Los notebooks 4, 5, 6 y 7 son de desarrollo y solo se repiten si se quiere volver a elegir algoritmos o hiperparámetros.

---

## 5. Qué hay en cada carpeta y cómo leerlo

### 5.1 `01_historico_procesado\` (notebook 1)

- `historico_YYYY.parquet` — una fila por NIU × mes del año, con `consumo_kwh_raw`, `dias_facturados_max`, `fecha_lectura_anterior/actual`, `tarifa_aplicada_kwh`, `estrato`, `ciclo`, `clase_servicio`, `tipo_lectura`, etc. Es el resumen "tal como lo dice la empresa", **sin repartir** las lecturas trimestrales. De aquí sale la **tarifa real** que usa el notebook 11.
- `detalle_mensual\` — el detalle factura por factura de cada archivo original. Solo para auditar.
- `historico_temporal.pkl` — respaldo temporal del notebook 1; se puede ignorar.

### 5.2 `02_serie_reconstruida\` (notebook 2)

- `serie_mensual_consumo_reconstruida.parquet` — serie mensual por cliente con las lecturas trimestrales ya repartidas en sus meses.
- `perfil_periodicidad_clientes.parquet` — por NIU: si su lectura es mensual o trimestral, cuántas lecturas largas tiene, etc.
- `validacion_conservacion_consumo.parquet` — prueba de que la suma de consumo antes y después de repartir es la misma.
- `aportes_lecturas_trimestrales.parquet` — trazabilidad: qué lectura larga aportó cuánto a qué mes.

### 5.3 `03_serie_modelado\` (notebook 3) ★

- `serie_mensual_modelado_preprocesada.parquet` — **la entrada de todos los modelos** (notebooks 4–11). Columnas clave: `NIU`, `periodo`, `consumo_kwh_mensual`, `es_rural`, `regimen` (observado / reconstruido), `ciclo`, `estrato`, `clase_servicio`.
- `niu_ciclo.parquet` — ciclo de lectura (0–99) de cada NIU. Lo usa el 11 para la vista operativa.
- `nius_alumbrado_publico_excluidos.parquet` — los NIU de alumbrado público que se sacaron.
- `auditoria_preprocesamiento_modelado.csv`, `auditoria_cobertura_mensual.csv` — cuántos clientes y cuánto consumo quedó por mes después de cada filtro.

En `02_serie_reconstruida\` queda además `control_calidad_mes_entrante.csv` (notebook 2): un chequeo por fila (columnas esenciales, clientes vs. previos, consumo total, tarifa, ciclos nuevos, duplicados, fechas de lectura) con `resultado` OK / ERROR / AVISO y el detalle. Los umbrales están documentados en `utilidades_calidad.py`.

### 5.4 `04_pronostico\desarrollo_01_modelo_unico\` (notebook 4) y `04_pronostico\desarrollo_02_segmentado\` (notebook 5) — referencia

Resultados de las dos primeras versiones del pronóstico (`modelo_consumo_ganador.joblib`, `modelos_segmentados_consumo.joblib`, `predicciones_*`, `metricas_*`). Sirven para contar la evolución del proyecto (un modelo → modelos por perfil → comparación de algoritmos → optimización). **Nada posterior los lee.**

### 5.5 `04_pronostico\modelo_final\` (notebooks 6, 7, 8)

Del 6 (sistema original): `comparacion_modelos_validacion.csv` (LGBM vs XGB vs CatBoost por grupo), `seleccion_modelo_por_perfil_horizonte.csv`, `metricas_sistema_por_perfil_horizonte.csv`, `metricas_sistema_ganador_backtest.csv`, `modelos_ganadores_segmentados.joblib`, `predicciones_segmentadas_ganadoras_*.parquet`, `perfiles_consumidores_corte_final.parquet` (perfil P0–P4 de cada cliente), `grandes_consumidores_corte_final.parquet`.

Del 7: `hiperparametros_optimos_por_grupo.json`, `seleccion_modelo_por_perfil_horizonte_optimizada.csv`, `modelos_ganadores_optimizados.joblib` (entrenados hasta el corte de validación, no el final), `optuna_estudios.sqlite3` (historial de la búsqueda; se puede borrar sin perder nada).

Del 8 (sistema final): todo lo que termina en `_optimizado` o `_optimizadas` (ver §3.2 y §3.4), más:
- `comparacion_backtest_original_vs_optimizado.csv` — WAPE del sistema del 6 vs. el del 8 por perfil y horizonte, con columna `comparable` (`False` cuando el mes objetivo era provisional y la comparación no es justa).
- `diagnostico_tope_muestra.csv` — resultado de la celda 32: WAPE con tope 60k / 120k / sin tope. Concluyó que el tope cuesta ~0,1 punto, por eso se mantiene.
- `historial_pronosticos\predicciones_6_meses_corte_AAAA-MM.parquet` — el pronóstico de cada corte, con `modo` y `fecha_corte_modelo` (con qué corte se entrenó el modelo que lo produjo). Los lee el notebook 12.

**Cómo leer las métricas:** `WAPE_final_pct` es el error porcentual ponderado; 25 % significa que, sumando todos los clientes del grupo, el pronóstico se desvía un 25 % del real. Se compara siempre con `WAPE_baseline_pct` (lo que daría repetir el consumo reciente): el modelo vale si está por debajo. Los perfiles: `P0_INTERMITENTE` (muchos ceros), `P1_REGULAR` (la mayoría), `P2_ALTO`, `P3_GRANDE`, `P4_INSUFICIENTE` (sin historia suficiente, solo línea base).

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

## 6. El mes provisional (importante para cualquier corrida futura)

Los clientes rurales se leen cada tres meses. En cualquier extracción, al **último mes** solo le ha llegado la lectura de una parte de ellos, así que ese mes aparece con la mitad del consumo normal (en la extracción de enero 2026: 47,9 % en rurales). No es un error: se completa hacia arriba cuando llegan las lecturas siguientes.

Por eso **ningún modelo debe entrenarse ni evaluarse con ese mes**. `utilidades_borde.py` lo detecta solo, en cada corrida, con dos pruebas (contra la mediana de los 12 meses previos **y** contra el mismo mes del año anterior, para no confundir estacionalidad con borde), y devuelve el último mes consolidado. Lo usan el notebook 8 (corte de entrenamiento y exclusión de objetivos provisionales de las métricas), el 9 y el 10 (fin de la ventana de 12 meses y de las ventanas de comparación: `MESES_RETROCESO_VENTANA = None` significa automático) y el 12 (solo evalúa contra meses consolidados).

Cuando llegue el archivo de febrero 2026: enero se completa, febrero pasa a ser el provisional, y el detector mueve el corte solo. **No hay que cambiar ningún número a mano.** Si alguna vez el detector quiere retroceder más de 3 meses, se detiene con error: significa que la extracción llegó mal y hay que revisarla antes de seguir.

---

## 7. Procedimiento cuando llega un mes nuevo

1. Copiar el archivo nuevo de la empresa a `Datos_Ebsa\` (junto a los demás, sin renombrar ni editar).
2. Abrir una consola en `C:\Users\Home\Documents\GitHub\ProyectoEBSA\Pipeline_Ebsa` y correr:

   ```
   python pipeline_mensual.py --modo aplicar
   ```

   Esto ejecuta 1 → 2 → 3 → 8 → 9 → 10 → 11 → 12 → 13 con kernel limpio, usando los modelos guardados (sin reentrenar). Tarda minutos. Cada notebook ejecutado, con sus salidas, queda en `Datos_Ebsa\09_registro_corridas\<fecha-hora>_aplicar\` como registro, junto a `resumen_corrida.txt`. Los notebooks originales no se tocan.
3. Si un paso falla, el pipeline se detiene, muestra el error y dice con qué comando reanudar (`--desde N`). Los dos fallos "buenos" (los que protegen las salidas) son: la **compuerta de calidad** del notebook 2, cuando el archivo llegó con menos clientes, tarifas en cero o un ciclo desconocido; y el **detector del borde**, cuando quiere retroceder más de 3 meses. En ambos casos hay que mirar el archivo, no forzar la corrida.
4. Revisar tres cosas en el registro: el bloque `CONTROL DE CALIDAD DEL MES ENTRANTE` (notebook 2), el bloque `DETECCIÓN DEL BORDE PROVISIONAL` (notebook 8) y el bloque de sesgo rural (notebook 11). Son los controles que dicen si el mes entró bien.
5. Abrir la página (`streamlit run app_ebsa.py`, §10) o leer directamente `07_gestion_caida\`, `04_pronostico\modelo_final\` y `08_seguimiento\`.

Otros usos del script:

```
python pipeline_mensual.py --lista                          # ver los pasos
python pipeline_mensual.py --modo aplicar --desde 9         # reanudar desde el 9
python pipeline_mensual.py --modo aplicar --solo 11,12,13   # solo esos pasos
python pipeline_mensual.py --modo reentrenar                # corrida de reentrenamiento (§8)
python pipeline_mensual.py --modo aplicar --datos "D:\otra\Datos_Ebsa"   # solo si los datos no están en Documentos\Datos_Ebsa
```

## 8. Modo aplicar y modo reentrenar

Los notebooks 8, 9 y 10 leen la variable de entorno `EBSA_MODO` (la fija `pipeline_mensual.py`; si se abren a mano en Jupyter, vale el valor por defecto de la primera celda, `reentrenar`).

| | `aplicar` (cada mes) | `reentrenar` (cada trimestre o semestre) |
|---|---|---|
| Pronóstico (8) | Carga `modelos_ganadores_optimizados_final.joblib`, verifica el contrato y pronostica desde el último mes consolidado. No hace backtest. | Backtest + reentrenamiento con toda la historia + pronóstico. Sobreescribe el `.joblib`. Horas. |
| Agrupamiento (9) | Carga `modelo_agrupamiento.joblib` y asigna cluster y nombre guardados. Los segmentos no cambian de nombre entre meses. | Comparación de algoritmos con Optuna y nuevos nombres. Sobreescribe el `.joblib`. |
| Caída (10) | Usa `criterios_caida_por_segmento.joblib`: la misma regla que el mes anterior. Guarda la deriva en `deriva_criterios_caida.csv`. | Recalcula los umbrales y los guarda. |

**Cuándo toca reentrenar.** Cualquiera de estas señales: el notebook 8 avisa que el modelo lleva más de 6 meses sin reentrenar; en `seguimiento_pronostico_por_perfil.csv` la columna `dif_vs_backtest_pp` es claramente positiva varios meses seguidos; el notebook 9 avisa que el perfil de un cluster ya no corresponde a su nombre; el notebook 10 avisa que algún segmento cambiaría de criterio o que los umbrales se movieron más de 10 puntos. Antes de reentrenar conviene correr también 6 y 7 si se quiere revisar la elección de algoritmos e hiperparámetros; si no, el 8 reutiliza los que están.

## 9. Retroalimentación de campo

La lista dice *quién* parece estar dejando de consumir; solo la visita dice *por qué*. Para cerrar ese ciclo:

1. Copiar `07_gestion_caida\retroalimentacion\resultado_gestion_plantilla.csv` como `resultado_gestion_<mes>.csv` en esa misma carpeta (la crea el notebook 13 la primera vez que corre).
2. Una fila por cliente visitado: `NIU`, `fecha_corte_lista` (el `fecha_corte` de la lista de donde salió, formato AAAA-MM), `fecha_visita`, `hallazgo`, `accion`, `observaciones`.
3. `hallazgo` toma un valor del catálogo, agrupado así: **con causa gestionable** (`MEDIDOR_DANADO`, `MEDIDOR_MANIPULADO_O_FRAUDE`, `ERROR_DE_LECTURA_O_FACTURACION`, `ACOMETIDA_O_RED_CON_FALLA`, `CONEXION_IRREGULAR`), **caída real sin gestión** (`PREDIO_DESOCUPADO`, `CAMBIO_DE_ACTIVIDAD_O_HABITO`, `AUTOGENERACION`, `CLIENTE_RETIRADO`), **sin novedad** (`SIN_NOVEDAD`: falso positivo) y **no verificado** (`NO_UBICADO`, `PENDIENTE`). El catálogo se puede ampliar en la primera celda del notebook 13.
4. El notebook 13 (lo corre el pipeline) produce `evaluacion_retroalimentacion_resumen.csv`: cobertura de la lista, precisión gestionable y precisión de caída real por severidad, trayectoria, estado en lista, tramo, zona, segmento y ciclo. Si un cruce muestra precisión baja de forma sostenida, ese grupo debe bajar en el orden de la lista; ese ajuste se hace en el notebook 11.

## 10. Página web

`app_ebsa.py` es una aplicación Streamlit que **solo lee** las salidas del pipeline (no entrena ni recalcula nada). Para abrirla:

```
pip install streamlit        # una sola vez
streamlit run app_ebsa.py    # se abre en http://localhost:8501
```

Secciones: Resumen (cifras del corte, trayectoria, estado en lista, valor por ciclo, severidad), Gestión por ciclo (lista operativa filtrable y descargable por ciclo), Ranking gerencial, Cortes (clase, estrato, zona, tramo), Buscar cliente (segmento, caída, posición en la lista y pronóstico a 6 meses de un NIU), Pronóstico 6 meses (totales proyectados y precisión por perfil), Seguimiento, Retroalimentación y Estado del pipeline (control de calidad y últimas corridas). La carpeta de datos se toma de `EBSA_DATOS` o se cambia en la barra lateral.

## 11. Entorno

Python 3.10+ con las dependencias de `requirements.txt` (`pip install -r requirements.txt`). Los `.joblib` de LightGBM, XGBoost, CatBoost y scikit-learn dependen de la versión instalada: para dejar constancia de las versiones exactas de la máquina que entrenó los modelos, correr una vez `python generar_lock_entorno.py`, que escribe `requirements-lock.txt`; otra máquina reproduce el entorno con `pip install -r requirements-lock.txt`. Si un `.joblib` no carga por cambio de versión, la salida es una corrida en modo reentrenar.

Los notebooks se abren desde `C:\Users\Home\Documents\GitHub\ProyectoEBSA\Pipeline_Ebsa` con `utilidades_borde.py` y `utilidades_calidad.py` en esa misma carpeta. La búsqueda de hiperparámetros del notebook 7 lleva semilla (`TPESampler(seed=...)`), igual que la del 9, así que una misma serie produce los mismos resultados.
