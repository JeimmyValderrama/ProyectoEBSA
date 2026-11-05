"""Backtest del pronóstico frente a pronósticos ingenuos, por zona y por cliente.

Qué responde (revisión del 2026-10-08):
  1. ¿Cuánto aporta el modelo frente a un ingenuo de verdad? La línea base del notebook 8 es el mismo
     mes del año anterior. A uno o dos meses, el ingenuo natural es repetir el consumo reciente
     (persistencia) o la media de los últimos 3 o 12 meses. Aquí se miden todos sobre el mismo
     backtest ya guardado, sin reentrenar nada.
  2. ¿El error es el mismo en urbanos y rurales? Los meses rurales son lecturas trimestrales
     repartidas entre los meses que cubren, así que el consumo "del corte" de un rural puede venir de
     una lectura que cerró después del corte. Por eso el backtest rural a 1-2 meses es optimista y se
     reporta aparte.
  3. ¿Cuánto se equivoca el cliente típico? El WAPE pondera por energía (lo dominan los grandes);
     aquí se añade el error relativo por cliente (mediana, percentil 90, % de clientes con error < 20 %).

Solo lee:  04_pronostico/modelo_final/real_vs_pronosticado_sistema_optimizado_backtest.parquet
           03_serie_modelado/serie_mensual_modelado_preprocesada.parquet
Escribe:   04_pronostico/modelo_final/comparacion_ingenuos_backtest.csv
           04_pronostico/modelo_final/error_por_cliente_backtest.csv

Uso:  python evaluar_ingenuos_backtest.py            (carpeta de datos de siempre o EBSA_DATOS)
      python evaluar_ingenuos_backtest.py --datos "D:\\otra\\Datos_Ebsa"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:  # la consola de Windows (cp1252) no representa algunos símbolos
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DATOS_POR_DEFECTO = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))


def wape(real: pd.Series, pred: pd.Series) -> float:
    total = float(real.sum())
    return float((real - pred).abs().sum() / total * 100) if total > 0 else np.nan


def sesgo(real: pd.Series, pred: pd.Series) -> float:
    total = float(real.sum())
    return float((pred.sum() - total) / total * 100) if total > 0 else np.nan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--datos", default=str(DATOS_POR_DEFECTO), help="Carpeta de datos (por defecto EBSA_DATOS o Documentos\\Datos_Ebsa)")
    args = ap.parse_args()
    base = Path(args.datos)
    dir_modelo = base / "04_pronostico" / "modelo_final"
    ruta_bt = dir_modelo / "real_vs_pronosticado_sistema_optimizado_backtest.parquet"
    ruta_serie = base / "03_serie_modelado" / "serie_mensual_modelado_preprocesada.parquet"
    for r in (ruta_bt, ruta_serie):
        if not r.exists():
            print(f"No existe {r}. Corre primero el pipeline en modo reentrenar (paso 8).")
            return 1

    bt = pd.read_parquet(ruta_bt, engine="pyarrow",
                         columns=["NIU", "fecha_corte", "horizonte", "fecha_target", "perfil", "regimen_actual",
                                  "real_kwh", "pred_ml_kwh", "baseline_kwh", "pred_final_kwh"])
    bt["NIU"] = bt["NIU"].astype("string").str.strip()
    bt["fecha_corte"] = pd.to_datetime(bt["fecha_corte"])
    cortes = sorted(bt["fecha_corte"].unique())
    if len(cortes) != 1:
        print(f"Se esperaba un solo corte de backtest y hay {len(cortes)}: {cortes}")
        return 1
    corte = pd.Timestamp(cortes[0])
    print(f"Backtest con corte {corte:%Y-%m}: {len(bt):,} pares cliente x horizonte, {bt['NIU'].nunique():,} clientes")

    # Consumo de los 12 meses que terminan en el corte, solo de los clientes del backtest
    desde = (corte.to_period("M") - 11).to_timestamp()
    serie = pd.read_parquet(ruta_serie, engine="pyarrow", columns=["NIU", "periodo", "consumo_kwh_mensual", "es_rural"],
                            filters=[("periodo", ">=", desde), ("periodo", "<=", corte)])
    serie["NIU"] = serie["NIU"].astype("string").str.strip()
    serie["periodo"] = pd.to_datetime(serie["periodo"])
    serie = serie[serie["NIU"].isin(set(bt["NIU"]))]
    ult3 = (corte.to_period("M") - 2).to_timestamp()
    por_niu = pd.DataFrame({
        "persistencia_kwh": serie[serie["periodo"].eq(corte)].groupby("NIU")["consumo_kwh_mensual"].first(),
        "media_3m_kwh": serie[serie["periodo"] >= ult3].groupby("NIU")["consumo_kwh_mensual"].mean(),
        "media_12m_kwh": serie.groupby("NIU")["consumo_kwh_mensual"].mean(),
        "es_rural": serie.groupby("NIU")["es_rural"].last(),
    })
    del serie
    bt = bt.merge(por_niu, left_on="NIU", right_index=True, how="left")
    bt["zona"] = np.where(bt["es_rural"].fillna(False).astype(bool), "RURAL", "URBANO")
    # un ingenuo sin dato (cliente sin fila en la ventana) cae en la media de 12 meses y, si tampoco, en la línea base
    for c in ("persistencia_kwh", "media_3m_kwh"):
        bt[c] = bt[c].fillna(bt["media_12m_kwh"])
    for c in ("persistencia_kwh", "media_3m_kwh", "media_12m_kwh"):
        bt[c] = bt[c].fillna(bt["baseline_kwh"]).clip(lower=0)
    bt["cero_kwh"] = 0.0

    candidatos = {
        "modelo_final": "pred_final_kwh", "modelo_solo_ml": "pred_ml_kwh",
        "ingenuo_mismo_mes_anio_anterior": "baseline_kwh", "ingenuo_persistencia": "persistencia_kwh",
        "ingenuo_media_3m": "media_3m_kwh", "ingenuo_media_12m": "media_12m_kwh", "ingenuo_cero": "cero_kwh",
    }
    ingenuos = [k for k in candidatos if k.startswith("ingenuo_")]

    filas = []
    vistas = [("TODOS", "TODOS")] + [("zona", z) for z in ("URBANO", "RURAL")]
    for nombre_vista, valor in vistas:
        sub_v = bt if nombre_vista == "TODOS" else bt[bt["zona"].eq(valor)]
        for perfil in ["TODOS"] + sorted(sub_v["perfil"].dropna().unique()):
            sub_p = sub_v if perfil == "TODOS" else sub_v[sub_v["perfil"].eq(perfil)]
            for h, g in sub_p.groupby("horizonte"):
                fila = {"zona": valor, "perfil": perfil, "horizonte": int(h), "n_clientes": int(len(g)),
                        "real_total_kwh": float(g["real_kwh"].sum())}
                for nombre, col in candidatos.items():
                    fila[f"WAPE_{nombre}_pct"] = wape(g["real_kwh"], g[col])
                fila["sesgo_modelo_final_pct"] = sesgo(g["real_kwh"], g["pred_final_kwh"])
                w_ing = {k: fila[f"WAPE_{k}_pct"] for k in ingenuos if pd.notna(fila[f"WAPE_{k}_pct"])}
                if w_ing:
                    mejor = min(w_ing, key=w_ing.get)
                    fila["mejor_ingenuo"] = mejor.replace("ingenuo_", "")
                    fila["WAPE_mejor_ingenuo_pct"] = w_ing[mejor]
                    fila["mejora_vs_mejor_ingenuo_pp"] = w_ing[mejor] - fila["WAPE_modelo_final_pct"]
                    # skill: 1 = perfecto, 0 = igual que el mejor ingenuo, negativo = peor que el ingenuo
                    fila["skill_vs_mejor_ingenuo"] = 1 - fila["WAPE_modelo_final_pct"] / w_ing[mejor] if w_ing[mejor] > 0 else np.nan
                filas.append(fila)
    comp = pd.DataFrame(filas)
    ruta_comp = dir_modelo / "comparacion_ingenuos_backtest.csv"
    comp.round(3).to_csv(ruta_comp, index=False, encoding="utf-8-sig")

    # Error por cliente (solo clientes con consumo real > 0 en el mes objetivo: el error relativo no existe en 0)
    pos = bt[bt["real_kwh"] > 0].copy()
    pos["error_rel_pct"] = (pos["pred_final_kwh"] - pos["real_kwh"]).abs() / pos["real_kwh"] * 100
    filas_c = []
    for (zona_v, perfil), sub in [(("TODOS", "TODOS"), pos)] + \
            [((z, "TODOS"), g) for z, g in pos.groupby("zona")] + \
            [(("TODOS", p), g) for p, g in pos.groupby("perfil")]:
        for h, g in sub.groupby("horizonte"):
            e = g["error_rel_pct"]
            filas_c.append({"zona": zona_v, "perfil": perfil, "horizonte": int(h), "n_clientes_con_consumo": int(len(g)),
                            "error_relativo_mediana_pct": float(e.median()), "error_relativo_p90_pct": float(e.quantile(0.90)),
                            "pct_clientes_error_menor_20": float((e < 20).mean() * 100),
                            "pct_clientes_error_menor_50": float((e < 50).mean() * 100)})
    por_cliente = pd.DataFrame(filas_c)
    ruta_cli = dir_modelo / "error_por_cliente_backtest.csv"
    por_cliente.round(2).to_csv(ruta_cli, index=False, encoding="utf-8-sig")

    pd.set_option("display.width", 220)
    cols = ["zona", "horizonte", "n_clientes", "WAPE_modelo_final_pct", "WAPE_ingenuo_mismo_mes_anio_anterior_pct",
            "WAPE_ingenuo_persistencia_pct", "WAPE_ingenuo_media_3m_pct", "WAPE_ingenuo_media_12m_pct",
            "mejor_ingenuo", "mejora_vs_mejor_ingenuo_pp"]
    print("\nMODELO vs. INGENUOS (todos los perfiles), WAPE %")
    print("=" * 110)
    print(comp[comp["perfil"].eq("TODOS")][cols].round(1).to_string(index=False))
    peores = comp[(comp["perfil"] != "TODOS") & (comp["zona"].eq("TODOS")) & (comp["mejora_vs_mejor_ingenuo_pp"] <= 0)]
    print("\nCeldas perfil x horizonte donde el modelo NO supera al mejor ingenuo:",
          "ninguna" if peores.empty else "")
    if not peores.empty:
        print(peores[["perfil", "horizonte", "WAPE_modelo_final_pct", "mejor_ingenuo", "WAPE_mejor_ingenuo_pct"]].round(1).to_string(index=False))
    print("\nERROR POR CLIENTE (clientes con consumo real > 0)")
    print("=" * 110)
    print(por_cliente[por_cliente["perfil"].eq("TODOS")].round(1).to_string(index=False))
    print("\nCÓMO LEERLO")
    print("  mejora_vs_mejor_ingenuo_pp: puntos de WAPE que el modelo le gana al mejor ingenuo de esa fila (negativo = pierde).")
    print("  RURAL a 1-2 meses es optimista: el consumo del corte sale de lecturas trimestrales repartidas que pueden")
    print("  cerrar después del corte. La cifra que vale para rurales es la del seguimiento en vivo (notebook 12).")
    print("\nGuardado:")
    print(" *", ruta_comp)
    print(" *", ruta_cli)
    return 0


if __name__ == "__main__":
    sys.exit(main())
