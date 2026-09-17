"""
comparar_modelos.py — ¿se deterioró el modelo? ¿mejoró al reentrenar?
======================================================================
Solo lee. Se corre después de simular_meses.py (o después de varios meses reales):

    python comparar_modelos.py
    python comparar_modelos.py --datos "C:\\...\\Datos_Ebsa_simulacion"

Arma tres vistas a partir del seguimiento en vivo (paso 12) y del registro de versiones:

  1. Línea de tiempo: WAPE en vivo por corte (horizonte 1 y 3), con la versión del
     modelo que hizo cada pronóstico. Un modelo que se deteriora sube con el tiempo;
     al reentrenar, la serie vuelve a bajar.
  2. Curva de envejecimiento: WAPE en vivo según los meses transcurridos desde que se
     entrenó el modelo (todas las versiones juntas). Dice cada cuánto conviene reentrenar.
  3. Cabeza a cabeza (si simular_meses.py corrió con --comparar-version): la versión
     vieja y la nueva pronosticando los MISMOS cortes y los MISMOS meses objetivo.

Salidas en <datos>\\09_registro_corridas\\simulacion\\:
  comparacion_modelos.csv, comparacion_cabeza_a_cabeza.csv, comparacion_modelos.png
"""
import argparse
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

# Windows: si la salida va a un archivo o a otro proceso (simular_meses.py), Python usa
# cp1252 y no puede escribir "✓" / "✗". Se fuerza UTF-8 en la salida de este script.
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def wape(real, pred):
    real = np.asarray(real, dtype="float64"); pred = np.asarray(pred, dtype="float64")
    m = np.isfinite(real) & np.isfinite(pred)
    t = np.abs(real[m]).sum()
    return float(np.abs(real[m] - pred[m]).sum() / t * 100) if t > 0 else np.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", default=os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
    args = ap.parse_args()
    datos = Path(args.datos)
    salida = datos / "09_registro_corridas" / "simulacion"
    salida.mkdir(parents=True, exist_ok=True)

    seg = datos / "08_seguimiento" / "seguimiento_pronostico_global.csv"
    if not seg.exists() or len(pd.read_csv(seg)) == 0:
        print("No hay seguimiento en vivo todavía (08_seguimiento). Corre el pipeline con al menos dos cortes.")
        return 1
    g = pd.read_csv(seg, encoding="utf-8-sig")
    if "fecha_corte_modelo" not in g.columns:
        print("El seguimiento no trae la versión del modelo: corre de nuevo el paso 12 con la versión actual del notebook.")
        return 1
    g["fecha_corte"] = g["fecha_corte"].astype(str)
    g["fecha_corte_modelo"] = g["fecha_corte_modelo"].astype(str)

    # ---------------- 1. línea de tiempo
    print("1. WAPE EN VIVO POR CORTE (global), con la versión del modelo que pronosticó")
    print("-" * 78)
    piv = g.pivot_table(index=["fecha_corte", "fecha_corte_modelo", "meses_desde_entrenamiento"],
                        columns="horizonte", values="WAPE_pct").round(1)
    piv.columns = [f"WAPE_h{int(c)}" for c in piv.columns]
    print(piv.to_string())
    piv.reset_index().to_csv(salida / "comparacion_modelos.csv", index=False, encoding="utf-8-sig")

    # ---------------- 2. envejecimiento
    print("\n2. ENVEJECIMIENTO: WAPE en vivo según meses desde el entrenamiento (todas las versiones)")
    print("-" * 78)
    def wape_ponderado(d):
        # WAPE de varios cortes juntos = ponderado por el consumo real de cada corte
        return pd.Series({"WAPE_pct": float((d["WAPE_pct"] * d["real_total_kwh"]).sum() / d["real_total_kwh"].sum()),
                          "n_cortes": len(d)})
    env = (g.groupby(["meses_desde_entrenamiento", "horizonte"]).apply(wape_ponderado, include_groups=False).reset_index())
    piv2 = env.pivot(index="meses_desde_entrenamiento", columns="horizonte", values="WAPE_pct").round(1)
    piv2.columns = [f"WAPE_h{int(c)}" for c in piv2.columns]
    piv2["n_cortes"] = env.groupby("meses_desde_entrenamiento")["n_cortes"].max()
    print(piv2.to_string())
    if len(piv2) >= 3 and "WAPE_h1" in piv2.columns:
        primero, ultimo = piv2["WAPE_h1"].iloc[0], piv2["WAPE_h1"].iloc[-1]
        print(f"\n   Lectura: a horizonte 1, el WAPE pasa de {primero:.1f}% (recién entrenado) a {ultimo:.1f}% "
              f"({int(piv2.index[-1])} meses después). "
              + ("Subida clara: conviene reentrenar antes de ese plazo." if ultimo - primero > 5 else
                 "Sin deterioro apreciable en ese plazo."))

    # ---------------- 3. cabeza a cabeza
    cmp_dir = datos / "04_pronostico" / "modelo_final" / "historial_pronosticos" / "comparacion"
    hist = datos / "04_pronostico" / "modelo_final" / "historial_pronosticos"
    filas_cc = []
    if cmp_dir.exists() and any(cmp_dir.glob("*.parquet")):
        print("\n3. CABEZA A CABEZA: versión vieja y nueva sobre los mismos cortes y meses objetivo")
        print("-" * 78)
        serie = pd.read_parquet(datos / "03_serie_modelado" / "serie_mensual_modelado_preprocesada.parquet",
                                columns=["NIU", "periodo", "consumo_kwh_mensual"] + (["estado_mes"] if "estado_mes" in
                                pd.read_parquet(datos / "03_serie_modelado" / "serie_mensual_modelado_preprocesada.parquet").columns else []))
        serie["NIU"] = serie["NIU"].astype("string").str.strip()
        serie["periodo"] = pd.to_datetime(serie["periodo"])
        if "estado_mes" in serie.columns:
            serie = serie[serie["estado_mes"].eq("CONSOLIDADO")]
        real = serie.set_index(["NIU", "periodo"])["consumo_kwh_mensual"]

        def evaluar(ruta, etiqueta_version):
            p = pd.read_parquet(ruta)
            p["NIU"] = p["NIU"].astype("string").str.strip()
            out = []
            for h in range(1, 7):
                fc = pd.to_datetime(p[f"fecha_pred_{h}m"])
                idx = pd.MultiIndex.from_arrays([p["NIU"], fc])
                r = real.reindex(idx).to_numpy()
                m = np.isfinite(r)
                if m.sum() == 0:
                    continue
                out.append({"horizonte": h, "version_modelo": etiqueta_version, "n": int(m.sum()),
                            "WAPE_pct": round(wape(r[m], p[f"pred_{h}m_kwh"].to_numpy()[m]), 2)})
            return out

        for ruta in sorted(cmp_dir.glob("predicciones_6_meses_corte_*_modelo*.parquet")):
            m = re.match(r"predicciones_6_meses_corte_(\d{4}-\d{2})_modelo(\d{4}-\d{2})\.parquet", ruta.name)
            if not m:
                continue
            corte, version_vieja = m.group(1), m.group(2)
            principal = hist / f"predicciones_6_meses_corte_{corte}.parquet"
            if not principal.exists():
                continue
            nueva = str(pd.read_parquet(principal, columns=["fecha_corte_modelo"])["fecha_corte_modelo"].iloc[0])[:7]
            for fila in evaluar(ruta, f"vieja {version_vieja}") + evaluar(principal, f"nueva {nueva}"):
                fila["fecha_corte"] = corte
                filas_cc.append(fila)
        if filas_cc:
            cc = pd.DataFrame(filas_cc)
            tabla = cc.pivot_table(index=["fecha_corte", "horizonte"], columns="version_modelo", values="WAPE_pct")
            cols = list(tabla.columns)
            if len(cols) == 2:
                vieja = [c for c in cols if c.startswith("vieja")][0]; nueva = [c for c in cols if c.startswith("nueva")][0]
                tabla["mejora_pp"] = (tabla[vieja] - tabla[nueva]).round(2)
            print(tabla.round(2).to_string())
            tabla.reset_index().to_csv(salida / "comparacion_cabeza_a_cabeza.csv", index=False, encoding="utf-8-sig")
            if "mejora_pp" in tabla.columns:
                med = tabla["mejora_pp"].mean()
                print(f"\n   Lectura: en promedio el modelo nuevo tiene {abs(med):.1f} puntos de WAPE "
                      + ("MENOS" if med > 0 else "MÁS") + " que el viejo sobre los mismos meses"
                      + (" -> reentrenar valió la pena." if med > 1 else " -> diferencia pequeña; el modelo viejo aguantaba." if med > -1 else " -> el viejo era mejor: revisar el reentrenamiento."))
        else:
            print("   (no hay pares comparables todavía: faltan meses reales posteriores a los cortes comparados)")
    else:
        print("\n3. Cabeza a cabeza: no hay pronósticos de comparación (simular_meses.py --comparar-version).")

    # ---------------- gráfica
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))
        ax = axes[0]
        for version, d in g[g["horizonte"].eq(1)].groupby("fecha_corte_modelo"):
            d = d.sort_values("fecha_corte")
            ax.plot(d["fecha_corte"], d["WAPE_pct"], marker="o", label=f"modelo {version}")
        ax.set_title("WAPE en vivo, horizonte 1 mes, por corte"); ax.set_ylabel("WAPE %"); ax.tick_params(axis="x", rotation=45); ax.legend(); ax.grid(alpha=.3)
        ax = axes[1]
        for h in [1, 3, 6]:
            if f"WAPE_h{h}" in piv2.columns:
                ax.plot(piv2.index, piv2[f"WAPE_h{h}"], marker="o", label=f"horizonte {h}")
        ax.set_title("Envejecimiento: WAPE según meses desde el entrenamiento"); ax.set_xlabel("meses desde el entrenamiento"); ax.legend(); ax.grid(alpha=.3)
        plt.tight_layout()
        fig.savefig(salida / "comparacion_modelos.png", dpi=130)
        print("\nGráfica:", salida / "comparacion_modelos.png")
    except Exception as e:  # noqa: BLE001
        print("(sin gráfica:", e, ")")
    print("Tablas:", salida / "comparacion_modelos.csv", "|", salida / "comparacion_cabeza_a_cabeza.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
