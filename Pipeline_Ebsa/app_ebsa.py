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

Vistas (barra lateral)
----------------------
  Comercial          : Panorama (cifras del corte y mapa de Boyacá), Clientes con probabilidad de fuga, Grandes caídas de
                       consumo, Clientes sin consumo (en cero o casi cero), Clientes que ya se fueron, Descargas. Lenguaje de negocio.
  Soporte            : Consultar un cliente (ficha en lenguaje simple: dónde está, qué le pasa, qué revisar),
                       Visitas por ciclo (ruta con dirección y municipio), Registrar resultado de visitas.
  Administrador      : todo lo técnico, que son las secciones de abajo.

Secciones de Administrador del modelo
-------------------------------------
  Resumen            : cifras del corte actual y lo que cambió frente al anterior
  Gestión por ciclo  : la lista operativa, ciclo por ciclo, para repartir a cuadrillas
  Ranking gerencial  : los clientes de mayor valor en riesgo, con filtros
  Riesgo de fuga     : clientes con probabilidad de irse a otro comercializador, los que ya se fueron,
                       vigilancia del mercado no regulado y calidad del modelo
  Cortes             : valor en riesgo por clase, estrato, zona y tramo
  Mapa               : municipios de Boyacá con clientes, caídas y riesgo de fuga (necesita el cruce con TC1)
  Buscar cliente     : todo lo que el proyecto sabe de un NIU (segmento, caída, pronóstico, fuga, ubicación)
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
    CLASES_SIN_GESTION, ZONAS_REGIONALES, ZONA_REGIONAL_POR_CICLO,
    enriquecer_glosario, grupo_desde_perfil, nombre_zona, nombre_zona_regional, nombre_clase,
)

# ----------------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------------
st.set_page_config(page_title="EBSA — Consumo de clientes", page_icon="⚡", layout="wide")
st.markdown("""<style>
[data-testid="stMetricValue"] { font-size: 1.55rem; white-space: normal; overflow: visible; text-overflow: clip; line-height: 1.2; }
[data-testid="stMetricLabel"] { white-space: normal; }
</style>""", unsafe_allow_html=True)

# Carpeta de datos, en este orden: variable de entorno EBSA_DATOS; una carpeta "datos" junto a la app
# (paquete para compañeros, ver empaquetar_app.py); la carpeta de siempre.
_DATOS_JUNTO_A_LA_APP = Path(__file__).resolve().parent / "datos"
DATOS_POR_DEFECTO = os.environ.get("EBSA_DATOS") or (str(_DATOS_JUNTO_A_LA_APP) if _DATOS_JUNTO_A_LA_APP.is_dir()
                                                     else r"C:\Users\Home\Documents\Datos_Ebsa")

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
    "ALTO": "Está en el 1 % de clientes con mayor puntaje del modelo (y por encima del riesgo promedio). Contactar primero.",
    "MEDIO": "Está entre el 1 % y el 5 % con mayor puntaje del modelo. Vigilar y contactar según valor.",
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


def fmt_n(x, dec: int = 0) -> str:
    """Número en formato colombiano: punto de miles y coma decimal (4.025.507 / 15,5)."""
    if x is None or (isinstance(x, float) and np.isnan(x)) or (hasattr(pd, "isna") and pd.isna(x)):
        return "—"
    t = f"{float(x):,.{dec}f}"
    return t.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def pesos(x) -> str:
    return "—" if pd.isna(x) else "$" + fmt_n(x)


def pesos_md(x) -> str:
    """Para st.markdown: el signo $ se escapa, si no Streamlit lo toma como fórmula matemática."""
    return "—" if pd.isna(x) else "\\$" + fmt_n(x)


def kwh(x) -> str:
    return "—" if pd.isna(x) else fmt_n(x) + " kWh"


def csv_es(df: pd.DataFrame) -> bytes:
    """CSV para Excel en español: separador ';' y coma decimal, con BOM para que abra con tildes."""
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


def tabla_con_ficha(df: pd.DataFrame, clave: str, vista_destino: str = "Soporte", **kw):
    """Tabla donde al hacer clic en una fila se abre debajo la ficha del cliente. El botón para ir a
    Consultar un cliente solo se muestra dentro de la misma vista (nunca de Comercial a Soporte). df debe tener columna NIU."""
    ev = tabla(df, on_select="rerun", selection_mode="single-row", key=f"tbl_{clave}", **kw)
    st.caption("Haz clic en una fila para ver la ficha del cliente debajo.")
    filas = []
    try:
        filas = list(ev.selection.rows)
    except Exception:
        filas = []
    # La selección queda guardada en la sesión por posición de fila. Si la tabla se recalcula con menos
    # filas (corrida nueva del pipeline, otro filtro), esa posición puede no existir ya: se descarta y
    # no se muestra ficha hasta que el usuario haga clic de nuevo (corrección 2026-10-07).
    filas = [f for f in filas if isinstance(f, int) and 0 <= f < len(df)]
    if filas:
        niu_sel = str(df.iloc[filas[0]]["NIU"]).strip()
        st.divider()
        c1, c2 = st.columns([3, 1])
        c1.subheader(f"Cliente {niu_sel}")
        # Regla (2026-10-09): desde Comercial NO se salta a Soporte. "Consultar un cliente" es solo de Soporte; en
        # Comercial la ficha se ve aquí mismo, desplegada bajo la tabla. El botón solo aparece dentro de la misma vista.
        if st.session_state.get("vista") == vista_destino and c2.button("Abrir en Consultar un cliente", key=f"ir_{clave}"):
            st.session_state["ir_a"] = (vista_destino, "Consultar un cliente" if vista_destino == "Soporte" else "Buscar cliente", niu_sel)
            st.rerun()
        ficha_cliente_simple(niu_sel)
    return ev


def n_evaluados_caida() -> int | None:
    e = cargar(R.estudio_caida, columns=["NIU"])
    return None if e is None else int(e["NIU"].nunique())


def linea_conteo(mostrados: int, filtrados: int, en_lista: int, universo: int | None = None,
                 que: str = "clientes", que_lista: str = "en toda la lista", que_universo: str = "clientes evaluados en total") -> None:
    """'Se muestran 100 de 2.405 clientes con los filtros · 2.405 en toda la lista · 48.094 clientes evaluados en total'."""
    txt = f"Se muestran **{fmt_n(mostrados)}** de **{fmt_n(filtrados)}** {que}"
    txt += " con los filtros actuales" if filtrados != en_lista else ""
    if filtrados != en_lista:
        txt += f" · **{fmt_n(en_lista)}** {que_lista}"
    if universo:
        txt += f" · **{fmt_n(universo)}** {que_universo}"
    st.markdown(txt)


def prob_pct(p) -> str:
    """Probabilidad en %, con decimales suficientes para que 0,004 % no se lea como 0,0 %."""
    if pd.isna(p):
        return "—"
    v = float(p) * 100
    if v >= 1:
        return fmt_n(v, 1) + " %"
    if v >= 0.01:
        return fmt_n(v, 2) + " %"
    return "< 0,01 %" if v > 0 else "0 %"


PRIORIDAD_SIMPLE = {"GESTIONAR": "Gestionar", "SEGUIMIENTO: caída antigua": "Seguimiento: lleva meses así",
                    "VIGILAR: se espera recuperación": "Vigilar: se espera recuperación",
                    "VIGILAR: estacional": "Vigilar: estacional (temporada baja)"}
ORDEN_PRIORIDAD = {"GESTIONAR": 0, "SEGUIMIENTO: caída antigua": 1, "VIGILAR: se espera recuperación": 2, "VIGILAR: estacional": 3}
TIPO_CAIDA_SIMPLE = {"CAIDA_CONFIRMADA": "Reciente", "CAIDA_SOSTENIDA": "Lleva meses así"}


def referencia_caida(df):
    """Consumo con el que se midió la pérdida (kWh/mes): consumo reciente + pérdida. En una caída reciente (cae frente al periodo
    anterior y frente al año pasado) es la MENOR de esas dos referencias, para no exagerar la pérdida; en una caída que lleva meses es
    la del año pasado. Es el "consumía" coherente con los pesos que se muestran; si faltan columnas, se usa el periodo anterior."""
    if "perdida_kwh_mes" in df.columns and "consumo_reciente_kwh" in df.columns:
        ref = pd.to_numeric(df["consumo_reciente_kwh"], errors="coerce").fillna(0) + pd.to_numeric(df["perdida_kwh_mes"], errors="coerce")
        return ref.fillna(pd.to_numeric(df["consumo_anterior_kwh"], errors="coerce")) if "consumo_anterior_kwh" in df.columns else ref
    return pd.to_numeric(df["consumo_anterior_kwh"], errors="coerce")


def caida_vs_referencia_pct(df):
    """Caída del consumo reciente frente a la referencia de la pérdida, en % (negativo = cayó)."""
    ref = referencia_caida(df)
    return (pd.to_numeric(df["consumo_reciente_kwh"], errors="coerce") - ref) / ref.where(ref > 0) * 100


# ----------------------------------------------------------------------------
# Carga de datos (con caché: se relee solo si cambia el archivo)
# ----------------------------------------------------------------------------
# Memoria (corrección 2026-10-09, revisión ronda 2): con st.cache_data cada llamada devolvía una COPIA completa de la
# tabla, y la página relee sus tablas en cada clic: con el pronóstico (580.000 filas) y la ubicación (596.000) eso eran
# cientos de MB nuevos por clic, y el servidor llegó a pasar de 6 GB en una sola sesión. Ahora las tablas se guardan
# una sola vez (st.cache_resource) y cada uso recibe una vista liviana (copia superficial). Con "copy on write" de
# pandas, modificar esa vista nunca altera la tabla guardada.
try:
    pd.options.mode.copy_on_write = True
except Exception:  # pandas 3 ya lo trae siempre activo
    pass


@st.cache_resource(show_spinner=False, max_entries=64)
def leer_csv(ruta: str, mtime: float, **kw) -> pd.DataFrame:
    kw.setdefault("low_memory", False)   # CSV grandes con columnas mixtas: una sola pasada, sin avisos ni fallos de pandas
    return pd.read_csv(ruta, encoding="utf-8-sig", **kw)


@st.cache_resource(show_spinner=False, max_entries=32)
def leer_parquet(ruta: str, mtime: float, columns=None) -> pd.DataFrame:
    return pd.read_parquet(ruta, columns=list(columns) if columns is not None else None, engine="pyarrow")


def cargar(ruta: Path, columns=None, **kw):
    """Devuelve el DataFrame o None si el archivo no existe. Es una vista liviana de la tabla guardada en caché."""
    if not ruta.exists():
        return None
    mtime = ruta.stat().st_mtime
    if ruta.suffix == ".parquet":
        return leer_parquet(str(ruta), mtime, columns=tuple(columns) if columns is not None else None).copy(deep=False)
    return leer_csv(str(ruta), mtime, **kw).copy(deep=False)


# Texto de apoyo que ve el usuario en las secciones principales
QUE_ES_ESTO = (
    "**Qué es esto.** El sistema lee cada mes los archivos TC2 de la empresa y hace tres cosas: "
    "(1) **detecta clientes cuyo consumo cayó** más de lo normal para clientes parecidos y los ordena por la facturación que se está perdiendo, "
    "para que el área comercial y las cuadrillas sepan a quién revisar primero; "
    "(2) **estima la probabilidad de fuga** de cada cliente a otro comercializador en los próximos seis meses; "
    "(3) **pronostica el consumo** de cada cliente a seis meses. El valor en pesos siempre usa la tarifa real del cliente, nunca una tarifa supuesta."
)

UMBRAL_CONFIABLE_PCT = 5.0   # mismo valor por defecto que proyeccion_anual_consumo.py (--umbral)

COLUMNAS_PESOS_PISTAS = ("valor", "perdida", "pérdida", "factura", "$", "pesos", "tarifa_kwh")
COLUMNAS_KWH_PISTAS = ("kwh", "consumo")


def tabla(df: pd.DataFrame, **kw):
    """st.dataframe con las columnas de pesos en formato $ con separador de miles y las de kWh con miles.
    Se detectan por el nombre de la columna; si ya viene column_config, se respeta."""
    if df is None:
        return None
    cfg = dict(kw.pop("column_config", None) or {})
    d = df
    try:
        d = df.copy()
        for c in df.columns:
            if c in cfg or not pd.api.types.is_numeric_dtype(df[c]):
                continue
            n = str(c).lower()
            if "pct" in n or "prob" in n or n in ("ranking", "puesto", "orden", "orden_en_ciclo", "estrato", "prioridad"):
                continue
            if any(p in n for p in COLUMNAS_PESOS_PISTAS):
                d[c] = df[c].map(lambda v: "" if pd.isna(v) else "$" + fmt_n(v))
                cfg[c] = st.column_config.TextColumn(c, help="Pesos por mes")
            elif any(p in n for p in COLUMNAS_KWH_PISTAS):
                dec = 0 if (df[c].dropna() % 1 == 0).all() else 1
                d[c] = df[c].map(lambda v, dec=dec: "" if pd.isna(v) else fmt_n(v, dec))
                cfg[c] = st.column_config.TextColumn(c)
    except Exception:
        d, cfg = df, (cfg or None)
    return st.dataframe(d, column_config=cfg or None, **kw)


_NOMBRE_A_REGIONAL = {ZONA_POR_CICLO[c]: z for c, z in ZONA_REGIONAL_POR_CICLO.items()}


def agregar_zona_regional(df: pd.DataFrame) -> pd.DataFrame:
    """Zona regional (8 direcciones) para listas viejas que no la traen: desde el ciclo, la etiqueta de ciclo o el nombre de zona."""
    if df is None or "zona_regional" in df.columns:
        return df
    d = df.copy()
    if "ciclo" in d.columns:
        d["zona_regional"] = nombre_zona_regional(d["ciclo"])
    elif "ciclo_etiqueta" in d.columns:
        d["zona_regional"] = nombre_zona_regional(pd.to_numeric(d["ciclo_etiqueta"], errors="coerce"))
    elif "zona_nombre" in d.columns:
        d["zona_regional"] = d["zona_nombre"].map(_NOMBRE_A_REGIONAL).fillna(d["zona_nombre"])
    elif "NIU" in d.columns:
        # Listas sin ciclo (p. ej. clientes_cero_sostenido.csv de una corrida anterior): ciclo actual desde niu_ciclo.parquet
        nc = ciclo_actual_por_niu()
        if nc is not None:
            d["_niu"] = d["NIU"].astype("string").str.strip()
            d = d.merge(nc, left_on="_niu", right_on="NIU_nc", how="left").drop(columns=["_niu", "NIU_nc"])
            d["zona_regional"] = nombre_zona_regional(d.pop("_ciclo_nc"))
        else:
            d["zona_regional"] = "SIN ZONA"
    else:
        d["zona_regional"] = "SIN ZONA"
    return d


def ciclo_actual_por_niu() -> pd.DataFrame | None:
    """NIU -> ciclo actual (último conocido) de todos los clientes, desde 03_serie_modelado/niu_ciclo.parquet."""
    try:
        nc = cargar(R.niu_ciclo)
    except NameError:
        return None
    if nc is None or "NIU" not in nc.columns:
        return None
    col = "ciclo_actual" if "ciclo_actual" in nc.columns else "ciclo"
    out = pd.DataFrame({"NIU_nc": nc["NIU"].astype("string").str.strip(), "_ciclo_nc": pd.to_numeric(nc[col], errors="coerce")})
    return out.drop_duplicates("NIU_nc")


def limpiar_lista(df: pd.DataFrame) -> pd.DataFrame:
    """Reglas de negocio aplicadas también en la página (por si la carpeta trae salidas de una versión anterior):
    fuera autogeneradores y las clases sin gestión (AC, AU, RI, PR)."""
    if df is None:
        return None
    d = df
    if "clase_servicio" in d.columns:
        d = d[~d["clase_servicio"].astype(str).str.strip().str.upper().isin(CLASES_SIN_GESTION)]
    if "zona_nombre" in d.columns:
        d = d[~d["zona_nombre"].astype(str).str.upper().eq("AUTOGENERADORES")]
    if "consumo_reciente_kwh" in d.columns and "meses_ventana" in d.columns:
        # cero sostenido (3+ meses en 0): ya no consume, no es una caída para revisar
        d = d[~((pd.to_numeric(d["consumo_reciente_kwh"], errors="coerce").fillna(0) <= 0)
                & (pd.to_numeric(d["meses_ventana"], errors="coerce").fillna(0) >= 3))]
    if "severidad" in d.columns:
        # Gravedad que se muestra a negocio: una caída que lleva meses así (CAIDA_SOSTENIDA) no se presenta como "grave"
        # aunque su tamaño lo sea; "grave" queda para caídas recientes. La severidad original sigue en la vista técnica.
        d = d.copy()
        _antigua = d["veredicto"].astype(str).eq("CAIDA_SOSTENIDA") if "veredicto" in d.columns else False
        d["gravedad"] = np.where(_antigua, "ANTIGUA", d["severidad"].astype(str))
    return agregar_zona_regional(d.reset_index(drop=True))


def filtro_zona_regional(col, df: pd.DataFrame, clave: str):
    if df is None or "zona_regional" not in df.columns:
        return []
    return col.multiselect("Zona regional", [z for z in ZONAS_REGIONALES if z in set(df["zona_regional"].astype(str))]
                           + sorted(set(df["zona_regional"].dropna().astype(str)) - set(ZONAS_REGIONALES)),
                           key=clave, placeholder="Todas", help="Agrupa el ciclo urbano, el rural y los seccionales de una misma dirección regional")


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
        self.cero_sostenido = self.gestion / "clientes_cero_sostenido.csv"
        # Proyección anual por zona (paso aparte: python proyeccion_anual_consumo.py)
        self.proy_dir = base / "14_proyeccion_anual"
        self.proy_mensual = self.proy_dir / "proyeccion_mensual_por_zona.csv"
        self.proy_anual = self.proy_dir / "proyeccion_anual_por_zona.csv"
        self.proy_error = self.proy_dir / "error_backtest_por_zona.csv"
        self.proy_comparacion = self.proy_dir / "comparacion_pronostico_individual.csv"
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
        self.niu_ciclo = base / "03_serie_modelado" / "niu_ciclo.parquet"
        self.autogeneradores = base / "03_serie_modelado" / "nius_autogeneradores_excluidos.parquet"
        # Ubicación (cruce aparte con el TC1: python cruzar_ubicacion_tc1.py)
        self.ubicacion = base / "13_ubicacion_clientes" / "ubicacion_clientes.parquet"
        self.municipios = base / "13_ubicacion_clientes" / "municipios_zona.csv"


# ----------------------------------------------------------------------------
# Barra lateral
# ----------------------------------------------------------------------------
st.sidebar.title("⚡ EBSA — Consumo")


# ----------------------------------------------------------------------------
# Usuarios: se leen de .streamlit/secrets.toml (fuera de Git). Cada usuario tiene
# una clave y la lista de vistas que puede abrir. Ver secrets.toml.ejemplo.
# ----------------------------------------------------------------------------
def _usuarios() -> dict | None:
    try:
        return {str(u): dict(v) for u, v in st.secrets["usuarios"].items()}
    except Exception:
        return None


USUARIOS = _usuarios()
if not USUARIOS:
    st.title("Falta el archivo de usuarios")
    st.error("No encuentro usuarios en `.streamlit\\secrets.toml` (en la carpeta desde la que se lanza la página). "
             "Copia `secrets.toml.ejemplo` como `.streamlit\\secrets.toml`, cambia las claves y vuelve a abrir la página.")
    st.stop()

