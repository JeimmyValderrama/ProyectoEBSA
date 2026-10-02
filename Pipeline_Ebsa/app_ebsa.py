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
  Comercial          : Panorama (cifras del corte y mapa de Boyacá), Clientes con riesgo de irse, Grandes caídas de
                       consumo, Clientes que ya se fueron, Descargas. Lenguaje de negocio.
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
    enriquecer_glosario, grupo_desde_perfil, nombre_zona, nombre_zona_regional,
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
    kw.setdefault("low_memory", False)   # CSV grandes con columnas mixtas: una sola pasada, sin avisos ni fallos de pandas
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


# Texto de apoyo que ve el usuario en las secciones principales
QUE_ES_ESTO = (
    "**Qué es esto.** El sistema lee cada mes los archivos TC2 de la empresa y hace tres cosas: "
    "(1) **detecta clientes cuyo consumo cayó** más de lo normal para clientes parecidos y los ordena por la facturación que se está perdiendo, "
    "para que el área comercial y las cuadrillas sepan a quién revisar primero; "
    "(2) **estima el riesgo de que un cliente se vaya** a otro comercializador en los próximos seis meses; "
    "(3) **pronostica el consumo** de cada cliente a seis meses. El valor en pesos siempre usa la tarifa real del cliente, nunca una tarifa supuesta."
)

COLUMNAS_PESOS_PISTAS = ("valor", "perdida", "pérdida", "factura", "$", "pesos", "tarifa_kwh")
COLUMNAS_KWH_PISTAS = ("kwh", "consumo")


def tabla(df: pd.DataFrame, **kw):
    """st.dataframe con las columnas de pesos en formato $ con separador de miles y las de kWh con miles.
    Se detectan por el nombre de la columna; si ya viene column_config, se respeta."""
    if df is None:
        return None
    cfg = dict(kw.pop("column_config", None) or {})
    try:
        for c in df.columns:
            if c in cfg or not pd.api.types.is_numeric_dtype(df[c]):
                continue
            n = str(c).lower()
            if any(p in n for p in COLUMNAS_PESOS_PISTAS) and "pct" not in n and "prob" not in n:
                try:
                    cfg[c] = st.column_config.NumberColumn(format="dollar")
                except Exception:
                    cfg[c] = st.column_config.NumberColumn(format="$%d")
            elif any(p in n for p in COLUMNAS_KWH_PISTAS) and "pct" not in n:
                try:
                    cfg[c] = st.column_config.NumberColumn(format="localized")
                except Exception:
                    cfg[c] = st.column_config.NumberColumn(format="%d")
    except Exception:
        cfg = cfg or None
    return st.dataframe(df, column_config=cfg or None, **kw)


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
    else:
        d["zona_regional"] = "SIN ZONA"
    return d


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
ruta_datos = st.sidebar.text_input("Carpeta de datos", DATOS_POR_DEFECTO)
R = Rutas(Path(ruta_datos))

if not R.base.exists():
    st.error(f"No existe la carpeta de datos: {R.base}")
    st.stop()

# Tres vistas, una por público. Comercial y Soporte hablan en lenguaje de negocio;
# Administrador del modelo conserva todo lo técnico (calidad, seguimiento, cortes, pipeline).
VISTAS = {
    "Comercial": ["Panorama", "Caídas de consumo", "Clientes con riesgo de irse", "Clientes que ya se fueron", "Descargas"],
    "Soporte": ["Consultar un cliente", "Visitas por ciclo", "Registrar resultado de visitas"],
    "Administrador del modelo": [
        "Resumen", "Gestión por ciclo", "Ranking gerencial", "Riesgo de fuga", "Cortes", "Mapa", "Buscar cliente",
        "Pronóstico 6 meses", "Descargas por grupo", "Seguimiento", "Retroalimentación", "Estado del pipeline",
    ],
}
VISTA_AYUDA = ("Comercial: cifras, mapa y listas para decidir a quién llamar. Soporte: la ficha de un cliente y las rutas de visita. "
               "Administrador del modelo: calidad de los modelos, cortes, seguimiento y estado del pipeline.")
vista = st.sidebar.radio("Vista", list(VISTAS), help=VISTA_AYUDA, horizontal=True)
seccion = st.sidebar.radio("Sección", VISTAS[vista])
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
pred6 = cargar(R.pred6)
if pred6 is not None:
    st.sidebar.caption(f"Pronóstico: corte **{str(pd.to_datetime(pred6['fecha_corte']).max())[:7]}**")
    if "grupo_consumo" not in pred6.columns and "perfil" in pred6.columns:
        pred6 = pred6.copy()
        pred6["grupo_consumo"] = grupo_desde_perfil(pred6["perfil"])
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


# ----------------------------------------------------------------------------
# Ubicación de los clientes (13_ubicacion_clientes, cruce aparte con el TC1)
# ----------------------------------------------------------------------------
COLS_UBICACION = ["NIU", "codigo_municipio", "municipio", "provincia", "departamento", "zona_mapa", "direccion",
                  "ubicacion_sui", "nivel_tension", "circuito", "transformador", "latitud", "longitud", "altitud",
                  "coordenadas_validas", "autogenerador_tc1", "periodo_tc1"]
