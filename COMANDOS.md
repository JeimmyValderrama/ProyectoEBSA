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
| Ver resultados | `python -m streamlit run app_ebsa.py` | Abre la página en el navegador (http://localhost:8501). Se cierra con Ctrl+C en la terminal. |

Si un paso falla, el pipeline se detiene, dice por qué y con qué comando reanudar (`--desde N`). Los dos fallos "buenos" son la compuerta de calidad del paso 2 (el archivo llegó con menos clientes urbanos, tarifas en cero, un ciclo desconocido) y el detector del borde del paso 3 (quiere retroceder demasiados meses): en ambos casos hay que mirar el archivo, no forzar la corrida.

---

## 2. Reentrenar (una vez al año, o cuando `estado_modelos.py` lo pida)

| Comando | Qué hace | Cuándo |
|---|---|---|
| `python pipeline_mensual.py --modo reentrenar` | Lo mismo que la corrida mensual, pero además reentrena el pronóstico (backtest + entrenamiento, ~1 hora extra), vuelve a comparar algoritmos de agrupamiento, recalcula los criterios de caída y reentrena el riesgo de fuga (parámetros fijos; Optuna solo como análisis de sensibilidad). Sobreescribe los `.joblib`. | **Una vez al año** (tope `MESES_MAX = 12` en `estado_modelos.py`), para que el modelo incorpore un ciclo estacional completo más; antes de eso solo si `estado_modelos.py` dice REENTRENAR por el seguimiento (dos cortes seguidos con más de la mitad de las celdas perfil × horizonte con WAPE en vivo por encima del backtest), o ante cambios estructurales (revisión tarifaria grande, cambio en la lectura rural, ciclos nuevos, llegada de archivos de años anteriores). Evidencia: en la simulación de 11 cortes el modelo de 7 meses pronosticaba igual que el recién entrenado y reentrenar movió 0,1 puntos de WAPE (Anexo E.3 del informe). Los criterios de caída se recalculan cuando `estado_modelos.py` avise deriva de umbrales > 10 puntos (es barato: `--solo 10,11,15`). |
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
| `python verificar_corrida.py` | Consistencia de la última corrida (histórico, cortes, pronóstico, listas, fuga, exportes, registro). Termina con código de salida 1 si hay errores. | Después de cada corrida. |
| `python estado_modelos.py` | Un veredicto por modelo (pronóstico, agrupamiento, caída, riesgo de fuga): MANTENER / REVISAR / REENTRENAR, con el motivo y el comando exacto si toca reentrenar. Lee la antigüedad de cada modelo, el seguimiento en vivo y la deriva de criterios. | Después de la corrida mensual, para decidir si el mes que viene se corre en modo reentrenar. |
| `python generar_ejemplo_retroalimentacion.py` | Ejemplo ilustrativo, con **resultados simulados**, de cómo se vería la página *Resultados de las visitas* si se registraran visitas. Escribe en `07_gestion_caida\retroalimentacion\ejemplo_simulado\`; la página lo muestra con un aviso mientras no haya visitas reales. Para quitarlo se borra esa carpeta. |
| `python evaluar_ingenuos_backtest.py` | El backtest del pronóstico frente a pronósticos ingenuos (repetir el último mes, media de 3 y de 12 meses, mismo mes del año anterior), separado en urbano y rural, y el error por cliente. Deja `comparacion_ingenuos_backtest.csv` y `error_por_cliente_backtest.csv` en `04_pronostico\modelo_final`. Solo lee; tarda menos de un minuto. | Después de cada reentrenamiento del pronóstico, y antes de citar una cifra de precisión. |
| `python comparar_modelos.py` | Deterioro y mejora de los modelos: WAPE en vivo por versión, curva de envejecimiento y cabeza a cabeza viejo vs nuevo (sección 4b). | Después de una simulación, o cada trimestre con los meses reales acumulados. |
| `python diagnostico_glosario.py` | Códigos del histórico (ciclo, clase, medidor, lectura, factura, estrato) que no tienen nombre en el glosario, cuántos clientes los tienen, y meses que llegaron sin esas columnas. | Cuando la empresa entregue glosario nuevo, o si la página muestra "sin nombre en glosario" con códigos que no conocías. |
| `python diagnostico_cruce_fuga.py` | Cruce del archivo de otros comercializadores contra la historia TC2: cuántos existen, cuándo salieron, cómo se ve la salida. | Cuando llegue una versión nueva del archivo de otros comercializadores, para ver cuántos ejemplos nuevos aporta. |
| `python diagnostico_fuga.py` | Cómo se ven en TC2 los ciclos 97 y 33, la clase IR y los clientes que dejan de aparecer. | Rara vez; sirvió para diseñar el producto de fuga. |

## 4c. Ubicación de los clientes y mapa (formato TC1) — aparte del pipeline

```
python cruzar_ubicacion_tc1.py
```

Lee `Datos_Ebsa\00_formato_TC1\TC1_MMAAAA.csv` (el más reciente) y `Código DANE.xls`, y deja `13_ubicacion_clientes\` (municipio, provincia, dirección, coordenadas y zona del mapa por NIU; tabla de municipios con su zona EBSA). No toca nada del pipeline. Se corre una vez y se repite cuando llegue un TC1 nuevo (no hace falta correrlo cada mes). Necesita `pip install xlrd` para leer el .xls. Con esa carpeta la página muestra el municipio en todas las listas y la sección **Mapa** (`pip install plotly` para el mapa con nombres al pasar el mouse).

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
| `copy secrets.toml.ejemplo .streamlit\secrets.toml` y editar las claves | Usuarios de la página (`comercial`, `soporte` y `admin`). El archivo no va a Git: hay que crearlo en cada máquina. |
| `python preparar_carpeta_datos.py` | Crear la estructura de carpetas de `Datos_Ebsa` y ver qué hay que copiar del proyecto anterior. |
| `python generar_lock_entorno.py` | Escribir `requirements-lock.txt` con las versiones exactas instaladas, para reproducir el entorno en otra máquina (`pip install -r requirements-lock.txt`). Los `.joblib` dependen de la versión. |

---

## 6. Retroalimentación de campo (cuando haya visitas)

1. Copiar `Datos_Ebsa\07_gestion_caida\retroalimentacion\resultado_gestion_plantilla.csv` como `resultado_gestion_<mes>.csv` en esa misma carpeta y llenarla (una fila por cliente visitado: NIU, fecha_corte_lista, fecha_visita, hallazgo, accion, observaciones).
2. `python pipeline_mensual.py --modo aplicar --solo 13` (o esperar a la corrida mensual, que lo incluye).
3. El resultado sale en la sección Retroalimentación de la página.

---

## 4d. Proyección de consumo por zona (compra de energía) — aparte del pipeline

```
pip install statsmodels
python proyeccion_anual_consumo.py
```

Agrega la serie consolidada por zona regional, ajusta Holt-Winters / SARIMA, mide el error con backtest y proyecta 36 meses con bandas; deja `14_proyeccion_anual\` y alimenta la sección *Proyección de consumo (compra de energía)* de la vista Comercial. Tarda unos minutos. Repetir después de cada corrida mensual si se quiere la proyección al día (no hace falta cada mes). Opciones: `--meses 48`, `--umbral 12`.

## 4e. Carpeta para que un compañero solo abra la página (sin pipeline)

```
python empaquetar_app.py
```
Deja `C:\Users\Home\Documents\EBSA_app_para_compartir\` con **las dos páginas** (original e interfaz nueva), `INICIAR_APP.bat`, `INICIAR_APP_V2.bat`, `LEEME.txt`, `secrets.toml.ejemplo` y una carpeta `datos\` con solo lo que las páginas leen (~680 MB; `--sin-exportes` la deja en ~320 MB sin la sección Descargas). Se comprime y se envía. En el otro PC: `pip install -r requirements_app.txt`, crear el archivo de usuarios como dice `LEEME.txt` y doble clic en `INICIAR_APP.bat` o `INICIAR_APP_V2.bat`; las páginas encuentran `datos\` solas. Cuando haya un mes nuevo se vuelve a empaquetar y se reenvía (la copia no se actualiza sola).

| Comando | Para qué |
|---|---|
| `python empaquetar_app.py` | Paquete con las dos páginas, **sin claves** (lleva `secrets.toml.ejemplo`). |
| `python empaquetar_app.py --sin-exportes` | Igual, sin `11_exportes_negocio` (la sección Descargas queda vacía). |
| `python empaquetar_app.py --destino D:\EBSA_app` | Otra carpeta de destino. Si existe, se reemplaza. |
| `python empaquetar_app.py --incluir-claves` | Copia también `.streamlit\secrets.toml` de esta máquina. Solo si quien recibe debe tener esas mismas claves. |

El paquete nunca lleva modelos `.joblib`, notebooks ni archivos de la empresa, y al terminar el programa lo revisa y lo dice. La carpeta `datos\` sí lleva información de clientes (NIU, dirección, consumo): se comparte solo con el equipo.

## 4f. Las dos versiones de la página

Desde `C:\Users\Home\Documents\GitHub\ProyectoEBSA\Pipeline_Ebsa`:

| Qué | Comando | Qué hace |
|---|---|---|
| Página original | `python -m streamlit run app_ebsa.py` | Abre la página de siempre en http://localhost:8501. |
| Interfaz nueva (V2) | `python -m streamlit run app_ebsa_v2.py` | Abre la misma información con la interfaz nueva. Necesita `componentes_v2.py` y `recursos_v2\` en la misma carpeta. |
| Las dos a la vez | `python -m streamlit run app_ebsa.py --server.port 8501` y, en otra consola, `python -m streamlit run app_ebsa_v2.py --server.port 8502` | Cada una en su puerto, para compararlas. |
| Ver la versión de Streamlit | `python -m streamlit version` | La V2 necesita 1.40 o superior; la original, 1.35. |
| Apagar una página | Ctrl+C en su consola | — |

Las dos leen la misma carpeta de datos y el mismo `.streamlit\secrets.toml`, y ninguna escribe en los datos. Después de correr el pipeline no hay que reiniciarlas: leen los archivos nuevos solas. Después de cambiar un archivo `.py` de la V2 sí hay que apagarla y volver a abrirla.

| Si pasa esto | Hacer esto |
|---|---|
| "Falta el archivo de usuarios" | `copy secrets.toml.ejemplo .streamlit\secrets.toml` y cambiar las claves (sección 5). |
| "Usuario o clave incorrectos" con la clave bien escrita | La clave del archivo sigue en `CAMBIAR`: mientras diga eso, ese usuario no entra. |
| `No module named 'componentes_v2'` | Falta `componentes_v2.py` junto a `app_ebsa_v2.py`, o la página se lanzó desde otra carpeta. |
| La V2 sale sin estilos o con el mapa de círculos | Falta la carpeta `recursos_v2\`. |
| `Port 8501 is already in use` | Hay otra página abierta en ese puerto: cerrarla o usar `--server.port 8502`. |
| "No existe la carpeta de datos" | Revisar `EBSA_DATOS` o, como `admin`, la *Carpeta de datos* (en la V2 está en *Datos y sesión*, al final del menú). |
| Una sección dice que falta un archivo | Falta esa corrida del pipeline, no la página (sección 1). |

## 6b. Decisiones de negocio que ya están en el código (no hay que configurarlas)

- **Autogeneradores (ciclo 50)**: fuera de todo el universo por su ciclo **actual** (último conocido), no por el más frecuente. Un cliente que acaba de pasar a autogenerador cae de consumo por diseño; antes se colaba en la lista de caída como CRÍTICA. Si vuelve a un ciclo normal, reingresa solo en la corrida siguiente. `verificar_corrida.py` marca ERROR si alguno aparece en la lista de caída.
- **Mercado no regulado (ciclo 33, clase IR o ≥ 55.000 kWh/mes)**: se puntúa con el modelo de fuga pero solo aparece en la pestaña *Vigilancia no regulados*; nunca en el ranking, las listas, los resúmenes ni los exportes. `verificar_corrida.py` marca ERROR si alguno aparece en el ranking.
- **Clases sin gestión (AC área común, AU autoconsumos EBSA, RI distritos de riego, PR provisionales)**: fuera de la lista de caída y del riesgo de fuga; siguen en la serie y el pronóstico. Los retirados quedan en `07_gestion_caida\clientes_excluidos_de_gestion.csv`.
- **Cero sostenido (3+ meses en cero o casi cero)**: ningún mes de la ventana reciente por encima del mayor entre 10 kWh y el 5 % de lo que el cliente consumía (ajuste del 2026-10-07; antes exigía 0 exacto). Fuera de la lista de caída; quedan en `07_gestion_caida\clientes_cero_sostenido.csv` con lo que facturaban antes y la página los muestra en la sección *Clientes sin consumo* de la vista Comercial. El riesgo de fuga sigue usando el cero exacto para su etiqueta de salida. Si se cambia esta regla en el notebook 11 basta con `python pipeline_mensual.py --modo aplicar --solo 11,15` (1–2 min) y `python verificar_corrida.py`.
- **Estacionales**: ya estuvieron en cero y volvieron antes de la caída actual, y el pronóstico prevé recuperación (vuelve al menos a la mitad del nivel previo y supera 10 kWh) → `prioridad_gestion = VIGILAR: estacional`, al final del ciclo. **Fuga**: el top % de la lista solo aplica con probabilidad ≥ tasa base.
- **Caídas antiguas**: todas las que solo caen frente al año pasado (`CAIDA_SOSTENIDA`) quedan con `prioridad_gestion = SEGUIMIENTO: caída antigua` y en la página su gravedad se muestra como "Antigua", no como "Grave", después de `GESTIONAR` en cada ciclo; la página muestra por defecto solo `GESTIONAR` y permite elegirlas en el filtro *Prioridad*.
- **Zona regional**: columna `zona_regional` en todas las listas (ciclo urbano + rural + seccionales de una misma dirección). La página filtra y resume por ella.
- **Etiqueta de ciclo de la lista operativa**: es el ciclo actual del cliente (la ruta de hoy), para que coincida con la zona del glosario que sale de los atributos del último mes.

---

## 7. Lo que NO hay que hacer

- No editar ni renombrar los archivos de la empresa; si un mes llega corregido, se copia con el mismo nombre de mes y el paso 1 lo reemplaza y avisa.
- No borrar `01_historico_procesado\resumen_por_archivo` sin motivo: obliga a releer todos los XLSX de `00_formato_TC2`.
- No correr dos pipelines a la vez sobre la misma carpeta de datos.
- No borrar ni reemplazar una página por la otra: `app_ebsa.py` y `app_ebsa_v2.py` se mantienen las dos. Un cambio de cálculo o de regla se hace en ambas.
- No subir a Git ni enviar por correo `.streamlit\secrets.toml`; no publicar en internet la carpeta `datos\` ni capturas con NIU o direcciones.
- No cambiar `EBSA_MODO` a `reentrenar` por costumbre: en aplicar los segmentos y los criterios se mantienen estables mes a mes, que es lo que permite comparar.