if "usuario" not in st.session_state:
    st.title("⚡ EBSA — Consumo de clientes")
    st.caption("Ingresa con tu usuario. *comercial* ve la vista Comercial; *soporte* ve Soporte y Comercial; *admin* ve todo, incluida la del administrador del modelo.")
    with st.form("ingreso"):
        u = st.text_input("Usuario")
        c = st.text_input("Clave", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if u in USUARIOS and c and c != "CAMBIAR" and c == str(USUARIOS[u].get("clave", "")):
                st.session_state["usuario"] = u
                st.rerun()
            st.error("Usuario o clave incorrectos.")
    st.stop()

USUARIO = st.session_state["usuario"]
PERFIL = USUARIOS.get(USUARIO) or {}
VISTAS_PERMITIDAS = [v for v in PERFIL.get("vistas", []) if v in ("Comercial", "Soporte", "Administrador del modelo")] or ["Comercial"]
ES_ADMIN = "Administrador del modelo" in VISTAS_PERMITIDAS
st.sidebar.caption(f"Sesión: **{PERFIL.get('nombre', USUARIO)}**")
if st.sidebar.button("Cerrar sesión", key="btn_salir"):
    for k in ("usuario", "vista", "seccion", "ruta_datos"):
        st.session_state.pop(k, None)
    st.rerun()

if ES_ADMIN:
    ruta_datos = st.sidebar.text_input("Carpeta de datos", DATOS_POR_DEFECTO, key="ruta_datos")
else:
    ruta_datos = DATOS_POR_DEFECTO   # los demás usuarios siempre ven la carpeta oficial
R = Rutas(Path(ruta_datos))

if not R.base.exists():
    st.error(f"No existe la carpeta de datos: {R.base}")
    st.stop()

# Tres vistas, una por público. Comercial y Soporte hablan en lenguaje de negocio;
# Administrador del modelo conserva todo lo técnico (calidad, seguimiento, cortes, pipeline).
VISTAS = {
    "Comercial": ["Panorama", "Caídas de consumo", "Clientes sin consumo", "Clientes con probabilidad de fuga", "Clientes que ya se fueron",
                  "Proyección de consumo (compra de energía)", "Descargas"],
    "Soporte": ["Consultar un cliente", "Caídas de consumo", "Visitas por ciclo", "Registrar resultado de visitas"],
    "Administrador del modelo": [
        "Resumen", "Gestión por ciclo", "Ranking gerencial", "Riesgo de fuga", "Cortes", "Mapa", "Buscar cliente",
        "Pronóstico 6 meses", "Proyección de consumo (compra de energía)", "Descargas por grupo", "Seguimiento", "Retroalimentación", "Estado del pipeline",
    ],
}
VISTA_AYUDA = ("Comercial: cifras, mapa y listas para decidir a quién llamar. Soporte: la ficha de un cliente y las rutas de visita. "
               "Administrador del modelo: calidad de los modelos, cortes, seguimiento y estado del pipeline.")
# Navegación programática (botón "Abrir ficha" en las listas): se fija antes de crear los radios
if "ir_a" in st.session_state and st.session_state["ir_a"]:
    _v, _s, _niu = st.session_state.pop("ir_a")
    st.session_state["vista"] = _v
    st.session_state["seccion"] = _s
    st.session_state["sop_niu" if _v == "Soporte" else "adm_niu"] = _niu
VISTAS = {v: secs for v, secs in VISTAS.items() if v in VISTAS_PERMITIDAS}
if st.session_state.get("vista") not in VISTAS:
    st.session_state["vista"] = list(VISTAS)[0]
vista = st.sidebar.radio("Vista", list(VISTAS), help=VISTA_AYUDA, horizontal=True, key="vista")
if st.session_state.get("seccion") not in VISTAS[vista]:
    st.session_state["seccion"] = VISTAS[vista][0]
seccion = st.sidebar.radio("Sección", VISTAS[vista], key="seccion")
# Secciones de Comercial/Soporte que reutilizan una pantalla técnica
seccion = {"Descargas": "Descargas por grupo", "Registrar resultado de visitas": "Retroalimentación"}.get(seccion, seccion)

operativa = limpiar_lista(cargar(R.operativa, dtype={"NIU": "string", "ciclo_etiqueta": "string"}))
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
@st.cache_resource(show_spinner="Cargando el pronóstico...", max_entries=2)
def pronostico_preparado(ruta: str, mtime: float) -> tuple:
    """Pronóstico a 6 meses listo para usar (una sola vez por archivo): NIU normalizado, grupo de consumo y su corte."""
    d = pd.read_parquet(ruta, engine="pyarrow")
    d["NIU"] = d["NIU"].astype("string").str.strip()
    if "grupo_consumo" not in d.columns and "perfil" in d.columns:
        d["grupo_consumo"] = grupo_desde_perfil(d["perfil"])
    return d, str(pd.to_datetime(d["fecha_corte"]).max())[:7]


pred6 = None
if R.pred6.exists():
    pred6, _corte_pred6 = pronostico_preparado(str(R.pred6), R.pred6.stat().st_mtime)
    pred6 = pred6.copy(deep=False)
    st.sidebar.caption(f"Pronóstico: corte **{_corte_pred6}**")
fuga = limpiar_lista(cargar(R.fuga_scores, dtype={"NIU": "string"}))
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


@st.cache_data(show_spinner="Buscando el último mes con consumo de cada cliente...")
def ultimo_mes_con_consumo(ruta: str, mtime: float, nius: tuple, hasta: str | None) -> pd.DataFrame:
    """Para una lista de NIU: último mes con consumo > 0 y meses en cero desde entonces (lee la serie con filtro)."""
    d = pd.read_parquet(ruta, engine="pyarrow", columns=["NIU", "periodo", "consumo_kwh_mensual"], filters=[("NIU", "in", list(nius))])
    d["NIU"] = d["NIU"].astype("string").str.strip()
    d["periodo"] = pd.to_datetime(d["periodo"])
    if hasta:
        d = d[d["periodo"] <= pd.Timestamp(hasta + "-01") + pd.offsets.MonthEnd(0)]
    ult = d[d["consumo_kwh_mensual"].fillna(0) > 0].groupby("NIU")["periodo"].max().rename("ultimo_mes_con_consumo")
    ult_dato = d.groupby("NIU")["periodo"].max().rename("_ultimo_dato")
    out = pd.concat([ult, ult_dato], axis=1).reset_index()
    out["meses_en_cero"] = ((out["_ultimo_dato"].dt.year - out["ultimo_mes_con_consumo"].dt.year) * 12
                            + (out["_ultimo_dato"].dt.month - out["ultimo_mes_con_consumo"].dt.month)).astype("Int64")
    out["ultimo_mes_con_consumo"] = out["ultimo_mes_con_consumo"].dt.strftime("%Y-%m")
    return out.drop(columns=["_ultimo_dato"])


# ----------------------------------------------------------------------------
# Ubicación de los clientes (13_ubicacion_clientes, cruce aparte con el TC1)
# ----------------------------------------------------------------------------
COLS_UBICACION = ["NIU", "codigo_municipio", "municipio", "provincia", "departamento", "zona_mapa", "direccion",
                  "ubicacion_sui", "nivel_tension", "circuito", "transformador", "latitud", "longitud", "altitud",
                  "coordenadas_validas", "autogenerador_tc1", "periodo_tc1"]
@st.cache_resource(show_spinner="Cargando la ubicación de los clientes...", max_entries=2)
def ubicacion_preparada(ruta: str, mtime: float) -> pd.DataFrame:
    """Cruce con el TC1 con el NIU ya normalizado (una sola vez por archivo)."""
    import pyarrow.parquet as _pq
    disponibles = set(_pq.read_schema(ruta).names)
    d = pd.read_parquet(ruta, columns=[c for c in COLS_UBICACION if c in disponibles], engine="pyarrow")
    d["NIU"] = d["NIU"].astype("string").str.strip()
    return d


ubicacion = ubicacion_preparada(str(R.ubicacion), R.ubicacion.stat().st_mtime).copy(deep=False) if R.ubicacion.exists() else None
if ubicacion is not None:
    st.sidebar.caption(f"Ubicación (TC1): **{str(ubicacion['periodo_tc1'].iloc[0]) if len(ubicacion) else '—'}**")
municipios = cargar(R.municipios, dtype={"codigo_municipio": "string"})


def agregar_municipio(df: pd.DataFrame) -> pd.DataFrame:
    """Une municipio y provincia a una lista con columna NIU (si existe el cruce con el TC1)."""
    if ubicacion is None or df is None or "NIU" not in df.columns or "municipio" in df.columns:
        return df
    d = df.copy()
    d["NIU"] = d["NIU"].astype("string").str.strip()
    return d.merge(ubicacion[["NIU", "municipio", "provincia"]].drop_duplicates("NIU"), on="NIU", how="left")


def filtro_municipio(col, df: pd.DataFrame, clave: str):
    """Multiselect de municipio (solo si la lista ya trae la columna)."""
    if "municipio" not in df.columns:
        return []
    return col.multiselect("Municipio", sorted(df["municipio"].dropna().astype(str).unique()), key=clave, placeholder="Todos")


ZONA_MAPA_COLOR = {   # misma paleta del mapa de zonas de la empresa
    "CENTRO": "#F2C94C", "TUNDAMA": "#F08BC7", "SUGAMUXI": "#4F6FD1", "OCCIDENTE": "#8BC34A",
    "ORIENTE": "#EF5B5B", "NORTE": "#3CB8A3", "RICAURTE": "#4FB8F0", "PUERTO BOYACA": "#F2994A",
}


# ----------------------------------------------------------------------------
# Mapa de Boyacá por municipio (lo usan la vista Comercial y la de Administrador)
# ----------------------------------------------------------------------------
BOYACA_LIMITES = {"west": -74.75, "east": -71.85, "south": 4.35, "north": 7.15}   # caja del departamento
BOYACA_CENTRO = {"lat": 5.62, "lon": -73.35}


@st.cache_data(show_spinner=False)
def _metricas_municipio_cache(mtime_u: float, mtime_op: float, mtime_f: float, mtime_m: float) -> pd.DataFrame:
    """Una fila por municipio con clientes, lista de caída, riesgo de fuga y centro geográfico."""
    base = municipios[[c for c in ["codigo_municipio", "municipio", "provincia", "departamento", "zona_ebsa",
                                   "clientes_tc1", "clientes_en_serie", "lat_centro", "lon_centro"] if c in municipios.columns]].copy()
    base["codigo_municipio"] = base["codigo_municipio"].astype(str)
    llave = ubicacion[["NIU", "codigo_municipio"]].drop_duplicates("NIU")
    llave["codigo_municipio"] = llave["codigo_municipio"].astype(str)
    if operativa is not None:
        o = operativa[["NIU", "gravedad", "trayectoria", "valor_riesgo_mes", "perdida_kwh_mes"]].copy()
        o["NIU"] = o["NIU"].astype("string").str.strip()
        o = o.merge(llave, on="NIU", how="inner")
        ag = o.groupby("codigo_municipio").agg(
            caida_clientes=("NIU", "size"),
            caida_criticos=("gravedad", lambda x: int(x.eq("CRITICA").sum())),
            caida_acelerando=("trayectoria", lambda x: int(x.eq("CAIDA_ACELERANDO").sum())),
            caida_valor_mes=("valor_riesgo_mes", "sum"),
            caida_kwh_mes=("perdida_kwh_mes", "sum")).reset_index()
        base = base.merge(ag, on="codigo_municipio", how="left")
    if fuga is not None:
        f = fuga[["NIU", "nivel_riesgo", "valor_esperado_perdida_mes", "valor_en_riesgo_mes"]].copy()
        f["NIU"] = f["NIU"].astype("string").str.strip()
        f = f.merge(llave, on="NIU", how="inner")
        ag = f.groupby("codigo_municipio").agg(
            fuga_puntuados=("NIU", "size"),
            fuga_alto=("nivel_riesgo", lambda x: int(x.eq("ALTO").sum())),
            fuga_medio=("nivel_riesgo", lambda x: int(x.eq("MEDIO").sum())),
            fuga_perdida_esperada_mes=("valor_esperado_perdida_mes", "sum"),
            fuga_facturacion_mes=("valor_en_riesgo_mes", "sum")).reset_index()
        base = base.merge(ag, on="codigo_municipio", how="left")
    for c in base.columns:
        if c.startswith(("caida_", "fuga_")):
            base[c] = base[c].fillna(0)
    base["caida_pct_clientes"] = (base.get("caida_clientes", 0) / base["clientes_en_serie"].replace(0, np.nan) * 100).round(2)
    base["fuga_alto_medio"] = base.get("fuga_alto", 0) + base.get("fuga_medio", 0)
    # Solo Boyacá: los municipios vecinos (Santander, Cundinamarca, Casanare) quedan fuera del mapa
    if "departamento" in base.columns:
        base = base[base["departamento"].astype(str).str.contains("BOYAC", na=False)]
    return base[base["lat_centro"].notna() & base["lon_centro"].notna()].copy()


def metricas_municipio():
    """Tabla por municipio o None (con aviso) si falta el cruce con el TC1."""
    if municipios is None or ubicacion is None:
        st.warning("Falta el cruce con el TC1 para dibujar el mapa. Desde la carpeta del código corre una vez:  "
                   "python cruzar_ubicacion_tc1.py  (lee 00_formato_TC1 y deja 13_ubicacion_clientes). Después recarga esta página.")
        return None
    with st.spinner("Preparando el mapa (la primera vez tarda unos segundos; después queda en caché)..."):
        return _metricas_municipio_cache(R.ubicacion.stat().st_mtime, R.operativa.stat().st_mtime if R.operativa.exists() else 0,
                                         R.fuga_scores.stat().st_mtime if R.fuga_scores.exists() else 0, R.municipios.stat().st_mtime)


# (nombre que ve el usuario) -> (columna, unidad)
METRICAS_MAPA_TECNICO = {
    "Clientes (TC1)": ("clientes_tc1", "clientes"),
    "Clientes en la serie de modelado": ("clientes_en_serie", "clientes"),
    "Caída: clientes en la lista": ("caida_clientes", "clientes"),
    "Caída: % de los clientes del municipio en la lista": ("caida_pct_clientes", "%"),
    "Caída: clientes CRÍTICA": ("caida_criticos", "clientes"),
    "Caída: clientes con caída acelerando": ("caida_acelerando", "clientes"),
    "Caída: valor en riesgo / mes": ("caida_valor_mes", "$"),
    "Caída: kWh en riesgo / mes": ("caida_kwh_mes", "kWh"),
    "Fuga: clientes ALTO + MEDIO": ("fuga_alto_medio", "clientes"),
    "Fuga: clientes ALTO": ("fuga_alto", "clientes"),
    "Fuga: pérdida esperada / mes": ("fuga_perdida_esperada_mes", "$"),
}
METRICAS_MAPA_COMERCIAL = {
    "Facturación que se está perdiendo por caída de consumo ($/mes)": ("caida_valor_mes", "$"),
    "Clientes con caída de consumo para revisar": ("caida_clientes", "clientes"),
    "Clientes con caída grave reciente": ("caida_criticos", "clientes"),
    "Clientes con probabilidad de fuga alta o media": ("fuga_alto_medio", "clientes"),
    "Pérdida esperada por probabilidad de fuga ($/mes)": ("fuga_perdida_esperada_mes", "$"),
    "Clientes de EBSA en el municipio": ("clientes_tc1", "clientes"),
}


def _fmt_metrica(v, unidad):
    if unidad == "$ por cliente":
        return pesos(v) + " por cliente"
    if unidad == "por cada 1.000 clientes":
        return fmt_n(v, 1) + " por cada 1.000 clientes"
    return pesos(v) if unidad == "$" else (fmt_n(v, 2) + " %" if unidad == "%" else fmt_n(v) + " " + unidad)


def dibujar_mapa(mm: pd.DataFrame, metricas: dict, clave: str, puntos: bool = False, altura: int = 600) -> pd.DataFrame:
    """Mapa de Boyacá con un círculo por municipio; devuelve la tabla filtrada que se dibujó."""
    metricas = {k: v for k, v in metricas.items() if v[0] in mm.columns}
    c1, c2 = st.columns([3, 2])
    met_nombre = c1.selectbox("Qué mostrar en el mapa", list(metricas), key=f"met_{clave}")
    met_col, met_unidad = metricas[met_nombre]
    zonas_disp = sorted(mm["zona_ebsa"].dropna().astype(str).unique())
    zonas_sel = c2.multiselect("Zona", zonas_disp, key=f"zona_{clave}", placeholder="Todas las zonas")
    d = mm.copy()
    if zonas_sel:
        d = d[d["zona_ebsa"].astype(str).isin(zonas_sel)]
    d["zona_ebsa"] = d["zona_ebsa"].fillna("SIN ZONA").astype(str)
    d["valor"] = pd.to_numeric(d[met_col], errors="coerce").fillna(0)
    total_val = d["valor"].sum()
    # Los totales siempre se parecen entre sí: donde hay más clientes hay más de todo (Tunja, Duitama, Sogamoso).
    # La vista "en proporción" divide por los clientes del municipio y muestra dónde el problema pesa más.
    unidad_total = met_unidad
    d["valor_total"] = d["valor"]
    puede_proporcion = met_unidad != "%" and met_col != "clientes_tc1" and "clientes_tc1" in d.columns
    modo = st.radio("Tamaño de los círculos", ["Total del municipio", "En proporción a sus clientes"], horizontal=True, key=f"modo_{clave}",
                    help="Total: la cifra completa del municipio; los municipios grandes siempre salen grandes. En proporción: la cifra "
                         "dividida entre los clientes del municipio; muestra dónde el problema pesa más para su tamaño.") if puede_proporcion else "Total del municipio"
    en_proporcion = modo.startswith("En proporción")
    st.session_state[f"modo_texto_{clave}"] = ""
    if en_proporcion:
        cli = pd.to_numeric(d["clientes_tc1"], errors="coerce")
        if met_unidad == "clientes":
            d["valor"] = (d["valor"] / cli * 1000).where(cli > 0, 0).fillna(0)
            met_unidad = "por cada 1.000 clientes"
        else:
            d["valor"] = (d["valor"] / cli).where(cli > 0, 0).fillna(0)
            met_unidad = "$ por cliente" if met_unidad == "$" else f"{met_unidad} por cliente"
        st.session_state[f"modo_texto_{clave}"] = f" ({met_unidad})"
    # (el signo $ se escapa: Streamlit lo tomaría como fórmula matemática)
    st.markdown(f"**{fmt_n(len(d))}** municipios de Boyacá · {met_nombre.replace('$', chr(92) + '$')}: "
                f"**{_fmt_metrica(total_val, unidad_total).replace('$', chr(92) + '$') if unidad_total != '%' else '—'}**"
                + (f" · corte {corte_actual}" if corte_actual else ""))
    d["etiqueta"] = d["municipio"].astype(str) + " (" + d["provincia"].astype(str).str.title() + ")"
    d["valor_texto"] = d["valor"].map(lambda v: _fmt_metrica(v, met_unidad))

    dibujado = False
    try:
        import plotly.express as px
        d_plot = d[d["valor"] > 0] if met_unidad != "%" else d
        if len(d_plot) == 0:
            d_plot = d
        kw = dict(lat="lat_centro", lon="lon_centro", size="valor", color="zona_ebsa", hover_name="etiqueta",
                  hover_data={"valor_texto": True, "zona_ebsa": True, "clientes_tc1": ":,", "valor": False, "lat_centro": False, "lon_centro": False},
                  labels={"valor_texto": met_nombre, "zona_ebsa": "Zona", "clientes_tc1": "Clientes"},
                  color_discrete_map=ZONA_MAPA_COLOR, size_max=42, zoom=7.3, center=BOYACA_CENTRO, height=altura)
        if hasattr(px, "scatter_map"):
            fig = px.scatter_map(d_plot, map_style="carto-positron", **kw)
            fig.update_layout(map=dict(bounds=BOYACA_LIMITES))
        else:
            fig = px.scatter_mapbox(d_plot, mapbox_style="carto-positron", **kw)
            fig.update_layout(mapbox=dict(bounds=BOYACA_LIMITES))
        fig.update_layout(margin=dict(l=0, r=0, t=0, b=0),
                          legend=dict(title_text="Zona", orientation="h", yanchor="bottom", y=0.01, xanchor="left", x=0.01,
                                      bgcolor="rgba(255,255,255,0.85)"))
        fig.update_traces(marker=dict(opacity=0.8))
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True, "displaylogo": False})
        dibujado = True
    except ImportError:
        pass
    if not dibujado:
        st.caption("Para el mapa con nombres al pasar el mouse instala plotly (pip install plotly). Mientras tanto, mapa básico:")
        d_map = d[d["valor"] > 0].copy() if met_unidad != "%" else d.copy()
        escala = d_map["valor"].max() if len(d_map) and d_map["valor"].max() > 0 else 1
        d_map["tam_m"] = (np.sqrt(d_map["valor"] / escala) * 9000).clip(lower=800)
        d_map["color"] = d_map["zona_ebsa"].map(ZONA_MAPA_COLOR).fillna("#999999")
        st.map(d_map.rename(columns={"lat_centro": "lat", "lon_centro": "lon"}), size="tam_m", color="color", zoom=7, height=altura)
    st.caption("Cada círculo es un municipio (tamaño = la cifra elegida, color = zona EBSA). Pasa el mouse para ver el nombre y la cifra; "
               "la rueda del mouse acerca el mapa."
               + (" En proporción, un municipio con muy pocos clientes puede salir grande por unos pocos casos: mira también cuántos clientes tiene."
                  if en_proporcion else " En total, los municipios con más clientes salen siempre más grandes; cambia a *En proporción* para ver dónde pesa más."))

    with st.expander("Ver la tabla por zona y por municipio"):
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("**Por zona**")
            z = d.groupby("zona_ebsa").agg(municipios=("codigo_municipio", "size"), clientes=("clientes_tc1", "sum"),
                                           valor=("valor_total", "sum" if unidad_total != "%" else "mean")).reset_index()
            if en_proporcion:   # proporción de la zona = total de la zona / clientes de la zona (no el promedio de municipios)
                z["valor"] = (z["valor"] / z["clientes"] * (1000 if unidad_total == "clientes" else 1)).where(z["clientes"] > 0, 0).round(1)
            z = z.sort_values("valor", ascending=False).rename(columns={"zona_ebsa": "Zona", "valor": met_nombre + (f" ({met_unidad})" if en_proporcion else "")})
            tabla(z, hide_index=True, use_container_width=True)
        with c2:
            st.markdown("**Por municipio**")
            cols_m = [c for c in ["municipio", "provincia", "zona_ebsa", "clientes_tc1", "caida_clientes", "caida_criticos",
                                  "caida_valor_mes", "fuga_alto", "fuga_medio", "fuga_perdida_esperada_mes"] if c in d.columns]
            t = d.sort_values("valor", ascending=False)[cols_m].rename(columns={
                "municipio": "Municipio", "provincia": "Provincia", "zona_ebsa": "Zona", "clientes_tc1": "Clientes",
                "caida_clientes": "Con caída", "caida_criticos": "Caída crítica", "caida_valor_mes": "Facturación en riesgo $/mes",
                "fuga_alto": "Fuga ALTO", "fuga_medio": "Fuga MEDIO", "fuga_perdida_esperada_mes": "Pérdida esperada fuga $/mes"})
            tabla(t, hide_index=True, use_container_width=True, height=380)
            st.download_button("Descargar municipios (CSV)", csv_es(t),
                               file_name=f"mapa_municipios_{corte_actual or ''}.csv", mime="text/csv", key=f"dl_{clave}")

    if puntos:
        with st.expander("Ver clientes de una lista como puntos en el mapa"):
            opciones = {}
            if operativa is not None:
                opciones["Caída: severidad CRÍTICA"] = operativa[operativa["gravedad"].eq("CRITICA")][["NIU", "valor_riesgo_mes"]].rename(columns={"valor_riesgo_mes": "valor"})
                if "trayectoria" in operativa.columns:
                    opciones["Caída: caída acelerando"] = operativa[operativa["trayectoria"].eq("CAIDA_ACELERANDO")][["NIU", "valor_riesgo_mes"]].rename(columns={"valor_riesgo_mes": "valor"})
                opciones["Caída: toda la lista"] = operativa[["NIU", "valor_riesgo_mes"]].rename(columns={"valor_riesgo_mes": "valor"})
            if fuga is not None:
                opciones["Fuga: riesgo ALTO"] = fuga[fuga["nivel_riesgo"].eq("ALTO")][["NIU", "valor_esperado_perdida_mes"]].rename(columns={"valor_esperado_perdida_mes": "valor"})
                opciones["Fuga: riesgo ALTO + MEDIO"] = fuga[fuga["nivel_riesgo"].isin(["ALTO", "MEDIO"])][["NIU", "valor_esperado_perdida_mes"]].rename(columns={"valor_esperado_perdida_mes": "valor"})
            if not opciones:
                st.info("No hay listas cargadas.")
            else:
                lista_sel = st.selectbox("Lista", list(opciones), key=f"pts_{clave}")
                pts = opciones[lista_sel].copy()
                pts["NIU"] = pts["NIU"].astype("string").str.strip()
                pts = pts.merge(ubicacion[["NIU", "municipio", "zona_mapa", "latitud", "longitud", "coordenadas_validas"]], on="NIU", how="inner")
                pts = pts[pts["coordenadas_validas"].fillna(False).astype(bool)]
                if zonas_sel:
                    pts = pts[pts["zona_mapa"].astype(str).isin(zonas_sel)]
                tope = 20000
                st.caption(f"{fmt_n(len(pts))} clientes con coordenadas" + (f"; se dibujan los {fmt_n(tope)} de mayor valor" if len(pts) > tope else ""))
                pts = pts.sort_values("valor", ascending=False).head(tope)
                pts["color"] = pts["zona_mapa"].map(ZONA_MAPA_COLOR).fillna("#999999")
                st.map(pts.rename(columns={"latitud": "lat", "longitud": "lon"}), color="color", size=250, zoom=7, height=520)
    return d