ubicacion = cargar(R.ubicacion, columns=COLS_UBICACION)
if ubicacion is not None:
    ubicacion["NIU"] = ubicacion["NIU"].astype("string").str.strip()
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
    return col.multiselect("Municipio", sorted(df["municipio"].dropna().astype(str).unique()), key=clave)


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
        o = operativa[["NIU", "severidad", "trayectoria", "valor_riesgo_mes", "perdida_kwh_mes"]].copy()
        o["NIU"] = o["NIU"].astype("string").str.strip()
        o = o.merge(llave, on="NIU", how="inner")
        ag = o.groupby("codigo_municipio").agg(
            caida_clientes=("NIU", "size"),
            caida_criticos=("severidad", lambda x: int(x.eq("CRITICA").sum())),
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
    "Clientes con caída grave (crítica)": ("caida_criticos", "clientes"),
    "Clientes con riesgo de irse a otro comercializador": ("fuga_alto_medio", "clientes"),
    "Pérdida esperada por clientes que podrían irse ($/mes)": ("fuga_perdida_esperada_mes", "$"),
    "Clientes de EBSA en el municipio": ("clientes_tc1", "clientes"),
}


def _fmt_metrica(v, unidad):
    return pesos(v) if unidad == "$" else (f"{v:,.2f} %" if unidad == "%" else f"{v:,.0f} {unidad}")


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
    # (el signo $ se escapa: Streamlit lo tomaría como fórmula matemática)
    st.markdown(f"**{len(d):,}** municipios de Boyacá · {met_nombre.replace('$', chr(92) + '$')}: "
                f"**{_fmt_metrica(total_val, met_unidad).replace('$', chr(92) + '$') if met_unidad != '%' else '—'}**"
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
               "la rueda del mouse acerca el mapa.")

    with st.expander("Ver la tabla por zona y por municipio"):
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("**Por zona**")
            z = d.groupby("zona_ebsa").agg(municipios=("codigo_municipio", "size"), clientes=("clientes_tc1", "sum"),
                                           valor=("valor", "sum" if met_unidad != "%" else "mean")).reset_index()
            z = z.sort_values("valor", ascending=False).rename(columns={"zona_ebsa": "Zona", "valor": met_nombre})
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
            st.download_button("Descargar municipios (CSV)", t.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"mapa_municipios_{corte_actual or ''}.csv", mime="text/csv", key=f"dl_{clave}")

    if puntos:
        with st.expander("Ver clientes de una lista como puntos en el mapa"):
            opciones = {}
            if operativa is not None:
                opciones["Caída: severidad CRÍTICA"] = operativa[operativa["severidad"].eq("CRITICA")][["NIU", "valor_riesgo_mes"]].rename(columns={"valor_riesgo_mes": "valor"})
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
                st.caption(f"{len(pts):,} clientes con coordenadas" + (f"; se dibujan los {tope:,} de mayor valor" if len(pts) > tope else ""))
                pts = pts.sort_values("valor", ascending=False).head(tope)
                pts["color"] = pts["zona_mapa"].map(ZONA_MAPA_COLOR).fillna("#999999")
                st.map(pts.rename(columns={"latitud": "lat", "longitud": "lon"}), color="color", size=250, zoom=7, height=520)
    return d


# ----------------------------------------------------------------------------
# Textos en lenguaje de negocio (vistas Comercial y Soporte)
# ----------------------------------------------------------------------------
TRAYECTORIA_SIMPLE = {
    "CAIDA_ACELERANDO": "Sigue bajando",
    "SIN_RECUPERACION_PREVISTA": "Se quedó en el nivel bajo",
    "RECUPERACION_PREVISTA": "Se espera que se recupere",
    "SIN_PRONOSTICO": "Sin pronóstico",
}
SEVERIDAD_SIMPLE = {"CRITICA": "Grave", "FUERTE": "Fuerte", "MODERADA": "Moderada"}
ESTADO_LISTA_SIMPLE = {"NUEVO": "Nuevo este mes", "PERSISTENTE": "Sigue desde el mes pasado", "REINCIDENTE": "Ya había estado antes", "": ""}
NIVEL_FUGA_SIMPLE = {"ALTO": "Alto: contactar primero", "MEDIO": "Medio: vigilar y contactar según valor", "BAJO": "Bajo"}


