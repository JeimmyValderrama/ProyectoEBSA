"""
preparar_carpeta_datos.py — crea la estructura de carpetas de Datos_Ebsa
=========================================================================

Uso (desde GitHub\ProyectoEBSA\Pipeline_Ebsa):

    python preparar_carpeta_datos.py

Crea las carpetas vacías que faltan (los notebooks también las crean al correr,
esto solo sirve para verlas de una vez) y dice qué hay que copiar a mano desde
el proyecto anterior para poder arrancar.

Estructura:

    Datos_Ebsa\
    ├── 00_formato_TC2\               <- los XLSX/CSV mensuales de la empresa, formato TC2 (entrada del paso 1)
    ├── 01_historico_procesado\       <- paso 1: historico_YYYY.parquet + detalle_mensual\
    ├── 02_serie_reconstruida\        <- paso 2: serie mensual con lecturas trimestrales repartidas
    │   └── copia_historicos\            (copia de trabajo de los historico_YYYY)
    ├── 03_serie_modelado\            <- paso 3: ENTRADA DE TODOS LOS MODELOS
    ├── 04_pronostico\
    │   ├── desarrollo_01_modelo_unico\  <- notebook 4 (referencia)
    │   ├── desarrollo_02_segmentado\    <- notebook 5 (referencia)
    │   └── modelo_final\                <- notebooks 6, 7 y 8: MODELO FINAL DE PRONÓSTICO
    │       └── historial_pronosticos\
    ├── 05_segmentos_clientes\        <- paso 9: MODELO FINAL DE AGRUPAMIENTO
    ├── 06_estudio_caida\             <- paso 10: CRITERIOS DE CAÍDA
    ├── 07_gestion_caida\             <- paso 11: LISTAS PARA GESTIÓN
    │   ├── historial\
    │   └── retroalimentacion\
    ├── 08_seguimiento\               <- paso 12: precisión en vivo
    └── 09_registro_corridas\         <- pipeline_mensual.py: registro de cada corrida

El código vive aparte, en C:\\Users\\Home\\Documents\\GitHub\\ProyectoEBSA\\Pipeline_Ebsa.
"""

import os
from pathlib import Path

DATOS_DIR = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))

CARPETAS = [
    "00_formato_TC2",
    "01_historico_procesado/detalle_mensual",
    "02_serie_reconstruida/copia_historicos",
    "03_serie_modelado",
    "04_pronostico/desarrollo_01_modelo_unico",
    "04_pronostico/desarrollo_02_segmentado",
    "04_pronostico/modelo_final/historial_pronosticos",
    "05_segmentos_clientes",
    "06_estudio_caida",
    "07_gestion_caida/historial",
    "07_gestion_caida/retroalimentacion",
    "08_seguimiento",
    "09_registro_corridas",
]

print("Carpeta de datos:", DATOS_DIR)
for c in CARPETAS:
    ruta = DATOS_DIR / c
    estado = "ya existía" if ruta.exists() else "creada"
    ruta.mkdir(parents=True, exist_ok=True)
    print(f"  {estado:<10} {c}")

print("""
QUÉ COPIAR A MANO DESDE EL PROYECTO ANTERIOR (C:\\Users\\Home\\Documents\\Datos Ebsa)
---------------------------------------------------------------------------
Obligatorio (una de las dos opciones):
  a) Los XLSX/CSV originales de la empresa (formato TC2)  ->  00_formato_TC2\\
     (y el pipeline arranca desde el paso 1), o
  b) Procesado\\historico_2022.parquet ... historico_2026.parquet  ->  01_historico_procesado\\
     (y el pipeline arranca desde el paso 2: --desde 2). Más rápido.

Obligatorio para el pronóstico (el notebook 8 los lee; son el resultado de los
notebooks 6 y 7, que tardan horas):
  Serie_tiempo_consumo\\modelacion_consumo_segmentada_comparativa\\
      seleccion_modelo_por_perfil_horizonte_optimizada.csv
      hiperparametros_optimos_por_grupo.json
      metricas_sistema_por_perfil_horizonte.csv
      metricas_sistema_ganador_backtest.csv
  ->  04_pronostico\\modelo_final\\

Nada más. Todo lo demás lo regenera la primera corrida:
  python pipeline_mensual.py --modo reentrenar --desde 2
""")