# ----------------------------------------------------------------------------
# Textos en lenguaje de negocio (vistas Comercial y Soporte)
# ----------------------------------------------------------------------------
TRAYECTORIA_SIMPLE = {
    "CAIDA_ACELERANDO": "Se prevé que baje más",
    "SIN_RECUPERACION_PREVISTA": "Se quedó en el nivel bajo",
    "RECUPERACION_PREVISTA": "Se espera que se recupere",
    "SIN_PRONOSTICO": "Sin pronóstico",
}
SEVERIDAD_SIMPLE = {"CRITICA": "Grave", "FUERTE": "Fuerte", "MODERADA": "Moderada", "ANTIGUA": "Antigua (lleva meses así)"}
GRIS_ANTIGUA = "#9aa0a6"
ESTADO_LISTA_SIMPLE = {"NUEVO": "Nuevo este mes", "PERSISTENTE": "Sigue desde el corte anterior", "REINCIDENTE": "Ya había estado antes", "": ""}
NIVEL_FUGA_SIMPLE = {"ALTO": "Alto: contactar primero", "MEDIO": "Medio: vigilar y contactar según valor", "BAJO": "Bajo"}


def que_revisar(fila) -> str:
    """Sugerencia en lenguaje simple para quien atiende al cliente, a partir de lo que dice la lista de caída."""
    t = str(fila.get("trayectoria", ""))
    sev = str(fila.get("gravedad", ""))
    clase = str(fila.get("clase_servicio_nombre", "")).lower()
    partes = []
    if str(fila.get("prioridad_gestion", "")) == "VIGILAR: estacional":
        return ("Cliente estacional: ya estuvo en cero en temporadas anteriores y volvió, y el modelo prevé que vuelva a consumir. "
                "No requiere visita; confirmar con el cliente cuándo reanuda actividad.")
    antigua = str(fila.get("veredicto", "")) == "CAIDA_SOSTENIDA"
    if antigua and t == "CAIDA_ACELERANDO":
        partes.append("La caída lleva meses y el modelo prevé que siga bajando: no es urgente, pero conviene revisarlo primero "
                      "dentro del seguimiento y confirmar qué cambió.")
    elif t == "CAIDA_ACELERANDO":
        partes.append("El consumo viene bajando y el modelo prevé que siga bajando: conviene contactar pronto.")
    elif antigua and t == "SIN_RECUPERACION_PREVISTA":
        partes.append("La caída no es de ahora: bajó hace meses frente al año pasado y se quedó en ese nivel. No es urgente; "
                      "en el próximo contacto, confirmar qué cambió (actividad, equipos, ocupación del predio).")
    elif t == "SIN_RECUPERACION_PREVISTA":
        partes.append("El consumo bajó y se mantiene en ese nivel: preguntar si cambió la actividad, el horario o los equipos.")
    elif t == "RECUPERACION_PREVISTA":
        partes.append("El consumo bajó pero el modelo espera que vuelva: vigilar; no hace falta visita todavía.")
    if sev == "CRITICA":
        partes.append("La caída es grave frente a clientes parecidos: revisar medidor, lectura y posibles fallas antes de dar por buena la cifra.")
    if "industrial" in clase or "comercial" in clase:
        partes.append("Cliente de negocio: una caída así suele ser cambio de actividad, cierre parcial, autogeneración o paso a otro comercializador.")
    if "oficial" in clase:
        partes.append("Entidad oficial: verificar si hubo cierre temporal, traslado o cambio de sede.")
    return " ".join(partes) if partes else "Revisar la lectura y el consumo reciente con el cliente."


def limpiar_niu(texto) -> str:
    """NIU tal como lo escribe o pega el usuario: sin espacios y sin el '.0' que añade Excel al copiar un número."""
    t = str(texto or "").strip()
    if t.endswith(".0") and t[:-2].isdigit():
        t = t[:-2]
    return t


def niu_existe(niu: str) -> bool:
    """¿Aparece el NIU en alguna de las tablas del corte? (ubicación TC1, pronóstico, lista de caída o probabilidad de fuga)"""
    for tabla_, col in ((ubicacion, "NIU"), (pred6, "NIU"), (operativa, "NIU"), (fuga, "NIU")):
        if tabla_ is not None and col in tabla_.columns and bool((tabla_[col].astype("string").str.strip() == niu).any()):
            return True
    cs_ = cargar(R.cero_sostenido, dtype={"NIU": "string"})
    return bool(cs_ is not None and (cs_["NIU"].astype("string").str.strip() == niu).any())


def ficha_cliente_simple(niu: str) -> None:
    """Qué sabe el proyecto de un cliente, contado para atención al cliente y campo."""
    u = ubicacion[ubicacion["NIU"] == niu] if ubicacion is not None else pd.DataFrame()
    o = operativa[operativa["NIU"] == niu] if operativa is not None else pd.DataFrame()
    fz = fuga[fuga["NIU"].astype("string").str.strip() == niu] if fuga is not None else pd.DataFrame()
    ya = cargar(R.fuga_ya_fuera, dtype={"NIU": "string"})
    yz = ya[ya["NIU"].astype("string").str.strip() == niu] if ya is not None else pd.DataFrame()
    vg_c = cargar(R.fuga_vigilancia, dtype={"NIU": "string"})
    vz = vg_c[vg_c["NIU"].astype("string").str.strip() == niu] if vg_c is not None else pd.DataFrame()
    auto_ex = cargar(R.autogeneradores)
    es_auto = bool(auto_ex is not None and niu in set(auto_ex["NIU"].astype("string").str.strip()))
    # (corrección 2026-10-09) un dato vacío del TC1 cuenta como "no": antes un vacío detenía la página con un error
    if len(u) and pd.notna(u["autogenerador_tc1"].iloc[0]) and bool(u["autogenerador_tc1"].iloc[0]):
        es_auto = True
    seg = cargar(R.clusters)
    sz = seg[seg["NIU"].astype("string").str.strip() == niu] if seg is not None else pd.DataFrame()
    ec = cargar(R.estudio_caida)
    ez = ec[ec["NIU"].astype("string").str.strip() == niu] if ec is not None else pd.DataFrame()

    # ----- Quién es y dónde está -----
    st.subheader("Quién es y dónde está")
    c1, c2, c3, c4 = st.columns(4)
    if len(u):
        uu = u.iloc[0]
        c1.metric("Municipio", str(uu.get("municipio", "—")))
        c2.metric("Zona", str(uu.get("zona_mapa", "—")) if pd.notna(uu.get("zona_mapa", np.nan)) else "—")
        c3.metric("Dirección", str(uu.get("direccion", "—"))[:28])
        c4.metric("Nivel de tensión", str(uu.get("nivel_tension", "—")))
    else:
        c1.metric("Municipio", "—")
        st.caption("Este NIU no está en el archivo TC1 cruzado (puede ser un cliente nuevo).")
    fuente = o.iloc[0] if len(o) else (fz.iloc[0] if len(fz) else (sz.iloc[0] if len(sz) else None))
    if fuente is not None:
        clase = fuente.get("clase_servicio_nombre", fuente.get("clase_servicio", "—"))
        grupo = fuente.get("grupo_consumo", "—")
        estrato = fuente.get("estrato", "—")
        st.markdown(f"Clase de servicio **{clase}** · estrato/sector **{estrato}** · tamaño **{grupo}**"
                    + (f" · segmento **{sz.iloc[0].get('cluster_id', '—')}**" if len(sz) else ""))
        if len(sz) and "segmento_descripcion" in sz.columns:
            st.caption(str(sz.iloc[0]["segmento_descripcion"]))

    # ----- Situación -----
    st.subheader("Situación hoy")
    avisos = []
    if es_auto:
        avisos.append(("warning", "**Autogenerador**: produce parte de su propia energía, por eso consume menos de la red. "
                                  "No aparece en las listas de caída ni de fuga; una caída en él no es un problema."))
    if len(yz):
        y = yz.iloc[0]
        avisos.append(("error", f"**Ya está con otro comercializador** ({y.get('comercializador', '—')}), desde "
                                f"{str(y.get('primer_mes_otro', ''))[:7]}. Estado en el archivo de la empresa: {y['estado']}."))
    if len(vz):
        v = vz.iloc[0]
        txt = f"**Cliente de mercado no regulado** ({v.get('motivo', '')}): por su tamaño puede negociar con cualquier comercializador. "
        if pd.notna(v.get("prob_fuga_6m", np.nan)):
            txt += f"Probabilidad de fuga: **{v.get('nivel_riesgo', '—')}** ({prob_pct(v['prob_fuga_6m'])} en 6 meses). Lo lleva el área comercial, no la cuadrilla."
        avisos.append(("info", txt))
    cs_c = cargar(R.cero_sostenido, dtype={"NIU": "string"})
    if cs_c is not None and niu in set(cs_c["NIU"].astype("string").str.strip()):
        cc = cs_c[cs_c["NIU"].astype("string").str.strip() == niu].iloc[0]
        avisos.append(("warning", f"**Lleva {int(cc.get('meses_en_cero_min', 3))} meses o más en cero o casi cero** (facturaba "
                                  f"{pesos(cc.get('valor_facturaba_antes_mes', np.nan))}/mes). No está en la lista de caída: "
                                  "ya no hay consumo que revisar; conviene confirmar si está retirado, suspendido o el predio está desocupado."))
    for tipo, txt in avisos:
        getattr(st, tipo)(txt)

    c1, c2, c3 = st.columns(3)
    if len(o):
        oo = o.iloc[0]
        _o1 = o.iloc[[0]]
        ref_kwh = float(referencia_caida(_o1).iloc[0])
        var = float(caida_vs_referencia_pct(_o1).iloc[0])
        es_antigua = str(oo.get("veredicto", "")) == "CAIDA_SOSTENIDA"
        c1.metric("Caída de consumo", f"{var:.0f} %" if pd.notna(var) else "—",
                  help="Consumo reciente frente a la referencia con la que se midió la pérdida: en una caída reciente, la menor entre el periodo "
                       "anterior y el mismo periodo del año pasado (para no exagerar); en una caída que lleva meses, el año pasado.")
        if str(oo.get("prioridad_gestion", "")) == "VIGILAR: estacional":
            c2.metric("Gravedad", "Estacional", help="Es temporada baja de un cliente que ya volvió otras veces: no se trata como caída grave.")
        else:
            c2.metric("Gravedad", SEVERIDAD_SIMPLE.get(str(oo.get("gravedad", "")), str(oo.get("gravedad", "—"))))
        c3.metric("Tendencia", TRAYECTORIA_SIMPLE.get(str(oo.get("trayectoria", "")), "—"),
                  help=PRIORIDAD_SIMPLE.get(str(oo.get("prioridad_gestion", "")), ""))
        if str(oo.get("prioridad_gestion", "")).startswith(("VIGILAR", "SEGUIMIENTO")):
            st.caption("Prioridad: **" + PRIORIDAD_SIMPLE.get(str(oo["prioridad_gestion"]), str(oo["prioridad_gestion"])) + "**")
        if es_antigua:
            _frase = (f"Hace un año consumía **{kwh(ref_kwh)}/mes** y ahora **{kwh(oo.get('consumo_reciente_kwh', np.nan))}/mes**: "
                      f"son **{pesos_md(oo.get('valor_riesgo_mes', np.nan))}/mes** menos de facturación. Frente a los meses anteriores "
                      f"(**{kwh(oo.get('consumo_anterior_kwh', np.nan))}/mes**) se mantiene: es una caída que lleva meses, no reciente. ")
        else:
            _frase = (f"Consumía **{kwh(ref_kwh)}/mes** y ahora **{kwh(oo.get('consumo_reciente_kwh', np.nan))}/mes**: "
                      f"son **{pesos_md(oo.get('valor_riesgo_mes', np.nan))}/mes** menos de facturación. ")
        st.markdown(_frase + ""
                    f"{ESTADO_LISTA_SIMPLE.get(str(oo.get('estado_en_lista', '')), '')}"
                    + (f" (lleva {int(oo.get('meses_consecutivos_en_lista', 1))} cortes seguidos en la lista)." if str(oo.get("estado_en_lista", "")) == "PERSISTENTE" else "."))
        st.info("**Qué revisar / qué decirle:** " + que_revisar(oo))
    elif len(ez):
        e = ez.iloc[0]
        ver = str(e["veredicto"])
        c1.metric("Caída de consumo", "Sin caída" if ver == "SIN_CAIDA" else ver.replace("_", " ").capitalize())
        c2.metric("Consumo anterior", kwh(e.get("consumo_anterior_kwh", np.nan)))
        c3.metric("Consumo reciente", kwh(e.get("consumo_reciente_kwh", np.nan)))
        st.caption(VEREDICTO_TEXTO.get(ver, ""))
        if ver == "SIN_CAIDA":
            st.success("No está en la lista de caída: su consumo se mantiene dentro de lo normal para clientes parecidos.")
    else:
        c1.metric("Caída de consumo", "Sin dato")
        st.caption("No está en el estudio de caída (sin historia suficiente, alumbrado, provisional o excluido).")

    if len(fz) and not len(yz):
        z = fz.iloc[0]
        nivel = str(z["nivel_riesgo"])
        c1, c2, c3 = st.columns(3)
        c1.metric("Probabilidad de fuga a otro comercializador", nivel)
        c2.metric("Probabilidad en 6 meses", prob_pct(z["prob_fuga_6m"]))
        c3.metric("Factura promedio (últimos 6 meses)", f"{pesos(z.get('valor_en_riesgo_mes', np.nan))}/mes",
                  help="Consumo promedio de los últimos 6 meses por su tarifa real; en un cliente estacional incluye la temporada alta.")
        txt = NIVEL_FUGA_SIMPLE.get(nivel, "")
        if isinstance(z.get("senales"), str) and z["senales"]:
            txt += f". Señales: {z['senales']}"
        st.caption(txt)
    elif not len(vz) and not len(yz):
        st.caption("No está entre los clientes a los que se les calcula probabilidad de fuga (es residencial, alumbrado, provisional o sin historia suficiente).")

    # ----- Consumo -----
    st.subheader("Cómo ha venido consumiendo")
    grafica_consumo_cliente(niu)


def grafica_consumo_cliente(niu: str) -> None:
    """Consumo real de los últimos 12 meses y pronóstico a 6 meses de un NIU (la usan Soporte y Administrador)."""
    if R.serie.exists():
        st.subheader("Consumo de los últimos 18 meses y pronóstico a 6")
        sc = serie_cliente(str(R.serie), R.serie.stat().st_mtime, niu)
        if len(sc):
            es_rural_c = bool(sc["es_rural"].fillna(False).astype(bool).iloc[-1])
            corte_c = CORTE_ZONA.get("RURAL" if es_rural_c else "URBANO", str(sc["periodo"].max())[:7])
            sc = sc.copy()
            sc["mes"] = sc["periodo"].dt.strftime("%Y-%m")
            real = sc[sc["mes"] <= corte_c].tail(18)[["mes", "consumo_kwh_mensual"]].rename(columns={"consumo_kwh_mensual": "kWh"})
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
                st.caption("Línea continua azul: consumo real (18 meses hasta el corte). Línea punteada naranja: pronóstico "
                           "del modelo. Rombos grises: meses con lectura parcial (rurales a la espera de la lectura trimestral).")
            except ImportError:
                piv = datos_g.pivot_table(index="mes", columns="serie", values="kWh", aggfunc="first")
                st.line_chart(piv, height=300)

            tabla_g = datos_g.copy()
            tabla_g["kWh"] = tabla_g["kWh"].round(1)
            if es_rural_c:
                st.caption(f"Cliente rural (lectura trimestral). Corte rural {corte_c}: los meses posteriores muestran "
                           "el pronóstico; el valor real reemplaza al pronosticado cuando llegue la lectura.")
            with st.expander("Ver los datos de la gráfica"):
                tabla(tabla_g, hide_index=True, use_container_width=True)
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
                tabla(t, hide_index=True, use_container_width=True)
            st.caption(f"Grupo de consumo: {GRUPO_CONSUMO_NOMBRE.get(str(p['perfil']), p['perfil'])} · zona {p.get('zona', '—')} · "
                       f"corte del pronóstico: {str(p['fecha_corte'])[:7]} · modelo entrenado con corte {str(p.get('fecha_corte_modelo', ''))[:7]}")
            if str(p.get("modelo_1m", "")) == "REGLA_CERO_SOSTENIDO":
                st.warning("Este cliente lleva sus dos últimos meses en cero (o casi): el pronóstico es persistencia del último "
                           "valor, no una recuperación. Si vuelve a consumir, la regla deja de aplicar sola el mes siguiente.")
        else:
            razon = "historia insuficiente o sin dato en el mes de corte"
            try:
                if len(sc):
                    ult = str(sc.loc[sc["consumo_kwh_mensual"].notna(), "periodo"].max())[:7]
                    n_ok = int(sc["consumo_kwh_mensual"].notna().sum())
                    if ult < corte_c:
                        razon = (f"**no tiene lectura en el mes de corte ({corte_c})**: su último dato es de {ult}. El modelo solo pronostica a los "
                                 f"clientes con dato en el corte; tendrá pronóstico cuando llegue su lectura de {corte_c}. Mientras tanto, la lista de caída "
                                 f"lo evalúa con su último mes conocido")
                    elif n_ok < 12:
                        razon = f"solo tiene {n_ok} meses con dato y el modelo necesita al menos 12"
                    else:
                        razon = (f"tiene dato en el corte ({corte_c}) e historia suficiente, pero no quedó en el archivo de pronóstico; revisar en el "
                                 "registro de la corrida el paso de pronóstico (por ejemplo, un cambio de zona o de perfil en el mes)")
            except NameError:
                pass
            st.info(f"El NIU no tiene pronóstico: {razon}.")


