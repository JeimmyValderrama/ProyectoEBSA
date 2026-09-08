# Proyecto EBSA — Consumo de energía por cliente

Análisis, agrupamiento, detección de caída y pronóstico del consumo eléctrico de los clientes de la Empresa de Energía de Boyacá (EBSA).

- **Clientes:** ~592.000 NIU.
- **Historia:** enero 2022 → enero 2026 (49 meses) en la extracción actual; crece un mes con cada archivo nuevo de la empresa.
- **Fuente:** los archivos mensuales XLSX/CSV que entrega la empresa. **Nunca se modifican**: el pipeline los lee tal cual llegan.

---

## 1. Qué entrega el proyecto (los dos productos)

El proyecto termina en **dos productos independientes**. Cada uno tiene su propio modelo final y sus propias salidas.

| Producto | Pregunta que responde | Notebooks | Salida principal |
|---|---|---|---|
| **A. Gestión de caída de consumo** | ¿Qué clientes están dejando de consumir, cuánto vale esa pérdida, en qué ciclo de lectura están y por dónde empieza la cuadrilla? Incluye, por cliente, si el modelo prevé que el **próximo mes** siga cayendo o se recupere. | 9 → 10 → 11 | `gestion_caida\gestion_caida_operativa.csv` y `gestion_caida_gerencial.csv` |
| **B. Pronóstico de consumo a 6 meses** | ¿Cuánto va a consumir cada cliente en cada uno de los próximos 6 meses? | 1 → 8 (el modelo se entrena en el 8) | `modelacion_consumo_segmentada_comparativa\predicciones_segmentadas_optimizadas_6_meses.parquet` |

El producto A **usa** una columna del producto B (`pred_1m_kwh`, el pronóstico del mes siguiente) para la trayectoria, por eso el notebook 8 se corre antes que el 11.

---

## 2. Rutas principales

Hay dos carpetas raíz. Solo estas dos rutas están escritas en el código; todo lo demás cuelga de ellas.

| Qué | Ruta | Dónde se define |
|---|---|---|
| **Código** (notebooks + `utilidades_borde.py`) | `C:\Users\Home\Documents\GitHub\ProyectoEBSA` | Es donde se abren los notebooks. `utilidades_borde.py` **debe estar en esta misma carpeta** para que el `import` funcione. |
| **Datos** (entradas, intermedios, modelos, salidas) | `C:\Users\Home\Documents\Datos Ebsa` | Variable `BASE_DIR` (o `DATA_DIR` en Exploración) en la primera celda de cada notebook. Si el proyecto se mueve de máquina, es lo único que hay que cambiar. |

Estructura completa de la carpeta de datos:

```
C:\Users\Home\Documents\Datos Ebsa\
│
├── *.xlsx / *.csv                          ← archivos originales de la empresa (uno por mes). NO SE TOCAN.
│
├── Procesado\                              ← Notebook 1 (Exploración)
│   ├── historico_2022.parquet ... historico_2026.parquet   (un resumen NIU × mes por año, 31 columnas)
│   └── detalle_mensual\                    (detalle factura a factura, por archivo)
│
└── Serie_tiempo_consumo\
    ├── fuente_historicos\                  ← copia de trabajo de los historico_YYYY (Notebook 2)
    ├── salidas\                            ← Notebook 2 (Reconstrucción rural)
    ├── preprocesamiento_modelo\            ← Notebook 3 (Preprocesamiento)   ★ ENTRADA DE TODOS LOS MODELOS
    ├── modelacion_consumo\                 ← Notebook 4 (primer modelo, sin segmentar) — histórico
    ├── modelacion_consumo_segmentada\      ← Notebook 5 (modelo segmentado v1) — histórico
    ├── modelacion_consumo_segmentada_comparativa\   ← Notebooks 6, 7 y 8   ★ MODELO FINAL DE PRONÓSTICO
    ├── agrupamiento_clientes\              ← Notebook 9    ★ MODELO FINAL DE AGRUPAMIENTO
    ├── estudio_caida\                      ← Notebook 10   ★ CRITERIOS FINALES DE CAÍDA
    └── gestion_caida\                      ← Notebook 11   ★ LISTAS FINALES PARA GESTIÓN
```

---

## 3. Modelos y archivos finales para la página web

Esto es lo que una aplicación web debe **leer**. Todo lo demás del proyecto es intermedio o de auditoría.

