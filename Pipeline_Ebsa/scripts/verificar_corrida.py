"""
verificar_corrida.py — revisa que la última corrida dejó todo consistente
=========================================================================
Solo lee. Correr desde Pipeline_Ebsa después de pipeline_mensual.py:

    python verificar_corrida.py

Qué revisa (cada línea sale con ✓ OK, ⚠ AVISO o ✗ ERROR):
  1. Histórico: meses sin huecos y el último mes con clientes normales.
  2. Cortes por zona (notebook 3): existen, y el corte urbano es el último mes del histórico.
  3. Pronóstico: una fila por cliente, cada zona con su corte, meses pronosticados
     correctos, sin valores negativos ni vacíos, copia en historial_pronosticos.
  4. Segmentos: todos los clientes con segmento, cortes por zona.
  5. Caída y listas de gestión: cortes por zona, tarifa real presente, copia en historial,
     columnas del glosario y del grupo de consumo.
  6. Riesgo de fuga: modelo, lista, cortes por zona, copia en historial.
  7. Exportes por grupo: índice y archivos existen y no están vacíos.
  8. Seguimiento: si hay cortes anteriores, que se hayan evaluado.
  9. Registro de la corrida: el último resumen_corrida.txt terminó completo.
"""
import os
import re
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

# Windows: si la salida va a un archivo o a otro proceso (simular_meses.py), Python usa
# cp1252 y no puede escribir "✓" / "✗". Se fuerza UTF-8 en la salida de este script.
import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