# ============================================================================
# VISTA COMERCIAL
# ============================================================================
if seccion == "Panorama":
    st.title("Panorama comercial")
    if operativa is None and fuga is None:
        st.warning("Todavía no hay salidas del pipeline. Corre python pipeline_mensual.py --modo aplicar y vuelve a abrir la página.")
        st.stop()
    st.markdown(f"Periodo facturado: **urbano {CORTE_ZONA.get('URBANO', corte_actual or '—')}** · **rural {CORTE_ZONA.get('RURAL', '—')}** "
                "(los rurales se leen por trimestres, por eso su periodo puede ir un par de meses atrás).")
    st.markdown(QUE_ES_ESTO)
    st.caption("Las listas no incluyen autogeneradores ni las clases área común, autoconsumos EBSA, distritos de riego y provisionales "
               "(regla de negocio acordada con el experto). El valor en pesos usa la tarifa real de cada cliente.")

    ya = cargar(R.fuga_ya_fuera, dtype={"NIU": "string"})
    vg = cargar(R.fuga_vigilancia, dtype={"NIU": "string"})
    c1, c2, c3, c4 = st.columns(4)
    if operativa is not None:
        _ges = operativa[operativa["prioridad_gestion"].astype(str).eq("GESTIONAR")] if "prioridad_gestion" in operativa.columns else operativa
        c1.metric("Clientes con caída de consumo", f"{fmt_n(len(operativa))}",
                  delta=f"{fmt_n(len(_ges))} para gestionar ahora", delta_color="off",
                  help="Todos los clientes cuyo consumo bajó más de lo normal para clientes parecidos. 'Para gestionar ahora' son las caídas recientes; "
                       "el resto son caídas que llevan meses así (seguimiento) o estacionales y con recuperación prevista (vigilar).")
        c2.metric("Facturación que se está perdiendo", f"{pesos(operativa['valor_riesgo_mes'].sum())}/mes",
                  delta=f"{pesos(_ges['valor_riesgo_mes'].sum())}/mes para gestionar", delta_color="off",
                  help="Lo que facturaban antes menos lo que facturan ahora, con la tarifa real de cada uno. Incluye seguimiento y vigilar.")
    if fuga is not None:
        senal = fuga[fuga["nivel_riesgo"].isin(["ALTO", "MEDIO"])]
        c3.metric("Probabilidad de fuga alta o media", f"{fmt_n(len(senal))} clientes",
                  help="Probabilidad de fuga ALTA o MEDIA según el modelo, entre los clientes comerciales, industriales, oficiales y acueductos. No significa que se vayan a ir: es a quién contactar primero.")
        c4.metric("Pérdida esperada (fuga)", f"{pesos(senal['valor_esperado_perdida_mes'].sum())}/mes",
                  help="Probabilidad de fuga × lo que factura hoy cada uno. Es un orden de magnitud para priorizar, no dinero que se vaya a perder con certeza.")
    c1, c2, c3, c4 = st.columns(4)
    if operativa is not None:
        c1.metric("Caídas graves recientes", f"{fmt_n(int(operativa['gravedad'].eq('CRITICA').sum()))}",
                  help="Caída reciente muy por encima de lo normal del segmento: revisar medidor y lectura antes de dar por buena la cifra. Las que llevan meses así se cuentan aparte, como antiguas.")
        if "estado_en_lista" in operativa.columns:
            c2.metric("Nuevos en la lista este mes", f"{fmt_n(int(operativa['estado_en_lista'].eq('NUEVO').sum()))}")
    if ya is not None and len(ya):
        c3.metric("Ya atendidos por otro comercializador", f"{fmt_n(int(ya['estado'].astype(str).str.startswith('CON OTRO').sum()))}",
                  help="Según el archivo de otros comercializadores de la empresa.")
    if vg is not None and len(vg):
        c4.metric("Grandes clientes en vigilancia (no regulados)", f"{fmt_n(len(vg))}",
                  help="Ciclo 33, clase no regulada o más de 55.000 kWh/mes: pueden negociar con cualquier comercializador.")
    cs = cargar(R.cero_sostenido, dtype={"NIU": "string"})
    if cs is not None and len(cs):
        st.caption(f"Aparte, **{fmt_n(len(cs))} clientes llevan 3 meses o más en cero o casi cero** (facturaban "
                   f"{pesos_md(cs['valor_facturaba_antes_mes'].sum())}/mes): no se cuentan como caída porque ya no consumen; "
                   "están en la sección *Clientes sin consumo*.")

    if operativa is not None:
        st.subheader("Caídas de consumo por zona regional")
        st.caption("Cuántos clientes tienen caída de consumo en cada dirección regional y de qué gravedad. "
                   "Grave = caída reciente muy por encima de lo normal del segmento: revisar medidor y lectura primero. "
                   "Antigua = lleva meses en ese nivel; va en seguimiento, no como urgente.")
        orden_sev = [x for x in ["CRITICA", "FUERTE", "MODERADA", "ANTIGUA"] if x in set(operativa["gravedad"].astype(str))]
        t_sev = operativa.groupby(["zona_regional", "gravedad"]).size().unstack(fill_value=0).reindex(columns=orden_sev)
        t_sev = t_sev.loc[t_sev.sum(axis=1).sort_values(ascending=False).index]
        t_sev.columns = [SEVERIDAD_SIMPLE.get(c, c) for c in t_sev.columns]
        t_sev.index = [str(z).replace("USUARIOS NO REGULADOS", "NO REGULADOS") for z in t_sev.index]   # el nombre largo salía cortado en el eje
        c1, c2 = st.columns([3, 2])
        with c1:
            st.bar_chart(t_sev, color=[NARANJA, "#f2a65a", AZUL, GRIS_ANTIGUA][:len(t_sev.columns)], height=320)
        with c2:
            rz = operativa.groupby("zona_regional").agg(**{"Clientes con caída": ("NIU", "size"),
                                                           "Facturación que se pierde ($/mes)": ("valor_riesgo_mes", "sum")}).reset_index()
            rz = rz.rename(columns={"zona_regional": "Zona regional"}).sort_values("Facturación que se pierde ($/mes)", ascending=False)
            tabla(rz, hide_index=True, use_container_width=True, height=320)

    st.subheader("Dónde está pasando")
    mm = metricas_municipio()
    if mm is not None:
        d_mapa = dibujar_mapa(mm, METRICAS_MAPA_COMERCIAL, clave="comercial", puntos=False, altura=560)
        top = d_mapa.sort_values("valor", ascending=False).head(10)
        if len(top) and top["valor"].sum() > 0:
            _cifra = str(st.session_state.get("met_comercial", "la cifra elegida"))
            _titulo_top = f"{_cifra}{st.session_state.get('modo_texto_comercial', '')}".replace("$", chr(92) + "$")   # el $ suelto se leería como fórmula
            st.markdown(f"**Los diez municipios con más: {_titulo_top}**")
            st.bar_chart(top.set_index("municipio")["valor"], color=AZUL, height=260)

    if operativa is not None:
        st.subheader("De qué tipo de clientes viene la facturación en riesgo")
        c1, c2 = st.columns(2)
        with c1:
            col = "clase_servicio_nombre" if "clase_servicio_nombre" in operativa.columns else "clase_servicio"
            t = operativa.groupby(col).agg(clientes=("NIU", "size"), valor=("valor_riesgo_mes", "sum")).sort_values("valor", ascending=False)
            st.bar_chart(t["valor"], color=AZUL, height=260)
            st.caption("Por clase de servicio ($/mes)")
        with c2:
            col = "grupo_consumo" if "grupo_consumo" in operativa.columns else "tramo_consumo"
            t = operativa.groupby(col).agg(clientes=("NIU", "size"), valor=("valor_riesgo_mes", "sum")).sort_values("valor", ascending=False)
            st.bar_chart(t["valor"], color=AZUL, height=260)
            st.caption("Por tamaño del cliente ($/mes)")

    es = cargar(R.entradas_salidas)
    if es is not None and len(es):
        with st.expander("Qué cambió frente al mes anterior"):
            tabla(es, hide_index=True, use_container_width=True)
            st.caption("Clientes que entraron, salieron o siguen en la lista de caída frente al corte anterior.")


elif seccion == "Clientes con probabilidad de fuga":
    st.title("Clientes con probabilidad de fuga a otro comercializador")
    if fuga is None:
        st.warning("Todavía no hay riesgo de fuga calculado (paso 14 del pipeline).")
        st.stop()
    corte_f = str(fuga["fecha_corte"].iloc[0])[:7]
    st.caption(f"Corte **{corte_f}**. El modelo mira cómo se comportaron los clientes que ya se fueron y busca los que hoy se parecen: "
               "caída reciente, meses en cero, zona con más salidas, tamaño. **Riesgo ALTO: contactar primero. MEDIO: vigilar y contactar según valor.** "
               "ALTO es el 1 % con mayor puntaje del modelo y MEDIO llega hasta el 5 %; nadie por debajo del riesgo promedio entra. "
               "La probabilidad es a 6 meses y está calibrada con lo que pasó en validación (de los clientes con ese puntaje, qué fracción "
               "se fue). Tiene un tope: a los pocos clientes con puntaje más alto que cualquiera visto en validación se les muestra la "
               "probabilidad máxima comprobada, no una mayor; la pérdida esperada es probabilidad × lo que factura. **Cómo leerlo:** con unos 80 clientes que se han ido, el "
               "modelo no ordena mejor que listar a los clientes por tamaño (consumo de 12 meses); en validación, de los 100 primeros se fueron 4. "
               "Es una lista de clientes grandes con señales para priorizar contactos, no una predicción de quién se va; la pérdida esperada es un orden de magnitud.")
    d = agregar_municipio(fuga)
    f1, f2, f3, f4, f5 = st.columns(5)
    niv = f1.multiselect("Probabilidad de fuga", ["ALTO", "MEDIO", "BAJO"], default=["ALTO", "MEDIO"], key="com_niv")
    zon = filtro_zona_regional(f2, d, "com_zon")
    mun = filtro_municipio(f3, d, "com_mun")
    cla = f4.multiselect("Clase de servicio", sorted(d["clase_servicio_nombre"].dropna().astype(str).unique()), key="com_cla", placeholder="Todas")
    tam = f5.multiselect("Tamaño", [g for g in GRUPOS_CONSUMO_ORDEN if g in d["grupo_consumo"].unique()], key="com_tam", placeholder="Todos")
    if niv:
        d = d[d["nivel_riesgo"].isin(niv)]
    if zon:
        d = d[d["zona_regional"].astype(str).isin(zon)]
    if mun:
        d = d[d["municipio"].astype(str).isin(mun)]
    if cla:
        d = d[d["clase_servicio_nombre"].astype(str).isin(cla)]
    if tam:
        d = d[d["grupo_consumo"].isin(tam)]
    d = d.sort_values(["valor_esperado_perdida_mes", "prob_fuga_6m"], ascending=False)
    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes", f"{fmt_n(len(d))}")
    c2.metric("Facturan (promedio 6 meses)", f"{pesos(d['valor_en_riesgo_mes'].sum())}/mes")
    c3.metric("Pérdida esperada", f"{pesos(d['valor_esperado_perdida_mes'].sum())}/mes")
    linea_conteo(min(len(d), 1000), len(d), int(fuga["nivel_riesgo"].isin(["ALTO", "MEDIO"]).sum()), len(fuga),
                 "clientes con riesgo", "con riesgo ALTO o MEDIO en total", "clientes evaluados por el modelo")
    t = pd.DataFrame({
        "Prioridad": d["ranking"],
        "NIU": d["NIU"],
        "Municipio": d["municipio"] if "municipio" in d.columns else "—",
        "Zona regional": d["zona_regional"],
        "Ciclo": d["zona_nombre"],
        "Clase": d["clase_servicio_nombre"],
        "Tamaño": d["grupo_consumo"],
        "Factura promedio 6 meses ($/mes)": d["valor_en_riesgo_mes"].round(0),
        "Probabilidad de fuga (6 meses)": d["prob_fuga_6m"].map(prob_pct),
        "Riesgo": d["nivel_riesgo"],
        "Pérdida esperada ($/mes)": d["valor_esperado_perdida_mes"].round(0),
        "Señales observadas": d["senales"].fillna(""),
        "Situación": d["estado_en_lista"].map(ESTADO_LISTA_SIMPLE).fillna("") if "estado_en_lista" in d.columns else "",
    })
    st.download_button("Descargar esta lista (CSV)", csv_es(t),
                       file_name=f"clientes_riesgo_de_irse_{corte_f}.csv", mime="text/csv")
    tabla_con_ficha(t.head(1000).reset_index(drop=True), "com_fuga", hide_index=True, use_container_width=True, height=520)

    vg = cargar(R.fuga_vigilancia, dtype={"NIU": "string"})
    st.subheader("Grandes clientes del mercado no regulado (seguimiento comercial)")
    st.caption("Clientes del ciclo 33, de clase no regulada o con más de 55.000 kWh/mes. Por su tamaño pueden negociar con cualquier "
               "comercializador, así que no van en la lista de arriba: se acompañan desde el área comercial.")
    if vg is None or len(vg) == 0:
        st.info("Hoy no hay clientes en vigilancia.")
    else:
        vg = agregar_municipio(vg)
        tv = pd.DataFrame({
            "NIU": vg["NIU"], "Municipio": vg["municipio"] if "municipio" in vg.columns else "—",
            "Por qué está aquí": vg["motivo"], "Clase": vg.get("clase_servicio_nombre", "—"),
            "Consumo promedio (kWh/mes)": pd.to_numeric(vg.get("consumo_prom_12m_kwh"), errors="coerce").round(0),
            "Factura ($/mes)": pd.to_numeric(vg.get("valor_facturado_mes"), errors="coerce").round(0),
            "Probabilidad de fuga": vg.get("nivel_riesgo", pd.Series("—", index=vg.index)).fillna("Sin puntuar"),
            "Probabilidad (6 meses)": pd.to_numeric(vg.get("prob_fuga_6m"), errors="coerce").map(prob_pct),
        })
        st.download_button("Descargar grandes clientes (CSV)", csv_es(tv),
                           file_name=f"grandes_clientes_no_regulados_{corte_f}.csv", mime="text/csv")
        tabla_con_ficha(tv.reset_index(drop=True), "com_vig", hide_index=True, use_container_width=True, height=360)


elif seccion == "Caídas de consumo":
    st.title("Clientes cuya facturación está cayendo")
    ger = cargar(R.gerencial, dtype={"NIU": "string", "ciclo_etiqueta": "string"})
    if ger is None:
        st.warning("Todavía no hay lista de caída (paso 11 del pipeline).")
        st.stop()
    st.caption(f"Periodo facturado **{corte_actual}**. Clientes cuyo consumo bajó más de lo normal para clientes parecidos, ordenados por la facturación "
               "que se está perdiendo cada mes. **Consumía** es el nivel con el que se midió la pérdida: en una caída reciente, el menor entre el periodo anterior y el mismo periodo del año pasado (para no exagerar la pérdida); en una caída que lleva meses, el del año pasado. **Gravedad**: qué tan fuera de lo normal es la caída. **Tendencia**: lo que el modelo espera para el mes que viene. "
               "Sin autogeneradores ni área común, autoconsumos EBSA, distritos de riego y provisionales.")
    cs_av = cargar(R.cero_sostenido, dtype={"NIU": "string"})
    if cs_av is not None and len(cs_av):
        st.info(f"Aparte hay **{fmt_n(len(cs_av))} clientes en cero o casi cero** desde hace 3 meses o más (facturaban "
                f"{pesos_md(cs_av['valor_facturaba_antes_mes'].sum())}/mes). No están en esta lista porque ya no hay una caída que "
                "revisar; se listan en la sección **Clientes sin consumo** para decidir qué hacer con ellos.")
    d = agregar_municipio(limpiar_lista(ger))
    n_lista_caida = len(d)
    col_zona = "zona_regional"
    col_clase = "clase_servicio_nombre" if "clase_servicio_nombre" in d.columns else "clase_servicio"
    with st.expander("Cuántos clientes hay por gravedad en cada zona regional", expanded=True):
        orden_sev = [x for x in ["CRITICA", "FUERTE", "MODERADA", "ANTIGUA"] if x in set(d["gravedad"].astype(str))]
        t_sev = d.groupby(["zona_regional", "gravedad"]).size().unstack(fill_value=0).reindex(columns=orden_sev)
        t_sev = t_sev.loc[t_sev.sum(axis=1).sort_values(ascending=False).index]
        t_sev.columns = [SEVERIDAD_SIMPLE.get(c, c) for c in t_sev.columns]
        t_sev.index = [str(z).replace("USUARIOS NO REGULADOS", "NO REGULADOS") for z in t_sev.index]   # el nombre largo salía cortado en el eje
        st.bar_chart(t_sev, color=[NARANJA, "#f2a65a", AZUL, GRIS_ANTIGUA][:len(t_sev.columns)], height=280)
    f1, f2, f3, f4, f5, f6 = st.columns(6)
    zon = filtro_zona_regional(f1, d, "gc_zon")
    mun = filtro_municipio(f2, d, "gc_mun")
    cla = f3.multiselect("Clase", sorted(d[col_clase].dropna().astype(str).unique()), key="gc_cla", placeholder="Todas")
    tam = f4.multiselect("Tamaño", [g for g in GRUPOS_CONSUMO_ORDEN if g in d.get("grupo_consumo", pd.Series(dtype=str)).unique()], key="gc_tam", placeholder="Todos")
    grav = f5.multiselect("Gravedad", ["CRITICA", "FUERTE", "MODERADA", "ANTIGUA"], format_func=lambda x: SEVERIDAD_SIMPLE.get(x, x), key="gc_grav", placeholder="Todas")
    ten = f6.multiselect("Tendencia", list(TRAYECTORIA_SIMPLE), format_func=lambda x: TRAYECTORIA_SIMPLE[x], key="gc_ten", placeholder="Todas")
    if "prioridad_gestion" not in d.columns:
        d["prioridad_gestion"] = np.where(d.get("trayectoria", pd.Series("", index=d.index)).eq("RECUPERACION_PREVISTA"), "VIGILAR: se espera recuperación", "GESTIONAR")
    g1, g2 = st.columns([3, 2])
    pri = g1.multiselect("Prioridad", list(PRIORIDAD_SIMPLE), default=["GESTIONAR"], format_func=lambda x: PRIORIDAD_SIMPLE[x], key="gc_pri",
                         help="Por defecto solo lo que hay que gestionar. 'Seguimiento' son caídas que llevan meses en el mismo nivel (reales, "
                              "pero no urgentes) y los 'Vigilar' son estacionales o con recuperación prevista: siguen en la lista, elígelos aquí para verlos.")
    tip = g2.multiselect("Tipo de caída", list(TIPO_CAIDA_SIMPLE), format_func=lambda x: TIPO_CAIDA_SIMPLE[x], key="gc_tip", placeholder="Todos",
                         help="Reciente: cae frente a su periodo anterior y frente al año pasado. Lleva meses así: frente al periodo anterior "
                              "se mantiene; la caída es contra el mismo periodo del año pasado.") if "veredicto" in d.columns else []
    if pri:
        d = d[d["prioridad_gestion"].isin(pri)]
    if tip:
        d = d[d["veredicto"].isin(tip)]
    if zon:
        d = d[d[col_zona].astype(str).isin(zon)]
    if mun:
        d = d[d["municipio"].astype(str).isin(mun)]
    if cla:
        d = d[d[col_clase].astype(str).isin(cla)]
    if tam:
        d = d[d["grupo_consumo"].isin(tam)]
    if grav:
        d = d[d["gravedad"].isin(grav)]
    if ten and "trayectoria" in d.columns:
        d = d[d["trayectoria"].isin(ten)]
    n = st.slider("Cuántos mostrar", 25, 2000, 200, step=25)
    # Orden: primero lo que hay que gestionar, luego vigilar; dentro de cada grupo por facturación perdida
    d = d.assign(_pri=d["prioridad_gestion"].map(ORDEN_PRIORIDAD).fillna(0))
    d = d.sort_values(["_pri", "valor_riesgo_mes"], ascending=[True, False])
    top = d.head(n)
    if len(d) == 0:
        st.info("Ningún cliente cumple estos filtros. Prueba a quitar alguno: por ejemplo, las caídas que llevan meses así están en la "
                "prioridad *Seguimiento*, no en *Gestionar*.")
        st.stop()
    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes (con los filtros)", f"{fmt_n(len(d))}")
    c2.metric("Facturación que se pierde", f"{pesos(d['valor_riesgo_mes'].sum())}/mes")
    c3.metric(f"Los {fmt_n(len(top))} primeros concentran", f"{(top['valor_riesgo_mes'].sum() / d['valor_riesgo_mes'].sum() * 100 if d['valor_riesgo_mes'].sum() else 0):.0f} %")
    linea_conteo(len(top), len(d), n_lista_caida, n_evaluados_caida(), "clientes con caída", "en toda la lista de caída", "clientes evaluados por el detector")
    t = pd.DataFrame({
        "Puesto": np.arange(1, len(top) + 1),
        "NIU": top["NIU"],
        "Municipio": top["municipio"] if "municipio" in top.columns else "—",
        "Zona regional": top[col_zona],
        "Ciclo": top["zona_nombre"] if "zona_nombre" in top.columns else "—",
        "Clase": top[col_clase],
        "Tamaño": top.get("grupo_consumo", "—"),
        "Tipo de caída": top["veredicto"].map(TIPO_CAIDA_SIMPLE).fillna("—") if "veredicto" in top.columns else "—",
        "Consumía (kWh/mes)": referencia_caida(top).round(0),
        "Consume ahora (kWh/mes)": top["consumo_reciente_kwh"].round(0),
        "Caída": caida_vs_referencia_pct(top).round(0).astype("Int64").astype(str) + " %",
        "Facturación que se pierde ($/mes)": top["valor_riesgo_mes"].round(0),
        "Gravedad": top["gravedad"].map(SEVERIDAD_SIMPLE).fillna(top["gravedad"]),
        "Tendencia": top["trayectoria"].map(TRAYECTORIA_SIMPLE).fillna("—") if "trayectoria" in top.columns else "—",
        "Prioridad": top["prioridad_gestion"].map(PRIORIDAD_SIMPLE).fillna(top["prioridad_gestion"]) if "prioridad_gestion" in top.columns else "Gestionar",
        "Situación": top["estado_en_lista"].map(ESTADO_LISTA_SIMPLE).fillna("") if "estado_en_lista" in top.columns else "",
    })
    st.download_button("Descargar esta lista (CSV)", csv_es(t),
                       file_name=f"caidas_consumo_{corte_actual or ''}.csv", mime="text/csv")
    tabla_con_ficha(t.reset_index(drop=True), "com_caida", hide_index=True, use_container_width=True, height=560)