### 3.1 Producto A — Gestión de caída (lo que se muestra)

Carpeta: `Datos Ebsa\Serie_tiempo_consumo\gestion_caida\`

| Archivo | Para qué sirve en la página |
|---|---|
| `gestion_caida_operativa.csv` | **Vista por ciclo.** Un cliente por fila, ordenado por ciclo (00–99) y, dentro del ciclo, por valor en riesgo. Es la lista que usa una cuadrilla. |
| `gestion_caida_gerencial.csv` | **Vista gerencial.** Los mismos clientes ordenados por valor en riesgo de mayor a menor, con `ranking` global. |
| `resumen_gestion_por_ciclo.csv` | Total de clientes, kWh y pesos en riesgo por ciclo, con % acumulado. Sirve para el gráfico "qué ciclos concentran el riesgo". |
| `resumen_gestion_por_corte.csv` | Los mismos totales por `estrato`, `clase_servicio`, `tramo_consumo` y `zona`. |
| `diagnostico_sesgo_pronostico.csv` | Explica si la trayectoria se calculó también para rurales (brecha de sesgo rural vs urbano). |
| `auditoria_tarifa.csv` | Cuántos clientes tienen tarifa real y cuántos no. |

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

### 3.2 Producto B — Pronóstico a 6 meses (lo que se muestra)

Carpeta: `Datos Ebsa\Serie_tiempo_consumo\modelacion_consumo_segmentada_comparativa\`

| Archivo | Contenido |
|---|---|
| `predicciones_segmentadas_optimizadas_6_meses.parquet` | **Una fila por cliente**, con `pred_1m_kwh` … `pred_6m_kwh` y sus fechas `fecha_pred_1m` … `fecha_pred_6m`, `promedio_pred_3m_kwh`, `promedio_pred_6m_kwh`, `perfil`, `modelo_Xm` (algoritmo usado), `alpha_ml_Xm` (peso del ML vs. la línea base), `fecha_corte`, `regimen_actual` (`observado` = leído ese mes; `reconstruido` = viene de una lectura trimestral repartida). |
| `predicciones_segmentadas_optimizadas_3_meses.parquet` | Igual, solo horizontes 1–3. |
| `metricas_sistema_por_perfil_horizonte_optimizado.csv` | Error esperado (WAPE %) por perfil y horizonte. **Lo que se debe mostrar como "precisión" del pronóstico.** |
| `metricas_sistema_ganador_backtest_optimizado.csv` | Error global por horizonte en el backtest. |
| `real_vs_pronosticado_sistema_optimizado_backtest.parquet` | Real vs. pronosticado del backtest, para gráficas de "cómo le fue al modelo". |

### 3.3 Modelos entrenados (lo que la página carga si necesita **volver a predecir**)

Si la página solo muestra las salidas ya calculadas, no necesita cargar modelos. Los necesita si va a puntuar clientes nuevos o el mes nuevo sin correr los notebooks.

| Modelo | Ruta | Qué contiene | Cómo se usa |
|---|---|---|---|
| **Pronóstico (final)** | `modelacion_consumo_segmentada_comparativa\modelos_ganadores_optimizados_final.joblib` | Diccionario con `modelos[(perfil, h)]` (un modelo por perfil × horizonte 1–6, LightGBM/XGBoost/CatBoost), `mapa_seleccion_optimizado` (qué algoritmo y qué `alpha_ml` usa cada grupo), `hiperparametros`, `features` (lista y orden exacto de columnas de entrada), `config_perfiles` (umbrales para clasificar clientes en P0–P4), `fecha_corte`, `horizontes`. | `import joblib; b = joblib.load(ruta); b["modelos"][("P1_REGULAR", 1)]`. Las features se construyen igual que en el notebook 8 (funciones `calcular_perfiles`, `crear_features`, `baseline_hibrido`); el pronóstico final es `alpha_ml × pred_ml + (1 − alpha_ml) × baseline`. |
| Pronóstico — hiperparámetros | `...\hiperparametros_optimos_por_grupo.json` | Los mismos hiperparámetros, legibles. | Auditoría / reentrenar. |
| Pronóstico — selección | `...\seleccion_modelo_por_perfil_horizonte_optimizada.csv` | Qué algoritmo ganó en cada perfil × horizonte y con qué `alpha_ml`. | Mostrar "qué modelo se usa para cada grupo". |
| **Agrupamiento (final)** | `agrupamiento_clientes\modelo_agrupamiento.joblib` | Diccionario con, por zona (`URBANO`, `RURAL`): `modelo` (clustering), `scaler` (RobustScaler), `limites_winsor` (recorte p1–p99), `mapa_segmentos` (cluster → nombre de negocio). Además `columnas_clustering` (orden exacto), `catalogo_segmentos` (nombre → acción y prioridad), `tramos_consumo`, `umbrales_negocio`, `semilla`, `ventana`. | Para un cliente nuevo: construir las mismas features de 12 meses → winsorizar con `limites_winsor` → `scaler.transform` → `modelo.predict` → `mapa_segmentos` → nombre `ZONA_SEGMENTO_TRAMO`. |
| **Criterios de caída (final)** | `estudio_caida\criterios_caida_por_segmento.joblib` (copia legible: `.csv`) | Umbrales de caída **por segmento** (`umbrales_vs_anterior`, `umbrales_vs_anio`), con el criterio usado (`PORCENTAJE` o `KWH`), y los parámetros (`K_DESVIACIONES`, banda [−60, −10] %, `UMBRAL_MINIMO_PERDIDA_KWH = 10`). | Reaplicar exactamente la misma regla en el mes siguiente sin recalcular umbrales, para que dos meses sean comparables. |
| **Detector del borde provisional** | `GitHub\ProyectoEBSA\utilidades_borde.py` | Función `ultimo_periodo_consolidado(serie)` → último mes que se puede usar. | Cualquier proceso que consuma la serie mensual debe llamar esto antes de entrenar o predecir (ver §6). |

> Los archivos `modelos_ganadores_segmentados.joblib` (notebook 6) y `modelos_ganadores_optimizados.joblib` (notebook 7) también existen en la misma carpeta, pero son **versiones anteriores**. El final es `modelos_ganadores_optimizados_final.joblib`.

---

## 4. Orden de ejecución

Todos los notebooks se corren de arriba abajo, con **kernel reiniciado**, en este orden. Cada uno lee lo que escribió el anterior.

| # | Notebook | Qué hace | Necesita | Produce en |
|---|---|---|---|---|
| 1 | `Exploracion_inicial.ipynb` | Lee todos los XLSX/CSV de la empresa, unifica encabezados (esquema canónico + alias), guarda el detalle y un resumen NIU × mes por año. Analiza presencia mensual y periodicidad. | Archivos originales en `Datos Ebsa\` | `Procesado\historico_YYYY.parquet`, `Procesado\detalle_mensual\` |
| 2 | `Reconstruccion_serie_tiempo_consumo_rural.ipynb` | Une los `historico_YYYY`, detecta lecturas largas (75–129 días = trimestrales, rurales) y reparte ese consumo en los meses que cubre. Deja una serie **mensual** por cliente. Valida que el consumo total se conserva. | Salida de 1 | `Serie_tiempo_consumo\salidas\` |
| 3 | `Preprocesamiento_serie_tiempo_para_modelado.ipynb` | Excluye alumbrado público (ciclo 15 + clase AP), marca ciclos rurales (10, 11, 12, 13, 19, 21, 22, 23, 38), deja la serie lista para modelar con `es_rural`, `consumo_kwh_mensual`, `regimen`, etc. Guarda el ciclo de cada NIU. | Salida de 2 | `Serie_tiempo_consumo\preprocesamiento_modelo\` ★ |
| 4 | `Modelado_prediccion_consumo_3_6_meses.ipynb` | **Primer modelo** (un solo modelo para todos los clientes, muestra de 50.000). Sirvió para demostrar que hacía falta segmentar. Se conserva como referencia; **no alimenta nada posterior**. | Salida de 3 | `modelacion_consumo\` |
| 5 | `Modelado_prediccion_consumo_segmentado_3_6_meses.ipynb` | Introduce los **perfiles** (P0 intermitente, P1 regular, P2 alto, P3 grande, P4 insuficiente), un modelo por perfil × horizonte, y el blend ML + línea base. Solo LightGBM. **Tampoco alimenta nada posterior.** | Salida de 3 | `modelacion_consumo_segmentada\` |
| 6 | `Modelado_segmentado_comparacion_modelos_3_6_meses.ipynb` | Compara LightGBM, XGBoost y CatBoost por perfil × horizonte, elige ganador, hace backtest y pronóstico. **Sus CSV de backtest los lee el notebook 8** para la comparación original vs optimizado. | Salida de 3 | `modelacion_consumo_segmentada_comparativa\` (`seleccion_modelo_por_perfil_horizonte.csv`, `metricas_sistema_*.csv`, `modelos_ganadores_segmentados.joblib`) |
| 7 | `Optimizacion_hiperparametros_modelos_finales.ipynb` | Optuna sobre los ganadores del 6. Guarda los mejores hiperparámetros y la selección optimizada. | Salida de 3 y 6 | `hiperparametros_optimos_por_grupo.json`, `seleccion_modelo_por_perfil_horizonte_optimizada.csv`, `optuna_estudios.sqlite3` |
| 8 | `Backtest_y_reentrenamiento_final_optimizado.ipynb` | **Modelo final de pronóstico.** Etapa 1: backtest con corte 2025-07 (examen contra meses ya ocurridos), excluyendo de las métricas los meses provisionales. Etapa 2: detecta el último mes consolidado con `utilidades_borde`, reentrena con toda la historia y pronostica 6 meses. Celda 32: diagnóstico del tope de muestra (opcional, lento). | Salida de 3, 6, 7 + `utilidades_borde.py` | `modelos_ganadores_optimizados_final.joblib`, `predicciones_segmentadas_optimizadas_3/6_meses.parquet`, `metricas_*_optimizado.csv`, `comparacion_backtest_original_vs_optimizado.csv` |
| 9 | `Agrupamiento_clientes_consumo.ipynb` | **Modelo final de agrupamiento.** Features de 12 meses por cliente, separación de grupos estructurales por regla (p. ej. 100 % ceros), winsor + RobustScaler, comparación de algoritmos con Optuna (semilla fija), nombres de negocio con acción y prioridad. | Salida de 3 (+ perfil de periodicidad de 2) | `agrupamiento_clientes\` |
| 10 | `Estudio_caida_consumo.ipynb` | **Criterios de caída.** Ventana de 3 meses (mensual) o 6 (rural), comparación vs. periodo anterior y vs. año pasado, umbrales por segmento, veredicto y severidad. | Salida de 3 y 9 | `estudio_caida\` |
| 11 | `Priorizacion_gestion_caida.ipynb` | **Listas de gestión.** Cruza la caída con ciclo, tarifa real, estrato, clase y tramo; calcula valor en riesgo; añade trayectoria con `pred_1m_kwh` del 8. | Salida de 3, 8, 9, 10 + `Procesado\` (tarifa) | `gestion_caida\` |
| — | `utilidades_borde.py` | Módulo Python (no es notebook, no se ejecuta solo). Lo importan el 8 y, en adelante, cualquier notebook que necesite saber hasta qué mes están completos los datos. | — | — |

**Dependencias resumidas:**

```
1 → 2 → 3 ─┬─→ 4 (referencia, termina ahí)
           ├─→ 5 (referencia, termina ahí)
           ├─→ 6 → 7 → 8 ──────────────┐   Producto B (pronóstico 6 meses)
           └─→ 9 → 10 → 11 ←───────────┘   Producto A (gestión de caída; el 11 lee pred_1m_kwh del 8)
