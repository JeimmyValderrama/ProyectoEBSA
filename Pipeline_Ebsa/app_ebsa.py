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
  Riesgo de fuga     : clientes con probabilidad de irse a otro comercializador, los que ya se fueron,
                       vigilancia del mercado no regulado y calidad del modelo
  Cortes             : valor en riesgo por clase, estrato, zona y tramo
  Buscar cliente     : todo lo que el proyecto sabe de un NIU (segmento, caída, pronóstico, fuga)
  Pronóstico 6 meses : precisión del modelo por grupo y horizonte, totales proyectados
  Descargas por grupo: los archivos de 11_exportes_negocio (pronóstico, caída y fuga por grupo de consumo)
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

from utilidades_glosario import (
    GRUPO_CONSUMO_NOMBRE, GRUPOS_CONSUMO_ORDEN, GRUPO_CONSUMO_DESCRIPCION, ZONA_POR_CICLO,
    enriquecer_glosario, grupo_desde_perfil, nombre_zona,
)

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


NIVEL_FUGA_TEXTO = {
    "ALTO": "Probabilidad de salida ≥ 5 veces la tasa base, o dentro del 1% más alto. Contactar primero.",
    "MEDIO": "Probabilidad ≥ 2 veces la tasa base, o dentro del 5% más alto. Vigilar y contactar según valor.",
    "BAJO": "Sin señales por encima de la población.",
}
ESTADO_OTRO_TEXTO = {
    "CON OTRO COMERCIALIZADOR": "Aparece en el último mes del archivo de otros comercializadores.",
    "REGRESÓ A EBSA": "Dejó de aparecer en el archivo de otros y vuelve a tener consumo en TC2.",
    "SIN HISTORIA EN TC2 (se fue antes de la historia)": "No hay filas suyas en TC2: se cambió antes de 2022 o nunca fue facturado por EBSA.",
    "SALIÓ DEL ARCHIVO DE OTROS (verificar)": "Ya no está en el archivo de otros pero tampoco consume en TC2.",
}


def etiqueta_ciclo(c) -> str:
    """'00' -> '00 — CENTRO' (nombre del glosario)."""
    try:
        n = int(str(c))
    except (TypeError, ValueError):
        return str(c)
    return f"{n:02d} — {ZONA_POR_CICLO.get(n, 'sin nombre en glosario')}"


def pesos(x) -> str:
    return "—" if pd.isna(x) else f"${x:,.0f}"


def pesos_md(x) -> str:
    """Para st.markdown: el signo $ se escapa, si no Streamlit lo toma como fórmula matemática."""
    return "—" if pd.isna(x) else f"\\${x:,.0f}"


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
        self.fuga = base / "10_riesgo_fuga"
        self.exportes = base / "11_exportes_negocio"

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
        self.fuga_scores = self.fuga / "riesgo_fuga_clientes.csv"
        self.fuga_gerencial = self.fuga / "lista_riesgo_fuga_gerencial.csv"
        self.fuga_por_zona = self.fuga / "lista_riesgo_fuga_por_zona.csv"
        self.fuga_ya_fuera = self.fuga / "clientes_con_otro_comercializador.csv"
        self.fuga_vigilancia = self.fuga / "vigilancia_mercado_no_regulado.csv"
        self.fuga_perfil_idos = self.fuga / "perfil_clientes_que_se_fueron.csv"
        self.fuga_resumen_zona = self.fuga / "resumen_riesgo_fuga_por_zona.csv"
        self.fuga_resumen_grupo = self.fuga / "resumen_riesgo_fuga_por_grupo.csv"
        self.fuga_metricas = self.fuga / "metricas_modelo_fuga.csv"
        self.fuga_importancia = self.fuga / "importancia_variables_fuga.csv"
        self.fuga_seguimiento = self.fuga / "seguimiento_riesgo_fuga.csv"
        self.indice_exportes = self.exportes / "indice_exportes.csv"
        self.cortes_zona = base / "03_serie_modelado" / "cortes_por_zona.csv"
        self.serie = base / "03_serie_modelado" / "serie_mensual_modelado_preprocesada.parquet"


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
    "Resumen", "Gestión por ciclo", "Ranking gerencial", "Riesgo de fuga", "Cortes", "Buscar cliente",
    "Pronóstico 6 meses", "Descargas por grupo", "Seguimiento", "Retroalimentación", "Estado del pipeline",
]
seccion = st.sidebar.radio("Sección", SECCIONES)

operativa = cargar(R.operativa, dtype={"NIU": "string", "ciclo_etiqueta": "string"})
if operativa is None:
    st.warning(
        f"No existe {R.operativa.name}. Corre el pipeline (python pipeline_mensual.py --modo aplicar) "
        "y vuelve a abrir la página."
    )