def que_revisar(fila) -> str:
    """Sugerencia en lenguaje simple para quien atiende al cliente, a partir de lo que dice la lista de caída."""
    t = str(fila.get("trayectoria", ""))
    sev = str(fila.get("severidad", ""))
    clase = str(fila.get("clase_servicio_nombre", "")).lower()
    partes = []
    if t == "CAIDA_ACELERANDO":
        partes.append("El consumo viene bajando y el modelo prevé que siga bajando: conviene contactar pronto.")
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
    if len(u) and bool(u["autogenerador_tc1"].iloc[0]):
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
            txt += f"Riesgo de irse: **{v.get('nivel_riesgo', '—')}** ({float(v['prob_fuga_6m']) * 100:.1f} % en 6 meses). Lo lleva el área comercial, no la cuadrilla."
        avisos.append(("info", txt))
    for tipo, txt in avisos:
        getattr(st, tipo)(txt)

    c1, c2, c3 = st.columns(3)
    if len(o):
        oo = o.iloc[0]
        var = float(oo.get("variacion_vs_anterior_pct", np.nan))
        c1.metric("Caída de consumo", f"{var:.0f} %" if pd.notna(var) else "—",
                  help="Consumo reciente frente al periodo anterior del mismo cliente")
        c2.metric("Gravedad", SEVERIDAD_SIMPLE.get(str(oo.get("severidad", "")), str(oo.get("severidad", "—"))))
        c3.metric("Tendencia", TRAYECTORIA_SIMPLE.get(str(oo.get("trayectoria", "")), "—"))
        st.markdown(f"Consumía **{kwh(oo.get('consumo_anterior_kwh', np.nan))}/mes** y ahora **{kwh(oo.get('consumo_reciente_kwh', np.nan))}/mes**: "
                    f"son **{pesos(oo.get('valor_riesgo_mes', np.nan))}/mes** menos de facturación. "
                    f"{ESTADO_LISTA_SIMPLE.get(str(oo.get('estado_en_lista', '')), '')}"
                    + (f" (lleva {int(oo.get('meses_consecutivos_en_lista', 1))} mes(es) seguidos en la lista)." if str(oo.get("estado_en_lista", "")) == "PERSISTENTE" else "."))
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
        c1.metric("Riesgo de irse a otro comercializador", nivel)
        c2.metric("Probabilidad en 6 meses", f"{float(z['prob_fuga_6m']) * 100:.1f} %")
        c3.metric("Factura hoy", f"{pesos(z.get('valor_en_riesgo_mes', np.nan))}/mes")
        txt = NIVEL_FUGA_SIMPLE.get(nivel, "")
        if isinstance(z.get("senales"), str) and z["senales"]:
            txt += f". Señales: {z['senales']}"
        st.caption(txt)
    elif not len(vz) and not len(yz):
        st.caption("No está entre los clientes a los que se les calcula riesgo de irse (es residencial, alumbrado, provisional o sin historia suficiente).")

    # ----- Consumo -----
    st.subheader("Cómo ha venido consumiendo")
    grafica_consumo_cliente(niu)


def grafica_consumo_cliente(niu: str) -> None:
    """Consumo real de los últimos 12 meses y pronóstico a 6 meses de un NIU (la usan Soporte y Administrador)."""
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
            st.info("El NIU no tiene pronóstico (historia insuficiente o sin dato en el mes de corte).")


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
        c1.metric("Clientes con caída de consumo para revisar", f"{len(operativa):,}",
                  help="Clientes cuyo consumo bajó más de lo normal para clientes parecidos. Es la lista de visitas y llamadas.")
        c2.metric("Facturación que se está perdiendo", f"{pesos(operativa['valor_riesgo_mes'].sum())}/mes",
                  help="Lo que facturaban antes menos lo que facturan ahora, con la tarifa real de cada uno.")
    if fuga is not None:
        senal = fuga[fuga["nivel_riesgo"].isin(["ALTO", "MEDIO"])]
        c3.metric("Clientes con riesgo de irse a otro comercializador", f"{len(senal):,}",
                  help="Riesgo ALTO o MEDIO según el modelo, entre los clientes comerciales, industriales, oficiales y acueductos.")
        c4.metric("Pérdida esperada si se van", f"{pesos(senal['valor_esperado_perdida_mes'].sum())}/mes",
                  help="Probabilidad de irse × lo que factura hoy cada uno. Es la cifra para priorizar.")
    c1, c2, c3, c4 = st.columns(4)
    if operativa is not None:
        c1.metric("Caídas graves (críticas)", f"{int(operativa['severidad'].eq('CRITICA').sum()):,}",
                  help="Caída muy por encima de lo normal del segmento: revisar medidor y lectura antes de dar por buena la cifra.")
        if "estado_en_lista" in operativa.columns:
            c2.metric("Nuevos en la lista este mes", f"{int(operativa['estado_en_lista'].eq('NUEVO').sum()):,}")
    if ya is not None and len(ya):
        c3.metric("Ya atendidos por otro comercializador", f"{int(ya['estado'].astype(str).str.startswith('CON OTRO').sum()):,}",
                  help="Según el archivo de otros comercializadores de la empresa.")
    if vg is not None and len(vg):
        c4.metric("Grandes clientes en vigilancia (no regulados)", f"{len(vg):,}",
                  help="Ciclo 33, clase no regulada o más de 55.000 kWh/mes: pueden negociar con cualquier comercializador.")

    if operativa is not None:
        st.subheader("Caídas de consumo por zona regional")
        st.caption("Cuántos clientes tienen caída de consumo en cada dirección regional y de qué gravedad. "
                   "Grave = muy por encima de lo normal del segmento: revisar medidor y lectura primero.")
        orden_sev = [x for x in ["CRITICA", "FUERTE", "MODERADA"] if x in set(operativa["severidad"].astype(str))]
        t_sev = operativa.groupby(["zona_regional", "severidad"]).size().unstack(fill_value=0).reindex(columns=orden_sev)
        t_sev = t_sev.loc[t_sev.sum(axis=1).sort_values(ascending=False).index]
        t_sev.columns = [SEVERIDAD_SIMPLE.get(c, c) for c in t_sev.columns]
        c1, c2 = st.columns([3, 2])
        with c1:
            st.bar_chart(t_sev, color=[NARANJA, "#f2a65a", AZUL][:len(t_sev.columns)], height=320)
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
            st.markdown("**Los diez municipios que más pesan en la cifra elegida**")
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


