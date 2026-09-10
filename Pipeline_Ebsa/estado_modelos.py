"""
estado_modelos.py — ¿toca reentrenar? Un veredicto por modelo, sin correr nada
==============================================================================
Solo lee las salidas que ya dejó la última corrida. Correr desde Pipeline_Ebsa:

    python estado_modelos.py

Para cada modelo dice cuándo se entrenó, con qué corte va la corrida actual, qué
dice el seguimiento en vivo, y termina con una recomendación:
  MANTENER    : nada indica que el modelo se haya degradado.
  REVISAR     : hay una señal, pero no concluyente (un mes malo, pocos datos).
  REENTRENAR  : hay una razón clara; el comando exacto sale al final.

Reglas (las mismas que usan los notebooks para avisar):
  Pronóstico   : > 6 meses sin reentrenar; o WAPE en vivo por encima del backtest
                 (dif_vs_backtest_pp > 5) en la mayoría de los horizontes durante 2+ cortes.
  Agrupamiento : > 6 meses sin reentrenar (los segmentos se mantienen estables a propósito).
  Caída        : algún segmento cambiaría de criterio, o umbrales que se movieron > 10 puntos
                 (deriva_criterios_caida.csv, que se recalcula cada mes en modo aplicar).
  Riesgo de fuga: > 6 meses sin reentrenar; o el archivo de otros comercializadores trae más
                 casos que los que vio el modelo; o los señalados ALTO no se van más que la tasa base.
"""
import os
import re
from pathlib import Path

import joblib
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
MESES_MAX = 6
veredictos = {}


def meses_entre(a, b):
    a, b = pd.Timestamp(a), pd.Timestamp(b)
    return (b.year - a.year) * 12 + (b.month - a.month)


def titulo(t):
    print("\n" + t)
    print("-" * 78)


# ----------------------------------------------------------------- corte actual
cortes = BASE / "03_serie_modelado" / "cortes_por_zona.csv"
if cortes.exists():
    t = pd.read_csv(cortes)
    CORTE = {str(z): pd.Timestamp(f) for z, f in zip(t["zona"], t["fecha_corte"])}
    corte_actual = CORTE["URBANO"]
    print(f"Corrida actual: corte urbano {CORTE['URBANO']:%Y-%m} | corte rural {CORTE['RURAL']:%Y-%m}")
else:
    corte_actual = None
    print("⚠ No hay cortes_por_zona.csv: corre el pipeline al menos hasta el paso 3.")

# ----------------------------------------------------------------- 1. pronóstico
titulo("1. PRONÓSTICO A 6 MESES (notebook 8)")
ruta = BASE / "04_pronostico" / "modelo_final" / "modelos_ganadores_optimizados_final.joblib"
razones = []
if ruta.exists():
    b = joblib.load(ruta)
    corte_modelo = pd.Timestamp(b["fecha_corte"])
    edad = meses_entre(corte_modelo, corte_actual) if corte_actual is not None else None
    print(f"  Entrenado con corte {corte_modelo:%Y-%m}" + (f" -> {edad} mes(es) de antigüedad" if edad is not None else ""))
    if edad is not None and edad > MESES_MAX:
        razones.append(f"lleva {edad} meses sin reentrenar (tope {MESES_MAX})")
    seg = BASE / "08_seguimiento" / "seguimiento_pronostico_por_perfil.csv"
    if seg.exists() and len(pd.read_csv(seg)):
        s = pd.read_csv(seg)
        s["fecha_corte"] = s["fecha_corte"].astype(str)
        por_corte = (s.groupby("fecha_corte")
                     .agg(horizontes=("horizonte", "nunique"),
                          malos=("dif_vs_backtest_pp", lambda x: int((x > 5).sum())),
                          filas=("dif_vs_backtest_pp", "size"),
                          wape_vivo=("WAPE_pct", "mean"), wape_backtest=("WAPE_backtest_pct", "mean")))
        por_corte["pct_malos"] = (por_corte["malos"] / por_corte["filas"] * 100).round(0)
        print("  Seguimiento en vivo (WAPE por perfil x horizonte, contra el backtest):")
        print("  " + por_corte.round(1).to_string().replace("\n", "\n  "))
        cortes_malos = por_corte[por_corte["pct_malos"] > 50]
        if len(cortes_malos) >= 2:
            razones.append(f"el error en vivo supera al backtest en más de la mitad de los casos en {len(cortes_malos)} cortes "
                           f"({', '.join(cortes_malos.index)})")
        elif len(cortes_malos) == 1:
            print(f"  ⚠ un corte con error en vivo alto ({cortes_malos.index[0]}): esperar un mes más antes de decidir")
    else:
        print("  Seguimiento en vivo: todavía sin meses consolidados posteriores a un pronóstico guardado.")
    veredictos["Pronóstico"] = ("REENTRENAR", razones) if razones else ("MANTENER", ["sin señales de degradación"])
