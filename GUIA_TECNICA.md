# Guía técnica del proyecto EBSA — para el ingeniero que lo hereda

Este documento explica **qué hay y cómo funciona**, siguiendo el flujo de datos de izquierda a derecha, y después **cómo se sabe que funciona** (backtest, seguimiento en vivo y simulación). Está pensado para alguien que va a mantener o extender el sistema, no para el usuario de negocio. Los comandos del día a día están en `COMANDOS.md`; la descripción producto por producto, en `README.md`.

---

## 0. La idea en un párrafo

EBSA entrega cada mes un archivo (formato TC2) con la facturación de ~592.000 clientes. El proyecto convierte esa entrega en tres productos: un **pronóstico de consumo a 6 meses por cliente**, una **lista mensual de clientes en caída** priorizada por valor en pesos, y un **riesgo de fuga a otro comercializador**. Todo corre como una cadena lineal de 15 notebooks orquestada por un script, deja registro de cada corrida, versiona sus modelos y se evalúa a sí misma cada mes contra los datos reales que van llegando.

---

## 1. Dónde está cada cosa

**Código: `GitHub\ProyectoEBSA\Pipeline_Ebsa`.**

| Pieza | Qué es |
|---|---|
| `Exploracion_inicial.ipynb` … `Exportes_negocio.ipynb` | Los 15 notebooks de la cadena (numerados 1–15 en `pipeline_mensual.py`). Los notebooks 4, 5, 6 y 7 son desarrollo y quedan como referencia; en operación corren 1, 2, 3, 8, 9, 10, 11, 12, 13, 14, 15. |
| `utilidades_borde.py` | Detector del borde provisional y cortes por zona (`cortes_por_zona`, `leer_cortes_por_zona`). |
| `utilidades_calidad.py` | Compuerta de calidad del mes entrante (`validar_mes_entrante`), listas `CICLOS_CONOCIDOS` y `CICLOS_RURALES`. |
| `utilidades_glosario.py` | Códigos → nombres de negocio (`ZONA_POR_CICLO`, `CLASE_SERVICIO_NOMBRE`, medidor, lectura, factura), grupos de consumo (`GRUPO_CONSUMO_NOMBRE`, `grupo_desde_mediana`), ciclos internos y sin gestión (`CICLOS_INTERNOS`, `CICLOS_SIN_GESTION`), valor facturado (`enriquecer_glosario`, `atributos_ultimo_mes`). |
| `utilidades_versiones.py` | Histórico de versiones de modelos (`guardar_version`, `resolver_modelo`, `registrar_uso`, `listar_versiones`). |
| `pipeline_mensual.py` | Orquestador: ejecuta los notebooks en orden con kernel limpio, pasa configuración por variables de entorno, deja registro. |
| `simular_meses.py`, `comparar_modelos.py` | Simulación mes a mes y lectura de resultados (§6). |
| `verificar_corrida.py`, `estado_modelos.py` | Consistencia de la última corrida; veredicto de reentrenamiento por modelo. |
| `diagnostico_glosario.py`, `diagnostico_cruce_fuga.py`, `diagnostico_fuga.py` | Diagnósticos de solo lectura. |
| `app_ebsa.py` | Página Streamlit. **Solo lee archivos**; nunca calcula nada. |
| `preparar_carpeta_datos.py`, `generar_lock_entorno.py`, `requirements.txt`, `resultado_gestion_plantilla.csv` | Instalación y plantilla de retroalimentación de campo. |

**Datos: `Documents\Datos_Ebsa`.** Una subcarpeta por etapa, numerada en el orden de la cadena. Regla: cada notebook escribe **solo** en su carpeta, y nadie toca `00_formato_TC2` ni `00_otros_comercializadores` (los archivos de la empresa).

