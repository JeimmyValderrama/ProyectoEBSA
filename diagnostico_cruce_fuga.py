"""
diagnostico_cruce_fuga.py — ¿los clientes del archivo de OTROS COMERCIALIZADORES aparecen en la historia TC2?
Solo lee; no escribe nada.

Antes de correrlo:
  1. Crear la carpeta   C:\\Users\\Home\\Documents\\Datos_Ebsa\\00_otros_comercializadores
  2. Copiar allí        USUARIOS_OTROS_COMERCIALIZADORES.xlsx   (el archivo de la empresa, tal cual)

Correr desde Pipeline_Ebsa:
    python diagnostico_cruce_fuga.py
    python diagnostico_cruce_fuga.py --archivo "D:\\otra\\ruta\\USUARIOS_OTROS_COMERCIALIZADORES.xlsx"
"""
import argparse
import os
import re
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

BASE = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
PROC = BASE / "01_historico_procesado"
OTROS = BASE / "00_otros_comercializadores"


def normalizar_niu(s: pd.Series) -> pd.Series:
    """Deja solo dígitos y quita ceros a la izquierda, para comparar NIU escritos distinto."""
    s = s.astype("string").str.strip().str.replace(r"\D", "", regex=True).str.lstrip("0")
    return s.replace("", pd.NA)