else:
    print("  No hay modelo guardado.")
    veredictos["Pronóstico"] = ("REENTRENAR", ["no existe modelos_ganadores_optimizados_final.joblib"])

# ----------------------------------------------------------------- 2. agrupamiento
titulo("2. AGRUPAMIENTO (notebook 9)")
ruta = BASE / "05_segmentos_clientes" / "modelo_agrupamiento.joblib"
razones = []
if ruta.exists():
    a = joblib.load(ruta)
    fin = pd.Timestamp(a["ventana"].get("corte_urbano", a["ventana"]["fin"]))
    edad = meses_entre(fin, corte_actual) if corte_actual is not None else None
    print(f"  Entrenado con ventana hasta {fin:%Y-%m} (el {str(a.get('fecha_entrenamiento', ''))[:10]})"
          + (f" -> {edad} mes(es)" if edad is not None else ""))
    for zona, d in a.get("subpoblaciones", {}).items():
        print(f"  {zona}: {d.get('algoritmo')} sobre {d.get('n_entrenamiento', 0):,} clientes, "
              f"segmentos {sorted(set(d.get('mapa_segmentos', {}).values()))}")
    if edad is not None and edad > MESES_MAX:
        razones.append(f"lleva {edad} meses con los mismos segmentos (tope {MESES_MAX})")
    # aviso del notebook 9 en la última corrida (perfil del cluster ya no corresponde al nombre)
    reg = sorted((BASE / "09_registro_corridas").glob("*/09_Agrupamiento_clientes_consumo.ipynb"))
    if reg:
        import json
        nb = json.load(open(reg[-1], encoding="utf-8"))
        salidas = "".join(
            "".join(o.get("text", "")) if isinstance(o.get("text", ""), list) else str(o.get("text", ""))
            for c in nb.get("cells", []) if c.get("cell_type") == "code"
            for o in c.get("outputs", []) if o.get("output_type") == "stream"
        )
        if "⚠" in salidas and ("no corresponde" in salidas or "ya no corresponde" in salidas):
            razones.append("en la última corrida el notebook avisó que el perfil de algún segmento ya no corresponde a su nombre")
    veredictos["Agrupamiento"] = ("REENTRENAR", razones) if razones else ("MANTENER", ["segmentos estables; se reentrena junto con el pronóstico"])
else:
    print("  No hay modelo guardado.")
    veredictos["Agrupamiento"] = ("REENTRENAR", ["no existe modelo_agrupamiento.joblib"])

# ----------------------------------------------------------------- 3. caída
titulo("3. CRITERIOS DE CAÍDA (notebook 10)")
ruta = BASE / "06_estudio_caida" / "criterios_caida_por_segmento.joblib"
razones = []
if ruta.exists():
    c = joblib.load(ruta)
    print(f"  Criterios calculados el {str(c.get('fecha_calculo', ''))[:10]} con ventana hasta "
          f"{str(c['ventana'].get('corte_urbano', c['ventana'].get('fin_efectivo', '')))[:7]}")
    deriva = BASE / "06_estudio_caida" / "deriva_criterios_caida.csv"
    if deriva.exists():
        d = pd.read_csv(deriva)
        cambian = d[d["cambia_criterio"].astype(str).str.lower().eq("true")]
        movidos = d[pd.to_numeric(d["dif_umbral_pct"], errors="coerce").abs() > 10]
        print(f"  Deriva medida este mes: {len(d)} segmentos | cambiarían de criterio: {len(cambian)} | "
              f"umbral movido > 10 puntos: {len(movidos)}")
        if len(cambian):
            razones.append("segmentos que cambiarían de criterio: " + ", ".join(cambian["cluster_id"].astype(str).head(6)))
        if len(movidos):
            razones.append("umbrales movidos más de 10 puntos en: " + ", ".join(movidos["cluster_id"].astype(str).head(6)))
    else:
        print("  Sin deriva_criterios_caida.csv (se genera en modo aplicar).")
    veredictos["Caída"] = ("REENTRENAR", razones) if razones else ("MANTENER", ["los umbrales guardados siguen vigentes"])
else:
    print("  No hay criterios guardados.")
    veredictos["Caída"] = ("REENTRENAR", ["no existe criterios_caida_por_segmento.joblib"])