elif seccion == "Clientes sin consumo":
    st.title("Clientes sin consumo (en cero o casi cero)")
    cs = cargar(R.cero_sostenido, dtype={"NIU": "string"})
    st.caption(f"Periodo facturado **{corte_actual}**. Clientes que llevan toda su ventana reciente (3 meses los de lectura mensual, 6 los "
               "rurales de lectura trimestral) **en cero o casi cero**: ningún mes pasa de 10 kWh ni del 5 % de lo que consumían. No se cuentan "
               "como caída de consumo (no hay una caída que una cuadrilla pueda revisar) y no suman a la facturación en riesgo, pero sí importan "
               "a comercial: aquí está lo que facturaban antes (referencia del periodo anterior o del mismo periodo del año pasado, con su "
               "tarifa real), para decidir qué hacer con cada uno.")
    if cs is None or len(cs) == 0:
        st.info("No hay clientes en cero sostenido en este corte (o la lista no se ha recalculado con la versión actual).")
    else:
        cs = agregar_zona_regional(agregar_municipio(cs))
        # Último mes con consumo: viene en el CSV (corridas nuevas) o se calcula aquí desde la serie
        if "ultimo_mes_con_consumo" not in cs.columns and R.serie.exists():
            try:
                um = ultimo_mes_con_consumo(str(R.serie), R.serie.stat().st_mtime, tuple(cs["NIU"].astype("string").str.strip().unique()), corte_actual)
                cs["NIU"] = cs["NIU"].astype("string").str.strip()
                cs = cs.merge(um, on="NIU", how="left")
            except Exception as ex:
                st.caption(f"No se pudo calcular el último mes con consumo: {ex}")
        _rec = pd.to_numeric(cs["consumo_reciente_kwh"], errors="coerce").fillna(0) if "consumo_reciente_kwh" in cs.columns else pd.Series(0.0, index=cs.index)
        cs["_situacion"] = np.where(_rec <= 0, "En cero", "Casi cero")
        cs["_meses"] = pd.to_numeric(cs["meses_en_cero"] if "meses_en_cero" in cs.columns else cs["meses_en_cero_min"], errors="coerce")
        # sin ningún mes con consumo en la serie: lleva así toda la historia disponible
        cs["_tramo_meses"] = np.select([cs["_meses"].isna(), cs["_meses"] <= 6, cs["_meses"] <= 12],
                                       ["Más de 12 meses", "Hasta 6 meses", "7 a 12 meses"], default="Más de 12 meses")
        cs["_que_hacer"] = cs["_tramo_meses"].map({
            "Hasta 6 meses": "Confirmar: suspensión o predio desocupado que puede volver",
            "7 a 12 meses": "Verificar el estado del servicio y si procede la reconexión",
            "Más de 12 meses": "Retiro de hecho: depurar catastro o gestionar reconexión",
        })
        _ref = pd.to_numeric(cs["consumo_referencia_kwh"] if "consumo_referencia_kwh" in cs.columns else cs["consumo_anterior_kwh"], errors="coerce")
        cs["_tamano"] = np.select([_ref >= 5000, _ref >= 500], ["Grande", "Mediano"], default="Pequeño")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Clientes sin consumo", f"{fmt_n(len(cs))}")
        c2.metric("En cero", f"{fmt_n(int((cs['_situacion'] == 'En cero').sum()))}")
        c3.metric("Casi cero", f"{fmt_n(int((cs['_situacion'] == 'Casi cero').sum()))}",
                  help="Consumen algo, pero ningún mes de la ventana pasa de 10 kWh ni del 5 % de lo que consumían.")
        c4.metric("Facturaban antes", f"{pesos(cs['valor_facturaba_antes_mes'].sum())}/mes")
        with st.expander("Cuántos hay según el tiempo que llevan sin consumo", expanded=True):
            _orden_t = ["Hasta 6 meses", "7 a 12 meses", "Más de 12 meses"]
            _res = cs.groupby("_tramo_meses").agg(**{"Clientes": ("NIU", "size"), "Facturaban antes ($/mes)": ("valor_facturaba_antes_mes", "sum")}).reindex(_orden_t).fillna(0)
            _res.insert(0, "Qué hacer (sugerido)", [cs.loc[cs["_tramo_meses"] == x, "_que_hacer"].iloc[0] if (cs["_tramo_meses"] == x).any() else "—" for x in _orden_t])
            _res["Clientes"] = _res["Clientes"].astype(int)
            tabla(_res.reset_index().rename(columns={"_tramo_meses": "Tiempo sin consumo"}), hide_index=True, use_container_width=True)
            st.caption("**Meses sin consumo**: los transcurridos desde el último mes en que el cliente consumió por encima de su umbral de casi cero. "
                       "**Qué hacer** es una sugerencia por ese tiempo; el proyecto es académico y no hay gestión real de clientes.")
        f1, f2, f3, f4, f5 = st.columns(5)
        zon_cs = filtro_zona_regional(f1, cs, "cs_zona")
        mun_cs = filtro_municipio(f2, cs, "cs_mun")
        sit_cs = f3.multiselect("Situación", ["En cero", "Casi cero"], key="cs_sit", placeholder="Todas")
        tie_cs = f4.multiselect("Tiempo sin consumo", ["Hasta 6 meses", "7 a 12 meses", "Más de 12 meses"], key="cs_tie", placeholder="Todos")
        tam_cs = f5.multiselect("Tamaño (por lo que consumía)", [x for x in ["Grande", "Mediano", "Pequeño"] if x in set(cs["_tamano"])], key="cs_tam", placeholder="Todos")
        dcs = cs
        if zon_cs:
            dcs = dcs[dcs["zona_regional"].astype(str).isin(zon_cs)]
        if mun_cs:
            dcs = dcs[dcs["municipio"].astype(str).isin(mun_cs)]
        if sit_cs:
            dcs = dcs[dcs["_situacion"].isin(sit_cs)]
        if tie_cs:
            dcs = dcs[dcs["_tramo_meses"].isin(tie_cs)]
        if tam_cs:
            dcs = dcs[dcs["_tamano"].isin(tam_cs)]
        dcs = dcs.sort_values("valor_facturaba_antes_mes", ascending=False, na_position="last")
        tcs = pd.DataFrame({
            "NIU": dcs["NIU"], "Municipio": dcs["municipio"] if "municipio" in dcs.columns else "—",
            "Zona regional": dcs["zona_regional"], "Clase": nombre_clase(dcs["clase_servicio"]) if "clase_servicio" in dcs.columns else "—",
            "Tamaño": dcs["_tamano"],
            "Situación": dcs["_situacion"],
            "Consumía antes (kWh/mes)": (dcs["consumo_referencia_kwh"] if "consumo_referencia_kwh" in dcs.columns else dcs["consumo_anterior_kwh"]).round(0),
            "Consume ahora (kWh/mes)": pd.to_numeric(dcs["consumo_reciente_kwh"], errors="coerce").round(1) if "consumo_reciente_kwh" in dcs.columns else 0,
            "Facturaba antes ($/mes)": dcs["valor_facturaba_antes_mes"].round(0),
            "Último mes con consumo": dcs["ultimo_mes_con_consumo"].fillna("sin consumo en la serie") if "ultimo_mes_con_consumo" in dcs.columns else "—",
            "Meses sin consumo": dcs["_meses"].astype("Int64"),
            "Qué hacer (sugerido)": dcs["_que_hacer"],
        })
        linea_conteo(len(tcs), len(dcs), len(cs), None, "clientes sin consumo", "en total")
        st.download_button("Descargar clientes sin consumo (CSV)", csv_es(tcs),
                           file_name=f"clientes_sin_consumo_{corte_actual or ''}.csv", mime="text/csv")
        tabla_con_ficha(tcs.reset_index(drop=True), "com_cero", hide_index=True, use_container_width=True, height=520)


elif seccion == "Clientes que ya se fueron":
    st.title("Clientes que ya están con otro comercializador")
    st.caption("Los clientes en cero o casi cero (que siguen conectados pero ya no consumen) están en la sección *Clientes sin consumo*.")

    st.subheader("Ya están con otro comercializador")
    ya = cargar(R.fuga_ya_fuera, dtype={"NIU": "string"})
    if ya is None or len(ya) == 0:
        st.info("No hay archivo de otros comercializadores en 00_otros_comercializadores.")
        st.stop()
    st.caption("Viene del archivo de otros comercializadores que entrega la empresa, cruzado con la historia de consumo en EBSA. "
               "Sirve para saber a quién ya no vale la pena buscar, cuánto facturaban y cómo eran, para reconocer a los que se parecen.")
    est = ya["estado"].value_counts()
    cc = st.columns(len(est))
    for col, (k, v) in zip(cc, est.items()):
        col.metric(k if len(k) < 30 else k[:28] + "…", f"{fmt_n(v)}", help=ESTADO_OTRO_TEXTO.get(k, k))
    if "valor_facturado_antes_salida_mes" in ya.columns and ya["valor_facturado_antes_salida_mes"].notna().any():
        st.markdown(f"Facturaban antes de irse **{pesos_md(ya['valor_facturado_antes_salida_mes'].sum())}/mes** "
                    f"(sobre {fmt_n(int(ya['valor_facturado_antes_salida_mes'].notna().sum()))} clientes con historia en EBSA).")
    d = agregar_municipio(ya) if "municipio" not in ya.columns else ya
    f1, f2 = st.columns(2)
    est_sel = f1.multiselect("Estado", list(est.index), key="ya_est", placeholder="Todos")
    com_sel = f2.multiselect("Comercializador", sorted(d["comercializador"].dropna().astype(str).unique()), key="ya_com", placeholder="Todos")
    if est_sel:
        d = d[d["estado"].isin(est_sel)]
    if com_sel:
        d = d[d["comercializador"].astype(str).isin(com_sel)]
    t = pd.DataFrame({
        "NIU": d["NIU"], "Estado": d["estado"], "Comercializador": d.get("comercializador", "—"),
        "Municipio": d.get("municipio", "—"), "Zona": d.get("zona_nombre", "—"), "Clase": d.get("clase_servicio_nombre", "—"),
        "Desde": d["primer_mes_otro"].astype(str).str[:7] if "primer_mes_otro" in d.columns else "—",
        "Mes de salida estimado": d["mes_salida"].astype(str).str[:7] if "mes_salida" in d.columns else "—",
        "Consumía antes (kWh/mes)": pd.to_numeric(d.get("consumo_prom_6m_antes_salida_kwh"), errors="coerce").round(0),
        "Facturaba antes ($/mes)": pd.to_numeric(d.get("valor_facturado_antes_salida_mes"), errors="coerce").round(0),
    })
    st.download_button("Descargar (CSV)", csv_es(t),
                       file_name="clientes_con_otro_comercializador.csv", mime="text/csv")
    tabla_con_ficha(t.reset_index(drop=True), "com_ya", hide_index=True, use_container_width=True, height=420)
    pi = cargar(R.fuga_perfil_idos)
    if pi is not None:
        with st.expander("Cómo son los que se fueron (clase, zona, tamaño, comercializador, municipio)"):
            for dim, tt in pi.groupby("dimension", sort=False):
                st.markdown(f"**{dim}**")
                tabla(tt.drop(columns=["dimension"]).head(15), hide_index=True, use_container_width=True)


elif seccion == "Proyección de consumo (compra de energía)":
    st.title("Proyección de consumo por zona para la compra de energía")
    pm = cargar(R.proy_mensual); pa = cargar(R.proy_anual); pe = cargar(R.proy_error)
    if pm is None or pa is None or pe is None:
        st.warning("Todavía no existe la proyección. Desde la carpeta del código corre:  python proyeccion_anual_consumo.py  "
                   "(tarda unos minutos; usa la serie consolidada de todos los clientes). Después recarga esta página.")
        st.stop()
    pm["periodo"] = pd.to_datetime(pm["periodo"])
    ultimo_real = str(pe["ultimo_mes_real"].iloc[0])
    umbral = float(pe["umbral_confiable_pct"].iloc[0])
    tecnico = vista == "Administrador del modelo"   # solo el administrador ve qué modelo hay detrás y su verificación
    if tecnico:
        st.markdown(f"Consumo mensual **real** de todos los clientes (sin alumbrado ni ciclos internos) hasta **{ultimo_real}**, agregado por zona "
                    "regional, y su **proyección** con un modelo clásico de series de tiempo (Holt-Winters o SARIMA, el que menos error tuvo "
                    "en el backtest de cada zona). Las bandas muestran dónde cae el 80 % y el 95 % de los escenarios del modelo.")
    else:
        st.markdown(f"Consumo mensual **real** de todos los clientes hasta **{ultimo_real}**, por zona regional y total, y su **proyección** a tres años. "
                    "Las bandas muestran el rango en el que se espera que caiga el consumo (80 % y 95 % de probabilidad).")
    st.info(f"**Cuántos años se pueden usar.** Un año se marca **CONFIABLE** cuando el error del modelo en el backtest (lo que se equivocó "
            f"pronosticando el pasado a ese horizonte) es ≤ {umbral:.0f} %; **ORIENTATIVO** si fue mayor; **NO VERIFICABLE** cuando la historia "
            "disponible (52 meses) no alcanza para probar ese horizonte, así que es extrapolación de tendencia y estacionalidad. "
            "Para comprar energía conviene usar los años CONFIABLES con su banda del 80 %, y tratar los demás como referencia.")

    zonas = [z for z in pa["zona_regional"].unique()]
    zonas = [z for z in zonas if z.startswith("TOTAL")] + [z for z in ZONAS_REGIONALES if z in zonas] + sorted(set(zonas) - set(ZONAS_REGIONALES) - {z for z in zonas if z.startswith("TOTAL")})
    c1, c2 = st.columns([2, 3])
    zona_sel = c1.selectbox("Zona", zonas, key="proy_zona")
    e = pe[pe["zona_regional"] == zona_sel].iloc[0]
    if tecnico:
        c2.markdown(f"Modelo elegido: **{e['modelo_elegido']}** · error del backtest a **1 año: {fmt_n(e['wape_anio1_pct'], 1) } %** "
                    f"({int(e['puntos_anio1'])} puntos) · a **2 años: {fmt_n(e['wape_anio2_pct'], 1)} %** ({int(e['puntos_anio2'])} puntos)"
                    + (f" · línea base estacional {fmt_n(e['wape_base_anio1_pct'], 1)} %" if "wape_base_anio1_pct" in e.index and pd.notna(e["wape_base_anio1_pct"]) else ""))
    else:
        c2.markdown(f"Margen de error medido: **{fmt_n(e['wape_anio1_pct'], 1)} %** a un año · **{fmt_n(e['wape_anio2_pct'], 1)} %** a dos años "
                    "(lo que la proyección se equivocó al probarla contra el pasado).")
    if tecnico and "cobertura_banda80_pct" in e.index:
        lb = e.get("ljung_box_p", np.nan)
        st.caption(f"Verificación: sesgo a 1 año {fmt_n(e.get('sesgo_anio1_pct', np.nan), 1)} % (cerca de 0 = no sobre ni subestima) · "
                   f"la banda del 80 % cubrió el {fmt_n(e.get('cobertura_banda80_pct', np.nan), 0)} % de los meses reales en el backtest (ideal ≈ 80 %"
                   + (f"; por eso se ensanchó ×{fmt_n(e['factor_calibracion_banda'], 2)}" if pd.notna(e.get("factor_calibracion_banda", np.nan)) and float(e.get("factor_calibracion_banda", 1)) > 1.0 else "")
                   + ") · "
                   f"residuos sin estructura (Ljung-Box p = {fmt_n(lb, 2) if pd.notna(lb) else '—'}): "
                   f"{'sí ✓' if pd.notna(lb) and lb > 0.05 else 'no ⚠'}"
                   + ("" if bool(e.get("supera_linea_base", True)) else " · ⚠ el modelo no supera la línea base estacional en esta zona"))

    # ----- Escenarios: BASE (ganador del backtest) y TENDENCIA (mejor modelo con tendencia) -----
    if "escenario" not in pm.columns:
        pm["escenario"] = "BASE"
    if "escenario" not in pa.columns:
        pa["escenario"] = "BASE"
    hay_tend = bool((pm["zona_regional"].eq(zona_sel) & pm["escenario"].eq("ALTERNATIVO")).any())
    esc_sel = "BASE"
    if hay_tend:
        mt_ = str(e.get("modelo_alternativo", "")); tipo_alt = str(e.get("tipo_alternativo", "alternativo"))
        alt_es_crecimiento = tipo_alt == "con tendencia"
        nombre_base = "Escenario estable (el consumo sigue como en los últimos dos años)" if alt_es_crecimiento else "Escenario de crecimiento (continúa la tendencia)"
        nombre_alt = "Escenario de crecimiento (continúa la tendencia de los primeros años)" if alt_es_crecimiento else "Escenario estable (el consumo se estanca)"
        err_alt = f"error 1 año {fmt_n(e.get('wape_alternativo_anio1_pct', np.nan), 1)} %, 2 años {fmt_n(e.get('wape_alternativo_anio2_pct', np.nan), 1)} %"
        if tecnico:
            etiquetas = {"BASE": f"Base: {e['modelo_elegido']} (el que mejor pronosticó el pasado)",
                         "ALTERNATIVO": f"Alternativo {tipo_alt}: {mt_} ({err_alt})"}
        else:
            etiquetas = {"BASE": nombre_base + " — el que mejor acertó el pasado", "ALTERNATIVO": nombre_alt + f" — {err_alt}"}
        esc_sel = st.radio("Escenario", ["BASE", "ALTERNATIVO"], horizontal=True, key="proy_esc", format_func=lambda x: etiquetas[x])
        st.caption("El escenario base es el que menos se equivocó al probarlo contra los últimos dos años; el otro responde la hipótesis contraria. "
                   "Cuál usar es una decisión de planeación: para no comprar de menos, lo usual es tomar el mayor de los dos como techo.")
    d = pm[(pm["zona_regional"] == zona_sel) & (pm["escenario"] == esc_sel)].sort_values("periodo").copy()
    d["mes"] = d["periodo"].dt.strftime("%Y-%m")
    st.subheader("Consumo mes a mes y proyección (GWh)")
    try:
        import plotly.graph_objects as go
        real = d[d["tipo"] == "REAL"]; proy = d[d["tipo"] == "PROYECCION"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=proy["periodo"], y=proy["sup95_gwh"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=proy["periodo"], y=proy["inf95_gwh"], fill="tonexty", fillcolor="rgba(235,104,52,0.12)",
                                 line=dict(width=0), name="Banda 95 %", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=proy["periodo"], y=proy["sup80_gwh"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=proy["periodo"], y=proy["inf80_gwh"], fill="tonexty", fillcolor="rgba(235,104,52,0.25)",
                                 line=dict(width=0), name="Banda 80 %", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=real["periodo"], y=real["real_gwh"], mode="lines+markers", name="Real",
                                 line=dict(color=AZUL, width=2.5), hovertemplate="%{x|%Y-%m}: %{y:,.1f} GWh<extra>Real</extra>"))
        if len(real) and len(proy):
            enlace = pd.concat([real.tail(1)[["periodo", "real_gwh"]].rename(columns={"real_gwh": "proyeccion_gwh"}), proy[["periodo", "proyeccion_gwh"]]])
        else:
            enlace = proy[["periodo", "proyeccion_gwh"]]
        fig.add_trace(go.Scatter(x=enlace["periodo"], y=enlace["proyeccion_gwh"], mode="lines+markers", name="Proyección",
                                 line=dict(color=NARANJA, width=2.5, dash="dash"), hovertemplate="%{x|%Y-%m}: %{y:,.1f} GWh<extra>Proyección</extra>"))
        # promedio anual real, para ver la tendencia de fondo sin el ruido mensual
        prom = real.assign(anio=real["periodo"].dt.year).groupby("anio")["real_gwh"].mean().reset_index()
        prom = prom[prom["anio"] < real["periodo"].max().year]   # solo años completos
        fig.add_trace(go.Scatter(x=pd.to_datetime(prom["anio"].astype(str) + "-07-01"), y=prom["real_gwh"], mode="lines+markers", name="Promedio anual real",
                                 line=dict(color="#1b3a6b", width=1.5), marker=dict(symbol="diamond", size=9),
                                 hovertemplate="%{x|%Y}: %{y:,.1f} GWh/mes promedio<extra>Promedio anual</extra>"))
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="GWh / mes", xaxis_title="Mes",
                          legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0), separators=",.")
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
    except ImportError:
        piv = d.set_index("mes")[["real_gwh", "proyeccion_gwh"]].rename(columns={"real_gwh": "Real", "proyeccion_gwh": "Proyección"})
        st.line_chart(piv, height=400)
    st.caption("Azul: consumo real consolidado. Naranja punteado: proyección del modelo; sombreado: bandas del 80 % y 95 %. "
               "Los meses rurales pendientes de lectura no se incluyen como reales.")

    # ----- Tabla anual -----
    st.subheader("Consumo por año (GWh)")
    a = pa[(pa["zona_regional"] == zona_sel) & (pa["escenario"] == esc_sel)].sort_values("anio").copy()
    # La etiqueta se recalcula con el error del modelo de ESTE escenario (archivos generados antes del 2026-10-09 le
    # ponían al escenario alternativo la etiqueta del base: un año con 10 % de error salía CONFIABLE).
    _err = pd.to_numeric(a["error_backtest_pct"], errors="coerce")
    _etq = a["confiabilidad"].astype(str)
    a["confiabilidad"] = np.where(_etq.isin(["CONFIABLE", "ORIENTATIVO"]) & _err.notna(),
                                  np.where(_err <= UMBRAL_CONFIABLE_PCT, "CONFIABLE", "ORIENTATIVO"), _etq)
    ta = pd.DataFrame({
        "Año": a["anio"].astype(int),
        "Meses reales": a["meses_reales"].astype(int), "Meses proyectados": a["meses_proyectados"].astype(int),
        "Consumo real (GWh)": a["real_gwh"].round(1), "Proyección (GWh)": a["proyeccion_gwh"].round(1),
        "Total del año (GWh)": a["total_gwh"].round(1),
        "Banda 80 % (GWh)": a.apply(lambda r: "" if r["meses_proyectados"] == 0 else f"{fmt_n(r['inf80_gwh'], 1)} – {fmt_n(r['sup80_gwh'], 1)}", axis=1),
        "Banda 95 % (GWh)": a.apply(lambda r: "" if r["meses_proyectados"] == 0 else f"{fmt_n(r['inf95_gwh'], 1)} – {fmt_n(r['sup95_gwh'], 1)}", axis=1),
        "Confiabilidad": a["confiabilidad"],
        "Error del backtest": a["error_backtest_pct"].map(lambda v: "" if pd.isna(v) else fmt_n(v, 1) + " %"),
    })
    for c in ["Consumo real (GWh)", "Proyección (GWh)", "Total del año (GWh)"]:
        ta[c] = ta[c].map(lambda v: "" if pd.isna(v) or v == 0 else fmt_n(v, 1))
    st.dataframe(ta, hide_index=True, use_container_width=True)
    conf = a[a["confiabilidad"].eq("CONFIABLE")]["anio"].astype(int).tolist()
    orient = a[a["confiabilidad"].eq("ORIENTATIVO")]["anio"].astype(int).tolist()
    nover = a[a["confiabilidad"].eq("NO VERIFICABLE")]["anio"].astype(int).tolist()
    msg = f"Para **{zona_sel}** se pueden usar para la compra de energía: **{', '.join(map(str, conf)) if conf else 'ningún año con el umbral actual'}**."
    if orient:
        msg += f" Orientativos (error mayor al umbral): {', '.join(map(str, orient))}."
    if nover:
        msg += f" No verificables con la historia disponible: {', '.join(map(str, nover))}."
    st.markdown(msg)
    st.caption("La banda anual suma las bandas mensuales, por eso es conservadora (más ancha que la del año como un todo). "
               "El año en curso combina meses reales y proyectados.")
    # Por qué la proyección sube, baja o queda plana: se explica con los años reales completos de la misma tabla
    _reales = a[(a["meses_proyectados"] == 0) & (a["meses_reales"] == 12)].sort_values("anio")
    _proys = a[a["meses_proyectados"] > 0].sort_values("anio")
    if len(_reales) >= 2 and len(_proys) >= 1:
        _u, _p = _reales.iloc[-1], _reales.iloc[-2]
        _cambio_real = (_u["total_gwh"] / _p["total_gwh"] - 1) * 100 if _p["total_gwh"] else np.nan
        _fin = _proys.iloc[-1]
        _cambio_proy = (_fin["total_gwh"] / _u["total_gwh"] - 1) * 100 if _u["total_gwh"] else np.nan
        _modelo = str(_fin.get("modelo", ""))
        _sin_tend = _modelo.startswith("ETS(") and ",N," in _modelo
        txt = (f"**Cómo leer la tendencia.** El último año real completo ({int(_u['anio'])}) cerró en {fmt_n(_u['total_gwh'], 1)} GWh, "
               f"{'+' if _cambio_real >= 0 else ''}{fmt_n(_cambio_real, 1)} % frente a {int(_p['anio'])} ({fmt_n(_p['total_gwh'], 1)} GWh). "
               f"La proyección de {int(_fin['anio'])} queda {'+' if _cambio_proy >= 0 else ''}{fmt_n(_cambio_proy, 1)} % frente a {int(_u['anio'])}.")
        if _sin_tend:
            txt += (" El modelo de este escenario no tiene tendencia: repite el nivel reciente con la forma del año (meses altos y bajos), "
                    "por eso los años proyectados salen casi iguales entre sí. Se eligió porque fue el que menos se equivocó al probarlo "
                    "contra los años ya conocidos; no afirma que el consumo no vaya a crecer, afirma que con esta historia no hay evidencia "
                    "suficiente de crecimiento. El rango posible es la banda, no la cifra central"
                    + (", y el otro escenario de arriba muestra qué pasaría si hubiera tendencia." if hay_tend else "."))
        st.info(txt)

    # ----- Todas las zonas, resumen -----
    with st.expander("Resumen de todas las zonas por año"):
        anios_p = sorted(pa.loc[pa["meses_proyectados"] > 0, "anio"].unique())
        pa_b = pa[pa["escenario"] == "BASE"]
        piv = pa_b.pivot_table(index="zona_regional", columns="anio", values="total_gwh", aggfunc="sum").round(1)
        piv = piv.reindex([z for z in zonas if z in piv.index])
        piv.columns = [str(c) for c in piv.columns]
        piv_txt = piv.map(lambda v: "" if pd.isna(v) else fmt_n(v, 1)) if hasattr(piv, "map") else piv.applymap(lambda v: "" if pd.isna(v) else fmt_n(v, 1))
        st.dataframe(piv_txt, use_container_width=True)
        st.caption("GWh por año calendario (real + proyección, escenario base). Los años " + ", ".join(map(str, anios_p)) + " incluyen meses proyectados.")
        if (pa["escenario"] == "ALTERNATIVO").any():
            piv_t = pa[pa["escenario"] == "ALTERNATIVO"].pivot_table(index="zona_regional", columns="anio", values="total_gwh", aggfunc="sum").round(1)
            piv_t = piv_t.reindex([z for z in zonas if z in piv_t.index]); piv_t.columns = [str(c) for c in piv_t.columns]
            st.markdown("**Escenario alternativo (GWh por año)**")
            st.dataframe(piv_t.map(lambda v: "" if pd.isna(v) else fmt_n(v, 1)) if hasattr(piv_t, "map") else piv_t.applymap(lambda v: "" if pd.isna(v) else fmt_n(v, 1)), use_container_width=True)
        if not tecnico:
            ren = {"zona_regional": "Zona", "wape_anio1_pct": "Margen de error 1 año (%)", "wape_anio2_pct": "Margen de error 2 años (%)"}
            tabla(pe[[c for c in ren if c in pe.columns]].rename(columns=ren).round(1), hide_index=True, use_container_width=True)
        ren = {"zona_regional": "Zona", "modelo_elegido": "Modelo", "wape_anio1_pct": "Error 1 año (%)", "wape_anio2_pct": "Error 2 años (%)",
               "wape_base_anio1_pct": "Línea base 1 año (%)", "sesgo_anio1_pct": "Sesgo 1 año (%)", "cobertura_banda80_pct": "Cobertura banda 80 % (%)",
               "factor_calibracion_banda": "Factor de ensanche de banda", "ljung_box_p": "Ljung-Box p",
               "modelo_alternativo": "Modelo alternativo", "tipo_alternativo": "Tipo", "wape_alternativo_anio1_pct": "Alternativo: error 1 año (%)", "wape_alternativo_anio2_pct": "Alternativo: error 2 años (%)", "puntos_anio1": "Puntos 1 año", "puntos_anio2": "Puntos 2 años"}
        cols_e = [c for c in ren if c in pe.columns]
        if tecnico:
          tabla(pe[cols_e].rename(columns=ren).round(2), hide_index=True, use_container_width=True)
          st.caption("Cada zona pasó por todos los candidatos (línea base estacional, 6 variantes de Holt-Winters y los 3 SARIMA de mejor AIC entre 72 órdenes) "
                     "y se quedó con el de menor error a 1 año en el backtest. Sesgo cerca de 0, cobertura cerca de 80 % y Ljung-Box p > 0,05 son las tres verificaciones.")
          pcm = cargar(R.proy_dir / "comparacion_modelos_por_zona.csv")
          if pcm is not None:
              with st.expander("Ver todos los candidatos probados por zona"):
                  zc = st.selectbox("Zona", zonas, key="proy_zona_cand")
                  t = pcm[pcm["zona_regional"] == zc].drop(columns=["zona_regional"]).sort_values("wape_anio1_pct")
                  t = t.rename(columns={"modelo": "Modelo", "wape_anio1_pct": "Error 1 año (%)", "wape_anio2_pct": "Error 2 años (%)",
                                        "sesgo_anio1_pct": "Sesgo 1 año (%)", "sesgo_anio2_pct": "Sesgo 2 años (%)",
                                        "cobertura_banda80_pct": "Cobertura banda 80 % (%)", "aic": "AIC", "puntos_anio1": "Puntos 1 año", "puntos_anio2": "Puntos 2 años"})
                  tabla(t.round(2), hide_index=True, use_container_width=True)

    pc = cargar(R.proy_comparacion) if tecnico else None
    if pc is not None and len(pc):
        with st.expander("Contraste con la suma de los pronósticos individuales (6 meses)"):
            pc = pc.copy(); pc["periodo"] = pd.to_datetime(pc["periodo"]).dt.strftime("%Y-%m")
            st.caption("Los 580.000 pronósticos por cliente sumados, mes a mes, frente a la proyección del modelo agregado del total. "
                       "Si coinciden, cada uno valida al otro; una diferencia sostenida indica sesgo en uno de los dos.")
            tabla(pc.rename(columns={"periodo": "Mes", "suma_individual_gwh": "Suma pronósticos individuales (GWh)",
                                     "proyeccion_gwh": "Modelo agregado (GWh)", "diferencia_pct": "Diferencia (%)"}).round(2),
                  hide_index=True, use_container_width=True)
    c1, c2 = st.columns(2)
    c1.download_button("Descargar proyección mensual (CSV)", csv_es(pm), file_name="proyeccion_mensual_por_zona.csv", mime="text/csv")
    c2.download_button("Descargar proyección anual (CSV)", csv_es(pa), file_name="proyeccion_anual_por_zona.csv", mime="text/csv")