elif seccion == "Clientes con riesgo de irse":
    st.title("Clientes con riesgo de irse a otro comercializador")
    if fuga is None:
        st.warning("Todavía no hay riesgo de fuga calculado (paso 14 del pipeline).")
        st.stop()
    corte_f = str(fuga["fecha_corte"].iloc[0])[:7]
    st.caption(f"Corte **{corte_f}**. El modelo mira cómo se comportaron los clientes que ya se fueron y busca los que hoy se parecen: "
               "caída reciente, meses en cero, zona con más salidas, tamaño. **Riesgo ALTO: contactar primero. MEDIO: vigilar y contactar según valor.** "
               "La probabilidad es a 6 meses; la pérdida esperada es probabilidad × lo que factura hoy.")
    d = agregar_municipio(fuga)
    f1, f2, f3, f4, f5 = st.columns(5)
    niv = f1.multiselect("Riesgo", ["ALTO", "MEDIO", "BAJO"], default=["ALTO", "MEDIO"], key="com_niv")
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
    c1.metric("Clientes", f"{len(d):,}")
    c2.metric("Facturan hoy", f"{pesos(d['valor_en_riesgo_mes'].sum())}/mes")
    c3.metric("Pérdida esperada", f"{pesos(d['valor_esperado_perdida_mes'].sum())}/mes")
    t = pd.DataFrame({
        "Prioridad": d["ranking"],
        "NIU": d["NIU"],
        "Municipio": d["municipio"] if "municipio" in d.columns else "—",
        "Zona regional": d["zona_regional"],
        "Ciclo": d["zona_nombre"],
        "Clase": d["clase_servicio_nombre"],
        "Tamaño": d["grupo_consumo"],
        "Factura hoy ($/mes)": d["valor_en_riesgo_mes"].round(0),
        "Probabilidad de irse (6 meses)": (d["prob_fuga_6m"] * 100).round(1).astype(str) + " %",
        "Riesgo": d["nivel_riesgo"],
        "Pérdida esperada ($/mes)": d["valor_esperado_perdida_mes"].round(0),
        "Por qué": d["senales"].fillna(""),
        "Situación": d["estado_en_lista"].map(ESTADO_LISTA_SIMPLE).fillna("") if "estado_en_lista" in d.columns else "",
    })
    tabla(t.head(1000), hide_index=True, use_container_width=True, height=520)
    st.download_button("Descargar esta lista (CSV)", t.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"clientes_riesgo_de_irse_{corte_f}.csv", mime="text/csv")

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
            "Riesgo de irse": vg.get("nivel_riesgo", pd.Series("—", index=vg.index)).fillna("Sin puntuar"),
            "Probabilidad (6 meses)": pd.to_numeric(vg.get("prob_fuga_6m"), errors="coerce").mul(100).round(1).astype(str).replace("nan", "—") + " %",
        })
        tabla(tv, hide_index=True, use_container_width=True, height=360)
        st.download_button("Descargar grandes clientes (CSV)", tv.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"grandes_clientes_no_regulados_{corte_f}.csv", mime="text/csv")