# Corte por zona: urbanos = último mes completo; rurales = último trimestre cerrado
cortes_zona = cargar(R.cortes_zona)
CORTE_ZONA = {}
if cortes_zona is not None:
    CORTE_ZONA = {str(z): str(f)[:7] for z, f in zip(cortes_zona["zona"], cortes_zona["fecha_corte"])}
    st.sidebar.caption(f"Corte **urbano {CORTE_ZONA.get('URBANO', '—')}** · **rural {CORTE_ZONA.get('RURAL', '—')}**")
    st.sidebar.caption("Los rurales se leen por trimestres: sus meses posteriores al corte rural son "
                       "provisionales y se muestran como pronosticados hasta que llegue la lectura.")
corte_actual = None
if operativa is not None and "fecha_corte" in operativa.columns:
    corte_actual = str(pd.to_datetime(operativa["fecha_corte"]).max())[:7]
    st.sidebar.caption(f"Lista de gestión: corte **{corte_actual}**")
pred6 = cargar(R.pred6)
if pred6 is not None:
    st.sidebar.caption(f"Pronóstico: corte **{str(pd.to_datetime(pred6['fecha_corte']).max())[:7]}**")
    if "grupo_consumo" not in pred6.columns and "perfil" in pred6.columns:
        pred6 = pred6.copy()
        pred6["grupo_consumo"] = grupo_desde_perfil(pred6["perfil"])
fuga = cargar(R.fuga_scores, dtype={"NIU": "string"})
if fuga is not None and "fecha_corte" in fuga.columns:
    st.sidebar.caption(f"Riesgo de fuga: corte **{str(pd.to_datetime(fuga['fecha_corte']).max())[:7]}**")