elif seccion == "Consultar un cliente":
    st.title("Consultar un cliente")
    st.caption("Escribe el NIU y verás, en una sola página, dónde está, qué le pasa al consumo, qué probabilidad de fuga tiene y qué conviene revisar o decirle.")
    with st.expander("¿No tienes el NIU? Buscar por municipio o situación"):
        base = None
        if operativa is not None:
            base = agregar_municipio(operativa[["NIU", "gravedad", "trayectoria", "valor_riesgo_mes", "clase_servicio_nombre"]])
            f1, f2, f3 = st.columns(3)
            munis = ["(todos)"] + (sorted(base["municipio"].dropna().astype(str).unique()) if "municipio" in base.columns else [])
            mun_sel = f1.selectbox("Municipio", munis, key="sop_mun")
            grav_sel = f2.selectbox("Gravedad", ["(todas)"] + list(SEVERIDAD_SIMPLE), format_func=lambda x: SEVERIDAD_SIMPLE.get(x, x), key="sop_grav")
            ten_sel = f3.selectbox("Tendencia", ["(todas)"] + list(TRAYECTORIA_SIMPLE), format_func=lambda x: TRAYECTORIA_SIMPLE.get(x, x), key="sop_ten")
            e = base
            if mun_sel != "(todos)":
                e = e[e["municipio"].astype(str) == mun_sel]
            if grav_sel != "(todas)":
                e = e[e["gravedad"] == grav_sel]
            if ten_sel != "(todas)":
                e = e[e["trayectoria"] == ten_sel]
            e = e.sort_values("valor_riesgo_mes", ascending=False).head(50)
            st.caption(f"{fmt_n(len(e))} clientes de la lista de caída cumplen el filtro (se muestran hasta 50). Copia el NIU y pégalo abajo.")
            tabla(pd.DataFrame({
                "NIU": e["NIU"], "Municipio": e.get("municipio", "—"), "Clase": e["clase_servicio_nombre"],
                "Gravedad": e["gravedad"].map(SEVERIDAD_SIMPLE), "Tendencia": e["trayectoria"].map(TRAYECTORIA_SIMPLE),
                "Facturación que se pierde ($/mes)": e["valor_riesgo_mes"].round(0)}), hide_index=True, use_container_width=True)
        else:
            st.info("Todavía no hay lista de caída.")
    niu = limpiar_niu(st.text_input("NIU del cliente", key="sop_niu"))
    if not niu:
        st.stop()
    if not niu_existe(niu):
        st.warning(f"No hay ningún cliente con el NIU **{niu}** en los datos del corte. Revisa el número (sin puntos ni espacios) "
                   "o búscalo por municipio en el desplegable de arriba.")
        st.stop()
    ficha_cliente_simple(niu)


elif seccion == "Visitas por ciclo":
    st.title("Lista de visitas por ciclo de lectura")
    if operativa is None:
        st.warning("Todavía no hay lista de caída (paso 11 del pipeline).")
        st.stop()
    st.caption("Elige la zona regional, el ciclo (la ruta de lectura) y, si quieres, el municipio. Los clientes van de mayor a menor facturación perdida: "
               "**Orden 1 es el cliente del ciclo con más facturación en riesgo**, por ahí empieza la cuadrilla. La columna **Qué revisar** resume lo que conviene mirar en la visita. "
               "No incluye autogeneradores ni área común, autoconsumos EBSA, distritos de riego y provisionales.")
    c_z, c_c = st.columns([1, 2])
    zonas_reg = [z for z in ZONAS_REGIONALES if z in set(operativa["zona_regional"].astype(str))] \
        + sorted(set(operativa["zona_regional"].dropna().astype(str)) - set(ZONAS_REGIONALES))
    zona_reg = c_z.selectbox("Zona regional", ["(todas)"] + zonas_reg, key="vis_zona_reg")
    base_c = operativa if zona_reg == "(todas)" else operativa[operativa["zona_regional"].astype(str) == zona_reg]
    ciclos = sorted(base_c["ciclo_etiqueta"].unique())
    ciclo = c_c.selectbox("Ciclo", ciclos, format_func=etiqueta_ciclo, key="vis_ciclo")
    d = operativa[operativa["ciclo_etiqueta"] == ciclo].copy()
    d["NIU"] = d["NIU"].astype("string").str.strip()
    if ubicacion is not None:
        d = d.merge(ubicacion[["NIU", "municipio", "direccion", "latitud", "longitud", "coordenadas_validas"]].drop_duplicates("NIU"), on="NIU", how="left")
    f1, f2, f3, f4, f5 = st.columns(5)
    mun = filtro_municipio(f1, d, "vis_mun")
    grav = f2.multiselect("Gravedad", ["CRITICA", "FUERTE", "MODERADA", "ANTIGUA"], format_func=lambda x: SEVERIDAD_SIMPLE.get(x, x), key="vis_grav", placeholder="Todas")
    ten = f3.multiselect("Tendencia", list(TRAYECTORIA_SIMPLE), format_func=lambda x: TRAYECTORIA_SIMPLE[x], key="vis_ten", placeholder="Todas")
    est = f4.multiselect("Situación", ["NUEVO", "PERSISTENTE", "REINCIDENTE"], format_func=lambda x: ESTADO_LISTA_SIMPLE.get(x, x), key="vis_est", placeholder="Todas")
    lec = f5.multiselect("Tipo de lectura", sorted(d["tipo_lectura_nombre"].dropna().astype(str).unique()), key="vis_lec", placeholder="Todas",
                         help="REAL: leída del medidor. ESTIMADA: la empresa estimó el consumo; una caída con lectura estimada puede no ser real.") if "tipo_lectura_nombre" in d.columns else []
    pri = st.multiselect("Prioridad", list(PRIORIDAD_SIMPLE), default=["GESTIONAR"], format_func=lambda x: PRIORIDAD_SIMPLE[x], key="vis_pri",
                         help="Por defecto solo lo que hay que gestionar; 'Seguimiento' son caídas que llevan meses en el mismo nivel y los 'Vigilar' son estacionales o con recuperación prevista: van después en el ciclo.") if "prioridad_gestion" in d.columns else []
    if pri:
        d = d[d["prioridad_gestion"].isin(pri)]
    if mun:
        d = d[d["municipio"].astype(str).isin(mun)]
    if grav:
        d = d[d["gravedad"].isin(grav)]
    if ten and "trayectoria" in d.columns:
        d = d[d["trayectoria"].isin(ten)]
    if est and "estado_en_lista" in d.columns:
        d = d[d["estado_en_lista"].isin(est)]
    if lec:
        d = d[d["tipo_lectura_nombre"].astype(str).isin(lec)]
    d = d.sort_values("orden_en_ciclo")
    if len(d) == 0:
        st.info("Ningún cliente de este ciclo cumple estos filtros. Prueba a quitar alguno o a elegir otra prioridad.")
        st.stop()
    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes para visitar", f"{fmt_n(len(d))}")
    c2.metric("Facturación que se pierde", f"{pesos(d['valor_riesgo_mes'].sum())}/mes")
    c3.metric("Caídas graves", f"{fmt_n(int(d['gravedad'].eq('CRITICA').sum()))}")
    linea_conteo(len(d), len(d), int((operativa["ciclo_etiqueta"] == ciclo).sum()), len(operativa),
                 "clientes de este ciclo", "en el ciclo sin filtros", "clientes en toda la lista de caída")
    t = pd.DataFrame({
        "Orden": d["orden_en_ciclo"], "NIU": d["NIU"],
        "Municipio": d["municipio"] if "municipio" in d.columns else "—",
        "Dirección": d["direccion"] if "direccion" in d.columns else "—",
        "Clase": d.get("clase_servicio_nombre", d.get("clase_servicio", "—")),
        "Lectura": d["tipo_lectura_nombre"] if "tipo_lectura_nombre" in d.columns else "—",
        "Tipo de caída": d["veredicto"].map(TIPO_CAIDA_SIMPLE).fillna("—") if "veredicto" in d.columns else "—",
        "Consumía (kWh/mes)": referencia_caida(d).round(0), "Consume ahora (kWh/mes)": d["consumo_reciente_kwh"].round(0),
        "Caída": caida_vs_referencia_pct(d).round(0).astype("Int64").astype(str) + " %",
        "Facturación que se pierde ($/mes)": d["valor_riesgo_mes"].round(0),
        "Gravedad": d["gravedad"].map(SEVERIDAD_SIMPLE).fillna(d["gravedad"]),
        "Tendencia": d["trayectoria"].map(TRAYECTORIA_SIMPLE).fillna("—") if "trayectoria" in d.columns else "—",
        "Prioridad": d["prioridad_gestion"].map(PRIORIDAD_SIMPLE).fillna(d["prioridad_gestion"]) if "prioridad_gestion" in d.columns else "Gestionar",
        "Situación": d["estado_en_lista"].map(ESTADO_LISTA_SIMPLE).fillna("") if "estado_en_lista" in d.columns else "",
        "Qué revisar": d.apply(que_revisar, axis=1),
    })
    st.download_button(f"Descargar la ruta del ciclo {ciclo} (CSV)", csv_es(t),
                       file_name=f"visitas_ciclo_{ciclo}_{corte_actual or ''}.csv", mime="text/csv")
    tabla_con_ficha(t.reset_index(drop=True), "sop_vis", hide_index=True, use_container_width=True, height=520)
    if "coordenadas_validas" in d.columns and d["coordenadas_validas"].fillna(False).astype(bool).any():
        with st.expander("Ver estos clientes en el mapa"):
            pts = d[d["coordenadas_validas"].fillna(False).astype(bool)].copy()
            pts["color"] = pts["gravedad"].map({"CRITICA": NARANJA, "FUERTE": "#f2a65a", "MODERADA": AZUL, "ANTIGUA": GRIS_ANTIGUA}).fillna(AZUL)
            st.map(pts.rename(columns={"latitud": "lat", "longitud": "lon"}), color="color", size=120, height=480)
            st.caption("Naranja: caída grave · naranja claro: fuerte · azul: moderada · gris: antigua (lleva meses así).")