elif seccion == "Caídas de consumo":
    st.title("Clientes cuya facturación está cayendo")
    ger = cargar(R.gerencial, dtype={"NIU": "string", "ciclo_etiqueta": "string"})
    if ger is None:
        st.warning("Todavía no hay lista de caída (paso 11 del pipeline).")
        st.stop()
    st.caption(f"Periodo facturado **{corte_actual}**. Clientes cuyo consumo bajó más de lo normal para clientes parecidos, ordenados por la facturación "
               "que se está perdiendo cada mes. **Gravedad**: qué tan fuera de lo normal es la caída. **Tendencia**: lo que el modelo espera para el mes que viene. "
               "Sin autogeneradores ni área común, autoconsumos EBSA, distritos de riego y provisionales.")
    d = agregar_municipio(limpiar_lista(ger))
    col_zona = "zona_regional"
    col_clase = "clase_servicio_nombre" if "clase_servicio_nombre" in d.columns else "clase_servicio"
    with st.expander("Cuántos clientes hay por gravedad en cada zona regional", expanded=True):
        orden_sev = [x for x in ["CRITICA", "FUERTE", "MODERADA"] if x in set(d["severidad"].astype(str))]
        t_sev = d.groupby(["zona_regional", "severidad"]).size().unstack(fill_value=0).reindex(columns=orden_sev)
        t_sev = t_sev.loc[t_sev.sum(axis=1).sort_values(ascending=False).index]
        t_sev.columns = [SEVERIDAD_SIMPLE.get(c, c) for c in t_sev.columns]
        st.bar_chart(t_sev, color=[NARANJA, "#f2a65a", AZUL][:len(t_sev.columns)], height=280)
    f1, f2, f3, f4, f5, f6 = st.columns(6)
    zon = filtro_zona_regional(f1, d, "gc_zon")
    mun = filtro_municipio(f2, d, "gc_mun")
    cla = f3.multiselect("Clase", sorted(d[col_clase].dropna().astype(str).unique()), key="gc_cla", placeholder="Todas")
    tam = f4.multiselect("Tamaño", [g for g in GRUPOS_CONSUMO_ORDEN if g in d.get("grupo_consumo", pd.Series(dtype=str)).unique()], key="gc_tam", placeholder="Todos")
    grav = f5.multiselect("Gravedad", ["CRITICA", "FUERTE", "MODERADA"], format_func=lambda x: SEVERIDAD_SIMPLE.get(x, x), key="gc_grav", placeholder="Todas")
    ten = f6.multiselect("Tendencia", list(TRAYECTORIA_SIMPLE), format_func=lambda x: TRAYECTORIA_SIMPLE[x], key="gc_ten", placeholder="Todas")
    if zon:
        d = d[d[col_zona].astype(str).isin(zon)]
    if mun:
        d = d[d["municipio"].astype(str).isin(mun)]
    if cla:
        d = d[d[col_clase].astype(str).isin(cla)]
    if tam:
        d = d[d["grupo_consumo"].isin(tam)]
    if grav:
        d = d[d["severidad"].isin(grav)]
    if ten and "trayectoria" in d.columns:
        d = d[d["trayectoria"].isin(ten)]
    n = st.slider("Cuántos mostrar", 25, 2000, 200, step=25)
    d = d.sort_values("valor_riesgo_mes", ascending=False)
    top = d.head(n)
    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes (con los filtros)", f"{len(d):,}")
    c2.metric("Facturación que se pierde", f"{pesos(d['valor_riesgo_mes'].sum())}/mes")
    c3.metric(f"Los {len(top):,} primeros concentran", f"{(top['valor_riesgo_mes'].sum() / d['valor_riesgo_mes'].sum() * 100 if d['valor_riesgo_mes'].sum() else 0):.0f} %")
    t = pd.DataFrame({
        "Puesto": top["ranking"] if "ranking" in top.columns else np.arange(1, len(top) + 1),
        "NIU": top["NIU"],
        "Municipio": top["municipio"] if "municipio" in top.columns else "—",
        "Zona regional": top[col_zona],
        "Ciclo": top["zona_nombre"] if "zona_nombre" in top.columns else "—",
        "Clase": top[col_clase],
        "Tamaño": top.get("grupo_consumo", "—"),
        "Consumía (kWh/mes)": top["consumo_anterior_kwh"].round(0),
        "Consume ahora (kWh/mes)": top["consumo_reciente_kwh"].round(0),
        "Caída": top["variacion_vs_anterior_pct"].round(0).astype("Int64").astype(str) + " %",
        "Facturación que se pierde ($/mes)": top["valor_riesgo_mes"].round(0),
        "Gravedad": top["severidad"].map(SEVERIDAD_SIMPLE).fillna(top["severidad"]),
        "Tendencia": top["trayectoria"].map(TRAYECTORIA_SIMPLE).fillna("—") if "trayectoria" in top.columns else "—",
        "Situación": top["estado_en_lista"].map(ESTADO_LISTA_SIMPLE).fillna("") if "estado_en_lista" in top.columns else "",
    })
    tabla(t, hide_index=True, use_container_width=True, height=560)
    st.download_button("Descargar esta lista (CSV)", t.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"grandes_caidas_{corte_actual or ''}.csv", mime="text/csv")


