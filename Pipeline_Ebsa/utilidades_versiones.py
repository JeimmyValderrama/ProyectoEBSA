"""
utilidades_versiones.py — histórico de versiones de los modelos
================================================================

Cada vez que un notebook entrena un modelo (modo reentrenar) guarda, además del
archivo "vigente" que usa la corrida, una COPIA con el corte en el nombre en

    Datos_Ebsa\\12_versiones_modelos\\<modelo>_corte_AAAA-MM.joblib

y una fila en registro_versiones.csv (modelo, corte, cuándo se entrenó, tamaño, notas).
Cada corrida en modo aplicar anota en registro_uso.csv qué versión usó para qué corte.

Con eso se puede:
  • ver qué modelo estaba vigente en cada mes (auditoría);
  • volver a una versión anterior si un reentrenamiento salió peor;
  • correr el pipeline con una versión concreta para compararla con otra:
        python pipeline_mensual.py --modo aplicar --version-modelo 2025-06
    (variable de entorno EBSA_VERSION_MODELO; si no existe esa versión de algún
    modelo, el notebook se detiene y lo dice).

Modelos versionados: pronostico (notebook 8), agrupamiento (9), criterios_caida (10),
riesgo_fuga (14).
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

CARPETA = "12_versiones_modelos"
MODELOS = ("pronostico", "agrupamiento", "criterios_caida", "riesgo_fuga")


def carpeta_versiones(base_dir) -> Path:
    c = Path(base_dir) / CARPETA
    c.mkdir(parents=True, exist_ok=True)
    return c


def etiqueta(fecha) -> str:
    return pd.Timestamp(fecha).strftime("%Y-%m")


def ruta_version(base_dir, modelo: str, version: str) -> Path:
    """Ruta del .joblib de una versión ('AAAA-MM')."""
    return carpeta_versiones(base_dir) / f"{modelo}_corte_{version}.joblib"


def guardar_version(base_dir, modelo: str, ruta_vigente, fecha_corte, notas: str = "", **extra) -> Path:
    """Copia el .joblib recién entrenado a la carpeta de versiones y lo registra."""
    if modelo not in MODELOS:
        raise ValueError(f"modelo debe ser uno de {MODELOS}")
    destino = ruta_version(base_dir, modelo, etiqueta(fecha_corte))
    shutil.copy2(ruta_vigente, destino)
    fila = {
        "modelo": modelo,
        "version": etiqueta(fecha_corte),
        "entrenado_el": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "archivo": destino.name,
        "tamano_kb": round(destino.stat().st_size / 1024, 1),
        "notas": notas,
    }
    fila.update({k: (v if not isinstance(v, (list, dict)) else str(v)) for k, v in extra.items()})
    registro = carpeta_versiones(base_dir) / "registro_versiones.csv"
    df = pd.DataFrame([fila])
    if registro.exists():
        viejo = pd.read_csv(registro, encoding="utf-8-sig")
        viejo = viejo[~((viejo["modelo"] == modelo) & (viejo["version"].astype(str) == fila["version"]))]
        df = pd.concat([viejo, df], ignore_index=True)
    df.sort_values(["modelo", "version"]).to_csv(registro, index=False, encoding="utf-8-sig")
    return destino


def resolver_modelo(base_dir, modelo: str, ruta_vigente) -> tuple[Path, str]:
    """
    Qué archivo cargar en modo aplicar: si EBSA_VERSION_MODELO está definida, la
    versión pedida (error claro si no existe); si no, el vigente. Devuelve (ruta, version_texto).
    """
    version = os.environ.get("EBSA_VERSION_MODELO", "").strip()
    if version:
        ruta = ruta_version(base_dir, modelo, version)
        if not ruta.exists():
            disponibles = sorted(p.name for p in carpeta_versiones(base_dir).glob(f"{modelo}_corte_*.joblib"))
            raise FileNotFoundError(
                f"No existe la versión {version} del modelo '{modelo}': {ruta}\n"
                f"Versiones disponibles: {disponibles or 'ninguna (aún no se ha reentrenado con versionado)'}"
            )
        return ruta, version
    return Path(ruta_vigente), "vigente"


def registrar_uso(base_dir, modelo: str, fecha_corte, version_usada: str, fecha_corte_modelo=None, modo: str = "aplicar"):
    """Anota qué versión de cada modelo se usó en la corrida de un corte."""
    registro = carpeta_versiones(base_dir) / "registro_uso.csv"
    if os.environ.get("EBSA_VERSION_MODELO", "").strip():
        modo = f"comparacion (version {os.environ['EBSA_VERSION_MODELO'].strip()})"   # no pisa la corrida normal
    fila = {
        "fecha_corte": etiqueta(fecha_corte),
        "modelo": modelo,
        "modo": modo,
        "version_usada": version_usada,
        "fecha_corte_modelo": etiqueta(fecha_corte_modelo) if fecha_corte_modelo is not None else "",
        "registrado_el": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    df = pd.DataFrame([fila])
    if registro.exists():
        viejo = pd.read_csv(registro, encoding="utf-8-sig")
        viejo = viejo[~((viejo["fecha_corte"].astype(str) == fila["fecha_corte"]) & (viejo["modelo"] == modelo)
                        & (viejo["modo"].astype(str) == fila["modo"]))]
        df = pd.concat([viejo, df], ignore_index=True)
    df.sort_values(["fecha_corte", "modelo"]).to_csv(registro, index=False, encoding="utf-8-sig")


def listar_versiones(base_dir) -> pd.DataFrame:
    registro = carpeta_versiones(base_dir) / "registro_versiones.csv"
    return pd.read_csv(registro, encoding="utf-8-sig") if registro.exists() else pd.DataFrame(columns=["modelo", "version"])