# ============================================================================
# VISTA ADMINISTRADOR DEL MODELO (todo lo técnico)
# ============================================================================
# ----------------------------------------------------------------------------
# Resumen
# ----------------------------------------------------------------------------
elif seccion == "Resumen":
    st.title("Resumen del periodo facturado")
    st.markdown(f"Periodo facturado: **urbano {CORTE_ZONA.get('URBANO', corte_actual or '—')}** · "
                f"**rural {CORTE_ZONA.get('RURAL', '—')}** (los rurales se leen por trimestres, por eso su periodo puede ir un par de meses atrás).")
    st.markdown(QUE_ES_ESTO)
    if operativa is None:
        st.stop()
    cs_r = cargar(R.cero_sostenido, dtype={"NIU": "string"})
    if cs_r is not None and len(cs_r):
        st.caption(f"Fuera de la lista: {fmt_n(len(cs_r))} clientes en cero sostenido (3+ meses en cero o casi cero; `clientes_cero_sostenido.csv`), "
                   "autogeneradores y las clases AC, AU, RI y PR (`clientes_excluidos_de_gestion.csv`).")

    g = operativa
    con_tarifa = g["tiene_tarifa"].astype(str).str.lower().eq("true") if "tiene_tarifa" in g.columns else pd.Series(True, index=g.index)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Clientes en la lista", f"{fmt_n(len(g))}")
    c2.metric("kWh/mes en riesgo", f"{fmt_n(g['perdida_kwh_mes'].sum())}")
    c3.metric("Valor en riesgo / mes", pesos(g["valor_riesgo_mes"].sum()),
              help="Pérdida de kWh × tarifa REAL de cada cliente. Los sin tarifa no se valoran.")
    c4.metric("Ciclos con clientes", f"{g['ciclo_etiqueta'].nunique()}")
    if (~con_tarifa).any():
        st.caption(f"{fmt_n(int((~con_tarifa).sum()))} clientes sin tarifa en el sistema comercial: aparecen en la lista pero sin valor.")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("¿Qué prevé el modelo para el mes siguiente?")
        if "trayectoria" in g.columns:
            t = g.groupby("trayectoria").agg(clientes=("NIU", "size"), valor_mes=("valor_riesgo_mes", "sum")).reset_index()
            t["valor_mes"] = t["valor_mes"].round(0)
            tabla(t.sort_values("clientes", ascending=False), hide_index=True, use_container_width=True)
            with st.expander("Qué significa cada trayectoria"):
                for k, v in TRAYECTORIA_TEXTO.items():
                    st.markdown(f"**{k}** — {v}")
    with col_b:
        st.subheader("¿Es nuevo en la lista o lleva meses?")
        if "estado_en_lista" in g.columns:
            e = g.groupby("estado_en_lista").agg(clientes=("NIU", "size"), valor_mes=("valor_riesgo_mes", "sum")).reset_index()
            tabla(e, hide_index=True, use_container_width=True)
            st.caption("NUEVO: primera vez. PERSISTENTE: también estaba el mes pasado. REINCIDENTE: estuvo en los últimos 12 meses.")
        es = cargar(R.entradas_salidas)
        if es is not None and len(es):
            u = es.iloc[-1]
            st.markdown(
                f"Frente al corte **{u['corte_anterior']}**: permanecen **{fmt_n(int(u['permanecen']))}**, "
                f"salieron **{fmt_n(int(u['salieron']))}**, entraron **{fmt_n(int(u['entraron']))}**."
            )

    st.subheader("Riesgo de fuga a otro comercializador")
    if fuga is None:
        st.info("Aún no hay corrida del riesgo de fuga (paso 14 del pipeline).")
    else:
        alto = fuga[fuga["nivel_riesgo"].eq("ALTO")]
        medio = fuga[fuga["nivel_riesgo"].eq("MEDIO")]
        ya = cargar(R.fuga_ya_fuera, dtype={"NIU": "string"})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Clientes puntuados", f"{fmt_n(len(fuga))}")
        c2.metric("Riesgo ALTO", f"{fmt_n(len(alto))}", help=NIVEL_FUGA_TEXTO["ALTO"])
        c3.metric("Riesgo MEDIO", f"{fmt_n(len(medio))}", help=NIVEL_FUGA_TEXTO["MEDIO"])
        c4.metric("Pérdida esperada / mes (ALTO+MEDIO)", pesos(pd.concat([alto, medio])["valor_esperado_perdida_mes"].sum()),
                  help="Probabilidad de salida × lo que factura hoy (consumo promedio 6 meses × tarifa real).")
        if ya is not None and len(ya):
            n_con = int(ya["estado"].astype(str).str.startswith("CON OTRO").sum())
            st.caption(f"Ya atendidos por otro comercializador: **{fmt_n(len(ya))}** NIU en el archivo de la empresa "
                       f"({fmt_n(n_con)} en el último mes del archivo). Detalle en la sección Riesgo de fuga.")

    st.subheader("Dónde está el valor: zonas regionales")
    rz = g.groupby("zona_regional").agg(clientes=("NIU", "size"), criticos=("severidad", lambda x: int(x.eq("CRITICA").sum())),
                                        kwh_mes=("perdida_kwh_mes", "sum"), valor_riesgo_mes=("valor_riesgo_mes", "sum")).reset_index()
    rz = rz.sort_values("valor_riesgo_mes", ascending=False)
    c1, c2 = st.columns([1, 1])
    with c1:
        st.bar_chart(rz.set_index("zona_regional")["valor_riesgo_mes"], color=AZUL, height=280)
    with c2:
        tabla(rz, hide_index=True, use_container_width=True)
    st.caption("Zona regional = ciclo urbano + rural + seccionales de una misma dirección regional (quien decide las acciones en terreno).")

    st.subheader("Dónde está el valor: ciclos de lectura")
    rc = cargar(R.resumen_ciclo, dtype={"ciclo_etiqueta": "string"})
    if rc is not None:
        rc = rc.sort_values("valor_riesgo_mes", ascending=False)
        rc.insert(1, "zona_nombre", rc["ciclo_etiqueta"].map(etiqueta_ciclo))
        st.bar_chart(rc.set_index("zona_nombre")["valor_riesgo_mes"], color=AZUL, height=280)
        tabla(rc, hide_index=True, use_container_width=True)

    st.subheader("Severidad")
    sev = g.groupby("severidad").agg(clientes=("NIU", "size"), kwh_mes=("perdida_kwh_mes", "sum"),
                                     valor_mes=("valor_riesgo_mes", "sum")).reset_index()
    tabla(sev, hide_index=True, use_container_width=True)
    st.caption("Severidad relativa al segmento: CRITICA ≥ 2 escalas por encima del umbral, FUERTE ≥ 1, MODERADA el resto.")


