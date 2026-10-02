"""
cruzar_ubicacion_tc1.py — municipio y coordenadas de cada cliente (formato TC1)
===============================================================================

Cruza el archivo TC1 de la empresa (uno por cliente: código DANE, dirección,
coordenadas, nivel de tensión, circuito, transformador) con la tabla de
códigos DANE → municipio, y deja una tabla NIU → ubicación lista para que la
página y las listas muestren el municipio y para dibujar el mapa.

Es un paso APARTE del pipeline mensual: no toca ningún notebook ni ninguna
salida existente. Se corre una vez y se repite solo cuando llegue un TC1 nuevo.

Cómo correrlo (desde la carpeta del código):

    python cruzar_ubicacion_tc1.py

Entradas (en la carpeta de datos, EBSA_DATOS o la ruta de siempre):
    00_formato_TC1/TC1_MMAAAA.csv       separado por ';', una fila por NIU (se toma el más reciente)
    00_formato_TC1/Código DANE.xls      hoja "Tabla Municipios" (todo el país) y hoja "Boyacá" (provincia)
    03_serie_modelado/niu_ciclo.parquet ciclo por NIU (para deducir la zona EBSA de cada municipio)

Salidas (carpeta nueva 13_ubicacion_clientes/):
    ubicacion_clientes.parquet   NIU, código DANE, municipio, provincia, departamento, dirección,
                                 ubicación SUI, estrato/sector, nivel de tensión, circuito, transformador,
                                 latitud, longitud, altitud, coordenadas_validas, autogenerador_tc1
    municipios_zona.csv          un renglón por municipio: zona EBSA (la de sus ciclos), clientes,
                                 centro geográfico (mediana de las coordenadas válidas)
    auditoria_cruce_tc1.csv      cifras del cruce (filas, duplicados, sin municipio, coordenadas inválidas,
                                 clientes del universo sin TC1, ...)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from utilidades_glosario import ZONA_POR_CICLO

BASE = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
DIR_TC1 = BASE / "00_formato_TC1"
DIR_SALIDA = BASE / "13_ubicacion_clientes"
RUTA_NIU_CICLO = BASE / "03_serie_modelado" / "niu_ciclo.parquet"

RUTA_UBICACION = DIR_SALIDA / "ubicacion_clientes.parquet"
RUTA_MUNICIPIOS = DIR_SALIDA / "municipios_zona.csv"
RUTA_AUDITORIA = DIR_SALIDA / "auditoria_cruce_tc1.csv"

# Caja geográfica plausible para Boyacá y los municipios vecinos que atiende EBSA
LON_MIN, LON_MAX = -75.0, -71.5
LAT_MIN, LAT_MAX = 4.3, 7.3

# Zona EBSA "de mapa" (8 zonas) por ciclo: el ciclo urbano y su rural comparten zona
ZONA_MAPA_POR_CICLO = {
    0: "CENTRO", 9: "CENTRO", 10: "CENTRO", 19: "CENTRO",
    1: "TUNDAMA", 11: "TUNDAMA",
    2: "SUGAMUXI", 12: "SUGAMUXI",
    3: "OCCIDENTE", 22: "OCCIDENTE",
    4: "ORIENTE", 13: "ORIENTE",
    5: "NORTE", 21: "NORTE",
    6: "RICAURTE", 23: "RICAURTE",
    7: "PUERTO BOYACA", 38: "PUERTO BOYACA",
}

COLUMNAS_TC1 = {
    "NIU": "NIU",
    "codigo DANE": "codigo_dane",
    "ubicacion": "ubicacion_sui",
    "direccion": "direccion",
    "estrato/sector": "estrato_sector",
    "nivel de tension": "nivel_tension",
    "codigo circuito": "circuito",
    "codigo transformador": "transformador",
    "latitud": "latitud",
    "longitud": "longitud",
    "altitud": "altitud",
    "autogenerador": "autogenerador_tc1",
}


def ultimo_tc1(carpeta: Path) -> Path:
    """TC1_MMAAAA.csv más reciente por el periodo del nombre (si no, por fecha de archivo)."""
    archivos = sorted(carpeta.glob("TC1_*.csv"))
    if not archivos:
        raise FileNotFoundError(f"No hay TC1_*.csv en {carpeta}")

    def clave(p: Path):
        m = re.search(r"TC1_(\d{2})(\d{4})", p.name)
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)

    return max(archivos, key=lambda p: (clave(p), p.stat().st_mtime))


def periodo_tc1(ruta: Path) -> str:
    m = re.search(r"TC1_(\d{2})(\d{4})", ruta.name)
    return f"{m.group(2)}-{m.group(1)}" if m else ""


def leer_tc1(ruta: Path) -> pd.DataFrame:
    """Lee solo las columnas necesarias; tolera cp1252 si el archivo no viene en UTF-8."""
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            t = pd.read_csv(ruta, sep=";", dtype=str, encoding=enc, usecols=list(COLUMNAS_TC1), low_memory=False)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"No se pudo leer {ruta.name} con utf-8, cp1252 ni latin-1")
    t = t.rename(columns=COLUMNAS_TC1)
    for c in t.columns:
        t[c] = t[c].astype("string").str.strip()
    return t


def leer_municipios(carpeta: Path) -> pd.DataFrame:
    """Tabla código DANE (5 dígitos) → municipio, departamento y provincia (Boyacá)."""
    candidatos = sorted(list(carpeta.glob("*DANE*.xls")) + list(carpeta.glob("*DANE*.xlsx")) + list(carpeta.glob("*DANE*.csv")))
    if not candidatos:
        raise FileNotFoundError(f"No hay archivo de códigos DANE (*DANE*.xls/.xlsx/.csv) en {carpeta}")
    ruta = candidatos[0]
    if ruta.suffix == ".csv":
        m = pd.read_csv(ruta, dtype=str, encoding="utf-8-sig")
        m.columns = [c.strip().lower() for c in m.columns]
        m = m.rename(columns={"codigo_municipio": "codigo_municipio", "nombre_mpio": "municipio"})
        m["codigo_municipio"] = m["codigo_municipio"].str.zfill(5)
        if "provincia" not in m.columns:
            m["provincia"] = pd.NA
        if "departamento" not in m.columns:
            m["departamento"] = pd.NA
        return m[["codigo_municipio", "municipio", "departamento", "provincia"]]

    try:
        libro = pd.ExcelFile(ruta)
    except ImportError as e:
        raise ImportError("Para leer el .xls hace falta xlrd:  pip install xlrd") from e

    # Hoja nacional: NOMBRE_DEPTO | PROVINCIA | CODIGO_MUNICIPIO | NOMBRE_MPIO | Nombre | Total
    hoja_nac = next((h for h in libro.sheet_names if "municip" in h.lower()), None)
    if hoja_nac is None:
        raise ValueError(f"{ruta.name}: no encuentro la hoja 'Tabla Municipios'. Hojas: {libro.sheet_names}")
    n = libro.parse(hoja_nac)
    n.columns = [str(c).strip().upper() for c in n.columns]
    col_cod = next(c for c in n.columns if "CODIGO" in c or "CÓDIGO" in c)
    col_nom = next(c for c in n.columns if c.startswith("NOMBRE_MPIO") or c == "NOMBRE MPIO")
    col_dep = next(c for c in n.columns if "DEPTO" in c)
    col_prov = next((c for c in n.columns if "PROVINCIA" in c), None)
    n[col_dep] = n[col_dep].ffill()
    if col_prov:
        n[col_prov] = n[col_prov].ffill()
    n = n[pd.to_numeric(n[col_cod], errors="coerce").notna()].copy()
    n["codigo_municipio"] = pd.to_numeric(n[col_cod]).astype(int).astype(str).str.zfill(5)
    n["municipio"] = n[col_nom].astype(str).str.strip().str.title()
    n["departamento"] = n[col_dep].astype(str).str.strip().str.upper().str.replace(r"^TOTAL\s+", "", regex=True)
    n["provincia"] = n[col_prov].astype(str).str.strip().str.upper() if col_prov else pd.NA
    n = n[["codigo_municipio", "municipio", "departamento", "provincia"]].drop_duplicates("codigo_municipio")

    # Hoja de Boyacá: trae la provincia bien para el departamento (la nacional a veces la deja vacía)
    hoja_boy = next((h for h in libro.sheet_names if "boyac" in h.lower()), None)
    if hoja_boy is not None:
        b = libro.parse(hoja_boy)
        b.columns = [str(c).strip().upper() for c in b.columns]
        bc = next((c for c in b.columns if "CÓDIGO" in c or "CODIGO" in c), None)
        bp = next((c for c in b.columns if "PROVINCIA" in c), None)
        if bc and bp:
            b[bp] = b[bp].ffill()
            b = b[pd.to_numeric(b[bc], errors="coerce").notna()]
            prov = dict(zip(pd.to_numeric(b[bc]).astype(int).astype(str).str.zfill(5), b[bp].astype(str).str.strip().str.upper()))
            n["provincia"] = n["codigo_municipio"].map(prov).fillna(n["provincia"])
    return n


def main() -> None:
    print("CRUCE TC1 → MUNICIPIO Y COORDENADAS POR CLIENTE")
    print("=" * 78)
    ruta_tc1 = ultimo_tc1(DIR_TC1)
    periodo = periodo_tc1(ruta_tc1)
    print(f"TC1            : {ruta_tc1.name} (periodo {periodo or 'sin periodo en el nombre'})")
    t = leer_tc1(ruta_tc1)
    filas = len(t)
    dup = int(t["NIU"].duplicated().sum())
    t = t.drop_duplicates("NIU", keep="last")
    print(f"Filas          : {filas:,} | NIU únicos {len(t):,} | duplicados descartados {dup:,}")

    # Código DANE: 8 dígitos = 5 del municipio + 3 del centro poblado
    t["codigo_dane"] = t["codigo_dane"].str.replace(r"\D", "", regex=True)
    t["codigo_municipio"] = t["codigo_dane"].str[:5]
    muni = leer_municipios(DIR_TC1)
    t = t.merge(muni, on="codigo_municipio", how="left")
    sin_muni = int(t["municipio"].isna().sum())
    print(f"Municipios     : {t['codigo_municipio'].nunique():,} códigos distintos; "
          f"{sin_muni:,} clientes con código que no está en la tabla DANE")
    fuera_boyaca = int((t["departamento"].notna() & ~t["departamento"].str.contains("BOYAC", na=False)).sum())
    print(f"Fuera de Boyacá: {fuera_boyaca:,} clientes (municipios vecinos de Santander, Cundinamarca o Casanare)")

    # Coordenadas
    for c in ("latitud", "longitud", "altitud"):
        t[c] = pd.to_numeric(t[c].str.replace(",", ".", regex=False), errors="coerce")
    t["coordenadas_validas"] = (t["longitud"].between(LON_MIN, LON_MAX) & t["latitud"].between(LAT_MIN, LAT_MAX))
    sin_coord = int(t["longitud"].isna().sum())
    coord_malas = int((~t["coordenadas_validas"] & t["longitud"].notna()).sum())
    print(f"Coordenadas    : válidas {int(t['coordenadas_validas'].sum()):,} | sin dato {sin_coord:,} | fuera de rango {coord_malas:,}")

    t["autogenerador_tc1"] = t["autogenerador_tc1"].eq("1")
    t["nivel_tension"] = pd.to_numeric(t["nivel_tension"], errors="coerce").astype("Int64")
    t["archivo_tc1"] = ruta_tc1.name
    t["periodo_tc1"] = periodo

    # Zona EBSA por municipio: la de los ciclos de sus clientes (niu_ciclo.parquet)
    zona_cliente = None
    en_universo = universo_sin_tc1 = 0
    if RUTA_NIU_CICLO.exists():
        nc = pd.read_parquet(RUTA_NIU_CICLO, engine="pyarrow")
        nc["NIU"] = nc["NIU"].astype("string").str.strip()
        col = "ciclo_actual" if "ciclo_actual" in nc.columns else "ciclo"
        nc["zona_mapa"] = pd.to_numeric(nc[col], errors="coerce").map(ZONA_MAPA_POR_CICLO)
        nc["zona_nombre"] = pd.to_numeric(nc[col], errors="coerce").map(lambda x: ZONA_POR_CICLO.get(int(x)) if pd.notna(x) else None)
        zona_cliente = nc[["NIU", "zona_mapa", "zona_nombre"]].drop_duplicates("NIU")
        t = t.merge(zona_cliente, on="NIU", how="left")
        en_universo = int(t["zona_nombre"].notna().sum())
        universo_sin_tc1 = int((~nc["NIU"].isin(t["NIU"])).sum())
        print(f"Universo       : {en_universo:,} clientes del TC1 están en la serie de modelado; "
              f"{universo_sin_tc1:,} clientes de la serie no aparecen en el TC1")
    else:
        t["zona_mapa"] = pd.NA
        t["zona_nombre"] = pd.NA
        print("⚠ No existe niu_ciclo.parquet: el municipio queda sin zona EBSA (corre el pipeline primero)")

    # --- Tabla de municipios ---
    g = t.groupby(["codigo_municipio"], dropna=False)
    muni_tabla = g.agg(
        municipio=("municipio", "first"), provincia=("provincia", "first"), departamento=("departamento", "first"),
        clientes_tc1=("NIU", "size"),
        clientes_en_serie=("zona_nombre", lambda s: int(s.notna().sum())),
        coordenadas_validas=("coordenadas_validas", "sum"),
    ).reset_index()
    centro = (t[t["coordenadas_validas"]].groupby("codigo_municipio")[["latitud", "longitud"]].median()
              .rename(columns={"latitud": "lat_centro", "longitud": "lon_centro"}).reset_index())
    muni_tabla = muni_tabla.merge(centro, on="codigo_municipio", how="left")
    if zona_cliente is not None:
        z = (t.dropna(subset=["zona_mapa"]).groupby(["codigo_municipio", "zona_mapa"]).size().rename("n").reset_index()
             .sort_values(["codigo_municipio", "n"], ascending=[True, False]))
        tot = z.groupby("codigo_municipio")["n"].transform("sum")
        z["pct_zona"] = (z["n"] / tot * 100).round(1)
        dominante = z.drop_duplicates("codigo_municipio")[["codigo_municipio", "zona_mapa", "pct_zona"]].rename(columns={"zona_mapa": "zona_ebsa"})
        muni_tabla = muni_tabla.merge(dominante, on="codigo_municipio", how="left")
        ambiguos = int((muni_tabla["pct_zona"] < 80).sum())
        print(f"Zona por municipio: {muni_tabla['zona_ebsa'].notna().sum():,} municipios con zona; "
              f"{ambiguos} con menos del 80 % de sus clientes en una sola zona")
    else:
        muni_tabla["zona_ebsa"] = pd.NA
        muni_tabla["pct_zona"] = np.nan
    muni_tabla = muni_tabla.sort_values("clientes_tc1", ascending=False)

    # --- Guardar ---
    DIR_SALIDA.mkdir(parents=True, exist_ok=True)
    cols = ["NIU", "codigo_dane", "codigo_municipio", "municipio", "provincia", "departamento", "zona_mapa", "zona_nombre",
            "ubicacion_sui", "direccion", "estrato_sector", "nivel_tension", "circuito", "transformador",
            "latitud", "longitud", "altitud", "coordenadas_validas", "autogenerador_tc1", "archivo_tc1", "periodo_tc1"]
    t[cols].to_parquet(RUTA_UBICACION, index=False, engine="pyarrow")
    muni_tabla.to_csv(RUTA_MUNICIPIOS, index=False, encoding="utf-8-sig")
    pd.DataFrame([
        {"dato": "archivo_tc1", "valor": ruta_tc1.name}, {"dato": "periodo_tc1", "valor": periodo},
        {"dato": "filas_tc1", "valor": filas}, {"dato": "niu_unicos", "valor": len(t)}, {"dato": "duplicados_descartados", "valor": dup},
        {"dato": "codigos_municipio_distintos", "valor": int(t["codigo_municipio"].nunique())},
        {"dato": "clientes_sin_municipio_en_tabla_dane", "valor": sin_muni},
        {"dato": "clientes_fuera_de_boyaca", "valor": fuera_boyaca},
        {"dato": "coordenadas_validas", "valor": int(t["coordenadas_validas"].sum())},
        {"dato": "coordenadas_sin_dato", "valor": sin_coord}, {"dato": "coordenadas_fuera_de_rango", "valor": coord_malas},
        {"dato": "autogeneradores_segun_tc1", "valor": int(t["autogenerador_tc1"].sum())},
        {"dato": "clientes_tc1_en_serie_modelado", "valor": en_universo},
        {"dato": "clientes_serie_sin_tc1", "valor": universo_sin_tc1},
    ]).to_csv(RUTA_AUDITORIA, index=False, encoding="utf-8-sig")

    print("\nGuardado:")
    print(f"  {RUTA_UBICACION}")
    print(f"  {RUTA_MUNICIPIOS}")
    print(f"  {RUTA_AUDITORIA}")
    print("\nMUNICIPIOS CON MÁS CLIENTES")
    print(muni_tabla.head(12)[["codigo_municipio", "municipio", "provincia", "zona_ebsa", "clientes_tc1", "coordenadas_validas"]].to_string(index=False))


if __name__ == "__main__":
    main()