@st.cache_data(show_spinner=False)
def serie_cliente(ruta: str, mtime: float, niu: str) -> pd.DataFrame:
    """Serie mensual de un solo NIU (lee el parquet con filtro, sin cargarlo entero)."""
    try:
        d = pd.read_parquet(ruta, engine="pyarrow", filters=[("NIU", "==", niu)],
                            columns=["NIU", "periodo", "consumo_kwh_mensual", "es_rural", "estado_mes"])
    except Exception:
        d = pd.read_parquet(ruta, engine="pyarrow", filters=[("NIU", "==", niu)],
                            columns=["NIU", "periodo", "consumo_kwh_mensual", "es_rural"])
        d["estado_mes"] = "CONSOLIDADO"
    d["periodo"] = pd.to_datetime(d["periodo"])
    return d.sort_values("periodo")


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

    st.subheader("Riesgo de fuga a otro comercializador")
    if fuga is None:
        st.info("Aún no hay corrida del riesgo de fuga (paso 14 del pipeline).")
    else:
        alto = fuga[fuga["nivel_riesgo"].eq("ALTO")]
        medio = fuga[fuga["nivel_riesgo"].eq("MEDIO")]
        ya = cargar(R.fuga_ya_fuera, dtype={"NIU": "string"})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Clientes puntuados", f"{len(fuga):,}")
        c2.metric("Riesgo ALTO", f"{len(alto):,}", help=NIVEL_FUGA_TEXTO["ALTO"])
        c3.metric("Riesgo MEDIO", f"{len(medio):,}", help=NIVEL_FUGA_TEXTO["MEDIO"])
        c4.metric("Pérdida esperada / mes (ALTO+MEDIO)", pesos(pd.concat([alto, medio])["valor_esperado_perdida_mes"].sum()),
                  help="Probabilidad de salida × lo que factura hoy (consumo promedio 6 meses × tarifa real).")
        if ya is not None and len(ya):
            n_con = int(ya["estado"].astype(str).str.startswith("CON OTRO").sum())
            st.caption(f"Ya atendidos por otro comercializador: **{len(ya):,}** NIU en el archivo de la empresa "
                       f"({n_con:,} en el último mes del archivo). Detalle en la sección Riesgo de fuga.")

    st.subheader("Dónde está el valor: ciclos de lectura")
    rc = cargar(R.resumen_ciclo, dtype={"ciclo_etiqueta": "string"})
    if rc is not None:
        rc = rc.sort_values("valor_riesgo_mes", ascending=False)
        rc.insert(1, "zona_nombre", rc["ciclo_etiqueta"].map(etiqueta_ciclo))
        st.bar_chart(rc.set_index("zona_nombre")["valor_riesgo_mes"], color=AZUL, height=280)
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
    ciclo = st.selectbox("Ciclo (zona del glosario)", ciclos, format_func=etiqueta_ciclo)
    d = operativa[operativa["ciclo_etiqueta"] == ciclo]

    f1, f2, f3, f4 = st.columns(4)
    sev = f1.multiselect("Severidad", sorted(d["severidad"].dropna().unique()))
    tra = f2.multiselect("Trayectoria", sorted(d["trayectoria"].dropna().unique())) if "trayectoria" in d.columns else []
    est = f3.multiselect("Estado en lista", sorted(d["estado_en_lista"].dropna().unique())) if "estado_en_lista" in d.columns else []
    grp = f4.multiselect("Grupo de consumo", [g for g in GRUPOS_CONSUMO_ORDEN if g in d.get("grupo_consumo", pd.Series(dtype=str)).unique()]) if "grupo_consumo" in d.columns else []
    if sev:
        d = d[d["severidad"].isin(sev)]
    if tra:
        d = d[d["trayectoria"].isin(tra)]
    if est:
        d = d[d["estado_en_lista"].isin(est)]
    if grp:
        d = d[d["grupo_consumo"].isin(grp)]

    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes", f"{len(d):,}")
    c2.metric("kWh/mes", f"{d['perdida_kwh_mes'].sum():,.0f}")
    c3.metric("Valor/mes", pesos(d["valor_riesgo_mes"].sum()))

    cols = [c for c in ["orden_en_ciclo", "NIU", "zona_nombre", "clase_servicio_nombre", "estrato", "grupo_consumo",
                        "cluster_id", "severidad", "trayectoria", "estado_en_lista", "meses_consecutivos_en_lista",
                        "consumo_anterior_kwh", "consumo_reciente_kwh", "perdida_kwh_mes",
                        "tarifa_kwh", "valor_riesgo_mes", "pred_1m_kwh", "consumo_promedio_semestral_kwh",
                        "valor_facturado_mes", "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in d.columns]
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
    col_zona = "zona_nombre" if "zona_nombre" in ger.columns else "zona"
    col_clase = "clase_servicio_nombre" if "clase_servicio_nombre" in ger.columns else "clase_servicio"
    f1, f2, f3, f4 = st.columns(4)
    zona = f1.multiselect("Zona", sorted(ger[col_zona].dropna().astype(str).unique()))
    if "grupo_consumo" in ger.columns:
        tramo = f2.multiselect("Grupo de consumo", [g for g in GRUPOS_CONSUMO_ORDEN if g in ger["grupo_consumo"].unique()])
    else:
        tramo = f2.multiselect("Tramo", sorted(ger["tramo_consumo"].dropna().unique()))
    clase = f3.multiselect("Clase de servicio", sorted(ger[col_clase].dropna().astype(str).unique()))
    n = f4.slider("Mostrar top", 25, 1000, 100, step=25)
    d = ger.copy()
    if zona:
        d = d[d[col_zona].astype(str).isin(zona)]
    if tramo:
        d = d[d["grupo_consumo" if "grupo_consumo" in d.columns else "tramo_consumo"].isin(tramo)]
    if clase:
        d = d[d[col_clase].astype(str).isin(clase)]
    total = d["valor_riesgo_mes"].sum()
    top = d.head(n)
    st.markdown(
        f"Los **{len(top):,}** primeros concentran **{pesos_md(top['valor_riesgo_mes'].sum())}/mes**, "
        f"el **{(top['valor_riesgo_mes'].sum() / total * 100 if total else 0):.1f}%** del valor filtrado "
        f"({pesos_md(total)} sobre {len(d):,} clientes)."
    )
    cols = [c for c in ["ranking", "NIU", "ciclo_etiqueta", "zona_nombre", "clase_servicio_nombre", "estrato", "grupo_consumo",
                        "cluster_id", "severidad", "trayectoria", "estado_en_lista",
                        "consumo_anterior_kwh", "consumo_reciente_kwh", "perdida_kwh_mes", "tarifa_kwh",
                        "valor_riesgo_mes", "consumo_promedio_semestral_kwh", "valor_facturado_mes",
                        "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in top.columns]
    st.dataframe(top[cols], hide_index=True, use_container_width=True, height=560)
    st.download_button("Descargar (CSV)", top[cols].to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"ranking_gerencial_{corte_actual or ''}.csv", mime="text/csv")


# ----------------------------------------------------------------------------
# Riesgo de fuga
# ----------------------------------------------------------------------------
elif seccion == "Riesgo de fuga":
    st.title("Riesgo de fuga a otro comercializador")
    if fuga is None:
        st.warning("No existe riesgo_fuga_clientes.csv. Corre el pipeline (paso 14) y vuelve a abrir la página.")
        st.stop()
    corte_f = str(fuga["fecha_corte"].iloc[0])[:7]
    metodo = str(fuga["metodo"].iloc[0]) if "metodo" in fuga.columns else "—"
    corte_modelo_f = str(fuga["fecha_corte_modelo"].iloc[0])[:7] if "fecha_corte_modelo" in fuga.columns else "—"
    alto = fuga[fuga["nivel_riesgo"].eq("ALTO")]
    medio = fuga[fuga["nivel_riesgo"].eq("MEDIO")]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Clientes puntuados", f"{len(fuga):,}")
    c2.metric("Riesgo ALTO", f"{len(alto):,}")
    c3.metric("Riesgo MEDIO", f"{len(medio):,}")
    c4.metric("Pérdida esperada / mes", pesos(pd.concat([alto, medio])["valor_esperado_perdida_mes"].sum()))
    c5.metric("Corte · modelo", f"{corte_f} · {corte_modelo_f}", help=f"Método: {metodo}")
    st.caption("Se puntúan los clientes de las clases de servicio que aparecen entre los que ya se fueron "
               "(comercial, industrial, oficial, acueductos, no regulados), sin alumbrado ni provisionales. "
               "Probabilidad de salida en los próximos 6 meses; el valor es lo que factura hoy con su tarifa real.")

    tabs = st.tabs(["Lista", "Por zona y grupo", "Ya con otro comercializador", "Vigilancia no regulados",
                    "Calidad del modelo", "Seguimiento"])

    with tabs[0]:
        f1, f2, f3, f4 = st.columns(4)
        niv = f1.multiselect("Nivel de riesgo", ["ALTO", "MEDIO", "BAJO"], default=["ALTO", "MEDIO"])
        zon = f2.multiselect("Zona", sorted(fuga["zona_nombre"].dropna().astype(str).unique()))
        grp = f3.multiselect("Grupo de consumo", [g for g in GRUPOS_CONSUMO_ORDEN if g in fuga["grupo_consumo"].unique()])
        cla = f4.multiselect("Clase de servicio", sorted(fuga["clase_servicio_nombre"].dropna().astype(str).unique()))
        d = fuga.copy()
        if niv:
            d = d[d["nivel_riesgo"].isin(niv)]
        if zon:
            d = d[d["zona_nombre"].astype(str).isin(zon)]
        if grp:
            d = d[d["grupo_consumo"].isin(grp)]
        if cla:
            d = d[d["clase_servicio_nombre"].astype(str).isin(cla)]
        orden = st.radio("Ordenar por", ["Pérdida esperada (probabilidad × valor)", "Probabilidad de salida"], horizontal=True)
        d = d.sort_values("valor_esperado_perdida_mes" if orden.startswith("Pérdida") else "prob_fuga_6m", ascending=False)
        st.markdown(f"**{len(d):,}** clientes · pérdida esperada **{pesos_md(d['valor_esperado_perdida_mes'].sum())}/mes** · "
                    f"facturación en juego **{pesos_md(d['valor_en_riesgo_mes'].sum())}/mes**")
        cols = [c for c in ["ranking", "NIU", "nivel_riesgo", "prob_fuga_6m", "valor_esperado_perdida_mes", "valor_en_riesgo_mes",
                            "zona_nombre", "clase_servicio_nombre", "grupo_consumo", "estrato", "consumo_actual_kwh",
                            "consumo_prom_6m_kwh", "consumo_prom_12m_kwh", "variacion_3m_vs_12m_pct", "meses_cero_3m",
                            "senales", "estado_en_lista", "meses_consecutivos_en_lista", "tarifa_kwh",
                            "consumo_promedio_semestral_kwh", "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in d.columns]
        st.dataframe(d[cols].head(1000), hide_index=True, use_container_width=True, height=520)
        st.download_button("Descargar lo filtrado (CSV)", d[cols].to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"riesgo_fuga_{corte_f}.csv", mime="text/csv")
        with st.expander("Qué significa cada nivel"):
            for k, v in NIVEL_FUGA_TEXTO.items():
                st.markdown(f"**{k}** — {v}")
            st.markdown("**Señales** — resumen en texto de por qué el modelo lo pone arriba: caída reciente, meses en cero, "
                        "zona con más salidas, tamaño. **estado_en_lista** — NUEVO / PERSISTENTE / REINCIDENTE frente a los cortes anteriores.")

    with tabs[1]:
        rz = cargar(R.fuga_resumen_zona)
        rg = cargar(R.fuga_resumen_grupo)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Por zona")
            if rz is not None:
                st.bar_chart(rz.set_index("zona_nombre")[["riesgo_alto", "riesgo_medio"]], color=[NARANJA, AZUL], height=300)
                st.dataframe(rz, hide_index=True, use_container_width=True)
        with c2:
            st.subheader("Por grupo de consumo")
            if rg is not None:
                st.dataframe(rg, hide_index=True, use_container_width=True)
                st.caption(" · ".join(f"**{g}**: {GRUPO_CONSUMO_DESCRIPCION[g]}" for g in GRUPOS_CONSUMO_ORDEN))

    with tabs[2]:
        ya = cargar(R.fuga_ya_fuera, dtype={"NIU": "string"})
        if ya is None or len(ya) == 0:
            st.info("No hay archivo de otros comercializadores en 00_otros_comercializadores.")
        else:
            st.subheader("Clientes atendidos por otros comercializadores (archivo de la empresa)")
            est = ya["estado"].value_counts()
            cc = st.columns(len(est))
            for col, (k, v) in zip(cc, est.items()):
                col.metric(k if len(k) < 28 else k[:26] + "…", f"{v:,}", help=ESTADO_OTRO_TEXTO.get(k, k))
            if "valor_facturado_antes_salida_mes" in ya.columns and ya["valor_facturado_antes_salida_mes"].notna().any():
                st.markdown(f"Facturaban antes de irse (solo con tarifa real): "
                            f"**{pesos_md(ya['valor_facturado_antes_salida_mes'].sum())}/mes** "
                            f"sobre {int(ya['valor_facturado_antes_salida_mes'].notna().sum()):,} clientes con historia TC2.")
            f1, f2 = st.columns(2)
            est_sel = f1.multiselect("Estado", list(est.index))
            com_sel = f2.multiselect("Comercializador", sorted(ya["comercializador"].dropna().astype(str).unique()))
            d = ya
            if est_sel:
                d = d[d["estado"].isin(est_sel)]
            if com_sel:
                d = d[d["comercializador"].astype(str).isin(com_sel)]
            cols = [c for c in ["NIU", "estado", "comercializador", "municipio", "usuario", "primer_mes_otro", "ultimo_mes_otro",
                                "mes_salida", "fuente_salida", "zona_nombre", "clase_servicio_nombre", "estrato",
                                "consumo_prom_6m_antes_salida_kwh", "consumo_prom_otro_kwh", "tarifa_kwh",
                                "valor_facturado_antes_salida_mes", "nivel_tension"] if c in d.columns]
            st.dataframe(d[cols], hide_index=True, use_container_width=True, height=420)
            st.download_button("Descargar (CSV)", d[cols].to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"clientes_con_otro_comercializador_{corte_f}.csv", mime="text/csv")
            pi = cargar(R.fuga_perfil_idos)
            if pi is not None:
                with st.expander("Perfil de los que se fueron (clase, zona, tamaño, comercializador, municipio)"):
                    for dim, t in pi.groupby("dimension", sort=False):
                        st.markdown(f"**{dim}**")
                        st.dataframe(t.drop(columns=["dimension"]).head(15), hide_index=True, use_container_width=True)

    with tabs[3]:
        vg = cargar(R.fuga_vigilancia, dtype={"NIU": "string"})
        st.subheader("Mercado no regulado")
        st.caption("Clientes en el ciclo 33 (USUARIOS NO REGULADOS), con clase IR (NO REGULADO) o con consumo promedio "
                   "≥ 55.000 kWh/mes: por tamaño pueden negociar con cualquier comercializador. Se listan aparte, con su riesgo.")
        if vg is None or len(vg) == 0:
            st.info("Ningún cliente cumple hoy los criterios de vigilancia.")
        else:
            st.dataframe(vg, hide_index=True, use_container_width=True, height=420)
            st.download_button("Descargar (CSV)", vg.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"vigilancia_no_regulados_{corte_f}.csv", mime="text/csv")

    with tabs[4]:
        mt = cargar(R.fuga_metricas)
        st.subheader("Qué tan bien ordena el modelo a los que efectivamente se fueron")
        if mt is None:
            st.info("Sin métricas: el modelo no se ha reentrenado todavía.")
        else:
            st.caption("Evaluación por cortes en el tiempo: se entrena con cortes anteriores y se mira si los clientes que "
                       "salieron en los 6 meses siguientes quedaron arriba en el ranking. AUC 0,5 = azar, 1 = perfecto. "
                       "precision_top100: de los 100 primeros, % que se fue. lift: cuántas veces más que elegir al azar.")
            st.dataframe(mt, hide_index=True, use_container_width=True)
        im = cargar(R.fuga_importancia)
        if im is not None:
            st.subheader("Variables que más pesan")
            st.bar_chart(im.set_index("variable")["importancia_pct"].head(15), color=AZUL, height=320)
        st.markdown(f"Método: **{metodo}** · modelo entrenado con corte **{corte_modelo_f}**.")

    with tabs[5]:
        sf = cargar(R.fuga_seguimiento)
        st.subheader("Qué pasó con los señalados en cortes anteriores")
        if sf is None or len(sf) == 0:
            st.info("Todavía no hay cortes anteriores con lista de riesgo de fuga. Se llena mes a mes.")
        else:
            st.caption("pct_salieron: % de los señalados en ese corte que aparecen luego en el archivo de otros "
                       "comercializadores (o en cero sostenido) dentro de sus 6 meses. Compararlo con la fila 'TODOS (tasa base)'. "
                       "ventana_completa = False: aún no han pasado los 6 meses.")
            st.dataframe(sf, hide_index=True, use_container_width=True)


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
            if "perfil" in ejemplos.columns:
                ejemplos["grupo_consumo"] = grupo_desde_perfil(ejemplos["perfil"])
            f1, f2, f3, f4 = st.columns(4)
            perfiles = ["(todos)"] + [g for g in GRUPOS_CONSUMO_ORDEN if g in ejemplos.get("grupo_consumo", pd.Series(dtype=str)).unique()]
            perfil_sel = f1.selectbox("Grupo de consumo", perfiles, help=" · ".join(f"{g}: {v}" for g, v in GRUPO_CONSUMO_DESCRIPCION.items()))
            segmentos = ["(todos)"] + sorted(ejemplos["cluster_id"].dropna().unique())
            seg_sel = f2.selectbox("Segmento de negocio", segmentos)
            trayectorias = ["(todos)"] + (sorted(ejemplos["trayectoria"].dropna().unique()) if "trayectoria" in ejemplos.columns else [])
            tra_sel = f3.selectbox("Trayectoria (solo clientes en la lista)", trayectorias)
            ciclos_ej = ["(todos)"] + (sorted(ejemplos["ciclo_etiqueta"].dropna().unique()) if "ciclo_etiqueta" in ejemplos.columns else [])
            cic_sel = f4.selectbox("Ciclo (solo clientes en la lista)", ciclos_ej)

            e = ejemplos
            if perfil_sel != "(todos)":
                e = e[e["grupo_consumo"] == perfil_sel]
            if seg_sel != "(todos)":
                e = e[e["cluster_id"] == seg_sel]
            if tra_sel != "(todos)":
                e = e[e["trayectoria"] == tra_sel]
            if cic_sel != "(todos)":
                e = e[e["ciclo_etiqueta"] == cic_sel]
            st.caption(f"{len(e):,} clientes cumplen el filtro. Se muestran hasta 50; copia el NIU y pégalo abajo.")
            cols_e = [c for c in ["NIU", "grupo_consumo", "cluster_id", "zona", "mediana_12m_kwh", "ciclo_etiqueta",
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

    if fuga is not None:
        fz = fuga[fuga["NIU"].astype("string").str.strip() == niu]
        ya = cargar(R.fuga_ya_fuera, dtype={"NIU": "string"})
        yz = ya[ya["NIU"].astype("string").str.strip() == niu] if ya is not None else pd.DataFrame()
        st.subheader("Riesgo de fuga a otro comercializador")
        if len(yz):
            y = yz.iloc[0]
            st.warning(f"Este cliente está en el archivo de otros comercializadores: **{y['estado']}** · "
                       f"{y.get('comercializador', '—')} · desde {str(y.get('primer_mes_otro', ''))[:7]} · "
                       f"mes de salida estimado {str(y.get('mes_salida', ''))[:7]} ({y.get('fuente_salida', '')}).")
        elif len(fz):
            z = fz.iloc[0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Nivel", str(z["nivel_riesgo"]))
            c2.metric("Probabilidad 6 meses", f"{float(z['prob_fuga_6m']) * 100:.2f}%")
            c3.metric("Facturación en juego / mes", pesos(z.get("valor_en_riesgo_mes", np.nan)))
            c4.metric("Puesto en el ranking", f"{int(z['ranking']):,} de {len(fuga):,}")
            st.caption(NIVEL_FUGA_TEXTO.get(str(z["nivel_riesgo"]), ""))
            if isinstance(z.get("senales"), str) and z["senales"]:
                st.markdown(f"**Señales:** {z['senales']}")
            st.markdown(f"Zona **{z.get('zona_nombre', '—')}** · clase **{z.get('clase_servicio_nombre', '—')}** · "
                        f"grupo **{z.get('grupo_consumo', '—')}** · medidor **{z.get('tipo_medidor_nombre', '—')}** · "
                        f"lectura **{z.get('tipo_lectura_nombre', '—')}**")
        else:
            st.info("El NIU no está en la población del riesgo de fuga (residencial, alumbrado, provisional, sin historia "
                    "suficiente o ya en cero sostenido).")

    if R.serie.exists():
        st.subheader("Consumo del último año y pronóstico")
        sc = serie_cliente(str(R.serie), R.serie.stat().st_mtime, niu)
        if len(sc):
            es_rural_c = bool(sc["es_rural"].fillna(False).astype(bool).iloc[-1])
            corte_c = CORTE_ZONA.get("RURAL" if es_rural_c else "URBANO", str(sc["periodo"].max())[:7])
            sc = sc.copy()
            sc["mes"] = sc["periodo"].dt.strftime("%Y-%m")
            real = sc[sc["mes"] <= corte_c].tail(12)[["mes", "consumo_kwh_mensual"]].rename(columns={"consumo_kwh_mensual": "kWh"})
            real["serie"] = "Real"
            parcial = sc[sc["mes"] > corte_c][["mes", "consumo_kwh_mensual"]].rename(columns={"consumo_kwh_mensual": "kWh"})
            parcial["serie"] = "Parcial (sin lectura completa)"

            pron = pd.DataFrame(columns=["mes", "kWh", "serie"])
            if pred6 is not None:
                pz = pred6[pred6["NIU"].astype("string").str.strip() == niu]
                if len(pz):
                    pz = pz.iloc[0]
                    pron = pd.DataFrame({
                        "mes": [str(pd.Timestamp(pz[f"fecha_pred_{h}m"]))[:7] for h in range(1, 7)],
                        "kWh": [float(pz[f"pred_{h}m_kwh"]) for h in range(1, 7)],
                    })
                    pron["serie"] = "Pronóstico"
                    # la línea punteada arranca en el último mes real para que se lea continua
                    if len(real):
                        pron = pd.concat([real.tail(1).assign(serie="Pronóstico"), pron], ignore_index=True)

            datos_g = pd.concat([real, parcial, pron], ignore_index=True)
            try:
                import altair as alt
                base_g = alt.Chart(datos_g).encode(
                    x=alt.X("mes:N", title="Mes", sort=None),
                    y=alt.Y("kWh:Q", title="kWh"),
                    tooltip=["mes", alt.Tooltip("kWh:Q", format=",.1f"), "serie"],
                )
                capa_real = base_g.transform_filter(alt.datum.serie == "Real").mark_line(
                    color=AZUL, strokeWidth=2.5, point=alt.OverlayMarkDef(color=AZUL))
                capa_pron = base_g.transform_filter(alt.datum.serie == "Pronóstico").mark_line(
                    color=NARANJA, strokeWidth=2.5, strokeDash=[6, 4], point=alt.OverlayMarkDef(color=NARANJA))
                capa_parcial = base_g.transform_filter(alt.datum.serie == "Parcial (sin lectura completa)").mark_point(
                    color="#8a8a8a", shape="diamond", size=90, filled=True)
                grafico = (capa_real + capa_pron + capa_parcial).properties(height=300)
                st.altair_chart(grafico, use_container_width=True)
                st.caption("Línea continua azul: consumo real (12 meses hasta el corte). Línea punteada naranja: pronóstico "
                           "del modelo. Rombos grises: meses con lectura parcial (rurales a la espera de la lectura trimestral).")
            except ImportError:
                piv = datos_g.pivot_table(index="mes", columns="serie", values="kWh", aggfunc="first")
                st.line_chart(piv, height=300)

            tabla = datos_g.copy()
            tabla["kWh"] = tabla["kWh"].round(1)
            if es_rural_c:
                st.caption(f"Cliente rural (lectura trimestral). Corte rural {corte_c}: los meses posteriores muestran "
                           "el pronóstico; el valor real reemplaza al pronosticado cuando llegue la lectura.")
            with st.expander("Ver los datos de la gráfica"):
                st.dataframe(tabla, hide_index=True, use_container_width=True)
        else:
            st.info("El NIU no tiene filas en la serie de modelado.")

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
            st.caption(f"Grupo de consumo: {GRUPO_CONSUMO_NOMBRE.get(str(p['perfil']), p['perfil'])} · zona {p.get('zona', '—')} · "
                       f"corte del pronóstico: {str(p['fecha_corte'])[:7]} · modelo entrenado con corte {str(p.get('fecha_corte_modelo', ''))[:7]}")
            if str(p.get("modelo_1m", "")) == "REGLA_CERO_SOSTENIDO":
                st.warning("Este cliente lleva sus dos últimos meses en cero (o casi): el pronóstico es persistencia del último "
                           "valor, no una recuperación. Si vuelve a consumir, la regla deja de aplicar sola el mes siguiente.")
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
    corte = str(pd.to_datetime(pred6["fecha_corte"]).max())[:7]
    if "zona" in pred6.columns:
        cz = pred6.groupby("zona")["fecha_corte"].max()
        corte = " · ".join(f"{z.lower()} {str(f)[:7]}" for z, f in cz.items())
    modo = pred6["modo"].iloc[0] if "modo" in pred6.columns else "—"
    corte_modelo = str(pred6["fecha_corte_modelo"].iloc[0])[:7] if "fecha_corte_modelo" in pred6.columns else "—"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes pronosticados", f"{len(pred6):,}")
    c2.metric("Corte de datos", corte, help="Urbanos: último mes completo. Rurales: último trimestre cerrado; "
              "sus primeros meses pronosticados son meses que ya pasaron pero aún no tienen lectura.")
    c3.metric("Modelo entrenado con corte", corte_modelo)
    c4.metric("Modo de la última corrida", str(modo))

    st.subheader("Consumo total proyectado por mes")
    # Cada zona tiene sus propias fechas de pronóstico: se suman por mes calendario
    filas_tot = []
    for h in range(1, 7):
        t = pred6[[f"fecha_pred_{h}m", f"pred_{h}m_kwh"]].rename(columns={f"fecha_pred_{h}m": "mes", f"pred_{h}m_kwh": "kWh"})
        filas_tot.append(t)
    tot = pd.concat(filas_tot)
    tot["mes"] = pd.to_datetime(tot["mes"]).dt.strftime("%Y-%m")
    tot = tot.groupby("mes", as_index=False)["kWh"].sum()
    if "zona" in pred6.columns and CORTE_ZONA:
        st.caption(f"Urbanos pronosticados desde {CORTE_ZONA.get('URBANO', '—')}; rurales desde "
                   f"{CORTE_ZONA.get('RURAL', '—')} (los meses rurales ya pasados se rellenan con el pronóstico "
                   "hasta que llegue la lectura trimestral).")
    c1, c2 = st.columns([2, 1])
    with c1:
        st.bar_chart(tot.set_index("mes")["kWh"], color=AZUL, height=260)
    with c2:
        st.dataframe(tot, hide_index=True, use_container_width=True)

    st.subheader("Precisión esperada (backtest) por grupo de consumo y horizonte")
    mp = cargar(R.metricas_perfil)
    if mp is not None:
        mp = mp.copy()
        mp["grupo_consumo"] = grupo_desde_perfil(mp["perfil"])
        piv = mp.pivot(index="grupo_consumo", columns="horizonte", values="WAPE_final_pct").round(1)
        piv = piv.reindex([g for g in GRUPOS_CONSUMO_ORDEN if g in piv.index])
        st.dataframe(piv, use_container_width=True)
        st.caption(
            "WAPE %: error porcentual ponderado. 'Sin historia suficiente' no tiene modelo (solo línea base): su error "
            "alto no es un fallo del sistema, es falta de historia. Se compara contra la línea base "
            "(repetir el consumo reciente) en la columna WAPE_baseline_pct del archivo."
        )
        st.caption(" · ".join(f"**{g}**: {GRUPO_CONSUMO_DESCRIPCION[g]}" for g in GRUPOS_CONSUMO_ORDEN))
    sel = cargar(R.seleccion)
    if sel is not None:
        with st.expander("Qué algoritmo usa cada grupo"):
            st.dataframe(sel, hide_index=True, use_container_width=True)

    if "modelo_1m" in pred6.columns:
        n_regla = int(pred6["modelo_1m"].eq("REGLA_CERO_SOSTENIDO").sum())
        if n_regla:
            st.caption(f"**{n_regla:,}** clientes con la regla de cero sostenido (dos meses en casi cero): su pronóstico es "
                       "persistencia, sin recuperación inventada. Se ven con modelo = REGLA_CERO_SOSTENIDO.")
    reg_v = cargar(R.base / "12_versiones_modelos" / "registro_versiones.csv")
    if reg_v is not None and len(reg_v):
        with st.expander("Versiones de los modelos (12_versiones_modelos)"):
            st.dataframe(reg_v, hide_index=True, use_container_width=True)
            reg_u = cargar(R.base / "12_versiones_modelos" / "registro_uso.csv")
            if reg_u is not None:
                st.caption("Qué versión usó cada corte:")
                st.dataframe(reg_u, hide_index=True, use_container_width=True)

    st.subheader("Clientes por grupo de consumo")
    cg = pred6["grupo_consumo"].value_counts().rename("clientes").to_frame() if "grupo_consumo" in pred6.columns else pred6["perfil"].value_counts().rename("clientes").to_frame()
    cg = cg.reindex([g for g in GRUPOS_CONSUMO_ORDEN if g in cg.index])
    st.dataframe(cg, use_container_width=True)
    st.caption("Los archivos del pronóstico por grupo, con zona, clase de servicio y valor facturado, están en la sección "
               "**Descargas por grupo**.")


# ----------------------------------------------------------------------------
# Descargas por grupo
# ----------------------------------------------------------------------------
elif seccion == "Descargas por grupo":
    st.title("Descargas por grupo de consumo")
    idx = cargar(R.indice_exportes)
    if idx is None or len(idx) == 0:
        st.warning("No existe 11_exportes_negocio/indice_exportes.csv. Corre el pipeline (paso 15).")
        st.stop()
    st.caption("Archivos que deja el pipeline en 11_exportes_negocio: una lista por grupo de consumo y una con todos, "
               "con zona, clase de servicio, tipo de medidor y de lectura, promedio semestral y valor facturado.")
    st.markdown(" · ".join(f"**{g}**: {GRUPO_CONSUMO_DESCRIPCION[g]}" for g in GRUPOS_CONSUMO_ORDEN))
    NOMBRES_PRODUCTO = {"pronostico_6_meses": "Pronóstico a 6 meses", "lista_caida": "Lista de caída de consumo",
                        "riesgo_fuga": "Riesgo de fuga a otro comercializador"}
    for producto, t in idx.groupby("producto", sort=False):
        st.subheader(NOMBRES_PRODUCTO.get(producto, producto))
        for r in t.itertuples():
            ruta = R.base / r.archivo
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.markdown(f"**{r.grupo_consumo}** — {int(r.clientes):,} clientes · corte {r.fecha_corte}")
            c2.caption(Path(r.archivo).name)
            if ruta.exists():
                c3.download_button("Descargar", ruta.read_bytes(), file_name=ruta.name, mime="text/csv",
                                   key=f"dl_{producto}_{r.grupo_consumo}_{Path(r.archivo).name}")
            else:
                c3.caption("no encontrado")


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
        idx_cols = ["fecha_corte"] + [c for c in ["fecha_corte_modelo", "meses_desde_entrenamiento"] if c in sg.columns]
        piv = sg.pivot_table(index=idx_cols, columns="horizonte", values="WAPE_pct").round(1)
        st.dataframe(piv, use_container_width=True)
        if "fecha_corte_modelo" in sg.columns:
            st.caption("fecha_corte_modelo: con qué versión del modelo se hizo cada pronóstico; meses_desde_entrenamiento: "
                       "cuánto llevaba sin reentrenar. Si el WAPE sube con esa antigüedad, toca reentrenar (estado_modelos.py lo dice).")
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

    sf = cargar(R.fuga_seguimiento)
    if sf is not None and len(sf):
        st.subheader("Riesgo de fuga: señalados en cortes anteriores que efectivamente se fueron")
        st.dataframe(sf, hide_index=True, use_container_width=True)

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
