"""
diagnostico_glosario.py — ¿qué códigos del histórico NO están en el glosario?
Solo lee; no escribe nada. Correr desde Pipeline_Ebsa:   python diagnostico_glosario.py

Revisa ciclo, clase de servicio, tipo de medidor, tipo de lectura, tipo de factura y estrato
en 01_historico_procesado, y lista cada valor que no tiene nombre en utilidades_glosario.py,
con cuántos NIU lo tienen y si sigue apareciendo en el último mes del histórico.
"""
import os
from pathlib import Path

import pandas as pd

# Windows: si la salida va a un archivo o a otro proceso (simular_meses.py), Python usa
# cp1252 y no puede escribir "✓" / "✗". Se fuerza UTF-8 en la salida de este script.
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
import pyarrow.parquet as pq

from utilidades_glosario import (
    ZONA_POR_CICLO, CLASE_SERVICIO_NOMBRE, TIPO_MEDIDOR_NOMBRE, TIPO_LECTURA_NOMBRE, TIPO_FACTURA_NOMBRE,
)

BASE = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
PROC = BASE / "01_historico_procesado"

CAMPOS = {
    "ciclo": ("numérico", set(ZONA_POR_CICLO)),
    "clase_servicio": ("texto", set(CLASE_SERVICIO_NOMBRE)),
    "tipo_medidor": ("numérico", set(TIPO_MEDIDOR_NOMBRE)),
    "tipo_lectura": ("numérico", set(TIPO_LECTURA_NOMBRE)),
    "tipo_factura": ("numérico", set(TIPO_FACTURA_NOMBRE)),
    "estrato": ("numérico", {0, 1, 2, 3, 4, 5, 6}),
}

archivos = sorted(PROC.glob("historico_*.parquet"))
if not archivos:
    raise FileNotFoundError(f"No hay historico_YYYY.parquet en {PROC}")

partes = []
for ruta in archivos:
    esquema = pq.ParquetFile(ruta).schema_arrow.names
    cols = ["NIU", "periodo"] + [c for c in CAMPOS if c in esquema]
    partes.append(pd.read_parquet(ruta, columns=cols, engine="pyarrow"))
h = pd.concat(partes, ignore_index=True)
h["periodo"] = pd.to_datetime(h["periodo"], errors="coerce")
ultimo = h["periodo"].max()
print(f"Histórico: {len(h):,} filas | {h['NIU'].nunique():,} NIU | hasta {ultimo:%Y-%m}")
print("Columnas disponibles:", [c for c in CAMPOS if c in h.columns])
faltan = [c for c in CAMPOS if c not in h.columns]
if faltan:
    print("⚠ Columnas que el histórico NO trae (el notebook 1 las extrae si el TC2 las tiene):", faltan)

for campo, (tipo, conocidos) in CAMPOS.items():
    if campo not in h.columns:
        continue
    v = h[campo]
    if tipo == "numérico":
        v = pd.to_numeric(v, errors="coerce").round()
        vacios = v.isna()
        v = v.astype("Int64")
    else:
        v = v.astype("string").str.strip().str.upper()
        vacios = v.isna() | (v == "")
    print("\n" + "=" * 78)
    print(f"{campo.upper()}  —  valores en el histórico: {sorted(str(x) for x in v.dropna().unique())}")
    print(f"  filas sin dato: {int(vacios.sum()):,} ({vacios.mean() * 100:.2f}%)")
    d = pd.DataFrame({"NIU": h["NIU"], "periodo": h["periodo"], "valor": v})[~vacios]
    resumen = (d.groupby("valor").agg(filas=("NIU", "size"), NIU=("NIU", "nunique"),
                                      NIU_ultimo_mes=("periodo", lambda s: int((s == ultimo).sum())))
               .reset_index().sort_values("NIU", ascending=False))
    resumen["en_glosario"] = resumen["valor"].map(lambda x: (x in conocidos) if tipo == "numérico" else (str(x) in conocidos))
    print(resumen.to_string(index=False))
    sin = resumen[~resumen["en_glosario"]]
    if len(sin):
        print(f"  >> SIN NOMBRE EN EL GLOSARIO: {sin['valor'].tolist()}  "
              f"({int(sin['NIU'].sum()):,} NIU en total; {int(sin['NIU_ultimo_mes'].sum()):,} en el último mes)")
    else:
        print("  >> todos los valores tienen nombre en el glosario")

# --- ¿Qué meses vienen sin estas columnas? (filas sin dato concentradas en archivos completos) ---
print("\n" + "=" * 78)
print("MESES CON MÁS DE LA MITAD DE LAS FILAS SIN DATO, POR CAMPO")
print("(si un mes aparece aquí, el archivo de ese mes llegó sin esa columna o vacía)")
h["mes"] = h["periodo"].dt.to_period("M").astype(str)
for campo in CAMPOS:
    if campo not in h.columns:
        continue
    v = h[campo]
    vacio = (pd.to_numeric(v, errors="coerce").isna() if CAMPOS[campo][0] == "numérico"
             else (v.astype("string").str.strip().isna() | (v.astype("string").str.strip() == "")))
    pct = vacio.groupby(h["mes"]).mean() * 100
    malos = pct[pct > 50]
    if len(malos):
        print(f"  {campo:<16}: " + ", ".join(f"{m} ({p:.0f}%)" for m, p in malos.items()))
    else:
        print(f"  {campo:<16}: ningún mes con más de la mitad sin dato")