```

**Corrida mínima para actualizar los productos con un mes nuevo:** 1 → 2 → 3 → 8 → 9 → 10 → 11. Los notebooks 4, 5, 6 y 7 son de desarrollo y solo se repiten si se quiere volver a elegir algoritmos o hiperparámetros.

---

## 5. Qué hay en cada carpeta y cómo leerlo

### 5.1 `Procesado\` (notebook 1)

- `historico_YYYY.parquet` — una fila por NIU × mes del año, con `consumo_kwh_raw`, `dias_facturados_max`, `fecha_lectura_anterior/actual`, `tarifa_aplicada_kwh`, `estrato`, `ciclo`, `clase_servicio`, `tipo_lectura`, etc. Es el resumen "tal como lo dice la empresa", **sin repartir** las lecturas trimestrales. De aquí sale la **tarifa real** que usa el notebook 11.
- `detalle_mensual\` — el detalle factura por factura de cada archivo original. Solo para auditar.
- `historico_temporal.pkl` — respaldo temporal del notebook 1; se puede ignorar.

### 5.2 `Serie_tiempo_consumo\salidas\` (notebook 2)

- `serie_mensual_consumo_reconstruida.parquet` — serie mensual por cliente con las lecturas trimestrales ya repartidas en sus meses.
- `perfil_periodicidad_clientes.parquet` — por NIU: si su lectura es mensual o trimestral, cuántas lecturas largas tiene, etc.
- `validacion_conservacion_consumo.parquet` — prueba de que la suma de consumo antes y después de repartir es la misma.
- `aportes_lecturas_trimestrales.parquet` — trazabilidad: qué lectura larga aportó cuánto a qué mes.

### 5.3 `Serie_tiempo_consumo\preprocesamiento_modelo\` (notebook 3) ★

- `serie_mensual_modelado_preprocesada.parquet` — **la entrada de todos los modelos** (notebooks 4–11). Columnas clave: `NIU`, `periodo`, `consumo_kwh_mensual`, `es_rural`, `regimen` (observado / reconstruido), `ciclo`, `estrato`, `clase_servicio`.
- `niu_ciclo.parquet` — ciclo de lectura (0–99) de cada NIU. Lo usa el 11 para la vista operativa.
- `nius_alumbrado_publico_excluidos.parquet` — los NIU de alumbrado público que se sacaron.
- `auditoria_preprocesamiento_modelado.csv`, `auditoria_cobertura_mensual.csv` — cuántos clientes y cuánto consumo quedó por mes después de cada filtro.

### 5.4 `modelacion_consumo\` (notebook 4) y `modelacion_consumo_segmentada\` (notebook 5) — históricos

Resultados de las dos primeras versiones del pronóstico (`modelo_consumo_ganador.joblib`, `modelos_segmentados_consumo.joblib`, `predicciones_*`, `metricas_*`). Sirven para contar la evolución del proyecto (un modelo → modelos por perfil → comparación de algoritmos → optimización). **Nada posterior los lee.**

### 5.5 `modelacion_consumo_segmentada_comparativa\` (notebooks 6, 7, 8)

Del 6 (sistema original): `comparacion_modelos_validacion.csv` (LGBM vs XGB vs CatBoost por grupo), `seleccion_modelo_por_perfil_horizonte.csv`, `metricas_sistema_por_perfil_horizonte.csv`, `metricas_sistema_ganador_backtest.csv`, `modelos_ganadores_segmentados.joblib`, `predicciones_segmentadas_ganadoras_*.parquet`, `perfiles_consumidores_corte_final.parquet` (perfil P0–P4 de cada cliente), `grandes_consumidores_corte_final.parquet`.

Del 7: `hiperparametros_optimos_por_grupo.json`, `seleccion_modelo_por_perfil_horizonte_optimizada.csv`, `modelos_ganadores_optimizados.joblib` (entrenados hasta el corte de validación, no el final), `optuna_estudios.sqlite3` (historial de la búsqueda; se puede borrar sin perder nada).

Del 8 (sistema final): todo lo que termina en `_optimizado` o `_optimizadas` (ver §3.2 y §3.3), más:
- `comparacion_backtest_original_vs_optimizado.csv` — WAPE del sistema del 6 vs. el del 8 por perfil y horizonte, con columna `comparable` (`False` cuando el mes objetivo era provisional y la comparación no es justa).
- `diagnostico_tope_muestra.csv` — resultado de la celda 32: WAPE con tope 60k / 120k / sin tope. Concluyó que el tope cuesta ~0,1 punto, por eso se mantiene.

**Cómo leer las métricas:** `WAPE_final_pct` es el error porcentual ponderado; 25 % significa que, sumando todos los clientes del grupo, el pronóstico se desvía un 25 % del real. Se compara siempre con `WAPE_baseline_pct` (lo que daría repetir el consumo reciente): el modelo vale si está por debajo. Los perfiles: `P0_INTERMITENTE` (muchos ceros), `P1_REGULAR` (la mayoría), `P2_ALTO`, `P3_GRANDE`, `P4_INSUFICIENTE` (sin historia suficiente, solo línea base).

### 5.6 `agrupamiento_clientes\` (notebook 9)

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

### 5.7 `estudio_caida\` (notebook 10)

- `estudio_caida_consumo.parquet` — **todos** los clientes evaluados, con `veredicto`, `severidad`, `tipo_hallazgo`, consumos y variaciones.
- `resumen_caida_por_segmento.csv` — por segmento: cuántos clientes marcados, % del segmento, kWh perdidos (solo de los marcados).
- `clientes_caida_prioritarios.csv` — lista corta ordenada por kWh perdidos y concentración.
- `criterios_caida_por_segmento.csv` / `.joblib` — los umbrales aplicados (ver §3.3).
- `diagnostico_borde_ventana.csv` — nivel del último mes vs. lo normal, por zona; justifica el retroceso de la ventana.

**Veredictos:** `CAIDA_CONFIRMADA` (cae vs. periodo anterior y vs. año pasado), `CAIDA_RECIENTE` (solo vs. anterior), `CAIDA_SOSTENIDA` (solo vs. año pasado: ya venía bajo), `SIN_CAIDA`, `SIN_BASE_COMPARABLE` (no hay periodo anterior), `NO_APLICA` (segmentos sin consumo o sin datos), `NO_EVALUADO` (no alcanzó a evaluarse en la ventana). **Severidad:** cuántas "escalas" (desviaciones robustas de su segmento) supera el umbral: ≥ 2 `CRITICA`, ≥ 1 `FUERTE`, resto `MODERADA`. **Tipo de hallazgo:** `DESCUBRIMIENTO` (cae un cliente de un segmento estable: es noticia) vs. `CONFIRMACION` (cae uno de un segmento que ya era de caída).

### 5.8 `gestion_caida\` (notebook 11)

Descrito completo en §3.1.

---

## 6. El mes provisional (importante para cualquier corrida futura)

Los clientes rurales se leen cada tres meses. En cualquier extracción, al **último mes** solo le ha llegado la lectura de una parte de ellos, así que ese mes aparece con la mitad del consumo normal (en la extracción de enero 2026: 47,9 % en rurales). No es un error: se completa hacia arriba cuando llegan las lecturas siguientes.

Por eso **ningún modelo debe entrenarse ni evaluarse con ese mes**. `utilidades_borde.py` lo detecta solo, en cada corrida, con dos pruebas (contra la mediana de los 12 meses previos **y** contra el mismo mes del año anterior, para no confundir estacionalidad con borde), y devuelve el último mes consolidado. El notebook 8 ya lo usa para el corte de entrenamiento y para excluir de las métricas los objetivos provisionales; los notebooks 9 y 10 retroceden un mes la ventana (`MESES_RETROCESO_VENTANA = 1`), que hoy coincide con lo que detecta el módulo.

Cuando llegue el archivo de febrero 2026: enero se completa, febrero pasa a ser el provisional, y el detector mueve el corte solo. **No hay que cambiar ningún número a mano.** Si alguna vez el detector quiere retroceder más de 3 meses, se detiene con error: significa que la extracción llegó mal y hay que revisarla antes de seguir.

---

## 7. Procedimiento cuando llega un mes nuevo

1. Copiar el archivo nuevo de la empresa a `Datos Ebsa\` (junto a los demás, sin renombrar ni editar).
2. Correr **1 → 2 → 3** (reconstruyen la serie completa con el mes nuevo).
3. Correr **8** (reentrena el pronóstico final hasta el último mes consolidado y pronostica 6 meses).
4. Correr **9 → 10 → 11** (agrupamiento, caída, listas de gestión).
5. Revisar en la salida del 8 el bloque `DETECCIÓN DEL BORDE PROVISIONAL` y en el 11 el bloque de sesgo rural: son los dos controles que dicen si el mes entró bien.
6. La página web lee las carpetas `gestion_caida\` y `modelacion_consumo_segmentada_comparativa\` (§3).

Tiempos aproximados en la máquina actual: 1–3 unos minutos cada uno; 8 es el más largo (entrena 24 modelos: 4 perfiles × 6 horizontes; la celda 32 de diagnóstico es opcional y se puede saltar); 9 depende de los trials de Optuna; 10 y 11 corren en menos de un minuto.

---

## 8. Entorno

Python 3.10+, con `pandas`, `numpy`, `pyarrow`, `scikit-learn`, `lightgbm`, `xgboost`, `catboost`, `optuna`, `joblib`, `matplotlib`, `openpyxl` (para leer los XLSX). Los notebooks se abren desde `C:\Users\Home\Documents\GitHub\ProyectoEBSA` con `utilidades_borde.py` en esa misma carpeta.