# ----------------------------------------------------------------- 4. fuga
titulo("4. RIESGO DE FUGA (notebook 14)")
ruta = BASE / "10_riesgo_fuga" / "modelo_riesgo_fuga.joblib"
razones = []
revisar = []
if ruta.exists():
    info = joblib.load(ruta)["info"]
    corte_modelo = pd.Timestamp(info["fecha_corte_modelo"] + "-01")
    edad = meses_entre(corte_modelo, corte_actual) if corte_actual is not None else None
    print(f"  Método {info['metodo']} | entrenado con corte {info['fecha_corte_modelo']} "
          f"({info.get('n_positivos_niu', 0)} clientes con salida conocida)"
          + (f" -> {edad} mes(es)" if edad is not None else ""))
    if edad is not None and edad > MESES_MAX:
        razones.append(f"lleva {edad} meses sin reentrenar (tope {MESES_MAX})")
    if str(info["metodo"]).startswith("SIMILITUD"):
        revisar.append("se está usando similitud (menos de 20 ejemplos): reentrenar en cuanto el archivo traiga más casos")
    # ¿hay más ejemplos que los que vio el modelo?
    etq = BASE / "10_riesgo_fuga" / "etiquetas_salida_por_niu.csv"
    if etq.exists():
        e = pd.read_csv(etq, usecols=["mes_salida"])
        n_ahora = int(e["mes_salida"].notna().sum())
        n_modelo = int(info.get("n_positivos_niu", 0))
        print(f"  Clientes con salida conocida hoy: {n_ahora} | que vio el modelo al entrenar: {n_modelo}")
        if n_ahora >= n_modelo * 1.15 and n_ahora - n_modelo >= 10:
            razones.append(f"hay {n_ahora - n_modelo} casos nuevos de salida que el modelo no vio")
    seg = BASE / "10_riesgo_fuga" / "seguimiento_riesgo_fuga.csv"
    if seg.exists() and len(pd.read_csv(seg)):
        s = pd.read_csv(seg)
        completos = s[s["ventana_completa"].astype(str).str.lower().eq("true")]
        if len(completos):
            alto = completos[completos["nivel_riesgo"].eq("ALTO")]
            base = completos[completos["nivel_riesgo"].str.startswith("TODOS")]
            if len(alto) and len(base):
                pa, pb = alto["pct_salieron"].mean(), base["pct_salieron"].mean()
                print(f"  Seguimiento con ventana completa: ALTO se fue el {pa:.1f}% vs tasa base {pb:.1f}%")
                if pb > 0 and pa < 2 * pb:
                    razones.append(f"los señalados ALTO no se van claramente más que la tasa base ({pa:.1f}% vs {pb:.1f}%)")
        else:
            print("  Seguimiento: hay cortes anteriores pero ninguno con la ventana de 6 meses completa todavía.")
    else:
        print("  Seguimiento: todavía sin cortes anteriores.")
    if razones:
        veredictos["Riesgo de fuga"] = ("REENTRENAR", razones)
    elif revisar:
        veredictos["Riesgo de fuga"] = ("REVISAR", revisar)
    else:
        veredictos["Riesgo de fuga"] = ("MANTENER", ["sin señales; el modelo se reentrena en minutos cuando haya casos nuevos"])
else:
    print("  No hay modelo guardado.")
    veredictos["Riesgo de fuga"] = ("REENTRENAR", ["no existe modelo_riesgo_fuga.joblib"])

# ----------------------------------------------------------------- veredicto
print("\n" + "=" * 78)
print("VEREDICTO")
print("=" * 78)
for modelo, (v, motivos) in veredictos.items():
    marca = {"MANTENER": "✓", "REVISAR": "⚠", "REENTRENAR": "✗"}[v]
    print(f"  {marca} {modelo:<15} {v:<11} " + "; ".join(motivos))

reentrenar_pron = veredictos.get("Pronóstico", ("",))[0] == "REENTRENAR" or veredictos.get("Agrupamiento", ("",))[0] == "REENTRENAR"
reentrenar_caida = veredictos.get("Caída", ("",))[0] == "REENTRENAR"
reentrenar_fuga = veredictos.get("Riesgo de fuga", ("",))[0] == "REENTRENAR"
print()
if reentrenar_pron:
    print("Comando: python pipeline_mensual.py --modo reentrenar        (todo; horas)")
elif reentrenar_caida and reentrenar_fuga:
    print("Comando: python pipeline_mensual.py --modo reentrenar --solo 10,11,14,15   (minutos)")
elif reentrenar_caida:
    print("Comando: python pipeline_mensual.py --modo reentrenar --solo 10,11,15      (minutos)")
elif reentrenar_fuga:
    print("Comando: python pipeline_mensual.py --modo reentrenar --solo 14,15         (minutos)")
else:
    print("No hace falta reentrenar. Seguir con las corridas mensuales en modo aplicar.")