def leer_otros(ruta: Path) -> pd.DataFrame:
    d = pd.read_excel(ruta, sheet_name=0)
    d.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in d.columns]
    d["periodo"] = pd.to_datetime(d["AÑO"].astype(int).astype(str) + "-" + d["MES"].astype(int).astype(str).str.zfill(2) + "-01")
    d["NIU_n"] = normalizar_niu(d["NIU"])
    d["CUENTA_n"] = normalizar_niu(d["CUENTA_USUARIO"]) if "CUENTA_USUARIO" in d.columns else pd.NA
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--archivo", default=None, help="ruta del xlsx de otros comercializadores (opcional)")
    args = ap.parse_args()

    if args.archivo:
        archivos = [Path(args.archivo)]
    else:
        archivos = sorted(OTROS.glob("*.xls*"))
    if not archivos:
        raise FileNotFoundError(f"No hay archivos .xlsx en {OTROS}. Crea la carpeta y copia allí USUARIOS_OTROS_COMERCIALIZADORES.xlsx")
    otros = pd.concat([leer_otros(a) for a in archivos], ignore_index=True)
    otros = otros.drop_duplicates(["NIU_n", "periodo"])

    print("=" * 78)
    print("ARCHIVO DE OTROS COMERCIALIZADORES")
    print("=" * 78)
    print(f"archivos: {[a.name for a in archivos]}")
    print(f"filas: {len(otros):,} | NIU: {otros['NIU_n'].nunique():,} | meses: {otros['periodo'].min():%Y-%m} -> {otros['periodo'].max():%Y-%m}")
    prim_otros = otros.groupby("NIU_n")["periodo"].min().rename("primer_mes_otro_comercializador")
    ult_otros = otros.groupby("NIU_n")["periodo"].max().rename("ultimo_mes_otro_comercializador")
    print("NIU por primer mes en que aparecen con otro comercializador:")
    print("   " + prim_otros.dt.strftime("%Y-%m").value_counts().sort_index().to_string().replace("\n", "\n   "))

    # ---------------- histórico TC2 ----------------
    cols = ["NIU", "periodo", "ciclo", "clase_servicio", "consumo_kwh_raw", "tarifa_aplicada_kwh", "estrato",
            "tipo_medidor", "tipo_lectura", "consumo_promedio_semestral_kwh"]
    partes = []
    for ruta in sorted(PROC.glob("historico_*.parquet")):
        disponibles = pd.read_parquet(ruta, engine="pyarrow").columns
        partes.append(pd.read_parquet(ruta, columns=[c for c in cols if c in disponibles], engine="pyarrow"))
    h = pd.concat(partes, ignore_index=True)
    h["NIU_n"] = normalizar_niu(h["NIU"])
    h["periodo"] = pd.to_datetime(h["periodo"], errors="coerce")
    h["ciclo"] = pd.to_numeric(h["ciclo"], errors="coerce")
    h["clase_servicio"] = h["clase_servicio"].astype("string").str.strip().str.upper()
    ultimo_tc2 = h["periodo"].max()
    print(f"\nHistórico TC2: {len(h):,} filas | {h['NIU_n'].nunique():,} NIU | {h['periodo'].min():%Y-%m} -> {ultimo_tc2:%Y-%m}")

    # ---------------- cruce ----------------
    nius_otros = set(prim_otros.index.dropna())
    nius_tc2 = set(h["NIU_n"].dropna().unique())
    en_tc2 = nius_otros & nius_tc2
    print("\n" + "=" * 78)
    print("CRUCE POR NIU")
    print("=" * 78)
    print(f"NIU de otros comercializadores que EXISTEN en la historia TC2: {len(en_tc2):,} de {len(nius_otros):,}")
    if "CUENTA_n" in otros.columns:
        cuentas = set(otros["CUENTA_n"].dropna().unique())
        print(f"(por CUENTA_USUARIO en vez de NIU: {len(cuentas & nius_tc2):,} coincidencias)")

    if not en_tc2:
        print("\nNingún NIU coincide: TC2 no los contiene ni antes ni después del cambio. "
              "Revisar si el NIU de TC2 tiene otro formato (mostrando muestra):")
        print("   TC2 :", h["NIU"].dropna().astype(str).head(5).tolist())
        print("   otros:", otros["NIU"].astype(str).head(5).tolist())
        return

    hh = h[h["NIU_n"].isin(en_tc2)].sort_values(["NIU_n", "periodo"])
    ult_tc2 = hh.groupby("NIU_n")["periodo"].max().rename("ultimo_mes_tc2")
    prim_tc2 = hh.groupby("NIU_n")["periodo"].min().rename("primer_mes_tc2")
    resumen = pd.concat([prim_tc2, ult_tc2, prim_otros, ult_otros], axis=1).loc[list(en_tc2)]
    resumen["meses_tc2_tras_cambio"] = (
        (resumen["ultimo_mes_tc2"].dt.year - resumen["primer_mes_otro_comercializador"].dt.year) * 12
        + (resumen["ultimo_mes_tc2"].dt.month - resumen["primer_mes_otro_comercializador"].dt.month)
    )
    sigue = resumen["ultimo_mes_tc2"] >= ultimo_tc2
    print(f"\nDe esos {len(resumen):,} NIU:")
    print(f"  • siguen apareciendo en TC2 hasta el último mes ({ultimo_tc2:%Y-%m}): {sigue.sum():,}")
    print(f"  • dejaron de aparecer en TC2 antes del último mes:                {(~sigue).sum():,}")
    print("\nÚltimo mes en TC2 (los que dejaron de aparecer):")
    print("   " + resumen.loc[~sigue, "ultimo_mes_tc2"].dt.strftime("%Y-%m").value_counts().sort_index().to_string().replace("\n", "\n   "))
    print("\nMeses entre el primer mes con otro comercializador y el último mes en TC2 "
          "(negativo = desapareció de TC2 ANTES de aparecer en el archivo de otros):")
    print("   " + resumen["meses_tc2_tras_cambio"].clip(-30, 30).value_counts().sort_index().to_string().replace("\n", "\n   "))

    # Perfil en TC2 (última fila de cada NIU)
    ultima = hh.groupby("NIU_n").last()
    print("\nPerfil en TC2 (última fila de cada NIU):")
    print("  ciclo:", ultima["ciclo"].value_counts().head(10).to_dict())
    print("  clase:", ultima["clase_servicio"].value_counts().head(10).to_dict())
    if "estrato" in ultima:
        print("  estrato:", ultima["estrato"].value_counts().head(8).to_dict())
    # ¿la clase/ciclo cambia después del cambio de comercializador? (p. ej. a IR / 33 / 97)
    hh2 = hh.merge(prim_otros, left_on="NIU_n", right_index=True)
    despues = hh2[hh2["periodo"] >= hh2["primer_mes_otro_comercializador"]]
    antes = hh2[hh2["periodo"] < hh2["primer_mes_otro_comercializador"]]
    if len(despues):
        print("\nFilas TC2 DESPUÉS del cambio: ciclo", despues["ciclo"].value_counts().head(8).to_dict(),
              "| clase", despues["clase_servicio"].value_counts().head(8).to_dict())
        print("   consumo mediano por fila después del cambio:", round(despues["consumo_kwh_raw"].median(), 1), "kWh")
    if len(antes):
        print("Filas TC2 ANTES del cambio: ciclo", antes["ciclo"].value_counts().head(8).to_dict(),
              "| clase", antes["clase_servicio"].value_counts().head(8).to_dict())
        print("   consumo mediano por fila antes del cambio:", round(antes["consumo_kwh_raw"].median(), 1), "kWh")

    # Consumo promedio de los últimos 6 meses en TC2 por NIU
    ult6 = hh[hh["periodo"] > (hh.groupby("NIU_n")["periodo"].transform("max") - pd.DateOffset(months=6))]
    prom6 = ult6.groupby("NIU_n")["consumo_kwh_raw"].mean()
    print("\nConsumo promedio mensual en TC2 (últimos 6 meses de cada NIU):")
    print("   " + pd.cut(prom6, [-1, 0, 500, 5000, 50000, 1e12],
                         labels=["0", "<500", "500-5.000", "5.000-50.000", ">50.000"]).value_counts().sort_index().to_string().replace("\n", "\n   "))

    # Detalle de los que entraron al archivo de otros DESPUÉS de su primer mes (los "cambios" observables)
    primer_mes_archivo = otros["periodo"].min()
    tardios = resumen[resumen["primer_mes_otro_comercializador"] > primer_mes_archivo].copy()
    print(f"\nNIU que aparecen con otro comercializador DESPUÉS de {primer_mes_archivo:%Y-%m} y existen en TC2: {len(tardios):,}")
    if len(tardios):
        det = tardios.join(ultima[["ciclo", "clase_servicio"]]).join(prom6.rename("consumo_prom_6m_tc2"))
        det = det.join(otros.drop_duplicates("NIU_n").set_index("NIU_n")[["COMERCIALIZADOR", "MUNICIPIO"]])
        for c in ["primer_mes_tc2", "ultimo_mes_tc2", "primer_mes_otro_comercializador", "ultimo_mes_otro_comercializador"]:
            det[c] = det[c].dt.strftime("%Y-%m")
        print(det.sort_values("primer_mes_otro_comercializador").to_string())

    # Los que dejaron de aparecer en TC2 (>=4 meses) que NO están en el archivo de otros: salidas por otras causas
    ult_por_niu = h.groupby("NIU_n")["periodo"].max()
    ausente = (ultimo_tc2.year - ult_por_niu.dt.year) * 12 + (ultimo_tc2.month - ult_por_niu.dt.month)
    idos = set(ausente[ausente >= 4].index)
    print(f"\nNIU que dejaron de aparecer en TC2 (>=4 meses): {len(idos):,} | de ellos en el archivo de otros: {len(idos & nius_otros):,}")


if __name__ == "__main__":
    main()
