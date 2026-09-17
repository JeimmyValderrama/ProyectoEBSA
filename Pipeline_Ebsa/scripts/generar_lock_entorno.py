"""
generar_lock_entorno.py — deja constancia de las versiones exactas instaladas
==============================================================================

Uso (en la máquina que entrenó los modelos):

    python generar_lock_entorno.py

Escribe requirements-lock.txt con la versión exacta de cada paquete que usa el
proyecto, más la versión de Python. Con ese archivo, otra máquina reproduce el
entorno con:

    pip install -r requirements-lock.txt

Por qué importa: los modelos guardados (.joblib) se serializan con las clases
de LightGBM, XGBoost, CatBoost y scikit-learn de la versión instalada. Un
cambio mayor de versión puede impedir cargarlos; el lock evita la sorpresa.
"""

import importlib.metadata as md
import platform
import sys
from datetime import datetime
from pathlib import Path

PAQUETES = [
    "pandas", "numpy", "pyarrow", "scikit-learn", "lightgbm", "xgboost", "catboost",
    "optuna", "joblib", "matplotlib", "openpyxl", "jupyter", "nbformat", "nbclient",
    "streamlit",
]

lineas = [
    f"# Generado el {datetime.now():%Y-%m-%d %H:%M} en {platform.node()} "
    f"({platform.system()} {platform.release()})",
    f"# Python {sys.version.split()[0]}",
]
faltan = []
for p in PAQUETES:
    try:
        lineas.append(f"{p}=={md.version(p)}")
    except md.PackageNotFoundError:
        faltan.append(p)

destino = Path(__file__).resolve().parent / "requirements-lock.txt"
destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")

print("Escrito:", destino)
print("\n".join(lineas))
if faltan:
    print("\n⚠ No instalados en este entorno (no se incluyen):", ", ".join(faltan))
