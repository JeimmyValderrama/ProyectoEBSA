"""
diagnostico_fuga.py — ¿cómo se ven en los datos los clientes que se fueron a otro comercializador?
Solo lee; no escribe nada. Correr desde Pipeline_Ebsa:  python diagnostico_fuga.py
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

BASE = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
PROC = BASE / "01_historico_procesado"

cols = ["NIU", "periodo", "ciclo", "clase_servicio", "consumo_kwh_raw", "tipo_factura"]
partes = []
for ruta in sorted(PROC.glob("historico_*.parquet")):
    disponibles = pd.read_parquet(ruta, engine="pyarrow").columns
    partes.append(pd.read_parquet(ruta, columns=[c for c in cols if c in disponibles], engine="pyarrow"))
h = pd.concat(partes, ignore_index=True)
h["NIU"] = h["NIU"].astype("string").str.strip()
h["periodo"] = pd.to_datetime(h["periodo"], errors="coerce")
h["ciclo"] = pd.to_numeric(h["ciclo"], errors="coerce")
h["clase_servicio"] = h["clase_servicio"].astype("string").str.strip().str.upper()
ultimo = h["periodo"].max()
print(f"Histórico: {len(h):,} filas | {h['NIU'].nunique():,} NIU | hasta {ultimo:%Y-%m}\n")

# 1. Ciclo 97 (OTROS COMERCIALIZADORES) y clase IR (NO REGULADO): ¿existen filas?
for etiqueta, mask in [("ciclo 97 OTROS COMERCIALIZADORES", h["ciclo"].eq(97)),
                       ("ciclo 33 USUARIOS NO REGULADOS", h["ciclo"].eq(33)),
                       ("clase IR NO REGULADO", h["clase_servicio"].eq("IR"))]:
    sub = h[mask]
    print(f"[{etiqueta}] filas: {len(sub):,} | NIU: {sub['NIU'].nunique():,}")
    if len(sub):
        por_mes = sub.groupby(sub["periodo"].dt.to_period("M"))["NIU"].nunique()
        print("   NIU por mes (primeros y últimos):")
        print("   " + por_mes.head(6).to_string().replace("\n", "\n   "))
        print("   ...")
        print("   " + por_mes.tail(6).to_string().replace("\n", "\n   "))
        # ¿esos NIU tuvieron antes otro ciclo / otra clase? (= se cambiaron)
        nius = sub["NIU"].unique()
        antes = h[h["NIU"].isin(nius) & ~mask]
        print(f"   de esos NIU, {antes['NIU'].nunique():,} tienen filas en OTRO ciclo/clase (historia antes del cambio)")
        if len(antes):
            print("   ciclos previos más comunes:", antes["ciclo"].value_counts().head(8).to_dict())
            print("   clases previas más comunes:", antes["clase_servicio"].value_counts().head(8).to_dict())
    print()

# 2. Clientes que DEJAN de aparecer antes del último mes (posible retiro o cambio de comercializador)
ult_por_niu = h.groupby("NIU")["periodo"].max()
n_meses_ausente = ((ultimo.year - ult_por_niu.dt.year) * 12 + (ultimo.month - ult_por_niu.dt.month))
print("[Clientes que dejan de aparecer] meses desde su última fila hasta el último mes del archivo:")
print(n_meses_ausente.value_counts().sort_index().head(15).to_string())
print(f"   NIU con última fila hace >= 4 meses (ya no están en el archivo): {(n_meses_ausente >= 4).sum():,}")
ultima_clase = h.sort_values("periodo").groupby("NIU")["clase_servicio"].last()
ultimo_ciclo = h.sort_values("periodo").groupby("NIU")["ciclo"].last()
idos = n_meses_ausente[n_meses_ausente >= 4].index
print("   clase de servicio de los que dejaron de aparecer:", ultima_clase.reindex(idos).value_counts().head(8).to_dict())
print("   ciclo de los que dejaron de aparecer:", ultimo_ciclo.reindex(idos).value_counts().head(10).to_dict())

# 3. Cambios de ciclo dentro de la historia de un mismo NIU
cambios = h.sort_values("periodo").groupby("NIU")["ciclo"].nunique()
print(f"\n[Cambios de ciclo] NIU con más de un ciclo en su historia: {(cambios > 1).sum():,}")
if (cambios > 1).any():
    nius_c = cambios[cambios > 1].index[:200000]
    hh = h[h["NIU"].isin(nius_c)].sort_values(["NIU", "periodo"])
    hh["ciclo_prev"] = hh.groupby("NIU")["ciclo"].shift()
    trans = hh[hh["ciclo"].ne(hh["ciclo_prev"]) & hh["ciclo_prev"].notna()]
    print("   transiciones más comunes (ciclo_prev -> ciclo):")
    print("   " + trans.groupby(["ciclo_prev", "ciclo"]).size().sort_values(ascending=False).head(12).to_string().replace("\n", "\n   "))