# ----------------------------------------------------------------------------
# Gestión por ciclo
# ----------------------------------------------------------------------------
elif seccion == "Gestión por ciclo":
    st.title("Lista operativa por ciclo de lectura")
    if operativa is None:
        st.stop()
    st.caption("Dentro de cada ciclo los clientes van de mayor a menor valor en riesgo: una cuadrilla empieza por el primero. "
               "**orden_en_ciclo** es ese puesto: 1 es el cliente del ciclo con más facturación en riesgo. "
               "No incluye autogeneradores ni las clases área común, autoconsumos EBSA, distritos de riego y provisionales (regla de negocio).")

    # Cuántos clientes por severidad, en general o por zona regional (pedido del experto de negocio)
    with st.expander("Clientes por severidad (general o por zona regional)", expanded=True):
        por = st.radio("Ver", ["General", "Por zona regional"], horizontal=True, key="sev_por")
        st.caption("Aquí se muestra la **severidad original** del estudio de caída (tamaño de la caída frente a clientes parecidos), "
                   "incluidas las caídas que llevan meses así. En las vistas Comercial y Soporte, y en el mapa, esas caídas antiguas "
                   "se muestran como 'Antigua' y 'Grave' queda solo para las recientes: por eso el conteo de críticas es menor allá.")
        orden_sev = [x for x in ["CRITICA", "FUERTE", "MODERADA"] if x in set(operativa["severidad"].astype(str))]
        if por == "General":
            t_sev = operativa.groupby("severidad").size().reindex(orden_sev).rename("clientes")
            st.bar_chart(t_sev, color=AZUL, height=240)
        else:
            t_sev = operativa.groupby(["zona_regional", "severidad"]).size().unstack(fill_value=0).reindex(columns=orden_sev)
            t_sev = t_sev.loc[t_sev.sum(axis=1).sort_values(ascending=False).index]
            st.bar_chart(t_sev, color=[NARANJA, "#f2a65a", AZUL][:len(orden_sev)], height=300)
            tabla(t_sev.reset_index(), hide_index=True, use_container_width=True)

    c_z, c_c = st.columns([1, 2])
    zonas_reg = [z for z in ZONAS_REGIONALES if z in set(operativa["zona_regional"].astype(str))] \
        + sorted(set(operativa["zona_regional"].dropna().astype(str)) - set(ZONAS_REGIONALES))
    zona_reg = c_z.selectbox("Zona regional", ["(todas)"] + zonas_reg, key="gc_zona_reg",
                             help="Agrupa el ciclo urbano, el rural y los seccionales de una misma dirección regional")
    base_c = operativa if zona_reg == "(todas)" else operativa[operativa["zona_regional"].astype(str) == zona_reg]
    ciclos = sorted(base_c["ciclo_etiqueta"].unique())
    ciclo = c_c.selectbox("Ciclo (ruta de lectura)", ciclos, format_func=etiqueta_ciclo)
    d = agregar_municipio(operativa[operativa["ciclo_etiqueta"] == ciclo])

    f1, f2, f3, f4, f5, f6 = st.columns(6)
    sev = f1.multiselect("Severidad", sorted(d["severidad"].dropna().unique()))
    tra = f2.multiselect("Trayectoria", sorted(d["trayectoria"].dropna().unique())) if "trayectoria" in d.columns else []
    est = f3.multiselect("Estado en lista", sorted(d["estado_en_lista"].dropna().unique())) if "estado_en_lista" in d.columns else []
    grp = f4.multiselect("Grupo de consumo", [g for g in GRUPOS_CONSUMO_ORDEN if g in d.get("grupo_consumo", pd.Series(dtype=str)).unique()]) if "grupo_consumo" in d.columns else []
    lec = f5.multiselect("Tipo de lectura", sorted(d["tipo_lectura_nombre"].dropna().astype(str).unique()), key="gc_lec",
                         help="REAL: lectura tomada del medidor. ESTIMADA: la empresa estimó el consumo. Una caída con lectura estimada puede no ser real.") if "tipo_lectura_nombre" in d.columns else []
    mun = filtro_municipio(f6, d, "mun_ciclo")
    if sev:
        d = d[d["severidad"].isin(sev)]
    if tra:
        d = d[d["trayectoria"].isin(tra)]
    if est:
        d = d[d["estado_en_lista"].isin(est)]
    if grp:
        d = d[d["grupo_consumo"].isin(grp)]
    if lec:
        d = d[d["tipo_lectura_nombre"].astype(str).isin(lec)]
    if mun:
        d = d[d["municipio"].astype(str).isin(mun)]

    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes", f"{fmt_n(len(d))}")
    c2.metric("kWh/mes", f"{fmt_n(d['perdida_kwh_mes'].sum())}")
    c3.metric("Valor/mes", pesos(d["valor_riesgo_mes"].sum()))
    linea_conteo(len(d), len(d), int((operativa["ciclo_etiqueta"] == ciclo).sum()), len(operativa),
                 "clientes de este ciclo", "en el ciclo sin filtros", "clientes en toda la lista de caída")

    cols = [c for c in ["orden_en_ciclo", "ciclo_etiqueta", "NIU", "municipio", "zona_regional", "zona_nombre", "clase_servicio_nombre", "estrato", "grupo_consumo",
                        "cluster_id", "severidad", "trayectoria", "prioridad_gestion", "estado_en_lista", "meses_consecutivos_en_lista",
                        "consumo_anterior_kwh", "consumo_reciente_kwh", "perdida_kwh_mes",
                        "tarifa_kwh", "valor_riesgo_mes", "pred_1m_kwh", "consumo_promedio_semestral_kwh",
                        "valor_facturado_mes", "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in d.columns]
    tabla_con_ficha(d[cols].reset_index(drop=True), "adm_ciclo", "Administrador del modelo", hide_index=True, use_container_width=True, height=520)
    st.download_button(
        f"Descargar ciclo {ciclo} (CSV)", csv_es(d[cols]),
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
    ger = agregar_municipio(limpiar_lista(ger))
    col_zona = "zona_regional"
    col_clase = "clase_servicio_nombre" if "clase_servicio_nombre" in ger.columns else "clase_servicio"
    st.caption("Sin autogeneradores ni las clases área común, autoconsumos EBSA, distritos de riego y provisionales (regla de negocio). "
               "El filtro de zona usa la zona regional: ciclo urbano, rural y seccionales juntos.")
    f1, f2, f3, f4, f5 = st.columns(5)
    zona = filtro_zona_regional(f1, ger, "ger_zona_reg")
    mun = filtro_municipio(f5, ger, "mun_ger")
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
    if mun:
        d = d[d["municipio"].astype(str).isin(mun)]
    total = d["valor_riesgo_mes"].sum()
    if "prioridad_gestion" in d.columns:
        d = d.assign(_pri=d["prioridad_gestion"].map(ORDEN_PRIORIDAD).fillna(0))
        d = d.sort_values(["_pri", "valor_riesgo_mes"], ascending=[True, False])
    top = d.head(n)
    linea_conteo(len(top), len(d), len(ger), n_evaluados_caida(), "clientes de la lista", "en toda la lista de caída", "clientes evaluados por el detector")
    st.markdown(
        f"Los **{fmt_n(len(top))}** primeros concentran **{pesos_md(top['valor_riesgo_mes'].sum())}/mes**, "
        f"el **{(top['valor_riesgo_mes'].sum() / total * 100 if total else 0):.1f}%** del valor filtrado "
        f"({pesos_md(total)} sobre {fmt_n(len(d))} clientes)."
    )
    cols = [c for c in ["ranking", "NIU", "ciclo_etiqueta", "municipio", "zona_regional", "zona_nombre", "clase_servicio_nombre", "estrato", "grupo_consumo",
                        "cluster_id", "severidad", "trayectoria", "estado_en_lista",
                        "consumo_anterior_kwh", "consumo_reciente_kwh", "perdida_kwh_mes", "tarifa_kwh",
                        "valor_riesgo_mes", "consumo_promedio_semestral_kwh", "valor_facturado_mes",
                        "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in top.columns]
    tabla_con_ficha(top[cols].reset_index(drop=True), "adm_rank", "Administrador del modelo", hide_index=True, use_container_width=True, height=560)
    st.download_button("Descargar (CSV)", csv_es(top[cols]),
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
    c1.metric("Clientes puntuados", f"{fmt_n(len(fuga))}")
    c2.metric("Riesgo ALTO", f"{fmt_n(len(alto))}")
    c3.metric("Riesgo MEDIO", f"{fmt_n(len(medio))}")
    c4.metric("Pérdida esperada / mes", pesos(pd.concat([alto, medio])["valor_esperado_perdida_mes"].sum()))
    c5.metric("Corte · modelo", f"{corte_f} · {corte_modelo_f}", help=f"Método: {metodo}")
    st.caption("Se puntúan los clientes de las clases de servicio que aparecen entre los que ya se fueron "
               "(comercial, industrial, oficial, acueductos), sin alumbrado, provisionales ni autogeneradores. "
               "Probabilidad de salida en los próximos 6 meses; el valor es lo que factura hoy con su tarifa real. "
               "El mercado no regulado (ciclo 33, clase IR o ≥ 55.000 kWh/mes) se puntúa aparte y solo aparece en "
               "la pestaña **Vigilancia no regulados**, nunca en este ranking.")

    tabs = st.tabs(["Lista", "Por zona y grupo", "Ya con otro comercializador", "Vigilancia no regulados",
                    "Calidad del modelo", "Seguimiento"])

    with tabs[0]:
        fuga_m = agregar_municipio(fuga)
        f1, f2, f3, f4, f5 = st.columns(5)
        niv = f1.multiselect("Nivel de riesgo", ["ALTO", "MEDIO", "BAJO"], default=["ALTO", "MEDIO"])
        zon = filtro_zona_regional(f2, fuga_m, "fuga_zona_reg")
        grp = f3.multiselect("Grupo de consumo", [g for g in GRUPOS_CONSUMO_ORDEN if g in fuga["grupo_consumo"].unique()])
        cla = f4.multiselect("Clase de servicio", sorted(fuga["clase_servicio_nombre"].dropna().astype(str).unique()))
        mun = filtro_municipio(f5, fuga_m, "mun_fuga")
        d = fuga_m.copy()
        if niv:
            d = d[d["nivel_riesgo"].isin(niv)]
        if zon:
            d = d[d["zona_regional"].astype(str).isin(zon)]
        if grp:
            d = d[d["grupo_consumo"].isin(grp)]
        if cla:
            d = d[d["clase_servicio_nombre"].astype(str).isin(cla)]
        if mun:
            d = d[d["municipio"].astype(str).isin(mun)]
        orden = st.radio("Ordenar por", ["Pérdida esperada (probabilidad × valor)", "Probabilidad de salida"], horizontal=True)
        d = d.sort_values("valor_esperado_perdida_mes" if orden.startswith("Pérdida") else "prob_fuga_6m", ascending=False)
        st.markdown(f"**{fmt_n(len(d))}** clientes · pérdida esperada **{pesos_md(d['valor_esperado_perdida_mes'].sum())}/mes** · "
                    f"facturación en juego **{pesos_md(d['valor_en_riesgo_mes'].sum())}/mes**")
        linea_conteo(min(len(d), 1000), len(d), int(fuga["nivel_riesgo"].isin(["ALTO", "MEDIO"]).sum()), len(fuga),
                     "clientes", "con riesgo ALTO o MEDIO en total", "clientes puntuados por el modelo")
        cols = [c for c in ["ranking", "NIU", "nivel_riesgo", "prob_fuga_6m", "valor_esperado_perdida_mes", "valor_en_riesgo_mes",
                            "municipio", "zona_regional", "zona_nombre", "clase_servicio_nombre", "grupo_consumo", "estrato", "consumo_actual_kwh",
                            "consumo_prom_6m_kwh", "consumo_prom_12m_kwh", "variacion_3m_vs_12m_pct", "meses_cero_3m",
                            "senales", "estado_en_lista", "meses_consecutivos_en_lista", "tarifa_kwh",
                            "consumo_promedio_semestral_kwh", "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in d.columns]
        tabla_con_ficha(d[cols].head(1000).reset_index(drop=True), "adm_fuga", "Administrador del modelo", hide_index=True, use_container_width=True, height=520)
        st.download_button("Descargar lo filtrado (CSV)", csv_es(d[cols]),
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
                tabla(rz, hide_index=True, use_container_width=True)
        with c2:
            st.subheader("Por grupo de consumo")
            if rg is not None:
                tabla(rg, hide_index=True, use_container_width=True)
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
                col.metric(k if len(k) < 28 else k[:26] + "…", f"{fmt_n(v)}", help=ESTADO_OTRO_TEXTO.get(k, k))
            if "valor_facturado_antes_salida_mes" in ya.columns and ya["valor_facturado_antes_salida_mes"].notna().any():
                st.markdown(f"Facturaban antes de irse (solo con tarifa real): "
                            f"**{pesos_md(ya['valor_facturado_antes_salida_mes'].sum())}/mes** "
                            f"sobre {fmt_n(int(ya['valor_facturado_antes_salida_mes'].notna().sum()))} clientes con historia TC2.")
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
            tabla(d[cols], hide_index=True, use_container_width=True, height=420)
            st.download_button("Descargar (CSV)", csv_es(d[cols]),
                               file_name=f"clientes_con_otro_comercializador_{corte_f}.csv", mime="text/csv")
            pi = cargar(R.fuga_perfil_idos)
            if pi is not None:
                with st.expander("Perfil de los que se fueron (clase, zona, tamaño, comercializador, municipio)"):
                    for dim, t in pi.groupby("dimension", sort=False):
                        st.markdown(f"**{dim}**")
                        tabla(t.drop(columns=["dimension"]).head(15), hide_index=True, use_container_width=True)

    with tabs[3]:
        vg = cargar(R.fuga_vigilancia, dtype={"NIU": "string"})
        st.subheader("Mercado no regulado")
        st.caption("Clientes en el ciclo 33 (USUARIOS NO REGULADOS), con clase IR (NO REGULADO) o con consumo promedio "
                   "≥ 55.000 kWh/mes: por tamaño pueden negociar con cualquier comercializador. Se puntúan con el mismo "
                   "modelo pero **no entran al ranking ni a las listas**: su seguimiento es comercial, no de cuadrilla. "
                   "El nivel sale solo de la probabilidad (ALTO ≥ 5 × tasa base, MEDIO ≥ 2 ×).")
        if vg is None or len(vg) == 0:
            st.info("Ningún cliente cumple hoy los criterios de vigilancia.")
        else:
            vg = agregar_municipio(vg)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("En vigilancia", f"{fmt_n(len(vg))}")
            if "nivel_riesgo" in vg.columns:
                c2.metric("Riesgo ALTO", f"{fmt_n(int(vg['nivel_riesgo'].eq('ALTO').sum()))}")
                c3.metric("Riesgo MEDIO", f"{fmt_n(int(vg['nivel_riesgo'].eq('MEDIO').sum()))}")
            if "valor_facturado_mes" in vg.columns:
                c4.metric("Facturación / mes", pesos(vg["valor_facturado_mes"].sum()))
            if "motivo" in vg.columns:
                st.caption(" · ".join(f"**{k}**: {v}" for k, v in vg["motivo"].value_counts().items()))
            cols_v = [c for c in ["NIU", "motivo", "estado", "nivel_riesgo", "prob_fuga_6m", "municipio", "zona_nombre",
                                  "clase_servicio_nombre", "grupo_consumo", "consumo_actual_kwh", "consumo_prom_6m_kwh",
                                  "consumo_prom_12m_kwh", "tarifa_kwh", "valor_facturado_mes", "senales", "fecha_corte"] if c in vg.columns]
            tabla(vg[cols_v], hide_index=True, use_container_width=True, height=420)
            st.download_button("Descargar (CSV)", csv_es(vg[cols_v]),
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
            tabla(mt, hide_index=True, use_container_width=True)
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
                       "La ventana se completa cuando pasan los 6 meses del corte; no es algo que se marque a mano. "
                       "Si la columna *observable* dice NO, las celdas vacías no significan que nadie se fue: el archivo de otros "
                       "comercializadores termina antes de esa lista y todavía no se puede saber.")
            sf = sf.copy()
            if "ventana_completa" in sf.columns:
                sf["ventana_completa"] = np.where(sf["ventana_completa"].astype(str).str.lower().eq("true"),
                                                  "Sí (6 meses cumplidos)", "No (en curso)")
            tabla(sf, hide_index=True, use_container_width=True)


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
            tabla(grupo.drop(columns=[corte_col]), hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------
# Mapa (municipios de Boyacá; necesita 13_ubicacion_clientes del cruce con el TC1)
# ----------------------------------------------------------------------------
elif seccion == "Mapa":
    st.title("Mapa: dónde están los clientes, las caídas y el riesgo de fuga")
    mm = metricas_municipio()
    if mm is None:
        st.stop()
    dibujar_mapa(mm, METRICAS_MAPA_TECNICO, clave="admin", puntos=True)


# ----------------------------------------------------------------------------
# Buscar cliente
# ----------------------------------------------------------------------------
elif seccion == "Buscar cliente":
    st.title("Buscar un cliente")

    # --- Ejemplos por perfil / segmento / trayectoria / ciclo, para no tener que
    #     conocer un NIU de memoria ---
    with st.expander("¿No tienes un NIU a mano? Buscar ejemplos por grupo, segmento, ciclo, municipio o situación"):
        seg_all = cargar(R.clusters, columns=["NIU", "cluster_id", "zona", "mediana_12m_kwh"])
        pred_all = pred6[["NIU", "perfil"]] if pred6 is not None else None
        ejemplos = None
        if seg_all is not None:
            ejemplos = seg_all.copy()
            ejemplos["NIU"] = ejemplos["NIU"].astype("string").str.strip()
            if pred_all is not None:
                pa = pred_all.copy(); pa["NIU"] = pa["NIU"].astype("string").str.strip()
                ejemplos = ejemplos.merge(pa, on="NIU", how="left")
            # Ciclo y zona de TODOS los clientes (niu_ciclo.parquet), no solo de los que están en la lista
            nc_all = cargar(R.niu_ciclo)
            if nc_all is not None:
                nc_all = nc_all.copy()
                nc_all["NIU"] = nc_all["NIU"].astype("string").str.strip()
                col_c = "ciclo_actual" if "ciclo_actual" in nc_all.columns else "ciclo"
                nc_all["ciclo_etiqueta"] = nc_all[col_c].map(lambda x: f"{int(x):02d}" if pd.notna(x) else "SIN_CICLO")
                nc_all["zona_nombre"] = nombre_zona(nc_all[col_c])
                ejemplos = ejemplos.merge(nc_all[["NIU", "ciclo_etiqueta", "zona_nombre"]].drop_duplicates("NIU"), on="NIU", how="left")
            ejemplos = agregar_municipio(ejemplos)
            # Situación en la lista de caída: el que no está, no está (no es un dato faltante)
            if operativa is not None:
                ejemplos = ejemplos.merge(
                    operativa[["NIU", "veredicto", "severidad", "trayectoria", "valor_riesgo_mes"]],
                    on="NIU", how="left",
                )
                for c in ["veredicto", "severidad", "trayectoria"]:
                    ejemplos[c] = ejemplos[c].astype("string").fillna("No está en la lista de caída")
            # Situación en el riesgo de fuga
            if fuga is not None:
                fz_all = fuga[["NIU", "nivel_riesgo", "prob_fuga_6m"]].copy()
                fz_all["NIU"] = fz_all["NIU"].astype("string").str.strip()
                ejemplos = ejemplos.merge(fz_all.rename(columns={"nivel_riesgo": "riesgo_fuga"}).drop_duplicates("NIU"), on="NIU", how="left")
                ejemplos["riesgo_fuga"] = ejemplos["riesgo_fuga"].astype("string").fillna("No puntuado")
        if ejemplos is None:
            st.info("Aún no hay segmentación ni pronóstico para listar ejemplos.")
        else:
            if "perfil" in ejemplos.columns:
                ejemplos["grupo_consumo"] = grupo_desde_perfil(ejemplos["perfil"]).fillna("Sin historia suficiente")
            f1, f2, f3, f4, f5, f6 = st.columns(6)
            perfiles = ["(todos)"] + [g for g in GRUPOS_CONSUMO_ORDEN if g in ejemplos.get("grupo_consumo", pd.Series(dtype=str)).unique()]
            perfil_sel = f1.selectbox("Grupo de consumo", perfiles, help=" · ".join(f"{g}: {v}" for g, v in GRUPO_CONSUMO_DESCRIPCION.items()))
            segmentos = ["(todos)"] + sorted(ejemplos["cluster_id"].dropna().unique())
            seg_sel = f2.selectbox("Segmento de negocio", segmentos)
            ciclos_ej = ["(todos)"] + (sorted(ejemplos["ciclo_etiqueta"].dropna().unique()) if "ciclo_etiqueta" in ejemplos.columns else [])
            cic_sel = f3.selectbox("Ciclo", ciclos_ej, format_func=lambda c: c if c == "(todos)" else etiqueta_ciclo(c))
            munis = ["(todos)"] + (sorted(ejemplos["municipio"].dropna().astype(str).unique()) if "municipio" in ejemplos.columns else [])
            mun_sel = f4.selectbox("Municipio", munis, help="Necesita el cruce con el TC1 (python cruzar_ubicacion_tc1.py)" if len(munis) == 1 else None)
            trayectorias = ["(todos)"] + (sorted(ejemplos["trayectoria"].dropna().unique()) if "trayectoria" in ejemplos.columns else [])
            tra_sel = f5.selectbox("Situación en caída", trayectorias)
            fugas = ["(todos)"] + (["ALTO", "MEDIO", "BAJO", "No puntuado"] if "riesgo_fuga" in ejemplos.columns else [])
            fug_sel = f6.selectbox("Riesgo de fuga", fugas)

            e = ejemplos
            if perfil_sel != "(todos)":
                e = e[e["grupo_consumo"] == perfil_sel]
            if seg_sel != "(todos)":
                e = e[e["cluster_id"] == seg_sel]
            if cic_sel != "(todos)":
                e = e[e["ciclo_etiqueta"] == cic_sel]
            if mun_sel != "(todos)":
                e = e[e["municipio"].astype(str) == mun_sel]
            if tra_sel != "(todos)":
                e = e[e["trayectoria"] == tra_sel]
            if fug_sel != "(todos)":
                e = e[e["riesgo_fuga"] == fug_sel]
            if "valor_riesgo_mes" in e.columns:
                e = e.sort_values(["valor_riesgo_mes", "mediana_12m_kwh"], ascending=[False, False], na_position="last")
            st.caption(f"{fmt_n(len(e))} clientes cumplen el filtro. Se muestran hasta 50; copia el NIU y pégalo abajo.")
            cols_e = [c for c in ["NIU", "municipio", "ciclo_etiqueta", "zona_nombre", "grupo_consumo", "cluster_id", "zona",
                                  "mediana_12m_kwh", "veredicto", "severidad", "trayectoria", "valor_riesgo_mes",
                                  "riesgo_fuga", "prob_fuga_6m"] if c in e.columns]
            tabla(e[cols_e].head(50), hide_index=True, use_container_width=True)

    niu = limpiar_niu(st.text_input("NIU", key="adm_niu"))
    if not niu:
        st.stop()
    if not niu_existe(niu):
        st.warning(f"No hay ningún cliente con el NIU **{niu}** en los datos del corte (ni en el TC1 cruzado, ni en el pronóstico, "
                   "ni en las listas). Revisa el número.")
        st.stop()

    # --- Avisos de condición comercial: autogenerador / mercado no regulado ---
    auto_ex = cargar(R.autogeneradores)
    es_autogenerador = bool(auto_ex is not None and niu in set(auto_ex["NIU"].astype("string").str.strip()))
    if ubicacion is not None:
        u = ubicacion[ubicacion["NIU"] == niu]
        if len(u) and pd.notna(u["autogenerador_tc1"].iloc[0]) and bool(u["autogenerador_tc1"].iloc[0]):
            es_autogenerador = True
    if es_autogenerador:
        st.warning("**Autogenerador** (ciclo 50 o marcado en el TC1): produce parte de su propia energía, por eso su consumo "
                   "de la red es bajo por diseño. Está excluido de la serie de modelado y de las listas de caída y fuga.")
    vg_c = cargar(R.fuga_vigilancia, dtype={"NIU": "string"})
    if vg_c is not None and niu in set(vg_c["NIU"].astype("string").str.strip()):
        v = vg_c[vg_c["NIU"].astype("string").str.strip() == niu].iloc[0]
        st.info(f"**Mercado no regulado** ({v.get('motivo', '')}): se puntúa aparte y no entra al ranking de fuga. "
                f"Nivel **{v.get('nivel_riesgo', '—')}**, probabilidad 6 meses "
                f"**{(float(v['prob_fuga_6m']) * 100):.2f}%**." if pd.notna(v.get("prob_fuga_6m", np.nan)) else
                f"**Mercado no regulado** ({v.get('motivo', '')}): en vigilancia, hoy sin puntuar ({v.get('estado', '')}).")

    # --- Ubicación (cruce con el TC1) ---
    if ubicacion is not None:
        u = ubicacion[ubicacion["NIU"] == niu]
        st.subheader("Ubicación")
        if len(u):
            u = u.iloc[0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Municipio", str(u.get("municipio", "—")))
            c2.metric("Provincia", str(u.get("provincia", "—")))
            c3.metric("Zona (mapa)", str(u.get("zona_mapa", "—")) if pd.notna(u.get("zona_mapa", np.nan)) else "—")
            c4.metric("Nivel de tensión", str(u.get("nivel_tension", "—")))
            st.markdown(f"Dirección: **{u.get('direccion', '—')}** · circuito **{u.get('circuito', '—')}** · "
                        f"transformador **{u.get('transformador', '—')}** · altitud **{fmt_n(u.get('altitud', np.nan))} m**"
                        if pd.notna(u.get("altitud", np.nan)) else
                        f"Dirección: **{u.get('direccion', '—')}** · circuito **{u.get('circuito', '—')}** · transformador **{u.get('transformador', '—')}**")
            # (corrección 2026-10-09) coordenadas_validas vacío en el TC1 = sin coordenadas (antes: "boolean value of NA is ambiguous")
            if pd.notna(u.get("coordenadas_validas", False)) and bool(u.get("coordenadas_validas", False)):
                st.map(pd.DataFrame({"lat": [float(u["latitud"])], "lon": [float(u["longitud"])]}), zoom=12, height=260, use_container_width=True)
            else:
                st.caption("Sin coordenadas válidas en el TC1.")
        else:
            st.info("El NIU no está en el archivo TC1 cruzado.")

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
            c4.metric("Puesto en el ranking", f"{fmt_n(int(z['ranking']))} de {fmt_n(len(fuga))}")
            st.caption(NIVEL_FUGA_TEXTO.get(str(z["nivel_riesgo"]), ""))
            if isinstance(z.get("senales"), str) and z["senales"]:
                st.markdown(f"**Señales:** {z['senales']}")
            st.markdown(f"Zona **{z.get('zona_nombre', '—')}** · clase **{z.get('clase_servicio_nombre', '—')}** · "
                        f"grupo **{z.get('grupo_consumo', '—')}** · medidor **{z.get('tipo_medidor_nombre', '—')}** · "
                        f"lectura **{z.get('tipo_lectura_nombre', '—')}**")
        else:
            st.info("El NIU no está en la población del riesgo de fuga (residencial, alumbrado, provisional, sin historia "
                    "suficiente o ya en cero sostenido).")

    grafica_consumo_cliente(niu)


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
    c1.metric("Clientes pronosticados", f"{fmt_n(len(pred6))}")
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
    tot = tot.groupby("mes", as_index=False).agg(kWh=("kWh", "sum"), clientes=("kWh", "size"))
    # Solo los meses en que están TODOS los clientes: como urbanos y rurales arrancan en meses distintos, el primer y el
    # último mes traen una sola zona y su total parecía una caída o un salto que no existe.
    _completo = tot["clientes"] >= 0.98 * tot["clientes"].max()
    n_parciales = int((~_completo).sum())
    tot = tot[_completo].drop(columns=["clientes"])
    if n_parciales:
        st.caption(f"Se omiten {n_parciales} mes(es) de los extremos que solo traen una de las dos zonas (urbana o rural): su total no es comparable.")
    if "zona" in pred6.columns and CORTE_ZONA:
        st.caption(f"Urbanos pronosticados desde {CORTE_ZONA.get('URBANO', '—')}; rurales desde "
                   f"{CORTE_ZONA.get('RURAL', '—')} (los meses rurales ya pasados se rellenan con el pronóstico "
                   "hasta que llegue la lectura trimestral).")
    c1, c2 = st.columns([2, 1])
    with c1:
        st.bar_chart(tot.set_index("mes")["kWh"], color=AZUL, height=260)
    with c2:
        tabla(tot, hide_index=True, use_container_width=True)

    st.subheader("Precisión esperada (backtest) por grupo de consumo y horizonte")
    mp = cargar(R.metricas_perfil)
    if mp is not None:
        mp = mp.copy()
        mp["grupo_consumo"] = grupo_desde_perfil(mp["perfil"])
        piv = mp.pivot(index="grupo_consumo", columns="horizonte", values="WAPE_final_pct").round(1)
        piv = piv.reindex([g for g in GRUPOS_CONSUMO_ORDEN if g in piv.index])
        tabla(piv, use_container_width=True)
        st.caption(
            "WAPE %: error porcentual ponderado. 'Sin historia suficiente' no tiene modelo (solo línea base): su error "
            "alto no es un fallo del sistema, es falta de historia. La columna WAPE_baseline_pct del archivo es la línea base "
            "'mismo mes del año anterior'; la comparación contra pronósticos más simples está en la tabla de abajo."
        )
        st.caption(" · ".join(f"**{g}**: {GRUPO_CONSUMO_DESCRIPCION[g]}" for g in GRUPOS_CONSUMO_ORDEN))
    ing = cargar(R.modelo / "comparacion_ingenuos_backtest.csv")
    if ing is not None and len(ing):
        st.subheader("El modelo frente a pronósticos simples (sin modelo)")
        ig = ing[(ing["zona"].astype(str) == "TODOS") & (ing["perfil"].astype(str) == "TODOS")].sort_values("horizonte")
        if len(ig):
            NOMBRE_INGENUO = {"persistencia": "repetir el último mes", "media_3m": "promedio de 3 meses", "media_12m": "promedio de 12 meses",
                              "mismo_mes_anio_anterior": "mismo mes del año anterior", "cero": "cero"}
            tabla(pd.DataFrame({
                "Meses adelante": ig["horizonte"].astype(int),
                "Error del modelo (%)": ig["WAPE_modelo_final_pct"].round(1),
                "Repetir el último mes (%)": ig["WAPE_ingenuo_persistencia_pct"].round(1),
                "Promedio de 3 meses (%)": ig["WAPE_ingenuo_media_3m_pct"].round(1),
                "Mismo mes del año anterior (%)": ig["WAPE_ingenuo_mismo_mes_anio_anterior_pct"].round(1),
                "Mejor pronóstico simple": ig["mejor_ingenuo"].map(NOMBRE_INGENUO).fillna(ig["mejor_ingenuo"]),
                "Ventaja del modelo (puntos)": ig["mejora_vs_mejor_ingenuo_pp"].round(1),
            }), hide_index=True, use_container_width=True)
            st.caption("Error porcentual ponderado del backtest. La ventaja del modelo frente al mejor pronóstico simple es pequeña a un mes y "
                       "crece con el plazo; en clientes rurales el backtest a 1 y 2 meses es optimista (lecturas trimestrales repartidas), "
                       "y la cifra que vale para ellos es la del seguimiento en vivo. Detalle por zona y perfil: comparacion_ingenuos_backtest.csv "
                       "(lo genera evaluar_ingenuos_backtest.py).")
    sel = cargar(R.seleccion)
    if sel is not None:
        with st.expander("Qué algoritmo usa cada grupo"):
            tabla(sel, hide_index=True, use_container_width=True)

    if "modelo_1m" in pred6.columns:
        n_regla = int(pred6["modelo_1m"].eq("REGLA_CERO_SOSTENIDO").sum())
        if n_regla:
            st.caption(f"**{fmt_n(n_regla)}** clientes con la regla de cero sostenido (dos meses en casi cero): su pronóstico es "
                       "persistencia, sin recuperación inventada. Se ven con modelo = REGLA_CERO_SOSTENIDO.")
    reg_v = cargar(R.base / "12_versiones_modelos" / "registro_versiones.csv")
    if reg_v is not None and len(reg_v):
        with st.expander("Versiones de los modelos (12_versiones_modelos)"):
            tabla(reg_v, hide_index=True, use_container_width=True)
            reg_u = cargar(R.base / "12_versiones_modelos" / "registro_uso.csv")
            if reg_u is not None:
                st.caption("Qué versión usó cada corte:")
                tabla(reg_u, hide_index=True, use_container_width=True)

    st.subheader("Clientes por grupo de consumo")
    cg = pred6["grupo_consumo"].value_counts().rename("clientes").to_frame() if "grupo_consumo" in pred6.columns else pred6["perfil"].value_counts().rename("clientes").to_frame()
    cg = cg.reindex([g for g in GRUPOS_CONSUMO_ORDEN if g in cg.index])
    tabla(cg, use_container_width=True)
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
    # Memoria (corrección 2026-10-09): antes cada recarga de esta sección leía TODOS los archivos (unos 350 MB) para
    # armar un botón por archivo. Ahora se listan y solo se lee el que se elige para descargar.
    opciones = {}
    for producto, t in idx.groupby("producto", sort=False):
        st.subheader(NOMBRES_PRODUCTO.get(producto, producto))
        filas = []
        for r in t.itertuples():
            ruta = R.base / r.archivo
            existe = ruta.exists()
            filas.append({"Grupo de consumo": r.grupo_consumo, "Clientes": int(r.clientes), "Corte": r.fecha_corte,
                          "Archivo": Path(r.archivo).name,
                          "Tamaño (MB)": round(ruta.stat().st_size / 1e6, 1) if existe else None,
                          "Estado": "disponible" if existe else "no encontrado"})
            if existe:
                opciones[f"{NOMBRES_PRODUCTO.get(producto, producto)} — {r.grupo_consumo} ({Path(r.archivo).name})"] = ruta
        tabla(pd.DataFrame(filas), hide_index=True, use_container_width=True)
    st.subheader("Descargar un archivo")
    if not opciones:
        st.info("No hay archivos disponibles para descargar.")
    else:
        elegido = st.selectbox("Archivo", list(opciones), key="dl_archivo", index=None, placeholder="Elige el archivo que quieres descargar")
        if elegido:
            ruta = opciones[elegido]
            st.download_button(f"Descargar {ruta.name}", ruta.read_bytes(), file_name=ruta.name, mime="text/csv", key="dl_boton")


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
        tabla(piv, use_container_width=True)
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
                tabla(sp.round(2), hide_index=True, use_container_width=True)
        sz = cargar(R.seg_zona)
        if sz is not None:
            with st.expander("Por zona"):
                tabla(sz.round(2), hide_index=True, use_container_width=True)

    sf = cargar(R.fuga_seguimiento)
    if sf is not None and len(sf):
        st.subheader("Riesgo de fuga: señalados en cortes anteriores que efectivamente se fueron")
        tabla(sf, hide_index=True, use_container_width=True)

    sl = cargar(R.seg_lista)
    st.subheader("Qué pasó con los clientes de las listas anteriores")
    if sl is None or len(sl) == 0:
        st.info("Todavía no hay meses posteriores consolidados para ninguna lista.")
    else:
        st.caption("RECUPERADO: volvió al menos al 90 % del nivel contra el que se midió su caída (periodo anterior o mismo "
                   "periodo del año pasado, el que originó el veredicto). SIGUE_CAYENDO: quedó por debajo del 90 % del promedio "
                   "de su ventana reciente. ESTABLE_BAJO: se quedó en el nivel caído. Cada lista de zona se cuenta una sola vez. "
                   "No hay grupo de control: son porcentajes descriptivos, no una prueba de que la lista acierte.")
        for corte_por in ["TOTAL", "trayectoria", "veredicto", "severidad", "zona"]:
            t = sl[sl["corte_por"] == corte_por]
            if len(t):
                st.markdown(f"**Por {corte_por.lower()}**")
                tabla(t.drop(columns=["corte_por"]), hide_index=True, use_container_width=True)


# ----------------------------------------------------------------------------
# Retroalimentación
# ----------------------------------------------------------------------------
elif seccion == "Retroalimentación":
    st.title("Resultados de las visitas contra la lista")
    rr = cargar(R.retro_resumen)
    es_ejemplo = False
    if rr is None or len(rr) == 0:
        st.info(
            "Aún no hay resultados de campo. Llenar la plantilla "
            "resultado_gestion_plantilla.csv (carpeta 07_gestion_caida/retroalimentacion de los datos) y correr "
            "Evaluacion_retroalimentacion_gestion.ipynb."
        )
        rr = cargar(R.gestion / "retroalimentacion" / "ejemplo_simulado" / "EJEMPLO_SIMULADO_evaluacion_resumen.csv")
        if rr is None or len(rr) == 0:
            st.caption("Para ver un ejemplo de cómo se vería esta página con visitas registradas: "
                       "python generar_ejemplo_retroalimentacion.py")
            st.stop()
        es_ejemplo = True
        st.warning("**EJEMPLO ILUSTRATIVO — RESULTADOS SIMULADOS.** Lo que sigue NO son visitas reales: es una muestra de clientes "
                   "de la lista a la que se le asignó un hallazgo al azar, solo para mostrar cómo se vería esta página si la empresa "
                   "registrara las visitas. Todos los grupos se simularon con las mismas probabilidades, así que las diferencias "
                   "entre grupos son azar y ninguna cifra de aquí mide la calidad de la lista.")
    sufijo = " (simulado)" if es_ejemplo else ""
    tot = rr[rr["corte_por"] == "TOTAL"]
    if len(tot):
        c1, c2, c3, c4 = st.columns(4)
        ver = float(tot["verificados"].sum())
        c1.metric("Clientes visitados" + sufijo, fmt_n(int(tot["visitados"].sum())))
        c2.metric("Con un problema que la empresa puede corregir" + sufijo,
                  f"{tot['con_causa_gestionable'].sum() / ver * 100:.0f} %" if ver else "—",
                  help="De los verificados: medidor dañado o manipulado, error de lectura o facturación, falla de red, conexión irregular.")
        c3.metric("Caída real, sin nada que corregir" + sufijo,
                  f"{tot['caida_real_sin_gestion'].sum() / ver * 100:.0f} %" if ver else "—",
                  help="Predio desocupado, cambio de actividad, autogeneración o cliente retirado: la lista acertó, pero no hay recuperación.")
        c4.metric("Sin novedad (falsa alarma)" + sufijo, f"{tot['sin_novedad'].sum() / ver * 100:.0f} %" if ver else "—")
        if "valor_riesgo_gestionable_mes" in tot.columns:
            st.caption(f"Facturación asociada a los casos con problema corregible{sufijo}: "
                       f"{pesos_md(tot['valor_riesgo_gestionable_mes'].sum())}/mes.")
    st.caption("precision_gestionable: % de verificados con un problema que la empresa puede corregir. "
               "precision_caida_real: % donde la caída era real, gestionable o no. sin_novedad: falsos positivos."
               + (" Con visitas reales, un grupo con precisión baja de forma sostenida debe bajar en el orden de la lista." if es_ejemplo else ""))
    for corte_por in ["TOTAL", "severidad", "trayectoria", "estado_en_lista", "tramo_consumo", "zona", "cluster_id"]:
        t = rr[rr["corte_por"] == corte_por]
        if len(t):
            st.markdown(f"**Por {corte_por.lower()}**" + sufijo)
            tabla(t.drop(columns=["corte_por"]), hide_index=True, use_container_width=True)


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
        tabla(cc, hide_index=True, use_container_width=True)

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
        tabla(sb, hide_index=True, use_container_width=True)