elif seccion == "Clientes que ya se fueron":
    st.title("Clientes que ya están con otro comercializador")
    ya = cargar(R.fuga_ya_fuera, dtype={"NIU": "string"})
    if ya is None or len(ya) == 0:
        st.info("No hay archivo de otros comercializadores en 00_otros_comercializadores.")
        st.stop()
    st.caption("Viene del archivo de otros comercializadores que entrega la empresa, cruzado con la historia de consumo en EBSA. "
               "Sirve para saber a quién ya no vale la pena buscar, cuánto facturaban y cómo eran, para reconocer a los que se parecen.")
    est = ya["estado"].value_counts()
    cc = st.columns(len(est))
    for col, (k, v) in zip(cc, est.items()):
        col.metric(k if len(k) < 30 else k[:28] + "…", f"{v:,}", help=ESTADO_OTRO_TEXTO.get(k, k))
    if "valor_facturado_antes_salida_mes" in ya.columns and ya["valor_facturado_antes_salida_mes"].notna().any():
        st.markdown(f"Facturaban antes de irse **{pesos_md(ya['valor_facturado_antes_salida_mes'].sum())}/mes** "
                    f"(sobre {int(ya['valor_facturado_antes_salida_mes'].notna().sum()):,} clientes con historia en EBSA).")
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
    tabla(t, hide_index=True, use_container_width=True, height=420)
    st.download_button("Descargar (CSV)", t.to_csv(index=False).encode("utf-8-sig"),
                       file_name="clientes_con_otro_comercializador.csv", mime="text/csv")
    pi = cargar(R.fuga_perfil_idos)
    if pi is not None:
        with st.expander("Cómo son los que se fueron (clase, zona, tamaño, comercializador, municipio)"):
            for dim, tt in pi.groupby("dimension", sort=False):
                st.markdown(f"**{dim}**")
                tabla(tt.drop(columns=["dimension"]).head(15), hide_index=True, use_container_width=True)


