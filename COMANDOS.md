# Comandos del proyecto EBSA — qué hace cada uno y cuándo usarlo

Todos se corren en una terminal abierta en la carpeta del código:

```
cd C:\Users\Home\Documents\GitHub\ProyectoEBSA\Pipeline_Ebsa
```

Los datos siempre se leen y escriben en `C:\Users\Home\Documents\Datos_Ebsa` (o en la carpeta que diga la variable de entorno `EBSA_DATOS`). Ningún comando modifica los archivos de la empresa (`00_formato_TC2`, `00_otros_comercializadores`).

---

## 1. Cada mes, cuando llega el archivo TC2 (rutina normal)

| Paso | Comando | Qué hace |
|---|---|---|
| Copiar el archivo | (a mano) `formato_tc2_AAAAMM.xlsx` → `Datos_Ebsa\00_formato_TC2\`. Si hay versión nueva del archivo de otros comercializadores → `Datos_Ebsa\00_otros_comercializadores\`. | El año y el mes salen del nombre del archivo. No borrar los meses anteriores de la carpeta: los ya procesados no se vuelven a leer. |
| Correr la cadena | `python pipeline_mensual.py --modo aplicar` | Ejecuta 1 → 2 → 3 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 con los modelos guardados (no entrena). Agrega el mes al histórico, reconstruye la serie, calcula los cortes por zona, pronostica, agrupa, mide caída, arma las listas, hace el seguimiento, puntúa el riesgo de fuga y deja los exportes por grupo. Tarda unos 20–25 minutos (leer un archivo TC2 nuevo ~5 min, reconstruir la serie ~5–10 min, el resto ~8 min). |
| Verificar | `python verificar_corrida.py` | Un minuto. Revisa que todo quedó consistente y lo resume en ✓ / ⚠ / ✗. Si hay ✗, no usar las listas de esa corrida. |
| Ver resultados | `streamlit run app_ebsa.py` | Abre la página en el navegador (http://localhost:8501). Se cierra con Ctrl+C en la terminal. |

Si un paso falla, el pipeline se detiene, dice por qué y con qué comando reanudar (`--desde N`). Los dos fallos "buenos" son la compuerta de calidad del paso 2 (el archivo llegó con menos clientes urbanos, tarifas en cero, un ciclo desconocido) y el detector del borde del paso 3 (quiere retroceder demasiados meses): en ambos casos hay que mirar el archivo, no forzar la corrida.

---

## 2. Reentrenar (cada trimestre o semestre, o cuando el seguimiento lo pida)

| Comando | Qué hace | Cuándo |
|---|---|---|
| `python pipeline_mensual.py --modo reentrenar` | Lo mismo que la corrida mensual, pero además reentrena el pronóstico (backtest + entrenamiento, ~1 hora extra), vuelve a comparar algoritmos de agrupamiento, recalcula los criterios de caída y reentrena el riesgo de fuga con Optuna. Sobreescribe los `.joblib`. | Cada 3–6 meses; o cuando el paso 8 avise que el modelo lleva más de 6 meses; o cuando en `08_seguimiento\seguimiento_pronostico_por_perfil.csv` la columna `dif_vs_backtest_pp` sea claramente positiva varios meses seguidos; o cuando el 9 o el 10 avisen que los segmentos o los umbrales ya no corresponden. |
| `python pipeline_mensual.py --modo reentrenar --solo 14,15` | Reentrena solo el riesgo de fuga (minutos) y rehace los exportes. | Cada vez que la empresa entregue una versión nueva del archivo de otros comercializadores con más casos, o cuando `10_riesgo_fuga\seguimiento_riesgo_fuga.csv` muestre que los señalados ALTO no se van más que la tasa base. |

---

## 2b. Versiones de los modelos

Cada reentrenamiento deja una copia del modelo con el corte en el nombre en `Datos_Ebsa\12_versiones_modelos\` (`pronostico_corte_2026-02.joblib`, `agrupamiento_...`, `criterios_caida_...`, `riesgo_fuga_...`), una fila en `registro_versiones.csv` y, en cada corrida, una fila en `registro_uso.csv` con qué versión usó cada corte. Para correr con una versión concreta en vez de la vigente:

```
python pipeline_mensual.py --modo aplicar --version-modelo 2025-06
```

Si esa versión no existe para alguno de los cuatro modelos, el paso se detiene y lista las disponibles. Sirve para volver atrás si un reentrenamiento salió peor y para las comparaciones de la sección 8.

---

## 3. Opciones del pipeline (se combinan con `--modo`)

| Opción | Ejemplo | Para qué |
|---|---|---|
| `--lista` | `python pipeline_mensual.py --lista` | Ver los pasos y confirmar que todos los notebooks están en la carpeta. No corre nada. |
| `--desde N` | `python pipeline_mensual.py --modo aplicar --desde 3` | Reanudar desde el paso N. Se usa después de corregir un fallo, o cuando solo cambió el código a partir de ese paso (por ejemplo, tras actualizar notebooks sin tocar el histórico). |
| `--hasta N` | `python pipeline_mensual.py --modo aplicar --hasta 3` | Detenerse después del paso N. Útil para dejar listo el histórico y la serie sin correr los modelos. |
| `--solo a,b,c` | `python pipeline_mensual.py --modo aplicar --solo 11,12,13` | Correr solo esos pasos. Por ejemplo, rehacer las listas y el seguimiento sin repetir el pronóstico. |
| `--datos ruta` | `python pipeline_mensual.py --modo aplicar --datos "D:\otra\Datos_Ebsa"` | Usar otra carpeta de datos (pruebas, otra máquina). Si no se indica, usa `Documentos\Datos_Ebsa`. |
| `--corte-max AAAA-MM` | `python pipeline_mensual.py --modo aplicar --corte-max 2025-09 --solo 3,8,9,10,11,12,13,14,15` | Simulación: la serie se recorta a ese mes en el paso 3 y todo lo demás cree que el archivo termina ahí (también el archivo de otros comercializadores). Para reproducir "qué habría dicho el sistema en ese mes". |
| `--version-modelo AAAA-MM` | `python pipeline_mensual.py --modo aplicar --version-modelo 2025-06` | Aplicar con una versión guardada de los modelos (sección 2b). |

Pasos disponibles: 1 Exploración (histórico), 2 Reconstrucción rural, 3 Preprocesamiento (cortes por zona), 8 Pronóstico, 9 Agrupamiento, 10 Caída, 11 Listas de gestión, 12 Seguimiento, 13 Retroalimentación, 14 Riesgo de fuga, 15 Exportes. Los notebooks 4, 5, 6 y 7 son de desarrollo y no forman parte de la corrida.

---

## 4. Diagnósticos (solo leen; no cambian nada)

| Comando | Qué muestra | Cuándo |
|---|---|---|
| `python verificar_corrida.py` | Consistencia de la última corrida (histórico, cortes, pronóstico, listas, fuga, exportes, registro). | Después de cada corrida. |
| `python estado_modelos.py` | Un veredicto por modelo (pronóstico, agrupamiento, caída, riesgo de fuga): MANTENER / REVISAR / REENTRENAR, con el motivo y el comando exacto si toca reentrenar. Lee la antigüedad de cada modelo, el seguimiento en vivo y la deriva de criterios. | Después de la corrida mensual, para decidir si el mes que viene se corre en modo reentrenar. |
| `python comparar_modelos.py` | Deterioro y mejora de los modelos: WAPE en vivo por versión, curva de envejecimiento y cabeza a cabeza viejo vs nuevo (sección 4b). | Después de una simulación, o cada trimestre con los meses reales acumulados. |
| `python diagnostico_glosario.py` | Códigos del histórico (ciclo, clase, medidor, lectura, factura, estrato) que no tienen nombre en el glosario, cuántos clientes los tienen, y meses que llegaron sin esas columnas. | Cuando la empresa entregue glosario nuevo, o si la página muestra "sin nombre en glosario" con códigos que no conocías. |
| `python diagnostico_cruce_fuga.py` | Cruce del archivo de otros comercializadores contra la historia TC2: cuántos existen, cuándo salieron, cómo se ve la salida. | Cuando llegue una versión nueva del archivo de otros comercializadores, para ver cuántos ejemplos nuevos aporta. |
| `python diagnostico_fuga.py` | Cómo se ven en TC2 los ciclos 97 y 33, la clase IR y los clientes que dejan de aparecer. | Rara vez; sirvió para diseñar el producto de fuga. |

---

## 4b. Prueba completa con varios meses ya recibidos (y demostración de deterioro / reentrenamiento)

Caso: tienes los archivos TC2 de marzo a junio y quieres (a) probar la operación mensual con ellos y (b) mostrar cómo se ve un modelo deteriorado frente a uno recién entrenado.

**Paso 1 — meter los meses al histórico (una sola vez, en la carpeta real):**
```
(copiar formato_tc2_202603.xlsx ... formato_tc2_202606.xlsx a Datos_Ebsa\00_formato_TC2)
python pipeline_mensual.py --modo aplicar --hasta 2
```
El paso 1 agrega los cuatro meses a `historico_2026.parquet` (uno por uno, reemplazando si ya existían); el paso 2 reconstruye la serie y pasa la compuerta con junio como último mes. Unos 40 minutos. Con esto la carpeta real queda con la historia completa pero **sin** modelos ni listas nuevas todavía.

**Paso 2 — copiar la carpeta de datos** (la simulación sobreescribe salidas y modelos; se hace sobre la copia):
```
robocopy C:\Users\Home\Documents\Datos_Ebsa C:\Users\Home\Documents\Datos_Ebsa_simulacion /E /XD 09_registro_corridas
```

**Paso 3 — simular mes a mes sobre la copia** (una sola línea; puede correr de noche):
```
python simular_meses.py --desde 2025-06 --hasta 2026-06 --reentrenar-en 2025-06,2026-02 --comparar-version 2025-06 --datos "C:\Users\Home\Documents\Datos_Ebsa_simulacion"
```
Qué hace: en 2025-06 entrena todo como si fuera ese mes (no ve nada posterior); de 2025-07 a 2026-01 aplica ese modelo mes a mes; en 2026-02 reentrena; de 2026-03 a 2026-06 aplica el nuevo. En cada corte guarda el pronóstico, las listas, el seguimiento, `verificar_corrida.py` y `estado_modelos.py`. Al final vuelve a pronosticar 2026-02 a 2026-06 con la versión vieja (2025-06) y guarda esos pronósticos aparte, para enfrentarlos con los del modelo nuevo sobre los mismos meses. Tiempo: cada corte en aplicar ~8 min (medido: 7,8 min para los pasos 3–15 sobre la carpeta real), cada reentrenamiento ~1,5–2 h (el primero de la simulación lo mide: columna `minutos` de `resumen_simulacion.csv`); 13 cortes con 2 reentrenamientos ≈ 5–6 horas, más ~25 min de la comparación final. Se puede dejar de noche. Para acortar, `--cada 2` (un corte sí y otro no) o un rango más corto. Si se interrumpe, se retoma con `--desde <el corte que falló>` y `--reentrenar-en` solo con los cortes de reentrenamiento que falten (los modelos ya entrenados quedaron en la copia).

**Paso 4 — leer el resultado:**
```
python comparar_modelos.py --datos "C:\Users\Home\Documents\Datos_Ebsa_simulacion"
```
Tres vistas: (1) el WAPE en vivo corte a corte con la versión del modelo que pronosticó; (2) la curva de envejecimiento (WAPE según meses desde el entrenamiento: dice cada cuánto conviene reentrenar); (3) cabeza a cabeza sobre los mismos meses, modelo viejo contra nuevo, con la mejora en puntos. Deja `comparacion_modelos.png` y dos CSV en `09_registro_corridas\simulacion\`, y `resumen_simulacion.csv` con una fila por corte (clientes en lista, ALTO/MEDIO de fuga, veredicto del estado del modelo).

**Paso 5 — dejar la carpeta real al día:** en `Datos_Ebsa` (la real) correr `python pipeline_mensual.py --modo reentrenar --desde 3`, para que los modelos vigentes queden entrenados con todo hasta junio. La copia de simulación se puede borrar o conservar como evidencia.

---

## 5. Instalación y entorno (una sola vez, o al cambiar de máquina)

| Comando | Para qué |
|---|---|
| `pip install -r requirements.txt` | Instalar las librerías (pandas, LightGBM, XGBoost, CatBoost, Optuna, Streamlit, etc.). |
| `python preparar_carpeta_datos.py` | Crear la estructura de carpetas de `Datos_Ebsa` y ver qué hay que copiar del proyecto anterior. |
| `python generar_lock_entorno.py` | Escribir `requirements-lock.txt` con las versiones exactas instaladas, para reproducir el entorno en otra máquina (`pip install -r requirements-lock.txt`). Los `.joblib` dependen de la versión. |

---

## 6. Retroalimentación de campo (cuando haya visitas)

1. Copiar `Datos_Ebsa\07_gestion_caida\retroalimentacion\resultado_gestion_plantilla.csv` como `resultado_gestion_<mes>.csv` en esa misma carpeta y llenarla (una fila por cliente visitado: NIU, fecha_corte_lista, fecha_visita, hallazgo, accion, observaciones).
2. `python pipeline_mensual.py --modo aplicar --solo 13` (o esperar a la corrida mensual, que lo incluye).
3. El resultado sale en la sección Retroalimentación de la página.

---

## 7. Lo que NO hay que hacer

- No editar ni renombrar los archivos de la empresa; si un mes llega corregido, se copia con el mismo nombre de mes y el paso 1 lo reemplaza y avisa.
- No borrar `01_historico_procesado\resumen_por_archivo` sin motivo: obliga a releer todos los XLSX de `00_formato_TC2`.
- No correr dos pipelines a la vez sobre la misma carpeta de datos.
- No cambiar `EBSA_MODO` a `reentrenar` por costumbre: en aplicar los segmentos y los criterios se mantienen estables mes a mes, que es lo que permite comparar.