BASE = Path(os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa"))
resultado = {"OK": 0, "AVISO": 0, "ERROR": 0}


def linea(nivel, texto):
    marca = {"OK": "✓", "AVISO": "⚠", "ERROR": "✗"}[nivel]
    resultado[nivel] += 1
    print(f"  {marca} {texto}")


def existe(ruta, que):
    if Path(ruta).exists():
        return True
    linea("ERROR", f"no existe {que}: {ruta}")
    return False


def seccion(t):
    print("\n" + t)
    print("-" * 78)


# ------------------------------------------------------------------ 1. histórico
seccion("1. HISTÓRICO (01_historico_procesado)")
archivos = sorted((BASE / "01_historico_procesado").glob("historico_*.parquet"))
ultimo_hist = None
if archivos:
    partes = [pd.read_parquet(a, columns=["NIU", "periodo"], engine="pyarrow") for a in archivos]
    h = pd.concat(partes, ignore_index=True)
    h["periodo"] = pd.to_datetime(h["periodo"]).dt.to_period("M").dt.to_timestamp()
    por_mes = h.groupby("periodo")["NIU"].nunique().sort_index()
    ultimo_hist = por_mes.index.max()
    huecos = [m for m in pd.date_range(por_mes.index.min(), ultimo_hist, freq="MS") if m not in por_mes.index]
    linea("OK" if not huecos else "ERROR",
          f"{len(por_mes)} meses de {por_mes.index.min():%Y-%m} a {ultimo_hist:%Y-%m}"
          + ("" if not huecos else "; faltan " + ", ".join(f"{m:%Y-%m}" for m in huecos)))
    ref = por_mes.iloc[-13:-1].median() if len(por_mes) > 1 else por_mes.iloc[-1]
    n_ult = por_mes.iloc[-1]
    linea("OK" if n_ult >= 0.6 * ref else "AVISO",
          f"último mes {ultimo_hist:%Y-%m}: {n_ult:,} clientes (mediana previa {ref:,.0f}); "
          "menos que la mediana es normal si el mes llegó sin rurales")
    del h, partes
else:
    linea("ERROR", "no hay historico_YYYY.parquet")

# ------------------------------------------------------------------ 2. cortes
seccion("2. CORTES POR ZONA (03_serie_modelado)")
ruta_cortes = BASE / "03_serie_modelado" / "cortes_por_zona.csv"
CORTES = {}
if existe(ruta_cortes, "cortes_por_zona.csv (lo escribe el paso 3)"):
    t = pd.read_csv(ruta_cortes)
    CORTES = {str(z): pd.Timestamp(f) for z, f in zip(t["zona"], t["fecha_corte"])}
    linea("OK", f"corte urbano {CORTES['URBANO']:%Y-%m} | corte rural {CORTES['RURAL']:%Y-%m}")
    if ultimo_hist is not None:
        linea("OK" if CORTES["URBANO"] == ultimo_hist else "AVISO",
              f"el corte urbano {'coincide con' if CORTES['URBANO'] == ultimo_hist else 'NO es'} el último mes del histórico "
              f"({ultimo_hist:%Y-%m}); si no coincide, el detector marcó provisional el último mes urbano")
    dif = (CORTES["URBANO"].year - CORTES["RURAL"].year) * 12 + (CORTES["URBANO"].month - CORTES["RURAL"].month)
    linea("OK" if 0 <= dif <= 3 else "AVISO", f"los rurales van {dif} mes(es) detrás de los urbanos (normal: 0 a 3)")
    ruta_serie = BASE / "03_serie_modelado" / "serie_mensual_modelado_preprocesada.parquet"
    if ruta_serie.exists():
        cols = pq.ParquetFile(ruta_serie).schema_arrow.names
        linea("OK" if "estado_mes" in cols else "AVISO",
              "la serie " + ("trae" if "estado_mes" in cols else "NO trae") + " la columna estado_mes (CONSOLIDADO/PROVISIONAL)")


def revisar_cortes(df, nombre, col_zona="zona"):
    if "fecha_corte" not in df.columns:
        linea("ERROR", f"{nombre}: sin columna fecha_corte")
        return
    fc = pd.to_datetime(df["fecha_corte"]).dt.to_period("M").dt.to_timestamp()
    if col_zona in df.columns and CORTES:
        for zona, esperado in CORTES.items():
            sub = fc[df[col_zona].astype(str).str.upper().eq(zona)]
            if len(sub) == 0:
                continue
            ok = (sub == esperado).all()
            nombre_zona = "urbanos" if zona == "URBANO" else "rurales"
            linea("OK" if ok else "ERROR",
                  f"{nombre}: {len(sub):,} filas {nombre_zona} con corte {sub.iloc[0]:%Y-%m}"
                  + ("" if ok else f" (se esperaba {esperado:%Y-%m})"))
    else:
        linea("OK", f"{nombre}: cortes {sorted(fc.dt.strftime('%Y-%m').unique())}")


# ------------------------------------------------------------------ 3. pronóstico
seccion("3. PRONÓSTICO (04_pronostico\\modelo_final)")
ruta_pred = BASE / "04_pronostico" / "modelo_final" / "predicciones_segmentadas_optimizadas_6_meses.parquet"
if existe(ruta_pred, "el pronóstico a 6 meses"):
    p = pd.read_parquet(ruta_pred, engine="pyarrow")
    dup = int(p["NIU"].duplicated().sum())
    linea("OK" if dup == 0 else "ERROR", f"{len(p):,} clientes pronosticados; NIU repetidos: {dup}")
    revisar_cortes(p, "pronóstico")
    for h in [1, 6]:
        fp = pd.to_datetime(p[f"fecha_pred_{h}m"]); fc = pd.to_datetime(p["fecha_corte"])
        ok = ((fp.dt.year - fc.dt.year) * 12 + (fp.dt.month - fc.dt.month) == h).all()
        linea("OK" if ok else "ERROR", f"fecha_pred_{h}m es corte + {h} mes(es) en todas las filas")
    preds = p[[f"pred_{h}m_kwh" for h in range(1, 7)]]
    linea("OK" if preds.isna().sum().sum() == 0 else "AVISO", f"pronósticos vacíos: {int(preds.isna().sum().sum()):,}")
    linea("OK" if (preds < 0).sum().sum() == 0 else "ERROR", f"pronósticos negativos: {int((preds < 0).sum().sum()):,}")
    if "modo" in p.columns:
        linea("OK", f"modo de la corrida: {p['modo'].iloc[0]} | modelo entrenado con corte {str(p['fecha_corte_modelo'].iloc[0])[:7]}")
    hist = BASE / "04_pronostico" / "modelo_final" / "historial_pronosticos"
    copia = hist / f"predicciones_6_meses_corte_{CORTES.get('URBANO', pd.Timestamp('1900-01-01')):%Y-%m}.parquet"
    linea("OK" if copia.exists() else "ERROR", f"copia versionada del corte: {copia.name}")

# ------------------------------------------------------------------ 4. segmentos
seccion("4. SEGMENTOS (05_segmentos_clientes)")
ruta_seg = BASE / "05_segmentos_clientes" / "clientes_clusters_consumo.parquet"
if existe(ruta_seg, "los segmentos"):
    s = pd.read_parquet(ruta_seg, columns=["NIU", "cluster_id", "zona", "fecha_corte"], engine="pyarrow")
    linea("OK" if s["cluster_id"].isna().sum() == 0 else "ERROR",
          f"{len(s):,} clientes; sin segmento: {int(s['cluster_id'].isna().sum()):,}")
    revisar_cortes(s, "segmentos")
    # Cobertura del pronóstico por zona: si una zona tiene pronóstico para muy pocos de sus
    # clientes, su corte quedó en un mes que esos clientes no tienen (p. ej. febrero sin
    # rurales dado por consolidado). Lo detecta el paso 3 por cobertura; esto es el seguro.
    if "p" in globals() and "zona" in p.columns and "zona" in s.columns:
        for zona in ("URBANO", "RURAL"):
            n_s = int(s["zona"].astype(str).str.upper().eq(zona).sum())
            n_p = int(p["zona"].astype(str).str.upper().eq(zona).sum())
            if n_s == 0:
                continue
            cob = n_p / n_s * 100
            nombre_zona = "urbanos" if zona == "URBANO" else "rurales"
            linea("OK" if cob >= 70 else "AVISO" if cob >= 30 else "ERROR",
                  f"{nombre_zona} con pronóstico: {n_p:,} de {n_s:,} clientes con segmento ({cob:.0f}%)"
                  + ("" if cob >= 70 else f"; el corte {zona.lower()} ({str(CORTES.get(zona, '?'))[:7]}) quedó en un mes que "
                     "esos clientes aún no tienen: revisa el detalle del borde en el log del paso 3"))

# ------------------------------------------------------------------ 5. caída y listas
seccion("5. CAÍDA Y LISTAS DE GESTIÓN (06_estudio_caida, 07_gestion_caida)")
ruta_caida = BASE / "06_estudio_caida" / "estudio_caida_consumo.parquet"
if existe(ruta_caida, "el estudio de caída"):
    c = pd.read_parquet(ruta_caida, columns=["NIU", "veredicto", "zona", "fecha_corte"], engine="pyarrow")
    revisar_cortes(c, "estudio de caída")
    linea("OK", "veredictos: " + ", ".join(f"{k} {v:,}" for k, v in c["veredicto"].value_counts().items()))
ruta_op = BASE / "07_gestion_caida" / "gestion_caida_operativa.csv"
if existe(ruta_op, "la lista operativa"):
    g = pd.read_csv(ruta_op, dtype={"NIU": "string"}, encoding="utf-8-sig")
    linea("OK", f"lista operativa: {len(g):,} clientes en {g['ciclo_etiqueta'].nunique()} ciclos")
    revisar_cortes(g, "lista operativa")
    for col in ["zona_nombre", "clase_servicio_nombre", "grupo_consumo", "tipo_medidor_nombre", "valor_facturado_mes"]:
        linea("OK" if col in g.columns else "AVISO", f"columna del glosario {col}: {'presente' if col in g.columns else 'FALTA'}")
    if "tiene_tarifa" in g.columns:
        sin = (~g["tiene_tarifa"].astype(str).str.lower().eq("true")).sum()
        linea("OK" if sin / max(len(g), 1) < 0.1 else "AVISO", f"clientes sin tarifa real en la lista: {int(sin):,}")
    copia = BASE / "07_gestion_caida" / "historial" / f"gestion_caida_operativa_corte_{CORTES.get('URBANO', pd.Timestamp('1900-01-01')):%Y-%m}.csv"
    linea("OK" if copia.exists() else "ERROR", f"copia versionada del corte: {copia.name}")

# ------------------------------------------------------------------ 6. fuga
seccion("6. RIESGO DE FUGA (10_riesgo_fuga)")
ruta_f = BASE / "10_riesgo_fuga" / "riesgo_fuga_clientes.csv"
if existe(ruta_f, "el riesgo de fuga"):
    f = pd.read_csv(ruta_f, dtype={"NIU": "string"}, encoding="utf-8-sig", low_memory=False)
    linea("OK", f"{len(f):,} clientes puntuados: " + ", ".join(f"{k} {v:,}" for k, v in f["nivel_riesgo"].value_counts().items()))
    revisar_cortes(f, "riesgo de fuga")
    linea("OK" if (BASE / "10_riesgo_fuga" / "modelo_riesgo_fuga.joblib").exists() else "ERROR", "modelo_riesgo_fuga.joblib")
    copia = BASE / "10_riesgo_fuga" / "historial" / f"riesgo_fuga_corte_{CORTES.get('URBANO', pd.Timestamp('1900-01-01')):%Y-%m}.csv"
    linea("OK" if copia.exists() else "ERROR", f"copia versionada del corte: {copia.name}")
    ya = BASE / "10_riesgo_fuga" / "clientes_con_otro_comercializador.csv"
    linea("OK" if ya.exists() else "AVISO", "lista de clientes con otro comercializador: " + ("presente" if ya.exists() else "no hay archivo de otros comercializadores"))

# ------------------------------------------------------------------ 7. exportes
seccion("7. EXPORTES POR GRUPO (11_exportes_negocio)")
ruta_idx = BASE / "11_exportes_negocio" / "indice_exportes.csv"
if existe(ruta_idx, "el índice de exportes"):
    idx = pd.read_csv(ruta_idx, encoding="utf-8-sig")
    faltan = [a for a in idx["archivo"] if not (BASE / a).exists()]
    vacios = [a for a in idx["archivo"] if (BASE / a).exists() and (BASE / a).stat().st_size < 100]
    linea("OK" if not faltan else "ERROR", f"{len(idx)} archivos en el índice; faltan {len(faltan)}")
    linea("OK" if not vacios else "AVISO", f"archivos vacíos: {len(vacios)}")
    linea("OK", "cortes en el índice: " + ", ".join(sorted(idx["fecha_corte"].astype(str).unique())))

# ------------------------------------------------------------------ 8. seguimiento
seccion("8. SEGUIMIENTO (08_seguimiento, 10_riesgo_fuga)")
hist_pred = sorted((BASE / "04_pronostico" / "modelo_final" / "historial_pronosticos").glob("predicciones_6_meses_corte_*.parquet"))
cortes_prev = [re.search(r"(\d{4}-\d{2})", a.name).group(1) for a in hist_pred]
if len(cortes_prev) <= 1:
    linea("OK", f"hay {len(cortes_prev)} corte guardado: el seguimiento empieza cuando haya un mes consolidado posterior")
else:
    sg = BASE / "08_seguimiento" / "seguimiento_pronostico_global.csv"
    if sg.exists() and len(pd.read_csv(sg)):
        t = pd.read_csv(sg)
        linea("OK", f"seguimiento del pronóstico evaluado para cortes {sorted(t['fecha_corte'].astype(str).unique())}")
    else:
        linea("AVISO", f"hay cortes guardados ({', '.join(cortes_prev)}) pero el seguimiento aún no tiene meses consolidados posteriores")
    sf = BASE / "10_riesgo_fuga" / "seguimiento_riesgo_fuga.csv"
    linea("OK" if sf.exists() else "AVISO", "seguimiento del riesgo de fuga: " + ("presente" if sf.exists() else "todavía sin cortes anteriores"))

# ------------------------------------------------------------------ 9. registro
seccion("9. REGISTRO DE LA CORRIDA (09_registro_corridas)")
corridas = sorted([p for p in (BASE / "09_registro_corridas").glob("*") if p.is_dir() and (p / "resumen_corrida.txt").exists()])
if corridas:
    ult = corridas[-1]
    resumen = ult / "resumen_corrida.txt"
    texto = resumen.read_text(encoding="utf-8") if resumen.exists() else ""
    completa = "CORRIDA COMPLETA" in texto
    fallo = "FALLÓ" in texto
    linea("OK" if completa and not fallo else "ERROR",
          f"última corrida {ult.name}: " + ("completa" if completa else "INCOMPLETA") + (" (con un paso fallido)" if fallo else ""))
    m = re.search(r"CORRIDA COMPLETA en ([\d.]+) min", texto)
    if m:
        linea("OK", f"duración {m.group(1)} min")
else:
    linea("AVISO", "sin corridas registradas")

# ------------------------------------------------------------------ resumen
print("\n" + "=" * 78)
print(f"RESULTADO: {resultado['OK']} OK | {resultado['AVISO']} avisos | {resultado['ERROR']} errores")
if resultado["ERROR"]:
    print("Hay errores: no uses las listas de esta corrida hasta revisarlos (pega esta salida para revisarla).")
elif resultado["AVISO"]:
    print("Sin errores. Los avisos son cosas para mirar, no para detenerse.")
else:
    print("Todo consistente.")