# ============================================================================
# VISTA SOPORTE (atención al cliente y campo)
# ============================================================================
elif seccion == "Consultar un cliente":
    st.title("Consultar un cliente")
    st.caption("Escribe el NIU y verás, en una sola página, dónde está, qué le pasa al consumo, si tiene riesgo de irse y qué conviene revisar o decirle.")
    with st.expander("¿No tienes el NIU? Buscar por municipio o situación"):
        base = None
        if operativa is not None:
            base = agregar_municipio(operativa[["NIU", "severidad", "trayectoria", "valor_riesgo_mes", "clase_servicio_nombre"]])
            f1, f2, f3 = st.columns(3)
            munis = ["(todos)"] + (sorted(base["municipio"].dropna().astype(str).unique()) if "municipio" in base.columns else [])
            mun_sel = f1.selectbox("Municipio", munis, key="sop_mun")
            grav_sel = f2.selectbox("Gravedad", ["(todas)"] + list(SEVERIDAD_SIMPLE), format_func=lambda x: SEVERIDAD_SIMPLE.get(x, x), key="sop_grav")
            ten_sel = f3.selectbox("Tendencia", ["(todas)"] + list(TRAYECTORIA_SIMPLE), format_func=lambda x: TRAYECTORIA_SIMPLE.get(x, x), key="sop_ten")
            e = base
            if mun_sel != "(todos)":
                e = e[e["municipio"].astype(str) == mun_sel]
            if grav_sel != "(todas)":
                e = e[e["severidad"] == grav_sel]
            if ten_sel != "(todas)":
                e = e[e["trayectoria"] == ten_sel]
            e = e.sort_values("valor_riesgo_mes", ascending=False).head(50)
            st.caption(f"{len(e):,} clientes de la lista de caída cumplen el filtro (se muestran hasta 50). Copia el NIU y pégalo abajo.")
            tabla(pd.DataFrame({
                "NIU": e["NIU"], "Municipio": e.get("municipio", "—"), "Clase": e["clase_servicio_nombre"],
                "Gravedad": e["severidad"].map(SEVERIDAD_SIMPLE), "Tendencia": e["trayectoria"].map(TRAYECTORIA_SIMPLE),
                "Facturación que se pierde ($/mes)": e["valor_riesgo_mes"].round(0)}), hide_index=True, use_container_width=True)
        else:
            st.info("Todavía no hay lista de caída.")
    niu = st.text_input("NIU del cliente", key="sop_niu").strip()
    if not niu:
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
    grav = f2.multiselect("Gravedad", ["CRITICA", "FUERTE", "MODERADA"], format_func=lambda x: SEVERIDAD_SIMPLE.get(x, x), key="vis_grav", placeholder="Todas")
    ten = f3.multiselect("Tendencia", list(TRAYECTORIA_SIMPLE), format_func=lambda x: TRAYECTORIA_SIMPLE[x], key="vis_ten", placeholder="Todas")
    est = f4.multiselect("Situación", ["NUEVO", "PERSISTENTE", "REINCIDENTE"], format_func=lambda x: ESTADO_LISTA_SIMPLE.get(x, x), key="vis_est", placeholder="Todas")
    lec = f5.multiselect("Tipo de lectura", sorted(d["tipo_lectura_nombre"].dropna().astype(str).unique()), key="vis_lec", placeholder="Todas",
                         help="REAL: leída del medidor. ESTIMADA: la empresa estimó el consumo; una caída con lectura estimada puede no ser real.") if "tipo_lectura_nombre" in d.columns else []
    if mun:
        d = d[d["municipio"].astype(str).isin(mun)]
    if grav:
        d = d[d["severidad"].isin(grav)]
    if ten and "trayectoria" in d.columns:
        d = d[d["trayectoria"].isin(ten)]
    if est and "estado_en_lista" in d.columns:
        d = d[d["estado_en_lista"].isin(est)]
    if lec:
        d = d[d["tipo_lectura_nombre"].astype(str).isin(lec)]
    d = d.sort_values("orden_en_ciclo")
    c1, c2, c3 = st.columns(3)
    c1.metric("Clientes para visitar", f"{len(d):,}")
    c2.metric("Facturación que se pierde", f"{pesos(d['valor_riesgo_mes'].sum())}/mes")
    c3.metric("Caídas graves", f"{int(d['severidad'].eq('CRITICA').sum()):,}")
    t = pd.DataFrame({
        "Orden": d["orden_en_ciclo"], "NIU": d["NIU"],
        "Municipio": d["municipio"] if "municipio" in d.columns else "—",
        "Dirección": d["direccion"] if "direccion" in d.columns else "—",
        "Clase": d.get("clase_servicio_nombre", d.get("clase_servicio", "—")),
        "Lectura": d["tipo_lectura_nombre"] if "tipo_lectura_nombre" in d.columns else "—",
        "Consumía (kWh/mes)": d["consumo_anterior_kwh"].round(0), "Consume ahora (kWh/mes)": d["consumo_reciente_kwh"].round(0),
        "Caída": d["variacion_vs_anterior_pct"].round(0).astype("Int64").astype(str) + " %",
        "Facturación que se pierde ($/mes)": d["valor_riesgo_mes"].round(0),
        "Gravedad": d["severidad"].map(SEVERIDAD_SIMPLE).fillna(d["severidad"]),
        "Tendencia": d["trayectoria"].map(TRAYECTORIA_SIMPLE).fillna("—") if "trayectoria" in d.columns else "—",
        "Situación": d["estado_en_lista"].map(ESTADO_LISTA_SIMPLE).fillna("") if "estado_en_lista" in d.columns else "",
        "Qué revisar": d.apply(que_revisar, axis=1),
    })
    tabla(t, hide_index=True, use_container_width=True, height=520)
    st.download_button(f"Descargar la ruta del ciclo {ciclo} (CSV)", t.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"visitas_ciclo_{ciclo}_{corte_actual or ''}.csv", mime="text/csv")
    if "coordenadas_validas" in d.columns and d["coordenadas_validas"].fillna(False).astype(bool).any():
        with st.expander("Ver estos clientes en el mapa"):
            pts = d[d["coordenadas_validas"].fillna(False).astype(bool)].copy()
            pts["color"] = pts["severidad"].map({"CRITICA": NARANJA, "FUERTE": "#f2a65a", "MODERADA": AZUL}).fillna(AZUL)
            st.map(pts.rename(columns={"latitud": "lat", "longitud": "lon"}), color="color", size=120, height=480)
            st.caption("Naranja: caída grave · naranja claro: fuerte · azul: moderada.")


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
    c1.metric("Clientes", f"{len(d):,}")
    c2.metric("kWh/mes", f"{d['perdida_kwh_mes'].sum():,.0f}")
    c3.metric("Valor/mes", pesos(d["valor_riesgo_mes"].sum()))

    cols = [c for c in ["orden_en_ciclo", "ciclo_etiqueta", "NIU", "municipio", "zona_regional", "zona_nombre", "clase_servicio_nombre", "estrato", "grupo_consumo",
                        "cluster_id", "severidad", "trayectoria", "estado_en_lista", "meses_consecutivos_en_lista",
                        "consumo_anterior_kwh", "consumo_reciente_kwh", "perdida_kwh_mes",
                        "tarifa_kwh", "valor_riesgo_mes", "pred_1m_kwh", "consumo_promedio_semestral_kwh",
                        "valor_facturado_mes", "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in d.columns]
    tabla(d[cols], hide_index=True, use_container_width=True, height=520)
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
    top = d.head(n)
    st.markdown(
        f"Los **{len(top):,}** primeros concentran **{pesos_md(top['valor_riesgo_mes'].sum())}/mes**, "
        f"el **{(top['valor_riesgo_mes'].sum() / total * 100 if total else 0):.1f}%** del valor filtrado "
        f"({pesos_md(total)} sobre {len(d):,} clientes)."
    )
    cols = [c for c in ["ranking", "NIU", "ciclo_etiqueta", "municipio", "zona_regional", "zona_nombre", "clase_servicio_nombre", "estrato", "grupo_consumo",
                        "cluster_id", "severidad", "trayectoria", "estado_en_lista",
                        "consumo_anterior_kwh", "consumo_reciente_kwh", "perdida_kwh_mes", "tarifa_kwh",
                        "valor_riesgo_mes", "consumo_promedio_semestral_kwh", "valor_facturado_mes",
                        "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in top.columns]
    tabla(top[cols], hide_index=True, use_container_width=True, height=560)
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
        st.markdown(f"**{len(d):,}** clientes · pérdida esperada **{pesos_md(d['valor_esperado_perdida_mes'].sum())}/mes** · "
                    f"facturación en juego **{pesos_md(d['valor_en_riesgo_mes'].sum())}/mes**")
        cols = [c for c in ["ranking", "NIU", "nivel_riesgo", "prob_fuga_6m", "valor_esperado_perdida_mes", "valor_en_riesgo_mes",
                            "municipio", "zona_regional", "zona_nombre", "clase_servicio_nombre", "grupo_consumo", "estrato", "consumo_actual_kwh",
                            "consumo_prom_6m_kwh", "consumo_prom_12m_kwh", "variacion_3m_vs_12m_pct", "meses_cero_3m",
                            "senales", "estado_en_lista", "meses_consecutivos_en_lista", "tarifa_kwh",
                            "consumo_promedio_semestral_kwh", "tipo_medidor_nombre", "tipo_lectura_nombre"] if c in d.columns]
        tabla(d[cols].head(1000), hide_index=True, use_container_width=True, height=520)
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
            tabla(d[cols], hide_index=True, use_container_width=True, height=420)
            st.download_button("Descargar (CSV)", d[cols].to_csv(index=False).encode("utf-8-sig"),
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
            c1.metric("En vigilancia", f"{len(vg):,}")
            if "nivel_riesgo" in vg.columns:
                c2.metric("Riesgo ALTO", f"{int(vg['nivel_riesgo'].eq('ALTO').sum()):,}")
                c3.metric("Riesgo MEDIO", f"{int(vg['nivel_riesgo'].eq('MEDIO').sum()):,}")
            if "valor_facturado_mes" in vg.columns:
                c4.metric("Facturación / mes", pesos(vg["valor_facturado_mes"].sum()))
            if "motivo" in vg.columns:
                st.caption(" · ".join(f"**{k}**: {v}" for k, v in vg["motivo"].value_counts().items()))
            cols_v = [c for c in ["NIU", "motivo", "estado", "nivel_riesgo", "prob_fuga_6m", "municipio", "zona_nombre",
                                  "clase_servicio_nombre", "grupo_consumo", "consumo_actual_kwh", "consumo_prom_6m_kwh",
                                  "consumo_prom_12m_kwh", "tarifa_kwh", "valor_facturado_mes", "senales", "fecha_corte"] if c in vg.columns]
            tabla(vg[cols_v], hide_index=True, use_container_width=True, height=420)
            st.download_button("Descargar (CSV)", vg[cols_v].to_csv(index=False).encode("utf-8-sig"),
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
                       "La ventana se completa cuando pasan los 6 meses del corte; no es algo que se marque a mano.")
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
            st.caption(f"{len(e):,} clientes cumplen el filtro. Se muestran hasta 50; copia el NIU y pégalo abajo.")
            cols_e = [c for c in ["NIU", "municipio", "ciclo_etiqueta", "zona_nombre", "grupo_consumo", "cluster_id", "zona",
                                  "mediana_12m_kwh", "veredicto", "severidad", "trayectoria", "valor_riesgo_mes",
                                  "riesgo_fuga", "prob_fuga_6m"] if c in e.columns]
            tabla(e[cols_e].head(50), hide_index=True, use_container_width=True)

    niu = st.text_input("NIU").strip()
    if not niu:
        st.stop()

    # --- Avisos de condición comercial: autogenerador / mercado no regulado ---
    auto_ex = cargar(R.autogeneradores)
    es_autogenerador = bool(auto_ex is not None and niu in set(auto_ex["NIU"].astype("string").str.strip()))
    if ubicacion is not None:
        u = ubicacion[ubicacion["NIU"] == niu]
        if len(u) and bool(u["autogenerador_tc1"].iloc[0]):
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
                        f"transformador **{u.get('transformador', '—')}** · altitud **{u.get('altitud', np.nan):,.0f} m**"
                        if pd.notna(u.get("altitud", np.nan)) else
                        f"Dirección: **{u.get('direccion', '—')}** · circuito **{u.get('circuito', '—')}** · transformador **{u.get('transformador', '—')}**")
            if bool(u.get("coordenadas_validas", False)):
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
            "alto no es un fallo del sistema, es falta de historia. Se compara contra la línea base "
            "(repetir el consumo reciente) en la columna WAPE_baseline_pct del archivo."
        )
        st.caption(" · ".join(f"**{g}**: {GRUPO_CONSUMO_DESCRIPCION[g]}" for g in GRUPOS_CONSUMO_ORDEN))
    sel = cargar(R.seleccion)
    if sel is not None:
        with st.expander("Qué algoritmo usa cada grupo"):
            tabla(sel, hide_index=True, use_container_width=True)

    if "modelo_1m" in pred6.columns:
        n_regla = int(pred6["modelo_1m"].eq("REGLA_CERO_SOSTENIDO").sum())
        if n_regla:
            st.caption(f"**{n_regla:,}** clientes con la regla de cero sostenido (dos meses en casi cero): su pronóstico es "
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
        st.caption("RECUPERADO: volvió al menos al 90% de lo que consumía antes de caer. SIGUE_CAYENDO: quedó por "
                   "debajo del 90% de su consumo reciente. ESTABLE_BAJO: se quedó en el nivel caído.")
        for corte_por in ["TOTAL", "trayectoria", "severidad", "zona"]:
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