| Carpeta | Quién escribe | Contenido principal |
|---|---|---|
| `00_formato_TC2\` | la empresa | XLSX/CSV mensuales. El año-mes sale del nombre (`formato_tc2_202604.xlsx`). |
| `00_otros_comercializadores\` | la empresa | XLSX de usuarios atendidos por otros comercializadores. |
| `01_historico_procesado\` | nb 1 | `historico_YYYY.parquet` (uno por año), `resumen_por_archivo\` (caché por archivo), `detalle_mensual\`. |
| `02_serie_reconstruida\` | nb 2 | `serie_mensual_consumo_reconstruida.parquet`, `perfil_periodicidad_clientes.parquet`, `control_calidad_mes_entrante.csv`, `copia_historicos\`. |
| `03_serie_modelado\` | nb 3 | `serie_mensual_modelado_preprocesada.parquet` (**entrada de todos los modelos**), `cortes_por_zona.csv`, `nius_alumbrado_publico_excluidos.parquet`, `nius_autogeneradores_excluidos.parquet`, auditorías. |
| `04_pronostico\modelo_final\` | nb 8 | `modelos_ganadores_optimizados_final.joblib`, `predicciones_segmentadas_optimizadas_6_meses.parquet`, métricas del backtest, `historial_pronosticos\` (una copia por corte + `comparacion\`). |
| `05_segmentos_clientes\` | nb 9 | `modelo_agrupamiento.joblib`, `clientes_clusters_consumo.parquet`, `catalogo_segmentos_negocio.csv`. |
| `06_estudio_caida\` | nb 10 | `criterios_caida_por_segmento.joblib`, `estudio_caida_consumo.parquet`, `deriva_criterios_caida.csv`, `resumen_caida_por_segmento.csv`. |
| `07_gestion_caida\` | nb 11 | `gestion_caida_operativa.csv`, `gestion_caida_gerencial.csv`, resúmenes por ciclo/corte, `historial\`, `retroalimentacion\`. |
| `08_seguimiento\` | nb 12 | `seguimiento_pronostico_global.csv`, `_por_perfil.csv`, `_por_zona.csv`, `seguimiento_lista_gestion.csv`, `diagnostico_sesgo_pronostico.csv`. |
| `09_registro_corridas\` | pipeline | Una carpeta por corrida (`<fecha-hora>_<modo>[_corteAAAA-MM]`) con los notebooks ejecutados y `resumen_corrida.txt`; `simulacion\` para la simulación. |
| `10_riesgo_fuga\` | nb 14 | `modelo_riesgo_fuga.joblib`, `riesgo_fuga_clientes.csv`, `etiquetas_salida_por_niu.csv`, `metricas_modelo_fuga.csv`, `hiperparametros_fuga.json`, `optuna_ensayos_fuga.csv`, `clientes_con_otro_comercializador.csv`, `vigilancia_mercado_no_regulado.csv`, `seguimiento_riesgo_fuga.csv`, `historial\`. |
| `11_exportes_negocio\` | nb 15 | Archivos por grupo de consumo + `indice_exportes.csv`. |
| `12_versiones_modelos\` | nbs 8, 9, 10, 14 | `<modelo>_corte_AAAA-MM.joblib`, `registro_versiones.csv`, `registro_uso.csv`. |

---

## 2. Cómo se ejecuta y cómo se configura

`pipeline_mensual.py` recorre los notebooks con `nbclient`, uno por uno, con kernel limpio, e imprime celda a celda con el tiempo acumulado. La configuración viaja por variables de entorno que cada notebook lee en su primera celda:

| Variable | Origen | Efecto |
|---|---|---|
| `EBSA_DATOS` | `--datos` | Carpeta de datos (por defecto `C:\Users\Home\Documents\Datos_Ebsa`). |
| `EBSA_MODO` | `--modo aplicar\|reentrenar` | En *aplicar* los notebooks 8, 9, 10 y 14 cargan el `.joblib` guardado; en *reentrenar* entrenan y lo sobreescriben (guardando versión). |
| `EBSA_CORTE_MAX` | `--corte-max AAAA-MM` | Trunca las entradas a ese mes (nb 3: la serie; nb 14: el histórico y el archivo de otros comercializadores). Es lo que permite simular el pasado sin fugas de información. |
| `EBSA_VERSION_MODELO` | `--version-modelo AAAA-MM` | Obliga a usar esa versión de cada modelo (error claro si no existe). El uso se registra en modo "comparación", que no pisa el registro normal. |

Opciones de rango: `--desde N`, `--hasta N`, `--solo a,b,c`. Cada notebook ejecutado, con todas sus salidas, queda en `09_registro_corridas\<corrida>\NN_<nombre>.ipynb`; si una celda falla, ahí está el error con todo lo anterior. `resumen_corrida.txt` dice qué pasos corrieron y cuánto tardaron. Las carpetas de registro sin `resumen_corrida.txt` (p. ej. `simulacion\`) se ignoran en `verificar_corrida.py`.

Tiempos medidos sobre la carpeta real (sept-2026): paso 1 ≈ 5 min por archivo nuevo (0,3 min si no hay nuevos), paso 2 ≈ 1,6 min, pasos 3–15 en aplicar ≈ 8–9 min, reentrenamiento completo ≈ 50–70 min.

---

## 3. La cadena, etapa por etapa

### 3.1 Ingesta — notebook 1 (`Exploracion_inicial.ipynb`) → `01_historico_procesado`

Lista los archivos de `00_formato_TC2`, detecta hoja/separador/encoding, resuelve las columnas por nombre contra un esquema canónico (`NIU`, `periodo`, `consumo_kwh_raw`, `dias_facturados_max`, `fecha_lectura_anterior`, `fecha_lectura_actual`, `tarifa_aplicada_kwh`, `ciclo`, `clase_servicio`, `estrato`, `consumo_promedio_semestral_kwh`, `tipo_factura`, `tipo_lectura`, `tipo_medidor`, `valor_facturado_consumo`), y toma el año-mes **del nombre del archivo** como fuente oficial (los campos "Año/Mes de reporte" del contenido se guardan solo para auditoría). Consolida a una fila NIU-mes por archivo.

Caché: el resumen de cada archivo queda en `resumen_por_archivo\<stem>_<ext>.parquet`; si existe y es más nuevo que el archivo, no se relee. "Anualizar": cada mes leído en la corrida se incorpora al `historico_YYYY.parquet` de su año conservando los demás meses; un mes que ya existía se reemplaza con aviso. Todas las columnas de texto se fuerzan a `string` (los archivos traen mezclas, p. ej. clase de servicio `0` numérico).

Trampa conocida: la lista de archivos se toma **al inicio** de la corrida; un archivo copiado después no entra hasta la siguiente.

### 3.2 Reconstrucción — notebook 2 (`Reconstruccion_serie_tiempo_consumo_rural.ipynb`) → `02_serie_reconstruida`

Carga solo las 9 columnas necesarias de los `historico_YYYY.parquet` (memoria), y **antes de todo** corre la compuerta de calidad (`utilidades_calidad.validar_mes_entrante`): compara el último mes contra los 12 previos, por zona, en clientes, consumo, tarifa, ciclos y clases nuevos, columnas y duplicados; los chequeos ERROR detienen la corrida (`estricto=True`). Reporte en `control_calidad_mes_entrante.csv`.

Clasifica cada NIU como **trimestral** con dos señales: lecturas de 75–129 días (`pct_lecturas_largas ≥ 0.60`) y apariciones cada ~3 meses (`pct_saltos_3_meses ≥ 0.50` o ≥ 3 lecturas largas), con mínimo 3 lecturas. Para los trimestrales reparte cada lectura por mes (`desagregar_lecturas`, vectorizada con numpy): método 1, fechas reales (1–160 días entre lecturas), proporcional a los días de cada mes en `[fecha_anterior, fecha_actual)`; método 2, respaldo sin fechas, partes iguales sobre `round(dias_facturados/30.44)` meses (1–5; 3 si no hay días) terminando en el mes de reporte. Consolida a NIU-mes (`consumo_kwh_mensual`, `dias_asignados`, `lecturas_que_aportan`, `metodos_usados`, `origen_consumo`, `consumo_imputado`) y une con los clientes mensuales (observados tal cual). El tipo de fecha se conserva igual al del histórico (pandas 2 → ns, pandas 3 → µs).

Consecuencia que gobierna todo lo demás: para un rural, los meses posteriores a su última lectura **no tienen fila**. Por eso el último mes de cualquier extracción está incompleto para rurales, y por eso existe el corte por zona.

### 3.3 Universo de modelado y cortes por zona — notebook 3 (`Preprocesamiento_serie_tiempo_para_modelado.ipynb`) → `03_serie_modelado`

En orden: excluye alumbrado público (NIU que alguna vez fue ciclo 15 + clase AP; lista en `nius_alumbrado_publico_excluidos.parquet`); agrega `ciclo` (moda histórica por NIU) y `es_rural` (`ciclo ∈ CICLOS_RURALES = [10, 11, 12, 13, 19, 21, 22, 23, 38]`); excluye **autogeneradores** (`ciclo ∈ CICLOS_SIN_GESTION = {50}`, decisión de la empresa; lista en `nius_autogeneradores_excluidos.parquet`); limpieza técnica y auditorías; con `EBSA_CORTE_MAX`, trunca la serie.

**Cortes por zona** (`utilidades_borde.cortes_por_zona`, celda 18b). Para cada zona y cada uno de los últimos meses, dos medidas: *nivel* (consumo promedio de los clientes con fila; detecta lecturas parciales) y *cobertura* (cuántos clientes tienen fila; detecta clientes enteros que faltan). Cada una se compara contra la mediana de los 12 meses previos **y** contra el mismo mes del año anterior (descarta estacionalidad). Nivel < 85 % o cobertura < 60 % en ambas comparaciones → mes provisional. Se retrocede desde el final hasta el primer mes sano; tope 3 meses urbano, 4 rural (más → `ValueError`, la extracción llegó mal). Resultado: `cortes_por_zona.csv` (`zona`, `fecha_corte`, `ultimo_mes_serie`, `meses_provisionales`, `filas_provisionales`) y la columna `estado_mes` (CONSOLIDADO/PROVISIONAL) en cada fila de la serie. **Todos los notebooks siguientes leen ese CSV con `leer_cortes_por_zona`; nadie recalcula el corte.** Es la única fuente de verdad de "hasta qué mes es real" para cada cliente. Con `--corte-max` los cortes se recalculan sobre la serie truncada, así que en la simulación cada corte ve exactamente lo que habría visto ese mes.

Caso real que motivó la prueba de cobertura: febrero 2026 llegó sin rurales pero 89 rurales tenían fila con promedio normal; con solo la prueba de nivel, febrero rural pasaba por consolidado y 219.000 rurales quedaban sin pronóstico.

### 3.4 Pronóstico — notebook 8 (`Backtest_y_reentrenamiento_final_optimizado.ipynb`) → `04_pronostico\modelo_final`

Los notebooks 4–7 (modelo único, segmentado, comparación de algoritmos, Optuna) son el desarrollo; el 8 es el que opera.

Construye una matriz NIU × mes de `consumo_kwh_mensual` (copias escribibles) y **enmascara por zona** las posiciones posteriores al corte de cada zona. Asigna un **perfil** por mediana de 12 meses: `P0_INTERMITENTE` (mediana ≤ 10 kWh o ≥ 50 % de ceros), `P1_REGULAR` (< 500), `P2_ALTO` (500–5.000), `P3_GRANDE` (≥ 5.000), `P4_INSUFICIENTE` (< 6 meses válidos; no se pronostica). Por perfil y horizonte (1–6 meses) elige entre algoritmos: LightGBM con rezagos y estacionalidad para P2/P3, línea base estacional para P1, persistencia para P0; la selección queda en `seleccion_modelo_por_perfil_horizonte_optimizada.csv` y los hiperparámetros vienen del notebook 7.

Modo *reentrenar*: backtest (§5.1) → entrenamiento con toda la historia consolidada → pronóstico → `guardar_version`. Modo *aplicar*: `resolver_modelo` (vigente o `EBSA_VERSION_MODELO`), verificación del contrato de features/umbrales, aviso si el modelo pasa de 6 meses, pronóstico, `registrar_uso`.

Reglas encima del modelo, aplicadas en la predicción final y en el backtest: **cero sostenido** (`PERFILES_REGLA_CERO = {P1, P2, P3}`, mediana 12m ≥ 100 kWh, últimos `MESES_CERO_REGLA = 2` meses consolidados ≤ 5 % de la mediana → los 6 meses = persistencia del último valor y `modelo_Nm = "REGLA_CERO_SOSTENIDO"`), y piso en cero. Cada fila de `predicciones_segmentadas_optimizadas_6_meses.parquet` trae `NIU`, `zona`, `perfil`, `fecha_corte` (de su zona), `fecha_pred_1m..6m`, `pred_1m..6m_kwh`, `modelo_1m..6m`, `fecha_corte_modelo`, `modo`. Una copia por corte va a `historial_pronosticos\predicciones_6_meses_corte_AAAA-MM.parquet` (nombrada por el corte urbano): es lo que evalúa el seguimiento.

### 3.5 Segmentos, caída y listas — notebooks 9, 10, 11

**Notebook 9 (`Agrupamiento_clientes_consumo.ipynb`) → `05_segmentos_clientes`.** Ventana de 12 posiciones por zona (termina en el corte de cada zona), MiniBatchKMeans por subpoblación urbana/rural sobre la forma normalizada de la curva; los clusters se traducen a nombres de negocio (`BASE_ESTABLE`, `BASE_EN_DESCENSO`, `INTERMITENTE_CRITICO`, `EN_REACTIVACION`, …) con `catalogo_segmentos_negocio.csv`. En aplicar asigna con el modelo guardado y avisa si el perfil de un cluster ya no corresponde a su nombre. Versionado.

**Notebook 10 (`Estudio_caida_consumo.ipynb`) → `06_estudio_caida`.** Matriz de 24 posiciones por zona; compara el consumo reciente contra el anterior con ventanas distintas para mensuales (`MESES_VENTANA_MENSUAL = 3`) y trimestrales; calibra un umbral de caída por segmento (piso `UMBRAL_MINIMO_CAIDA_PCT = -10`) y da un veredicto por cliente: `SIN_CAIDA`, `CAIDA_RECIENTE`, `CAIDA_SOSTENIDA`, `CAIDA_CONFIRMADA`, `NO_APLICA`, `SIN_BASE_COMPARABLE`. En aplicar usa los criterios guardados y mide su **deriva** (`deriva_criterios_caida.csv`: cuánto se movería cada umbral si se recalculara hoy). Versionado.

**Notebook 11 (`Priorizacion_gestion_caida.ipynb`) → `07_gestion_caida`.** Convierte el estudio en la lista operativa: valor en riesgo = kWh perdidos × **tarifa real del cliente** (`tiene_tarifa`; nunca imputada), prioridad, reparto por ciclo con cupo, trayectoria (con corrección de sesgo rural: `EXCLUIR_RURAL_DE_TRAYECTORIA` automático por brecha), columnas del glosario y grupo de consumo (`enriquecer_glosario`, `agregar_atributos_a_lista`), `estado_en_lista` (NUEVO/REPITE/SALE) contra el corte anterior, resúmenes, copia por corte en `historial\`. Cada fila conserva la `fecha_corte` de su zona; el archivo se nombra por el corte urbano.

### 3.6 Seguimiento y retroalimentación — notebooks 12 y 13 → `08_seguimiento`

El 12 es el corazón de la evaluación en vivo (§5.2). El 13 (`Evaluacion_retroalimentacion_gestion.ipynb`) lee `retroalimentacion\` (plantilla `resultado_gestion_plantilla.csv` llenada por campo) y resume qué pasó con los clientes visitados; si no hay archivos, termina sin hacer nada.

### 3.7 Riesgo de fuga — notebook 14 (`Riesgo_fuga_comercializador.ipynb`) → `10_riesgo_fuga`

Lee todos los XLSX de `00_otros_comercializadores` (quita duplicados NIU-mes). **Etiqueta** por NIU (`etiquetas_salida_por_niu.csv`): `mes_salida` = mínimo entre su primer mes en ese archivo, el inicio de un cero sostenido ≥ 3 meses y el mes siguiente a su última fila en TC2; el ciclo 97 cuenta automáticamente; `regreso_a_ebsa` si vuelve a facturar. **Población**: clases de servicio observadas entre los que se fueron (+ IR), menos `CLASES_EXCLUIDAS_SIEMPRE = {AP, PR}`, ciclos internos (`{15, 90, 91, 94, 96, 98, 99}`), ciclo 97 y ciclos sin gestión ({50}); si no hay archivo, `CLASES_POR_DEFECTO`.

**Variables en cada corte histórico**, calculadas con matrices mensuales de atributos consistentes en el tiempo (tarifa, promedio semestral, tipo de lectura, tipo de medidor; forward-fill; `tarifa_rel` respecto a la clase): consumo reciente, tendencia, ceros, meses activos, etc. El objetivo es "sale en los próximos `HORIZONTE_MESES = 6`". *Esto es deliberado: la primera versión tomaba la última fila del cliente y daba AUC 0,99, que era fuga de información del futuro; con matrices en el tiempo bajó a 0,95 real.* Modelo LightGBM con `scale_pos_weight`, **validación temporal** (últimos 6 cortes completos como prueba, entrenamiento no solapado), Optuna 30 ensayos (semilla 42, objetivo average precision, ensayo 0 = parámetros base) → `hiperparametros_fuga.json`, `optuna_ensayos_fuga.csv`; probabilidades des-ponderadas `p/(p+(1-p)k)`; con < 20 ejemplos usa un puntaje de similitud en vez de LightGBM. Niveles: ALTO = prob ≥ `MULT_ALTO = 5` × tasa base o top 1 %; MEDIO = ≥ 2× o top 5 %. Cada cliente se puntúa en el corte de su zona. Salidas: `riesgo_fuga_clientes.csv` (+ recurrencia contra cortes anteriores, `historial\`), listas por zona y gerencial, `clientes_con_otro_comercializador.csv`, `vigilancia_mercado_no_regulado.csv` (≥ 55.000 kWh, ciclo 33, clase IR), `perfil_clientes_que_se_fueron.csv`, `importancia_variables_fuga.csv`, `seguimiento_riesgo_fuga.csv`. Versionado.

### 3.8 Exportes y página — notebook 15 y `app_ebsa.py`

El 15 parte pronóstico, caída y fuga por grupo de consumo (Grande / Mediano / Pequeño / Intermitente / Sin historia suficiente) con nombres de negocio y una columna `nota` para los meses rurales provisionales; `indice_exportes.csv`. La app (Streamlit) muestra cortes en la barra lateral, ranking gerencial, lista operativa, riesgo de fuga, descargas por grupo, seguimiento y un buscador de cliente (línea continua = real, punteada = pronóstico desde el último real, rombos grises = meses rurales provisionales, aviso cuando aplica la regla de cero sostenido, versión del modelo). Si algo no se ve en la página, falta la corrida, no la app.

---

## 4. Transversales

**Glosario (`utilidades_glosario.py`).** Un solo lugar para código → nombre. Si un código no está, el texto es `CICLO 8 (sin nombre en glosario)`; nunca se inventa. Estado actual: ciclos 9 y 19 = CENTRO SECCIONALES urbano/rural, 50 = AUTOGENERADORES, 97 = OTROS COMERCIALIZADORES, 33 = NO REGULADOS; clase `0` = SIN CLASIFICAR. `diagnostico_glosario.py` lista lo que falte.

**Versiones (`utilidades_versiones.py`).** Modelos versionados: `pronostico` (nb 8), `agrupamiento` (9), `criterios_caida` (10), `riesgo_fuga` (14). `guardar_version` copia el `.joblib` a `12_versiones_modelos\<modelo>_corte_AAAA-MM.joblib` y escribe `registro_versiones.csv`; `registrar_uso` escribe `registro_uso.csv` (corte, modelo, modo, versión usada, corte del modelo). Con `EBSA_VERSION_MODELO`, `resolver_modelo` devuelve esa versión y el uso se registra como `comparacion (version X)`.

**Cortes por zona en cada notebook.** Pronóstico: enmascara por zona y pronostica desde el corte de cada zona (un rural con corte marzo recibe abril–septiembre; abril y mayo se muestran como "pronosticado, a la espera de la lectura trimestral"). Agrupamiento, caída, listas y fuga: ventanas que terminan en el corte de la zona; toda fila lleva `fecha_corte`. Seguimiento: evalúa un mes solo cuando es consolidado para la zona del cliente. Archivos del mes nombrados por el corte urbano.

**Windows.** Todos los scripts fuerzan UTF-8 en su salida (`sys.stdout.reconfigure`) y `simular_meses.py` lanza a los hijos con `PYTHONIOENCODING=utf-8`; sin eso, "✓" rompe cuando la salida va a un archivo. Los CSV grandes se leen con `low_memory=False` y sin `usecols` (bug de pandas 3 con columnas mixtas).

---

## 5. Cómo se sabe que funciona — los tres niveles de evaluación

Todos los niveles cumplen la misma regla: **nunca se usa información posterior al corte que se evalúa, y solo se mide contra meses consolidados de la zona del cliente.**

### 5.1 Backtest (dentro del notebook que entrena)

*Pronóstico (nb 8, modo reentrenar).* Corte de backtest `CORTE_BACKTEST_FINAL` = 2025-07 por defecto, o `min(2025-07, corte_max − 6 meses)` con `--corte-max`. Entrena solo con lo anterior al corte, pronostica los 6 meses siguientes (que ya ocurrieron) y mide WAPE por perfil y horizonte, excluyendo de la métrica los meses provisionales de cada zona (`PERIODOS_PROVISIONALES`) y aplicando las mismas reglas de negocio que en producción. Salidas: `metricas_sistema_ganador_backtest_optimizado.csv`, `metricas_sistema_por_perfil_horizonte_optimizado.csv`, `comparacion_backtest_original_vs_optimizado.csv` (columna `comparable = False` cuando el mes objetivo era provisional). Estas cifras son la "promesa" del modelo; el seguimiento en vivo las usa como referencia.

*Fuga (nb 14, modo reentrenar).* Validación temporal: los últimos 6 cortes completos son la prueba, entrenando cada vez solo con los cortes anteriores no solapados. `metricas_modelo_fuga.csv` trae AUC, average precision, y la captura: % de los que se fueron que cae en el top 1 % (ALTO) y top 5 % (ALTO+MEDIO). Resultado actual: AUC 0,95; el 1 % captura 54–58 % de las salidas; el 5 %, 85–93 %. El 77 % de la importancia está en el consumo promedio de 6 meses.

El backtest responde "¿el modelo aprendió algo?", pero es una foto de un solo corte.

### 5.2 Seguimiento en vivo (notebook 12, cada mes en producción)

Cada pronóstico generado queda **congelado** en `historial_pronosticos\predicciones_6_meses_corte_AAAA-MM.parquet`, con `fecha_corte_modelo`. El 12 los recorre todos y, para cada uno, evalúa cada horizonte cuyo mes objetivo ya sea consolidado para la zona del cliente (`estado_mes` de la serie actual). Salidas:

- `seguimiento_pronostico_global.csv`: una fila por `fecha_corte` × `horizonte` con `WAPE_pct`, `real_total_kwh`, `fecha_corte_modelo`, `meses_desde_entrenamiento`.
- `seguimiento_pronostico_por_perfil.csv`: lo mismo por perfil, con `WAPE_backtest_pct` y `dif_vs_backtest_pp` (cuánto más error hay en vivo que el prometido por el backtest). **Ese diferencial es la señal de deterioro.**
- `seguimiento_pronostico_por_zona.csv`, `diagnostico_sesgo_pronostico.csv` (¿sobre o subestima, y dónde?).
- `seguimiento_lista_gestion.csv`: de los clientes que salieron en listas anteriores, cuántos siguieron cayendo, se recuperaron o desaparecieron.
- `10_riesgo_fuga\seguimiento_riesgo_fuga.csv` (nb 14): de los ALTO/MEDIO de cortes anteriores, cuántos aparecieron después en el archivo de otros comercializadores.

`estado_modelos.py` es el lector de todo esto. Por modelo calcula: edad (`MESES_MAX = 6` como tope de respaldo), y para el pronóstico la tabla por corte con `pct_malos` (celdas perfil × horizonte con `dif_vs_backtest_pp > 5`); marca REENTRENAR si dos o más cortes superan el 50 % de celdas malas o si pasa el tope de edad; REVISAR con un solo corte malo. Para agrupamiento mira estabilidad de segmentos; para caída, la deriva de umbrales (> 10 puntos); para fuga, si hay ≥ 15 % más ejemplos de salida que los que vio el modelo. Imprime el veredicto y el comando exacto.

### 5.3 Simulación (`simular_meses.py` + `comparar_modelos.py`)

El seguimiento en vivo necesita meses reales para acumular evidencia y eso tarda un año. La simulación acelera el calendario **sobre una copia de la carpeta de datos** (sobrescribe salidas y modelos):

```
robocopy Datos_Ebsa Datos_Ebsa_simulacion /E /XD 09_registro_corridas
python simular_meses.py --desde 2025-06 --hasta 2026-04 --reentrenar-en 2025-06,2026-02 --comparar-version 2025-06 --datos "...\Datos_Ebsa_simulacion"
python comparar_modelos.py --datos "...\Datos_Ebsa_simulacion"
```

Qué hace por cada corte del rango: `pipeline_mensual.py --corte-max <corte> --solo 3,8,…,15` en modo reentrenar (si el corte está en `--reentrenar-en`) o aplicar. Con `--corte-max`, el nb 3 trunca la serie y recalcula los cortes por zona sobre la serie truncada, el nb 8 usa backtest dinámico, el nb 14 trunca el histórico y el archivo de otros comercializadores: **en cada corte el sistema ve exactamente lo que habría visto ese mes.** Cada corte deja su pronóstico en `historial_pronosticos`, y el nb 12 lo evalúa contra los meses que "ya pasaron" dentro de la simulación; al final, el seguimiento tiene una fila por corte y por versión de modelo, que es lo que el seguimiento en vivo tendría dentro de un año. Por corte guarda además `<corte>_<modo>.log`, `<corte>_verificar.txt` y `<corte>_estado.txt` (qué habría dicho el operador ese mes), y una fila en `resumen_simulacion.csv` (minutos, clientes en lista, valor en riesgo, ALTO/MEDIO de fuga, versión del pronóstico, total pronosticado, veredicto, último WAPE evaluado). `--cada N` salta cortes; `--solo-fuga` reentrena solo el 14 en los cortes de reentrenamiento. Si se interrumpe, se retoma con `--desde <corte que falló>` y `--reentrenar-en` solo con los que falten.

`--comparar-version AAAA-MM` añade la pieza que ningún seguimiento da por sí solo: al terminar, vuelve a pronosticar los cortes posteriores al último reentrenamiento con la versión vieja (`--version-modelo`, pasos 3 y 8) y guarda esos pronósticos en `historial_pronosticos\comparacion\predicciones_6_meses_corte_<corte>_modelo<version>.parquet`, restaurando después el pronóstico del modelo nuevo. Así viejo y nuevo quedan medidos sobre **los mismos cortes y los mismos meses objetivo**.

`comparar_modelos.py` lee `seguimiento_pronostico_global.csv` y la carpeta `comparacion\` y arma tres vistas (en `09_registro_corridas\simulacion\`):

1. `comparacion_modelos.csv`: WAPE en vivo por corte y horizonte, con la versión del modelo que pronosticó y `meses_desde_entrenamiento` (línea de tiempo).
2. Envejecimiento: WAPE según meses desde el entrenamiento, ponderado por consumo real, todas las versiones juntas (cada cuánto conviene reentrenar).
3. `comparacion_cabeza_a_cabeza.csv`: WAPE de la versión vieja y la nueva por corte y horizonte, con `mejora_pp`.

Más `comparacion_modelos.png` con las dos primeras.

### 5.4 Lo que dijo la evaluación hasta hoy (sept-2026)

Simulación de 11 cortes (jun-2025 → abr-2026, reentrenando en jun-2025 y feb-2026, 580 mil clientes): el modelo de jun-2025 aplicado siete meses sin reentrenar mantuvo el WAPE a un mes entre 14,5 % y 18,7 %, con dos picos (22,6 % pronosticando octubre y 21,9 % pronosticando enero) que son propios del mes objetivo, no de la edad; a 3 y 6 meses, 22–26 % y 26–31 %, también planos. El cabeza a cabeza (feb–abr 2026) dio 0,1 puntos a favor del viejo. `estado_modelos.py` pidió reentrenar en enero solo por edad (7 > 6 meses). Conclusión de ingeniería: el reentrenamiento del pronóstico debe dispararse por `pct_malos` del seguimiento, con la edad como respaldo (y ese tope puede subir a 12 con esta evidencia); el error crece con el horizonte, no con la edad del modelo, y a 6 meses es un orden de magnitud, no una cifra.

---

## 6. Cómo depurar

1. El pipeline dice qué paso y qué celda fallaron, y con qué comando reanudar (`--desde N`). Abrir el notebook ejecutado en `09_registro_corridas\<corrida>\NN_<nombre>.ipynb`: tiene las salidas de todas las celdas anteriores.
2. Si los números se ven raros sin error, leer en este orden: bloque `CONTROL DE CALIDAD DEL MES ENTRANTE` (paso 2), bloque `DETECCIÓN DEL BORDE PROVISIONAL — POR ZONA` (paso 3; dice nivel, clientes, cobertura y por cuál prueba cayó cada mes), y `python verificar_corrida.py` (unos 50 chequeos entre carpetas, incluida la cobertura del pronóstico por zona y que no haya autogeneradores en la lista de caída ni no regulados en el ranking de fuga). Casi todos los problemas vistos estaban ahí: archivo que llegó distinto, corte mal detectado o carpeta incompleta.
3. Los dos fallos "buenos" (protegen las salidas): la compuerta del paso 2 y el tope del detector del paso 3. No se fuerzan; se mira el archivo.
4. `estado_modelos.py` para la pregunta "¿reentreno?"; `diagnostico_glosario.py` cuando aparezcan "sin nombre en glosario"; `diagnostico_cruce_fuga.py` cuando la empresa entregue un archivo nuevo de otros comercializadores.

## 7. Lo que no se debe tocar sin entender por qué está

- Los cortes por zona y `estado_mes`: todo lo demás depende de ellos.
- El orden de exclusiones del notebook 3 (AP y ciclo 50 salen antes de que exista la serie de modelado) y la regla de que los notebooks no recalculan el corte.
- Las matrices de atributos en el tiempo del notebook 14: quitarlas "simplifica" y reintroduce la fuga de información (AUC 0,99 falso).
- La tarifa siempre es la real del cliente; no se imputa. Los valores en pesos que no se pueden calcular quedan vacíos, no estimados.
- Los archivos de la empresa (`00_*`) no se editan; si un archivo llega mal, se pide de nuevo.
- La caché por archivo del paso 1: borrar `resumen_por_archivo` obliga a releer todo (horas).

## 8. Pendientes conocidos

Prueba de rutina con mayo y junio como meses nuevos en la carpeta real; decidir el tope de edad (6 → 12) en `estado_modelos.py`; TC2 de 2019–2021, si la empresa los entrega, para dar más ejemplos al modelo de fuga (hoy 68 salidas conocidas); mensaje específico en la página para NIU de ciclo 50 (hoy "no encontrado").

## Anexo — Ubicación y mapa (formato TC1, fuera del pipeline)

`cruzar_ubicacion_tc1.py` es un paso independiente: lee `00_formato_TC1\TC1_MMAAAA.csv` (una fila por NIU; código DANE en la columna N = 5 dígitos del municipio + 3 del centro poblado; dirección; ubicación SUI; nivel de tensión; circuito; transformador; latitud/longitud/altitud; marca de autogenerador) y `Código DANE.xls`, y deja `13_ubicacion_clientes\` con `ubicacion_clientes.parquet` (NIU → municipio, provincia, departamento, zona del mapa, coordenadas validadas) y `municipios_zona.csv` (municipio → zona EBSA deducida de los ciclos de sus clientes, centro geográfico). La página lo usa para poner municipio a las listas y para la sección Mapa (plotly, círculos por municipio; sin polígonos oficiales). No depende del corte mensual: se repite solo cuando llegue un TC1 nuevo. Hallazgos del primer cruce (agosto 2026): 594.687 NIU, 132 municipios (123 de Boyacá y 9 vecinos), 99,3 % con coordenadas válidas, cada municipio cae 100 % en una sola zona EBSA, 318 autogeneradores marcados en el TC1 frente a 267 en ciclo 50.

Dos reglas de negocio fijadas el 2026-10-02: los autogeneradores se excluyen por su **ciclo actual** (nb3 celda 9c; `niu_ciclo.parquet` guarda `ciclo` más frecuente y `ciclo_actual`; nb11 etiqueta la lista con el actual) y el mercado no regulado se puntúa en fuga pero vive solo en `vigilancia_mercado_no_regulado.csv` (nb14 celdas 9 y 11); `verificar_corrida.py` vigila ambas.
