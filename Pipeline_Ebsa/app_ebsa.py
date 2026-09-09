"""
app_ebsa.py — página web del proyecto EBSA (Streamlit)
=======================================================

Muestra las salidas que ya calculó el pipeline. No entrena ni recalcula nada:
lee los CSV/parquet de las carpetas de salida y los presenta.

Cómo correrla (desde C:\\Users\\Home\\Documents\\GitHub\\ProyectoEBSA\\Pipeline_Ebsa):

    pip install streamlit          # una sola vez
    streamlit run app_ebsa.py

Se abre en el navegador (http://localhost:8501). La carpeta de datos se toma
de la variable de entorno EBSA_DATOS o, si no existe, de la ruta de siempre;
también se puede cambiar en la barra lateral.

Secciones
---------
  Resumen            : cifras del corte actual y lo que cambió frente al anterior
  Gestión por ciclo  : la lista operativa, ciclo por ciclo, para repartir a cuadrillas
  Ranking gerencial  : los clientes de mayor valor en riesgo, con filtros
  Cortes             : valor en riesgo por clase, estrato, zona y tramo
  Buscar cliente     : todo lo que el proyecto sabe de un NIU (segmento, caída, pronóstico)
  Pronóstico 6 meses : precisión del modelo por perfil y horizonte, totales proyectados
  Seguimiento        : pronósticos y listas anteriores contra lo que realmente pasó
  Retroalimentación  : resultados de las visitas contra las listas (cuando existan)
  Estado del pipeline: última corrida, control de calidad del mes entrante
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

# ----------------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------------
st.set_page_config(page_title="EBSA — Consumo de clientes", page_icon="⚡", layout="wide")

# Carpeta de datos: C:\Users\Home\Documents\Datos_Ebsa (o la variable de entorno EBSA_DATOS)
DATOS_POR_DEFECTO = os.environ.get("EBSA_DATOS", r"C:\Users\Home\Documents\Datos_Ebsa")

# Colores: un solo tono para magnitudes; naranja solo cuando hay dos series.
AZUL = "#2a78d6"
NARANJA = "#eb6834"

TRAYECTORIA_TEXTO = {
    "CAIDA_ACELERANDO": "El modelo prevé que el mes que viene siga bajando. Máxima urgencia.",
    "SIN_RECUPERACION_PREVISTA": "El modelo no prevé cambio mayor a su propio error: se queda en el nivel caído.",
    "RECUPERACION_PREVISTA": "El modelo prevé que vuelva. Vigilar, no despachar.",
    "NO_EVALUABLE_RURAL": "Rural excluido de trayectoria por sesgo del pronóstico en el borde.",
    "SIN_PRONOSTICO": "El cliente no tiene fila en el pronóstico (historia insuficiente).",
}
VEREDICTO_TEXTO = {
    "CAIDA_CONFIRMADA": "Cae frente al periodo anterior Y frente al mismo periodo del año pasado.",
    "CAIDA_SOSTENIDA": "Ya venía bajo frente al año pasado y sigue ahí.",
    "CAIDA_RECIENTE": "Cae frente al periodo anterior, pero no frente al año pasado.",
    "SIN_CAIDA": "No cumple el criterio de caída de su segmento.",
    "SIN_BASE_COMPARABLE": "No hay periodo anterior con dato suficiente.",
    "NO_APLICA": "Segmento sin consumo o sin datos: no se evalúa.",
    "NO_EVALUADO": "No alcanzó a evaluarse en la ventana.",
}


def pesos(x) -> str:
    return "—" if pd.isna(x) else f"${x:,.0f}"


def kwh(x) -> str:
    return "—" if pd.isna(x) else f"{x:,.0f} kWh"


# ----------------------------------------------------------------------------
# Carga de datos (con caché: se relee solo si cambia el archivo)
# ----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def leer_csv(ruta: str, mtime: float, **kw) -> pd.DataFrame:
    return pd.read_csv(ruta, encoding="utf-8-sig", **kw)


@st.cache_data(show_spinner=False)
def leer_parquet(ruta: str, mtime: float, columns=None) -> pd.DataFrame:
    return pd.read_parquet(ruta, columns=columns, engine="pyarrow")


def cargar(ruta: Path, columns=None, **kw):
    """Devuelve el DataFrame o None si el archivo no existe."""
    if not ruta.exists():
        return None
    mtime = ruta.stat().st_mtime
    if ruta.suffix == ".parquet":
        return leer_parquet(str(ruta), mtime, columns=columns)
    return leer_csv(str(ruta), mtime, **kw)


class Rutas:
    def __init__(self, base: Path):
        self.base = base
        self.gestion = base / "07_gestion_caida"
        self.modelo = base / "04_pronostico" / "modelo_final"
        self.agrup = base / "05_segmentos_clientes"
        self.caida = base / "06_estudio_caida"
        self.seguimiento = base / "08_seguimiento"
        self.salidas = base / "02_serie_reconstruida"
        self.corridas = base / "09_registro_corridas"

        self.operativa = self.gestion / "gestion_caida_operativa.csv"
        self.gerencial = self.gestion / "gestion_caida_gerencial.csv"
        self.resumen_ciclo = self.gestion / "resumen_gestion_por_ciclo.csv"
        self.resumen_corte = self.gestion / "resumen_gestion_por_corte.csv"
        self.entradas_salidas = self.gestion / "resumen_entradas_salidas_lista.csv"
        self.sesgo = self.gestion / "diagnostico_sesgo_pronostico.csv"
        self.pred6 = self.modelo / "predicciones_segmentadas_optimizadas_6_meses.parquet"
        self.metricas_perfil = self.modelo / "metricas_sistema_por_perfil_horizonte_optimizado.csv"
        self.metricas_global = self.modelo / "metricas_sistema_ganador_backtest_optimizado.csv"
        self.seleccion = self.modelo / "seleccion_modelo_por_perfil_horizonte_optimizada.csv"
        self.clusters = self.agrup / "clientes_clusters_consumo.parquet"
        self.catalogo = self.agrup / "catalogo_segmentos_negocio.csv"
        self.estudio_caida = self.caida / "estudio_caida_consumo.parquet"
        self.resumen_caida = self.caida / "resumen_caida_por_segmento.csv"
        self.seg_global = self.seguimiento / "seguimiento_pronostico_global.csv"
        self.seg_perfil = self.seguimiento / "seguimiento_pronostico_por_perfil.csv"
        self.seg_zona = self.seguimiento / "seguimiento_pronostico_por_zona.csv"
        self.seg_lista = self.seguimiento / "seguimiento_lista_gestion.csv"
        self.retro_resumen = self.gestion / "retroalimentacion" / "evaluacion_retroalimentacion_resumen.csv"
        self.control_calidad = self.salidas / "control_calidad_mes_entrante.csv"


# ----------------------------------------------------------------------------
# Barra lateral
# ----------------------------------------------------------------------------
st.sidebar.title("⚡ EBSA — Consumo")
ruta_datos = st.sidebar.text_input("Carpeta de datos", DATOS_POR_DEFECTO)
R = Rutas(Path(ruta_datos))

if not R.base.exists():
    st.error(f"No existe la carpeta de datos: {R.base}")
    st.stop()

SECCIONES = [
    "Resumen", "Gestión por ciclo", "Ranking gerencial", "Cortes", "Buscar cliente",
    "Pronóstico 6 meses", "Seguimiento", "Retroalimentación", "Estado del pipeline",
]
seccion = st.sidebar.radio("Sección", SECCIONES)

operativa = cargar(R.operativa, dtype={"NIU": "string", "ciclo_etiqueta": "string"})
if operativa is None:
    st.warning(
        f"No existe {R.operativa.name}. Corre el pipeline (python pipeline_mensual.py --modo aplicar) "
        "y vuelve a abrir la página."
    )

corte_actual = None
if operativa is not None and "fecha_corte" in operativa.columns:
    corte_actual = str(operativa["fecha_corte"].iloc[0])[:7]
    st.sidebar.caption(f"Corte de la lista de gestión: **{corte_actual}**")
pred6 = cargar(R.pred6)
if pred6 is not None:
    st.sidebar.caption(f"Corte del pronóstico: **{str(pred6['fecha_corte'].iloc[0])[:7]}**")


# ----------------------------------------------------------------------------
# Resumen
# ----------------------------------------------------------------------------
if seccion == "Resumen":
    st.title("Resumen del corte")
    if operativa is None:
        st.stop()

    g = operativa
    con_tarifa = g["tiene_tarifa"].astype(str).str.lower().eq("true") if "tiene_tarifa" in g.columns else pd.Series(True, index=g.index)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes en la lista", f"{len(g):,}")
    c2.metric("kWh/mes en riesgo", f"{g['perdida_kwh_mes'].sum():,.0f}")
    c3.metric("Valor en riesgo / mes", pesos(g["valor_riesgo_mes"].sum()),
              help="Pérdida de kWh × tarifa REAL de cada cliente. Los sin tarifa no se valoran.")
    c4.metric("Ciclos con clientes", f"{g['ciclo_etiqueta'].nunique()}")
    if (~con_tarifa).any():
        st.caption(f"{int((~con_tarifa).sum()):,} clientes sin tarifa en el sistema comercial: aparecen en la lista pero sin valor.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("¿Qué prevé el modelo para el mes siguiente?")
        if "trayectoria" in g.columns:
            t = g.groupby("trayectoria").agg(clientes=("NIU", "size"), valor_mes=("valor_riesgo_mes", "sum")).reset_index()
            t["valor_mes"] = t["valor_mes"].round(0)
            st.dataframe(t.sort_values("clientes", ascending=False), hide_index=True, use_container_width=True)
            with st.expander("Qué significa cada trayectoria"):
                for k, v in TRAYECTORIA_TEXTO.items():
                    st.markdown(f"**{k}** — {v}")
    with col_b:
        st.subheader("¿Es nuevo en la lista o lleva meses?")
        if "estado_en_lista" in g.columns:
            e = g.groupby("estado_en_lista").agg(clientes=("NIU", "size"), valor_mes=("valor_riesgo_mes", "sum")).reset_index()
            st.dataframe(e, hide_index=True, use_container_width=True)
            st.caption("NUEVO: primera vez. PERSISTENTE: también estaba el mes pasado. REINCIDENTE: estuvo en los últimos 12 meses.")
        es = cargar(R.entradas_salidas)
        if es is not None and len(es):
            u = es.iloc[-1]
            st.markdown(
                f"Frente al corte **{u['corte_anterior']}**: permanecen **{int(u['permanecen']):,}**, "
                f"salieron **{int(u['salieron']):,}**, entraron **{int(u['entraron']):,}**."
            )

    st.subheader("Dónde está el valor: ciclos de lectura")
    rc = cargar(R.resumen_ciclo, dtype={"ciclo_etiqueta": "string"})
    if rc is not None:
        rc = rc.sort_values("valor_riesgo_mes", ascending=False)
        st.bar_chart(rc.set_index("ciclo_etiqueta")["valor_riesgo_mes"], color=AZUL, height=280)
        st.dataframe(rc, hide_index=True, use_container_width=True)

    st.subheader("Severidad")
    sev = g.groupby("severidad").agg(clientes=("NIU", "size"), kwh_mes=("perdida_kwh_mes", "sum"),
                                     valor_mes=("valor_riesgo_mes", "sum")).reset_index()
    st.dataframe(sev, hide_index=True, use_container_width=True)
    st.caption("Severidad relativa al segmento: CRITICA ≥ 2 escalas por encima del umbral, FUERTE ≥ 1, MODERADA el resto.")


# ----------------------------------------------------------------------------
# Gestión por ciclo
# ----------------------------------------------------------------------------
elif seccion == "Gestión por ciclo":
    st.title("Lista operativa por ciclo de lectura")
    if operativa is None:
        st.stop()
    st.caption("Dentro de cada ciclo los clientes van de mayor a menor valor en riesgo: una cuadrilla empieza por el primero.")
    ciclos = sorted(operativa["ciclo_etiqueta"].unique())
    ciclo = st.selectbox("Ciclo", ciclos)
    d = operativa[operativa["ciclo_etiqueta"] == ciclo]

    f1, f2, f3 = st.columns(3)
    sev = f1.multiselect("Severidad", sorted(d["severidad"].dropna().unique()))
    tra = f2.multiselect("Trayectoria", sorted(d["trayectoria"].dropna().unique())) if "trayectoria" in d.columns else []
    est = f3.multiselect("Estado en lista", sorted(d["estado_en_lista"].dropna().unique())) if "estado_en_lista" in d.columns else []
    if sev:
        d = d[d["severidad"].isin(sev)]
    if tra:
        d = d[d["trayectoria"].isin(tra)]
    if est:
        d = d[d["estado_en_lista"].isin(est)]

    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes", f"{len(d):,}")
    c2.metric("kWh/mes", f"{d['perdida_kwh_mes'].sum():,.0f}")
    c3.metric("Valor/mes", pesos(d["valor_riesgo_mes"].sum()))

    cols = [c for c in ["orden_en_ciclo", "NIU", "zona", "clase_servicio", "estrato", "tramo_consumo", "cluster_id",
                        "severidad", "trayectoria", "estado_en_lista", "meses_consecutivos_en_lista",
                        "consumo_anterior_kwh", "consumo_reciente_kwh", "perdida_kwh_mes",
                        "tarifa_kwh", "valor_riesgo_mes", "pred_1m_kwh"] if c in d.columns]
    st.dataframe(d[cols], hide_index=True, use_container_width=True, height=520)
    st.download_button(
        f"Descargar ciclo {ciclo} (CSV)", d[cols].to_csv(index=False).encode("utf-8-sig"),
        file_name=f"gestion_ciclo_{ciclo}_{corte_actual or ''}.csv", mime="text/csv",
    )


# ----------------------------------------------------------------------------
# Ranking gerencial
# ----------------------------------------------------------------------------
elif seccion == "Ranking gerencial":
    st.title("Ranking por valor en riesgo")
    ger = cargar(R.gerencial, dtype={"NIU": "string", "ciclo_etiqueta": "string"})
    if ger is None:
        st.warning("No existe la lista gerencial.")
        st.stop()
    f1, f2, f3, f4 = st.columns(4)
    zona = f1.multiselect("Zona", sorted(ger["zona"].dropna().unique()))
    tramo = f2.multiselect("Tramo", sorted(ger["tramo_consumo"].dropna().unique()))
    clase = f3.multiselect("Clase de servicio", sorted(ger["clase_servicio"].dropna().astype(str).unique()))
    n = f4.slider("Mostrar top", 25, 1000, 100, step=25)
    d = ger.copy()
    if zona:
        d = d[d["zona"].isin(zona)]
    if tramo:
        d = d[d["tramo_consumo"].isin(tramo)]
    if clase:
        d = d[d["clase_servicio"].astype(str).isin(clase)]
    total = d["valor_riesgo_mes"].sum()
    top = d.head(n)
    st.markdown(
        f"Los **{len(top):,}** primeros concentran **{pesos(top['valor_riesgo_mes'].sum())}/mes**, "
        f"el **{(top['valor_riesgo_mes'].sum() / total * 100 if total else 0):.1f}%** del valor filtrado "
        f"({pesos(total)} sobre {len(d):,} clientes)."
    )
    cols = [c for c in ["ranking", "NIU", "ciclo_etiqueta", "zona", "clase_servicio", "estrato", "tramo_consumo",
                        "cluster_id", "severidad", "trayectoria", "estado_en_lista",
                        "consumo_anterior_kwh", "consumo_reciente_kwh", "perdida_kwh_mes", "tarifa_kwh",
                        "valor_riesgo_mes"] if c in top.columns]
    st.dataframe(top[cols], hide_index=True, use_container_width=True, height=560)
    st.download_button("Descargar (CSV)", top[cols].to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"ranking_gerencial_{corte_actual or ''}.csv", mime="text/csv")


# ----------------------------------------------------------------------------
# Cortes
# ----------------------------------------------------------------------------
elif seccion == "Cortes":
    st.title("Valor en riesgo por cortes de gestión")
    rc = cargar(R.resumen_corte)
    if rc is None:
        st.warning("No existe resumen_gestion_por_corte.csv")
        st.stop()
    corte_col = "corte" if "corte" in rc.columns else rc.columns[0]
    for nombre, grupo in rc.groupby(corte_col):
        st.subheader(nombre.replace("_", " ").capitalize())
        grupo = grupo.sort_values("valor_riesgo_mes", ascending=False)
        c1, c2 = st.columns([1, 1])
        with c1:
            st.bar_chart(grupo.set_index("valor_corte")["valor_riesgo_mes"], color=AZUL, height=260)
        with c2:
            st.dataframe(grupo.drop(columns=[corte_col]), hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------
# Buscar cliente
# ----------------------------------------------------------------------------
elif seccion == "Buscar cliente":
    st.title("Buscar un cliente")

    # --- Ejemplos por perfil / segmento / trayectoria / ciclo, para no tener que
    #     conocer un NIU de memoria ---
    with st.expander("¿No tienes un NIU a mano? Buscar ejemplos por perfil, segmento, trayectoria o ciclo"):
        seg_all = cargar(R.clusters, columns=["NIU", "cluster_id", "zona", "mediana_12m_kwh"])
        pred_all = pred6[["NIU", "perfil"]] if pred6 is not None else None
        ejemplos = None
        if seg_all is not None:
            ejemplos = seg_all.copy()
            ejemplos["NIU"] = ejemplos["NIU"].astype("string").str.strip()
            if pred_all is not None:
                pa = pred_all.copy(); pa["NIU"] = pa["NIU"].astype("string").str.strip()
                ejemplos = ejemplos.merge(pa, on="NIU", how="left")
            if operativa is not None:
                ejemplos = ejemplos.merge(
                    operativa[["NIU", "ciclo_etiqueta", "veredicto", "severidad", "trayectoria", "valor_riesgo_mes"]],
                    on="NIU", how="left",
                )
        if ejemplos is None:
            st.info("Aún no hay segmentación ni pronóstico para listar ejemplos.")
        else:
            f1, f2, f3, f4 = st.columns(4)
            perfiles = ["(todos)"] + sorted(ejemplos["perfil"].dropna().unique()) if "perfil" in ejemplos.columns else ["(todos)"]
            perfil_sel = f1.selectbox("Perfil de pronóstico", perfiles)
            segmentos = ["(todos)"] + sorted(ejemplos["cluster_id"].dropna().unique())
            seg_sel = f2.selectbox("Segmento de negocio", segmentos)
            trayectorias = ["(todos)"] + (sorted(ejemplos["trayectoria"].dropna().unique()) if "trayectoria" in ejemplos.columns else [])
            tra_sel = f3.selectbox("Trayectoria (solo clientes en la lista)", trayectorias)
            ciclos_ej = ["(todos)"] + (sorted(ejemplos["ciclo_etiqueta"].dropna().unique()) if "ciclo_etiqueta" in ejemplos.columns else [])
            cic_sel = f4.selectbox("Ciclo (solo clientes en la lista)", ciclos_ej)

            e = ejemplos
            if perfil_sel != "(todos)":
                e = e[e["perfil"] == perfil_sel]
            if seg_sel != "(todos)":
                e = e[e["cluster_id"] == seg_sel]
            if tra_sel != "(todos)":
                e = e[e["trayectoria"] == tra_sel]
            if cic_sel != "(todos)":
                e = e[e["ciclo_etiqueta"] == cic_sel]
            st.caption(f"{len(e):,} clientes cumplen el filtro. Se muestran hasta 50; copia el NIU y pégalo abajo.")
            cols_e = [c for c in ["NIU", "perfil", "cluster_id", "zona", "mediana_12m_kwh", "ciclo_etiqueta",
                                  "veredicto", "severidad", "trayectoria", "valor_riesgo_mes"] if c in e.columns]
            st.dataframe(e[cols_e].head(50), hide_index=True, use_container_width=True)

    niu = st.text_input("NIU").strip()
    if not niu:
        st.stop()

    seg = cargar(R.clusters)
    if seg is not None:
        seg["NIU"] = seg["NIU"].astype("string").str.strip()
        s = seg[seg["NIU"] == niu]
        st.subheader("Segmento")
        if len(s):
            s = s.iloc[0]
            c1, c2, c3 = st.columns(3)
            c1.metric("Segmento", s.get("cluster_id", "—"))
            c2.metric("Consumo mediano 12m", kwh(s.get("mediana_12m_kwh", np.nan)))
            c3.metric("Prioridad", str(s.get("segmento_prioridad_texto", "—")))
            if "segmento_descripcion" in s.index:
                st.markdown(f"**Qué es:** {s['segmento_descripcion']}")
            if "segmento_accion" in s.index:
                st.markdown(f"**Acción sugerida:** {s['segmento_accion']}")
        else:
            st.info("El NIU no está en la segmentación.")

    ec = cargar(R.estudio_caida)
    if ec is not None:
        ec["NIU"] = ec["NIU"].astype("string").str.strip()
        e = ec[ec["NIU"] == niu]
        st.subheader("Estudio de caída")
        if len(e):
            e = e.iloc[0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Veredicto", str(e["veredicto"]))
            c2.metric("Severidad", str(e.get("severidad", "—")))
            c3.metric("Consumo anterior", kwh(e.get("consumo_anterior_kwh", np.nan)))
            c4.metric("Consumo reciente", kwh(e.get("consumo_reciente_kwh", np.nan)))
            st.caption(VEREDICTO_TEXTO.get(str(e["veredicto"]), ""))
            st.markdown(
                f"Variación vs. periodo anterior: **{e.get('variacion_vs_anterior_pct', np.nan):.1f}%** · "
                f"vs. año pasado: **{e.get('variacion_vs_anio_pct', np.nan):.1f}%** · ventana de "
                f"**{int(e.get('meses_ventana', 0))} meses**"
            )
        else:
            st.info("El NIU no está en el estudio de caída.")

    if operativa is not None:
        o = operativa[operativa["NIU"] == niu]
        if len(o):
            o = o.iloc[0]
            st.subheader("En la lista de gestión")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Ciclo", str(o["ciclo_etiqueta"]))
            c2.metric("Orden en el ciclo", int(o["orden_en_ciclo"]))
            c3.metric("Valor en riesgo / mes", pesos(o["valor_riesgo_mes"]))
            c4.metric("Trayectoria", str(o.get("trayectoria", "—")))
            st.caption(TRAYECTORIA_TEXTO.get(str(o.get("trayectoria", "")), ""))
            if "estado_en_lista" in o.index:
                st.markdown(f"Estado: **{o['estado_en_lista']}** — {int(o.get('meses_consecutivos_en_lista', 1))} mes(es) seguido(s) en la lista.")

    if pred6 is not None:
        p = pred6[pred6["NIU"].astype("string").str.strip() == niu]
        st.subheader("Pronóstico a 6 meses")
        if len(p):
            p = p.iloc[0]
            filas = []
            for h in range(1, 7):
                filas.append({"mes": str(p[f"fecha_pred_{h}m"])[:7], "pronóstico kWh": float(p[f"pred_{h}m_kwh"]),
                              "modelo": p[f"modelo_{h}m"]})
            t = pd.DataFrame(filas)
            c1, c2 = st.columns([2, 1])
            with c1:
                st.line_chart(t.set_index("mes")["pronóstico kWh"], color=AZUL, height=260)
            with c2:
                st.dataframe(t, hide_index=True, use_container_width=True)
            st.caption(f"Perfil del cliente: {p['perfil']} · corte del pronóstico: {str(p['fecha_corte'])[:7]}")
        else:
            st.info("El NIU no tiene pronóstico (historia insuficiente o sin dato en el mes de corte).")


# ----------------------------------------------------------------------------
# Pronóstico
# ----------------------------------------------------------------------------
elif seccion == "Pronóstico 6 meses":
    st.title("Pronóstico de consumo a 6 meses")
    if pred6 is None:
        st.warning("No existe el archivo de predicciones.")
        st.stop()
    corte = str(pred6["fecha_corte"].iloc[0])[:7]
    modo = pred6["modo"].iloc[0] if "modo" in pred6.columns else "—"
    corte_modelo = str(pred6["fecha_corte_modelo"].iloc[0])[:7] if "fecha_corte_modelo" in pred6.columns else "—"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes pronosticados", f"{len(pred6):,}")
    c2.metric("Corte de datos", corte)
    c3.metric("Modelo entrenado con corte", corte_modelo)
    c4.metric("Modo de la última corrida", str(modo))

    st.subheader("Consumo total proyectado por mes")
    tot = pd.DataFrame({
        "mes": [str(pred6[f"fecha_pred_{h}m"].iloc[0])[:7] for h in range(1, 7)],
        "kWh": [float(pred6[f"pred_{h}m_kwh"].sum()) for h in range(1, 7)],
    })
    c1, c2 = st.columns([2, 1])
    with c1:
        st.bar_chart(tot.set_index("mes")["kWh"], color=AZUL, height=260)
    with c2:
        st.dataframe(tot, hide_index=True, use_container_width=True)

    st.subheader("Precisión esperada (backtest) por perfil y horizonte")
    mp = cargar(R.metricas_perfil)
    if mp is not None:
        piv = mp.pivot(index="perfil", columns="horizonte", values="WAPE_final_pct").round(1)
        st.dataframe(piv, use_container_width=True)
        st.caption(
            "WAPE %: error porcentual ponderado. P4_INSUFICIENTE no tiene modelo (solo línea base): su error "
            "alto no es un fallo del sistema, es falta de historia. Se compara contra la línea base "
            "(repetir el consumo reciente) en la columna WAPE_baseline_pct del archivo."
        )
    sel = cargar(R.seleccion)
    if sel is not None:
        with st.expander("Qué algoritmo usa cada grupo"):
            st.dataframe(sel, hide_index=True, use_container_width=True)

    st.subheader("Clientes por perfil")
    st.dataframe(pred6["perfil"].value_counts().rename("clientes").to_frame(), use_container_width=True)


# ----------------------------------------------------------------------------
# Seguimiento
# ----------------------------------------------------------------------------
elif seccion == "Seguimiento":
    st.title("Seguimiento: lo pronosticado contra lo que pasó")
    sg = cargar(R.seg_global)
    if sg is None or len(sg) == 0:
        st.info("Todavía no hay meses pronosticados que ya estén consolidados. Se llena mes a mes "
                "(Seguimiento_pronostico_mensual.ipynb).")
    else:
        st.subheader("Error en vivo del pronóstico (WAPE %) por corte y horizonte")
        piv = sg.pivot(index="fecha_corte", columns="horizonte", values="WAPE_pct").round(1)
        st.dataframe(piv, use_container_width=True)
        mg = cargar(R.metricas_global)
        if mg is not None:
            st.caption("Referencia del backtest por horizonte: " +
                       ", ".join(f"h{int(r.horizonte)}={r.WAPE_final_pct:.1f}%" for r in mg.itertuples()))
        sp = cargar(R.seg_perfil)
        if sp is not None:
            with st.expander("Por perfil (con diferencia contra el backtest)"):
                st.dataframe(sp.round(2), hide_index=True, use_container_width=True)
        sz = cargar(R.seg_zona)
        if sz is not None:
            with st.expander("Por zona"):
                st.dataframe(sz.round(2), hide_index=True, use_container_width=True)

    sl = cargar(R.seg_lista)
    st.subheader("Qué pasó con los clientes de las listas anteriores")
    if sl is None or len(sl) == 0:
        st.info("Todavía no hay meses posteriores consolidados para ninguna lista.")
    else:
        st.caption("RECUPERADO: volvió al menos al 90% de lo que consumía antes de caer. SIGUE_CAYENDO: quedó por "
                   "debajo del 90% de su consumo reciente. ESTABLE_BAJO: se quedó en el nivel caído.")
        for corte_por in ["TOTAL", "trayectoria", "severidad", "zona"]:
            t = sl[sl["corte_por"] == corte_por]
            if len(t):
                st.markdown(f"**Por {corte_por.lower()}**")
                st.dataframe(t.drop(columns=["corte_por"]), hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------
# Retroalimentación
# ----------------------------------------------------------------------------
elif seccion == "Retroalimentación":
    st.title("Resultados de las visitas contra la lista")
    rr = cargar(R.retro_resumen)
    if rr is None or len(rr) == 0:
        st.info(
            "Aún no hay resultados de campo. Llenar la plantilla "
            f"{R.gestion / 'retroalimentacion' / 'resultado_gestion_plantilla.csv'} y correr "
            "Evaluacion_retroalimentacion_gestion.ipynb."
        )
        st.stop()
    st.caption("precision_gestionable: % de verificados con un problema que la empresa puede corregir. "
               "precision_caida_real: % donde la caída era real, gestionable o no. sin_novedad: falsos positivos.")
    for corte_por in ["TOTAL", "severidad", "trayectoria", "estado_en_lista", "tramo_consumo", "zona", "cluster_id"]:
        t = rr[rr["corte_por"] == corte_por]
        if len(t):
            st.markdown(f"**Por {corte_por.lower()}**")
            st.dataframe(t.drop(columns=["corte_por"]), hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------
# Estado del pipeline
# ----------------------------------------------------------------------------
elif seccion == "Estado del pipeline":
    st.title("Estado del pipeline")
    cc = cargar(R.control_calidad)
    st.subheader("Control de calidad del último mes entrante")
    if cc is None:
        st.info("Sin reporte de control de calidad (se genera en Reconstruccion_serie_tiempo_consumo_rural.ipynb).")
    else:
        st.dataframe(cc, hide_index=True, use_container_width=True)

    st.subheader("Últimas corridas")
    if R.corridas.exists():
        corridas = sorted([p for p in R.corridas.iterdir() if p.is_dir()], reverse=True)[:10]
        if not corridas:
            st.info("Sin corridas registradas.")
        for c in corridas:
            with st.expander(c.name):
                r = c / "resumen_corrida.txt"
                st.code(r.read_text(encoding="utf-8") if r.exists() else "(sin resumen)")
    else:
        st.info("No existe la carpeta corridas/ (la crea pipeline_mensual.py).")

    st.subheader("Sesgo del pronóstico rural vs. urbano (última priorización)")
    sb = cargar(R.sesgo)
    if sb is not None:
        st.dataframe(sb, hide_index=True, use_container_width=True)
