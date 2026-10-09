"""
componentes_v2.py — piezas reutilizables de la página nueva (app_ebsa_v2.py)
==========================================================================

Aquí vive TODO lo visual de la versión 2: estilos, barra superior, menú, indicadores, avisos, gráficos,
filtros y tablas. No calcula cifras de negocio: recibe los datos ya calculados por app_ebsa_v2.py
(que conserva la lógica de app_ebsa.py) y los presenta.

Piezas:
  inyectar_estilos()            identidad visual (colores, tipografías, tarjetas)
  barra_superior(...)           franja oscura con el nombre, las vistas y el periodo
  menu_lateral(...)             secciones agrupadas en la barra lateral
  menu_inferior(...)            las mismas secciones, abajo, en celular
  titulo_pagina(...)            título y bajada de cada sección
  kpis([...])                   tarjetas de indicadores
  banda([...])                  franja de prioridades (Gestionar / Seguimiento / Vigilar)
  aviso(texto, tipo)            mensajes: información, limitación del modelo, calidad de datos, alerta
  como_leer(texto)              explicación larga, plegada
  tarjeta(titulo, bajada)       contenedor con borde y encabezado
  barras(...), barras_apiladas(...), lineas(...)   gráficos ordenados y con formato colombiano
  filtros(clave, campos)        filtros consistentes con botón Restablecer
  tabla_pro(df, clave, ...)     tabla con búsqueda, orden, paginación, columnas prioritarias y ficha
  tabla(df)                     tabla corta con formato de pesos y kWh

Formato de Colombia: punto de miles y coma decimal (4.025.507 / 15,5), fechas "abril de 2026".
"""
from __future__ import annotations

import base64
import html as _html
import math
import os
import re
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

RECURSOS = Path(__file__).resolve().parent / "recursos_v2"

# ----------------------------------------------------------------------------
# Identidad visual
# ----------------------------------------------------------------------------
# El amarillo es el del sitio público de EBSA (ebsa.com.co), usado solo como acento. No se usa el logotipo
# ni el lema de la empresa: es un proyecto académico, no un producto oficial.
C = {
    "carbon": "#232322", "carbon2": "#33332f", "tinta": "#1d1d1b", "tinta2": "#55584f", "tinta3": "#7b7e75",
    "plano": "#f1f2ee", "sup": "#ffffff", "linea": "#dcdfd6", "linea2": "#eceee8",
    "marca": "#ffc629",
    "gestionar": "#eb6834", "seguimiento": "#2a78d6", "vigilar": "#1baf7a", "vigilar_osc": "#12855c", "mudo": "#9a9d96",
    "naranja_claro": "#f2a65a", "azul_osc": "#1b3a6b",
    "bien": "#0a7d0a", "bien_f": "#e5f3e3", "aviso": "#8a5a00", "aviso_f": "#fdf0cf",
    "alerta": "#b3261e", "alerta_f": "#fbe6e3", "neutro_f": "#edeee9",
}
FUENTE_TEXTO = "'Source Sans 3','Segoe UI',Arial,sans-serif"
FUENTE_TITULO = "'Barlow Semi Condensed','Arial Narrow',Arial,sans-serif"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

def _version_streamlit() -> tuple:
    try:
        return tuple(int(x) for x in st.__version__.split(".")[:2])
    except Exception:
        return (0, 0)


# "Ancho completo": las versiones nuevas de Streamlit lo piden como width="stretch"; las anteriores, use_container_width=True
ANCHO = {"width": "stretch"} if _version_streamlit() >= (1, 50) else {"use_container_width": True}

MODO_PRUEBAS = os.environ.get("EBSA_V2_PRUEBAS") == "1"   # solo para las pruebas automáticas: deja registro de lo mostrado


# ----------------------------------------------------------------------------
# Formato de Colombia
# ----------------------------------------------------------------------------
def fmt_n(x, dec: int = 0) -> str:
    """Número en formato colombiano: punto de miles y coma decimal (4.025.507 / 15,5)."""
    if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
        return "—"
    t = f"{float(x):,.{dec}f}"
    return t.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def pesos(x) -> str:
    return "—" if pd.isna(x) else "$" + fmt_n(x)


def pesos_millones(x, dec: int | None = None) -> str:
    """$674,8 M · $2.146 M (millones de pesos). Con decimal si es menor de 1.000 millones."""
    if x is None or pd.isna(x):
        return "—"
    m = float(x) / 1e6
    if dec is None:
        dec = 0 if abs(m) >= 1000 else 1
    return "$" + fmt_n(m, dec) + " M"


def mes_largo(aaaa_mm) -> str:
    """'2026-04' -> 'abril de 2026'. Si no se puede leer, devuelve el texto tal cual."""
    try:
        t = str(aaaa_mm)[:7]
        return f"{MESES[int(t[5:7]) - 1]} de {t[:4]}"
    except Exception:
        return str(aaaa_mm)


def mes_corto(aaaa_mm) -> str:
    """'2026-04' -> 'abr 2026'."""
    try:
        t = str(aaaa_mm)[:7]
        return f"{MESES_CORTOS[int(t[5:7]) - 1]} {t[:4]}"
    except Exception:
        return str(aaaa_mm)


def fecha_co(valor) -> str:
    """Fecha en formato colombiano dd/mm/aaaa."""
    try:
        return pd.Timestamp(valor).strftime("%d/%m/%Y")
    except Exception:
        return str(valor)


def csv_es(df: pd.DataFrame) -> bytes:
    """CSV para Excel en español: separador ';' y coma decimal, con BOM para que abra con tildes."""
    return df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")


# ----------------------------------------------------------------------------
# Utilidades internas
# ----------------------------------------------------------------------------
def es_movil() -> bool:
    """¿La página se está viendo desde un celular? (por el navegador que la pide). Si no se puede saber, no."""
    try:
        ua = st.context.headers.get("User-Agent", "") or ""
        return "Mobi" in ua or "Android" in ua
    except Exception:
        return False


def _esc(t) -> str:
    return _html.escape(str(t), quote=True)


def md(texto) -> str:
    """Texto con **negrita**, *cursiva* y `código` a HTML seguro (para las piezas propias)."""
    t = _esc(texto).replace("\\$", "$")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t


def _html_out(codigo: str) -> None:
    """Escribe HTML propio en la página (sin interpretar '$' como fórmula)."""
    if hasattr(st, "html"):
        st.html(codigo)
    else:   # versiones anteriores de Streamlit
        st.markdown(codigo, unsafe_allow_html=True)


def _contenedor(clave: str, **kw):
    """Contenedor con nombre (para darle estilo). En versiones de Streamlit sin 'key' en contenedores, uno normal."""
    try:
        return st.container(key=clave, **kw)
    except TypeError:
        return st.container(**kw)


def registrar(tipo: str, clave: str, dato) -> None:
    """Solo en pruebas automáticas: guarda qué se mostró, para comparar con la página original."""
    if MODO_PRUEBAS:
        st.session_state.setdefault("_v2_registro", []).append((tipo, clave, dato))


# ----------------------------------------------------------------------------
# Estilos
# ----------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def _fuentes_css() -> str:
    """Tipografías incluidas en recursos_v2/fuentes (no dependen de internet). Si faltan, se usan las del sistema."""
    caras = [("Barlow Semi Condensed", 600, "barlow-semi-condensed-latin-600-normal.woff2"),
             ("Source Sans 3", 400, "source-sans-3-latin-400-normal.woff2"),
             ("Source Sans 3", 600, "source-sans-3-latin-600-normal.woff2")]
    partes = []
    for familia, peso, archivo in caras:
        ruta = RECURSOS / "fuentes" / archivo
        if ruta.exists():
            b64 = base64.b64encode(ruta.read_bytes()).decode("ascii")
            partes.append(f"@font-face{{font-family:'{familia}';font-style:normal;font-weight:{peso};font-display:swap;"
                          f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    return "".join(partes)


_CSS = """
:root{
  --carbon:#232322; --carbon2:#33332f; --ink:#1d1d1b; --ink2:#55584f; --ink3:#7b7e75;
  --plano:#f1f2ee; --sup:#ffffff; --linea:#dcdfd6; --linea2:#eceee8; --marca:#ffc629;
  --g:#eb6834; --s:#2a78d6; --v:#1baf7a; --vo:#12855c; --mudo:#9a9d96;
  --bien:#0a7d0a; --bien-f:#e5f3e3; --aviso:#8a5a00; --aviso-f:#fdf0cf; --alerta:#b3261e; --alerta-f:#fbe6e3; --neutro-f:#edeee9;
  --disp:'Barlow Semi Condensed','Arial Narrow',Arial,sans-serif; --txt:'Source Sans 3','Segoe UI',Arial,sans-serif;
  --alto-barra:58px;
}
/* ---------- base */
html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp button, .stApp select,
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"], [data-baseweb="select"], [data-baseweb="popover"] li {font-family:var(--txt);}
.stApp{background:var(--plano);color:var(--ink);color-scheme:light;}
/* respaldo por si el navegador llega en modo oscuro antes de recibir el tema claro: el texto nunca queda blanco sobre blanco */
.stApp input, .stApp textarea{color:var(--ink)!important;-webkit-text-fill-color:var(--ink)!important;caret-color:var(--ink);}
.stApp input::placeholder, .stApp textarea::placeholder{color:var(--ink3)!important;-webkit-text-fill-color:var(--ink3)!important;opacity:1;}
[data-testid="stMain"] [data-testid="stWidgetLabel"] p, section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p, [data-testid="stMain"] [data-testid="stMarkdownContainer"] p{color:var(--ink);}
[data-testid="stCaptionContainer"] p{color:var(--ink2)!important;}
.stApp button[kind="primary"] p, .stApp button[kind="primaryFormSubmit"] p, .stApp [data-testid="stBaseButton-primary"] p, .stApp [data-testid="stBaseButton-primaryFormSubmit"] p{color:#fff!important;}
section[data-testid="stSidebar"] .stButton button[kind="primary"] p, section[data-testid="stSidebar"] .stButton [data-testid="stBaseButton-primary"] p{color:var(--ink)!important;}
[data-testid="InputInstructions"]{color:var(--ink3)!important;}
[data-testid="stAppViewContainer"]{background:var(--plano);}
.stApp :focus-visible{outline:3px solid var(--marca);outline-offset:2px;}
h1,h2,h3,h4,[data-testid="stHeading"] h1,[data-testid="stHeading"] h2,[data-testid="stHeading"] h3{font-family:var(--disp)!important;font-weight:600!important;letter-spacing:.1px;color:var(--ink);}
[data-testid="stHeading"] h2{font-size:24px;padding:.6rem 0 .2rem;}
[data-testid="stHeading"] h3{font-size:20px;padding:.5rem 0 .1rem;}
[data-testid="stCaptionContainer"]{color:var(--ink2);font-size:13.5px;}
[data-testid="stMainBlockContainer"], .stMainBlockContainer{max-width:1340px;padding:calc(var(--alto-barra) + 24px) 32px 56px;}

/* ---------- barra superior (la franja de Streamlit pintada de carbón) */
.stApp::before{content:"";position:fixed;top:0;left:0;right:0;height:var(--alto-barra);background:var(--carbon);z-index:999989;}
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-v2_"]), [data-testid="stVerticalBlockBorderWrapper"]:has(> div > [class*="st-key-v2_"]), [data-testid="stVerticalBlockBorderWrapper"]:has(> [class*="st-key-v2_"]), [data-testid="stElementContainer"]:has(> [data-testid="stMarkdownContainer"] > style:only-child){position:absolute;width:0!important;height:0;overflow:visible;}
header[data-testid="stHeader"]{background:transparent;height:var(--alto-barra);min-height:var(--alto-barra);color:#fff;}
header[data-testid="stHeader"] button, header[data-testid="stHeader"] svg, header[data-testid="stHeader"] span{color:#fff!important;fill:#fff;}
[data-testid="stToolbarActions"],[data-testid="stMainMenu"],[data-testid="stAppDeployButton"]{display:none!important;}
[data-testid="stToolbar"]{background:transparent;}
[data-testid="stDecoration"]{display:none;}
[data-testid="stSidebarCollapsedControl"]{top:8px!important;left:8px!important;z-index:999996;}
[data-testid="stSidebarCollapsedControl"] button, [data-testid="stSidebarCollapsedControl"] svg{color:#fff!important;fill:#fff!important;}
.st-key-v2_marca{position:fixed;top:0;left:20px;height:var(--alto-barra);z-index:999995;width:auto!important;display:flex;flex-direction:column;justify-content:center;pointer-events:none;}
.v2-marca{display:flex;align-items:center;gap:12px;color:#fff;white-space:nowrap;}
.v2-marca i{display:block;width:10px;height:34px;background:var(--marca);border-radius:2px;}
.v2-marca b{display:block;font-family:var(--disp);font-weight:600;font-size:19px;line-height:1.1;letter-spacing:.2px;}
.v2-marca small{display:block;font-size:12px;color:#c9cbc3;line-height:1.25;}
.st-key-v2_vistas{position:fixed;top:0;left:338px;height:var(--alto-barra);z-index:999995;width:auto!important;}
.st-key-v2_vistas{display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;align-items:stretch;gap:4px!important;}
.st-key-v2_vistas > *{width:auto!important;flex:0 0 auto!important;min-width:0;}
.st-key-v2_vistas .stButton, .st-key-v2_vistas [data-testid="stButton"]{width:auto!important;height:var(--alto-barra);}
.stApp .st-key-v2_vistas button{height:var(--alto-barra);min-height:0;margin:0;padding:0 16px;background:transparent!important;border:0!important;border-top:3px solid transparent!important;border-bottom:3px solid transparent!important;border-radius:0!important;box-shadow:none!important;color:#d6d8d0!important;}
.stApp .st-key-v2_vistas button p{color:#d6d8d0!important;font-weight:600;font-size:15px;white-space:nowrap;}
.stApp .st-key-v2_vistas button:hover p, .stApp .st-key-v2_vistas button[kind="primary"] p, .stApp .st-key-v2_vistas [data-testid="stBaseButton-primary"] p{color:#fff!important;}
.stApp .st-key-v2_vistas button[kind="primary"], .stApp .st-key-v2_vistas [data-testid="stBaseButton-primary"]{border-bottom-color:var(--marca)!important;}
.st-key-v2_usuario{position:fixed;top:0;right:18px;height:var(--alto-barra);z-index:999995;width:auto!important;display:flex;flex-direction:column;justify-content:center;}
.st-key-v2_usuario > div{width:auto!important;}
.v2-corte{font-size:13px;padding:5px 11px;border:1px solid #5a5b55;border-radius:999px;color:#eceee6;white-space:nowrap;}
.st-key-v2_usuario [data-testid="stPopover"] button{background:var(--carbon2);border:0;color:#fff;border-radius:999px;min-height:34px;padding:2px 12px;font-weight:600;font-size:13px;}
.st-key-v2_usuario [data-testid="stPopover"] button p{color:#fff;font-size:13px;font-weight:600;}
.st-key-v2_usuario [data-testid="stPopover"] button svg{fill:#fff;color:#fff;}

/* ---------- barra lateral: menú de secciones */
section[data-testid="stSidebar"]{background:var(--sup);border-right:1px solid var(--linea);top:var(--alto-barra);height:calc(100vh - var(--alto-barra));width:248px!important;min-width:248px!important;}
section[data-testid="stSidebar"][aria-expanded="false"]{min-width:0!important;}
[data-testid="stSidebarHeader"]{display:none;}
[data-testid="stSidebarContent"]{padding-top:18px;}
[data-testid="stSidebarUserContent"]{padding:0 12px 24px!important;}
[data-testid="stSidebarContent"] > div{padding-left:0;padding-right:0;}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:2px;}
.v2-grp{display:block;padding:14px 10px 5px;font-size:13px;color:var(--ink3);}
.v2-grp.primero{padding-top:2px;}
section[data-testid="stSidebar"] .stButton button{justify-content:flex-start;text-align:left;border:0;border-left:3px solid transparent;border-radius:6px;background:transparent;padding:7px 10px;min-height:0;color:var(--ink2);box-shadow:none;}
section[data-testid="stSidebar"] .stButton button p{font-weight:600;font-size:15px;color:inherit;text-align:left;}
section[data-testid="stSidebar"] .stButton button div{justify-content:flex-start;text-align:left;}
section[data-testid="stSidebar"] .stButton button:hover{background:var(--plano);color:var(--ink);}
section[data-testid="stSidebar"] .stButton button[kind="primary"], section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-primary"]{background:var(--plano);color:var(--ink);border-left-color:var(--marca);}
.v2-nota-lat{margin:22px 10px 0;font-size:12.5px;color:var(--ink3);line-height:1.4;}

/* ---------- menú inferior (solo celular) */
.st-key-v2_inferior{display:none;}

/* ---------- título de página */
.v2-ph{margin:0 0 4px;}
.v2-ph h1{font-family:var(--disp);font-weight:600;font-size:34px;line-height:1.05;margin:0 0 4px;padding:0;letter-spacing:.1px;color:var(--ink);}
.v2-ph p{margin:0;color:var(--ink2);font-size:15.5px;max-width:92ch;}

/* ---------- tarjetas (contenedores con borde) */
[data-testid="stExpander"] details{background:var(--sup);border-color:var(--linea)!important;border-radius:8px!important;}
.st-key-v2_marca, .st-key-v2_vistas, .st-key-v2_usuario{width:max-content!important;max-width:max-content!important;}
.st-key-v2_marca > *, .st-key-v2_vistas > *, .st-key-v2_usuario > *{width:max-content!important;}
[class*="st-key-v2card"] > div, [class*="st-key-v2hero"] > div{max-width:100%!important;}
[data-testid="stMain"] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"][data-testid="stMain"] [data-testid="stLayoutWrapper"], [data-testid="stMain"] [data-testid="stVerticalBlock"]{max-width:100%;min-width:0;}
[class*="st-key-v2card"], [class*="st-key-v2hero"]{box-sizing:border-box;}
[class*="st-key-v2card"]{background:var(--sup);border:1px solid var(--linea);border-radius:8px;padding:16px 18px 14px;}
[data-testid="stMain"] [data-testid="stLayoutWrapper"], [data-testid="stMain"] [data-testid="stVerticalBlock"]{max-width:100%;min-width:0;}
[class*="st-key-v2card"], [class*="st-key-v2hero"]{box-sizing:border-box;}
[class*="st-key-v2card"]{background:var(--sup);border:1px solid var(--linea)!important;border-radius:8px!important;padding:16px 18px 14px!important;}
[class*="st-key-v2hero"]{background:var(--sup);border:1px solid var(--linea)!important;border-top:4px solid var(--carbon)!important;border-radius:8px!important;padding:18px 22px 14px!important;}
.v2-ch h3{font-family:var(--disp);font-weight:600;font-size:20px;line-height:1.2;margin:0;padding:0;color:var(--ink);}
.v2-ch p{margin:3px 0 0;color:var(--ink2);font-size:14px;max-width:86ch;}
.v2-hero-h h3{font-size:26px;}
.v2-hero-h p{font-size:15.5px;}
.v2-pie{margin:2px 0 0;font-size:13.5px;color:var(--ink2);max-width:86ch;}
[data-testid="stExpander"] summary p{font-weight:600;color:var(--ink);font-size:15px;}

/* ---------- banda de prioridades */
.v2-banda{display:flex;gap:3px;margin-top:2px;}
.v2-seg{min-width:0;padding:9px 16px 9px;color:#fff;display:flex;flex-direction:column;gap:0;}
.v2-seg:first-child{border-radius:6px 0 0 6px}.v2-seg:last-child{border-radius:0 6px 6px 0}
.v2-seg-n{font-weight:600;font-size:14.5px;line-height:1.25;}
.v2-seg-v{font-family:var(--disp);font-weight:600;font-size:38px;line-height:1.02;white-space:nowrap;}
.v2-seg-v small{font-size:16px;font-weight:600;opacity:.92;}
.v2-seg-c{font-size:14px;opacity:.96;white-space:nowrap;}

/* ---------- indicadores */
.v2-kpis{display:grid;grid-template-columns:repeat(var(--cols,4),minmax(0,1fr));gap:14px;}
.v2-kpi{position:relative;background:var(--sup);border:1px solid var(--linea);border-left:4px solid var(--linea);border-radius:8px;padding:12px 15px 11px;min-width:0;}
.v2-kpi-t{font-size:14px;color:var(--ink2);font-weight:600;line-height:1.25;padding-right:18px;}
.v2-kpi-v{font-family:var(--disp);font-weight:600;font-size:34px;line-height:1.1;margin:2px 0 2px;color:var(--ink);overflow-wrap:anywhere;}
.v2-kpi-v small{font-size:16px;font-weight:600;color:var(--ink2);}
.v2-kpi-v.texto{font-size:24px;line-height:1.15;}
.v2-kpi-n{font-size:13.5px;color:var(--ink2);line-height:1.3;}
.v2-kpi.t-alerta{border-left-color:var(--alerta)}.v2-kpi.t-g{border-left-color:var(--g)}.v2-kpi.t-s{border-left-color:var(--s)}
.v2-kpi.t-bien{border-left-color:var(--bien)}.v2-kpi.t-aviso{border-left-color:#e0a100}.v2-kpi.t-marca{border-left-color:var(--carbon)}
.v2-kpis.compacto .v2-kpi{padding:9px 13px 8px;}
.v2-kpis.compacto .v2-kpi-v{font-size:25px;}
.v2-kpis.compacto .v2-kpi-v.texto{font-size:19px;}
.v2-ay{position:absolute;top:9px;right:10px;width:18px;height:18px;border-radius:50%;border:1px solid var(--linea);color:var(--ink3);font-size:12px;font-weight:700;line-height:16px;text-align:center;cursor:help;background:var(--sup);}
.v2-ay:hover::after,.v2-ay:focus::after{content:attr(data-t);position:absolute;z-index:60;top:24px;right:-4px;width:min(280px,70vw);background:var(--carbon);color:#fff;font-family:var(--txt);font-size:13px;font-weight:400;line-height:1.35;text-align:left;padding:8px 10px;border-radius:6px;box-shadow:0 4px 14px rgba(0,0,0,.22);}

/* ---------- avisos y etiquetas */
.v2-aviso{display:flex;gap:10px;align-items:flex-start;padding:10px 13px;background:#fbfaf5;border:1px solid var(--linea);border-left:4px solid var(--mudo);border-radius:6px;font-size:14px;color:var(--ink2);line-height:1.42;}
.v2-aviso > div{min-width:0;overflow-wrap:anywhere;}
.v2-aviso b{color:var(--ink);}
.v2-aviso .ico{flex:none;font-weight:700;font-size:12.5px;border-radius:4px;padding:1px 8px;white-space:nowrap;margin-top:1px;background:var(--neutro-f);color:var(--ink2);}
.v2-aviso.a-limite{border-left-color:#e0a100}.v2-aviso.a-limite .ico{background:var(--aviso-f);color:var(--aviso)}
.v2-aviso.a-calidad{border-left-color:var(--s)}.v2-aviso.a-calidad .ico{background:#e3eefb;color:#1d5aa6}
.v2-aviso.a-alerta{border-left-color:var(--alerta);background:#fdf6f5}.v2-aviso.a-alerta .ico{background:var(--alerta-f);color:var(--alerta)}
.v2-aviso.a-bien{border-left-color:var(--bien)}.v2-aviso.a-bien .ico{background:var(--bien-f);color:var(--bien)}
.v2-aviso.a-academico{border-left-color:var(--carbon)}
.v2-tag{display:inline-flex;align-items:center;gap:6px;border-radius:4px;padding:2px 8px 2px 7px;font-size:12.5px;font-weight:700;white-space:nowrap;}
.v2-tag::before{content:"";width:8px;height:8px;border-radius:50%;background:currentColor;}
.v2-tag.t-alerta{background:var(--alerta-f);color:var(--alerta)}.v2-tag.t-alerta::before{border-radius:1px;transform:rotate(45deg)}
.v2-tag.t-aviso{background:var(--aviso-f);color:var(--aviso)}.v2-tag.t-aviso::before{border-radius:0;clip-path:polygon(50% 0,100% 100%,0 100%)}
.v2-tag.t-bien{background:var(--bien-f);color:var(--bien)}
.v2-tag.t-neutro{background:var(--neutro-f);color:var(--ink2)}.v2-tag.t-neutro::before{background:none;border:2px solid currentColor;width:8px;height:8px;box-sizing:border-box}
.v2-ley{display:flex;flex-wrap:wrap;gap:4px 16px;margin:0;font-size:13.5px;color:var(--ink2);}
.v2-ley i{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:6px;vertical-align:-1px;}
.v2-conteo{font-size:14px;color:var(--ink2);margin:0;}
.v2-conteo b{color:var(--ink);}
.v2-anual{display:grid;grid-template-columns:repeat(var(--cols,6),minmax(0,1fr));gap:8px;}
.v2-an{border-top:2px solid var(--s);padding-top:6px;}
.v2-an.p{border-top:2px dashed var(--g);}
.v2-an b{display:block;font-size:13px;color:var(--ink2);}
.v2-an > span{display:block;font-family:var(--disp);font-weight:600;font-size:21px;line-height:1.1;color:var(--ink);}
.v2-an small{font-size:12px;color:var(--ink3);}

/* ---------- fichas en celular (las tablas pasan a tarjetas) */
.v2-fila{border:1px solid var(--linea);border-radius:8px;padding:9px 12px;background:var(--sup);display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;}
.v2-fila div{min-width:0;font-size:14px;color:var(--ink);overflow-wrap:anywhere;}
.v2-fila div span{display:block;font-size:12px;color:var(--ink3);}
.v2-fila div.ancho{grid-column:1 / -1;}
.v2-fila div.fuerte{font-weight:700;}

/* ---------- controles */
.stApp [data-baseweb="tag"]{background:var(--carbon)!important;color:#fff!important;}
.stApp [data-baseweb="tag"] span, .stApp [data-baseweb="tag"] svg{color:#fff!important;fill:#fff!important;}
[data-testid="stMain"] .stButton button, [data-testid="stMain"] .stDownloadButton button, [data-testid="stMain"] [data-testid="stPopover"] button{border:1px solid var(--linea);background:var(--sup);border-radius:6px;font-weight:600;color:var(--ink);}
[data-testid="stMain"] .stButton button:hover, [data-testid="stMain"] .stDownloadButton button:hover{border-color:var(--ink3);color:var(--ink);}
[data-testid="stMain"] .stButton button[kind="primary"], [data-testid="stMain"] .stFormSubmitButton button[kind="primary"], [data-testid="stMain"] button[data-testid="stBaseButton-primaryFormSubmit"]{background:var(--carbon);border-color:var(--carbon);color:#fff;}
[data-testid="stMain"] .stButton button[kind="primary"] p{color:#fff;}
[data-testid="stMain"] .stButton button p, [data-testid="stMain"] .stDownloadButton button p{font-weight:600;font-size:14.5px;}
.stApp [data-baseweb="select"] > div, .stApp [data-baseweb="input"], .stApp [data-baseweb="base-input"]{border-color:var(--linea);background:var(--sup);}
.stApp [data-testid="stTextInput"] [data-baseweb="input"], .stApp [data-testid="stSelectbox"] [data-baseweb="select"] > div, .stApp [data-testid="stMultiSelect"] [data-baseweb="select"] > div{border:1px solid var(--linea);border-radius:6px;background:var(--sup);}
.stApp [data-baseweb="base-input"]{border:0;}
.stApp [data-testid="stTextInputRootElement"], .stApp [data-testid="stNumberInputContainer"]{border:1px solid var(--linea)!important;border-radius:6px;background:var(--sup);}
[data-testid="stForm"]{background:var(--sup);border-color:var(--linea);border-radius:8px;}
[class*="st-key-v2fila"] [data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important;align-items:center;gap:10px;}
[class*="st-key-v2fila"] [data-testid="stColumn"], [class*="st-key-v2fila"] [data-testid="column"]{min-width:0!important;}
[data-testid="stDataFrame"]{border:1px solid var(--linea);border-radius:8px;overflow:hidden;}
[data-testid="stTabs"] [data-baseweb="tab"] p{font-weight:600;font-size:15px;}
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{background-color:var(--marca);}
[data-testid="stTabs"] [aria-selected="true"] p{color:var(--ink);}
[data-testid="stAlert"]{border-radius:6px;}
.v2-login{max-width:430px;margin:5vh auto 0;}

@media (min-width:769px){[data-testid="stSidebarCollapsedControl"]{display:none!important;}}
/* ---------- tableta y celular */
@media (max-width:1080px){
  .st-key-v2_vistas{left:210px;}
  .v2-marca small{display:none;}
  .v2-corte{display:none;}
  .v2-kpis{grid-template-columns:repeat(2,minmax(0,1fr));}
}
@media (max-width:768px){
  :root{--alto-barra:52px;}
  section[data-testid="stSidebar"]{top:0;height:100vh;width:min(300px,86vw)!important;min-width:0!important;z-index:999999;}
  [data-testid="stSidebarContent"]{padding-top:54px;}
  [data-testid="stSidebarHeader"]{display:flex;position:absolute;top:6px;right:6px;z-index:5;}
  [data-testid="stMainBlockContainer"], .stMainBlockContainer{padding:calc(var(--alto-barra) + 14px) 14px 92px;}
  .st-key-v2_marca{left:52px;}
  .v2-marca i{width:8px;height:26px;}
  .v2-marca b{font-size:16px;max-width:92px;white-space:normal;line-height:1.02;}
  .st-key-v2_vistas{left:auto;right:6px;}
  .st-key-v2_usuario{display:none;}
  .v2-aviso{flex-direction:column;gap:5px;}
  .v2-aviso .ico{align-self:flex-start;}
  .v2-ph h1{font-size:27px;}
  .v2-ph p{font-size:14.5px;}
  [class*="st-key-v2card"]{padding:13px 13px 11px!important;}
  [class*="st-key-v2hero"]{padding:14px 14px 12px!important;}
  .v2-hero-h h3{font-size:21px;}
  .v2-hero-h p{font-size:14.5px;}
  .v2-ch h3{font-size:18.5px;}
  .v2-banda{flex-direction:column;}
  .v2-seg{flex:none!important;flex-direction:row;flex-wrap:wrap;align-items:baseline;gap:0 10px;border-radius:6px!important;padding:7px 13px 8px;}
  .v2-seg-n{width:100%;}
  .v2-seg-v{font-size:29px;}
  .v2-kpis{gap:9px;}
  .v2-kpi{padding:10px 11px 9px;}
  .v2-kpi-v{font-size:27px;}
  .v2-kpi-v.largo{font-size:21px;}
  .v2-kpi-v.largo small{font-size:13px;}
  .v2-kpi-v.texto{font-size:19px;}
  .v2-kpi-t{font-size:13px;}
  .v2-kpi-n{font-size:12.5px;}
  .v2-anual{grid-template-columns:repeat(3,minmax(0,1fr));}
  /* menú inferior */
  .st-key-v2_inferior{display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;gap:0!important;overflow-x:auto;scrollbar-width:none;position:fixed;left:0;right:0;bottom:0;z-index:999990;width:100%!important;background:var(--sup);border-top:1px solid var(--linea);padding:0 4px env(safe-area-inset-bottom);}
  .st-key-v2_inferior::-webkit-scrollbar{display:none;}
  .st-key-v2_inferior > *{width:auto!important;flex:0 0 auto!important;}
  .stApp .st-key-v2_inferior button{margin:0;min-height:0;padding:9px 12px 10px;background:transparent!important;border:0!important;border-top:4px solid transparent!important;border-radius:0!important;box-shadow:none!important;}
  .stApp .st-key-v2_inferior button p{font-size:13.5px;font-weight:600;color:var(--ink3)!important;white-space:nowrap;}
  .stApp .st-key-v2_inferior button[kind="primary"], .stApp .st-key-v2_inferior [data-testid="stBaseButton-primary"]{border-top-color:var(--marca)!important;}
  .stApp .st-key-v2_inferior button[kind="primary"] p, .stApp .st-key-v2_inferior [data-testid="stBaseButton-primary"] p{color:var(--ink)!important;}
  .st-key-v2_vistas{gap:0!important;}
  .stApp .st-key-v2_vistas button{padding:0 8px;}
  .stApp .st-key-v2_vistas button p{font-size:14px;}
}
"""


def inyectar_estilos() -> None:
    """Identidad visual de la página. Se llama una vez al comienzo de cada ejecución."""
    st.markdown("<style>" + _fuentes_css() + _CSS + "</style>", unsafe_allow_html=True)


def aplicar_tema() -> None:
    """Deja la página siempre en tema claro, aunque el computador o el navegador estén en modo oscuro, sin tocar
    .streamlit/config.toml (que comparte la página original). El tema se fija en el servidor; como el navegador solo lo
    recibe al comenzar una ejecución, la primera vez se vuelve a ejecutar la página para que llegue de inmediato (sin esto,
    la pantalla de ingreso salía con letras blancas sobre fondo blanco en equipos con modo oscuro)."""
    cambio = False
    try:
        from streamlit import config as _cfg
        for k, v in (("theme.base", "light"), ("theme.primaryColor", C["seguimiento"]), ("theme.backgroundColor", C["plano"]),
                     ("theme.secondaryBackgroundColor", "#ffffff"), ("theme.textColor", C["tinta"])):
            if _cfg.get_option(k) != v:
                _cfg.set_option(k, v)
                cambio = True
    except Exception:
        return
    if cambio and not st.session_state.get("_v2_tema_reintento"):
        st.session_state["_v2_tema_reintento"] = True      # una sola vez por sesión: nunca un ciclo de reejecuciones
        st.rerun()


# ----------------------------------------------------------------------------
# Navegación
# ----------------------------------------------------------------------------
NOTA_ACADEMICA = "Proyecto académico (UPTC) aplicado a datos de EBSA. No es un producto oficial de la empresa."


def _elegir_vista(clave_vista: str, v: str) -> None:
    st.session_state[clave_vista] = v


def barra_superior(vistas: list[str], corte_texto: str = "", etiquetas: dict | None = None, clave_vista: str = "vista"):
    """Franja superior: nombre del proyecto, vistas (pestañas) y periodo de los datos. Devuelve la vista elegida.
    Las pestañas son botones (como el menú lateral): su texto se ve igual en cualquier versión de Streamlit."""
    etiquetas = etiquetas or {}
    with _contenedor("v2_marca"):
        _html_out('<div class="v2-marca"><i></i><div><b>Analítica de consumo</b>'
                  '<small>Proyecto académico UPTC · no oficial de EBSA</small></div></div>')
    vista = None
    if vistas:
        if st.session_state.get(clave_vista) not in vistas:
            st.session_state[clave_vista] = vistas[0]
        vista = st.session_state[clave_vista]
        with _contenedor("v2_vistas"):
            for v in vistas:
                st.button(etiquetas.get(v, v), key=f"v2vista_{v}", type="primary" if v == vista else "secondary",
                          on_click=_elegir_vista, args=(clave_vista, v))
    if corte_texto:
        with _contenedor("v2_usuario"):
            _html_out(f'<span class="v2-corte">{_esc(corte_texto)}</span>')
    return vista


def menu_lateral(grupos: dict, seccion_actual: str, al_elegir, etiquetas: dict | None = None, nota: str = NOTA_ACADEMICA, donde=None) -> None:
    """Menú de secciones agrupado (barra lateral). grupos = {"Listas": ["Caídas de consumo", ...]}."""
    etiquetas = etiquetas or {}
    primero = True
    with (donde if donde is not None else st.sidebar):
        for grupo, secciones in grupos.items():
            if not secciones:
                continue
            _html_out(f'<span class="v2-grp{" primero" if primero else ""}">{_esc(grupo)}</span>')
            primero = False
            for s in secciones:
                st.button(etiquetas.get(s, s), key=f"v2nav_{s}", type="primary" if s == seccion_actual else "secondary",
                          **ANCHO, on_click=al_elegir, args=(s,))
        if nota:
            _html_out(f'<p class="v2-nota-lat">{_esc(nota)}</p>')


def menu_inferior(secciones: list[str], seccion_actual: str, al_elegir, etiquetas: dict | None = None) -> None:
    """Las secciones de la vista en una franja inferior deslizable (solo se ve en celular)."""
    etiquetas = etiquetas or {}
    with _contenedor("v2_inferior"):
        for s_ in secciones:
            st.button(etiquetas.get(s_, s_), key=f"v2inf_{s_}", type="primary" if s_ == seccion_actual else "secondary",
                      on_click=al_elegir, args=(s_,))


def titulo_pagina(titulo: str, bajada: str = "") -> None:
    _html_out(f'<div class="v2-ph"><h1>{_esc(titulo)}</h1>' + (f"<p>{md(bajada)}</p>" if bajada else "") + "</div>")


# ----------------------------------------------------------------------------
# Indicadores, banda, avisos
# ----------------------------------------------------------------------------
def kpis(items: list[dict], columnas: int | None = None, compacto: bool = False, clave: str = "") -> None:
    """Tarjetas de indicadores. Cada item: titulo, valor, unidad (opcional), nota (opcional), tono (alerta, g, s, bien,
    aviso, marca), ayuda (texto al pasar el mouse o tocar la i), texto=True si el valor es una palabra y no una cifra."""
    items = [i for i in items if i]
    if not items:
        return
    columnas = columnas or min(4, len(items))
    partes = []
    for it in items:
        registrar("kpi", clave, (str(it.get("titulo", "")), str(it.get("valor", "")) + (str(it.get("unidad", "")) if it.get("unidad") else ""),
                                 str(it.get("nota", "") or "")))
        tono = f' t-{it["tono"]}' if it.get("tono") else ""
        ay = f'<span class="v2-ay" tabindex="0" role="note" aria-label="{_esc(it["ayuda"])}" data-t="{_esc(it["ayuda"])}">i</span>' if it.get("ayuda") else ""
        unidad = f'<small>{_esc(it["unidad"])}</small>' if it.get("unidad") else ""
        nota = f'<div class="v2-kpi-n">{md(it["nota"])}</div>' if it.get("nota") else ""
        partes.append(f'<div class="v2-kpi{tono}">{ay}<div class="v2-kpi-t">{_esc(it.get("titulo", ""))}</div>'
                      f'<div class="v2-kpi-v{" texto" if it.get("texto") else ""}{" largo" if len(str(it.get("valor", ""))) > 10 else ""}">{_esc(it.get("valor", "—"))}{unidad}</div>{nota}</div>')
    _html_out(f'<div class="v2-kpis{" compacto" if compacto else ""}" style="--cols:{columnas}">' + "".join(partes) + "</div>")


def banda(segmentos: list[dict]) -> None:
    """Franja proporcional. Cada segmento: nombre, valor (texto grande), unidad, detalle, peso (ancho relativo), color."""
    total = sum(max(float(s.get("peso", 1)), 0) for s in segmentos) or 1
    partes = []
    for s in segmentos:
        # ancho proporcional, con un mínimo para que el texto siempre quepa
        flex = max(float(s.get("peso", 1)) / total, 0.17)
        partes.append(f'<div class="v2-seg" style="flex:{flex:.4f} 1 0;background:{s.get("color", C["carbon"])}">'
                      f'<span class="v2-seg-n">{_esc(s["nombre"])}</span>'
                      f'<span class="v2-seg-v">{_esc(s["valor"])}<small>{_esc(s.get("unidad", ""))}</small></span>'
                      f'<span class="v2-seg-c">{_esc(s.get("detalle", ""))}</span></div>')
        registrar("banda", s["nombre"], (str(s["valor"]) + str(s.get("unidad", "")), str(s.get("detalle", ""))))
    _html_out('<div class="v2-banda">' + "".join(partes) + "</div>")


_AVISO_ROTULO = {"info": "Nota", "limite": "Limitación del modelo", "calidad": "Calidad de los datos", "alerta": "Atención",
                 "bien": "Correcto", "academico": "Proyecto académico", "ejemplo": "Ejemplo simulado"}


def aviso(texto: str, tipo: str = "info", rotulo: str | None = None) -> None:
    """Mensaje destacado. tipo: info, limite (limitación del modelo), calidad (calidad de los datos), alerta, bien, academico.
    Cada tipo lleva su rótulo en texto, no solo el color."""
    clase = {"ejemplo": "limite"}.get(tipo, tipo)
    registrar("aviso", tipo, texto)
    _html_out(f'<div class="v2-aviso a-{clase}"><span class="ico">{_esc(rotulo or _AVISO_ROTULO.get(tipo, "Nota"))}</span>'
              f'<div>{md(texto)}</div></div>')


def como_leer(texto: str, titulo: str = "Cómo leer esta página", abierto: bool = False) -> None:
    """Explicación larga, plegada para que las cifras queden primero."""
    with st.expander(titulo, expanded=abierto):
        st.markdown(texto)


def etiqueta(texto: str, tono: str = "neutro") -> str:
    """HTML de una etiqueta de estado (forma + texto, no solo color). tono: alerta, aviso, bien, neutro."""
    return f'<span class="v2-tag t-{tono}">{_esc(texto)}</span>'


def leyenda(items: list[tuple]) -> None:
    _html_out('<div class="v2-ley">' + "".join(f'<span><i style="background:{c}"></i>{_esc(n)}</span>' for n, c in items) + "</div>")


def pie(texto: str) -> None:
    _html_out(f'<p class="v2-pie">{md(texto)}</p>')


def encabezado(titulo: str, bajada: str = "", hero: bool = False) -> None:
    _html_out(f'<div class="v2-ch{" v2-hero-h" if hero else ""}"><h3>{_esc(titulo)}</h3>' + (f"<p>{md(bajada)}</p>" if bajada else "") + "</div>")


@contextmanager
def tarjeta(titulo: str = "", bajada: str = "", hero: bool = False, clave: str | None = None, plegable: bool = False):
    """Contenedor blanco con borde y encabezado. plegable=True: en celular se muestra plegado (menos desplazamiento)."""
    if plegable and titulo and es_movil():
        with st.expander(titulo, expanded=False) as cont:
            if bajada:
                st.caption(bajada)
            yield cont
        return
    st.session_state["_v2_ntarj"] = st.session_state.get("_v2_ntarj", 0) + 1
    nombre = ("v2hero_" if hero else "v2card_") + (clave or str(st.session_state["_v2_ntarj"]))
    try:
        cont = st.container(key=nombre)
    except TypeError:
        cont = st.container(border=True)
    with cont:
        if titulo:
            encabezado(titulo, bajada, hero)
        yield cont


def reiniciar_contadores() -> None:
    st.session_state["_v2_ntarj"] = 0
    if MODO_PRUEBAS:
        st.session_state["_v2_registro"] = []


def linea_conteo(mostrados: int, filtrados: int, en_lista: int, universo: int | None = None,
                 que: str = "clientes", que_lista: str = "en toda la lista", que_universo: str = "clientes evaluados en total") -> None:
    """'2.405 clientes con los filtros · 29.057 en toda la lista · 48.094 clientes evaluados en total'."""
    txt = f"<b>{fmt_n(filtrados)}</b> {que}"
    if mostrados != filtrados:
        txt = f"Se incluyen <b>{fmt_n(mostrados)}</b> de " + txt
    if filtrados != en_lista:
        txt += f" con los filtros actuales · <b>{fmt_n(en_lista)}</b> {que_lista}"
    if universo:
        txt += f" · <b>{fmt_n(universo)}</b> {que_universo}"
    registrar("conteo", que, (int(mostrados), int(filtrados), int(en_lista), int(universo) if universo else None))
    _html_out(f'<p class="v2-conteo">{txt}</p>')


# ----------------------------------------------------------------------------
# Gráficos (Altair: viene con Streamlit, no necesita instalar nada)
# ----------------------------------------------------------------------------
_EXPR_MILES = "replace(format(datum.value, ',.0f'), regexp(',', 'g'), '.')"
_EXPR_DEC1 = "replace(replace(replace(format(datum.value, ',.1f'), regexp(',', 'g'), '§'), '.', ','), regexp('§', 'g'), '.')"


_CONFIG_GRAFICO = {
    "font": "Source Sans 3", "background": "transparent", "autosize": {"type": "fit-x", "contains": "padding"},
    "view": {"stroke": None},
    "axis": {"labelFont": "Source Sans 3", "titleFont": "Source Sans 3", "labelFontSize": 13, "titleFontSize": 13,
             "labelColor": C["tinta"], "titleColor": C["tinta2"], "gridColor": C["linea2"], "domainColor": "#c5c8c0", "tickColor": "#c5c8c0"},
    "legend": {"labelFont": "Source Sans 3", "titleFont": "Source Sans 3", "labelFontSize": 13, "titleFontSize": 13, "labelColor": C["tinta2"]},
    "text": {"font": "Source Sans 3"},
}


def _extension(categorias, limite: int) -> int:
    """Espacio para las etiquetas del eje, calculado por el número de letras (el navegador a veces mide el texto antes de
    cargar la tipografía y recortaba el comienzo de la etiqueta más larga)."""
    largo = max((len(str(c)) for c in categorias), default=4)
    return int(min(limite, largo * 7.6) + 14)


def _mostrar(ch, clave: str | None = None, geometrias: list | None = None):
    """Dibuja un gráfico de Altair. Se convierte a su descripción (Vega-Lite) sin la validación completa de Altair y se le
    pone el estilo común: así cada gráfico cuesta milisegundos y no medio segundo por clic.
    geometrias: lista de polígonos (GeoJSON) para las capas del mapa que se declararon con datos vacíos."""
    try:
        spec = ch.to_dict(validate=False)
        spec["config"] = _CONFIG_GRAFICO
        if geometrias is not None:
            for capa in spec.get("layer", []):
                if capa.get("data", {}).get("values") == []:
                    capa["data"] = {"values": geometrias}
        try:
            st.vega_lite_chart(spec, **ANCHO, theme=None, key=clave)
        except TypeError:
            st.vega_lite_chart(spec, **ANCHO, theme=None)
    except Exception:
        # respaldo: el camino normal de Streamlit
        cfg = ch.configure(font="Source Sans 3", background="transparent").configure_view(stroke=None)
        st.altair_chart(cfg, **ANCHO, theme=None)


def barras(serie: pd.Series, formato=fmt_n, color: str | None = None, nombre_valor: str = "Valor", nombre_categoria: str = "",
           alto_fila: int = 30, clave: str | None = None, max_etiqueta: int = 190, textos: list | None = None) -> None:
    """Barras horizontales, en el orden en que viene la serie (índice = categoría), con la cifra escrita al final de cada barra."""
    import altair as alt
    s = pd.to_numeric(serie, errors="coerce").fillna(0)
    registrar("grafico", clave or nombre_valor, [(str(k), float(v)) for k, v in s.items()])
    if len(s) == 0:
        st.caption("Sin datos para graficar.")
        return
    d = pd.DataFrame({"cat": [str(i) for i in s.index], "val": s.values})
    d["txt"] = list(textos) if textos is not None else [formato(v) for v in d["val"]]
    tope = float(d["val"].max()) if float(d["val"].max()) > 0 else 1.0
    movil = es_movil()
    largo_txt = max(len(str(t)) for t in d["txt"])
    lim = 120 if movil else max_etiqueta
    base = alt.Chart(d).encode(
        y=alt.Y("cat:N", sort=None, title=None, axis=alt.Axis(labelLimit=lim, minExtent=_extension(d["cat"], lim), ticks=False, domain=False, labelPadding=8)),
        x=alt.X("val:Q", title=None, axis=None, scale=alt.Scale(domain=[0, tope * (1 + (0.045 if movil else 0.024) * (largo_txt + 2))])),
        tooltip=[alt.Tooltip("cat:N", title=nombre_categoria or "Categoría"), alt.Tooltip("txt:N", title=nombre_valor)])
    barras_ = base.mark_bar(color=color or C["seguimiento"], cornerRadiusEnd=3, height=max(alto_fila - 12, 10))
    texto = base.mark_text(align="left", dx=6, fontWeight=600, fontSize=13, color=C["tinta"]).encode(text="txt:N")
    _mostrar((barras_ + texto).properties(height=alt.Step(alto_fila)), clave)


def barras_apiladas(tabla_ancha: pd.DataFrame, colores: dict, formato=fmt_n, nombre_categoria: str = "", nombre_serie: str = "",
                    alto_fila: int = 30, clave: str | None = None, leyenda_arriba: bool = True) -> None:
    """Barras horizontales apiladas: filas = categorías (en su orden), columnas = series (en su orden). Total al final."""
    import altair as alt
    t = tabla_ancha.fillna(0)
    registrar("grafico", clave or nombre_serie, [(str(i), str(c), float(t.loc[i, c])) for i in t.index for c in t.columns])
    if len(t) == 0:
        st.caption("Sin datos para graficar.")
        return
    series = [str(c) for c in t.columns]
    if leyenda_arriba:
        leyenda([(s, colores.get(s, C["mudo"])) for s in series])
    largo = t.copy()
    largo.columns = series
    largo.index = [str(i) for i in largo.index]
    largo = largo.rename_axis("cat").reset_index().melt(id_vars="cat", var_name="serie", value_name="val")
    largo["orden"] = largo["serie"].map({s: i for i, s in enumerate(series)})
    largo["txt"] = [formato(v) for v in largo["val"]]
    tot = largo.groupby("cat", sort=False)["val"].sum().reset_index()
    tot["txt"] = [formato(v) for v in tot["val"]]
    tope = float(tot["val"].max()) if len(tot) and float(tot["val"].max()) > 0 else 1.0
    cats = [str(i) for i in t.index]
    movil = es_movil()
    lim = 110 if movil else 180
    eje_y = alt.Y("cat:N", sort=cats, title=None, axis=alt.Axis(labelLimit=lim, minExtent=_extension(cats, lim), ticks=False, domain=False, labelPadding=8))
    escala_x = alt.Scale(domain=[0, tope * (1.28 if movil else 1.14)])
    b = alt.Chart(largo).mark_bar(height=max(alto_fila - 12, 10), stroke="#fff", strokeWidth=1).encode(
        y=eje_y, x=alt.X("val:Q", title=None, axis=None, scale=escala_x, stack="zero"),
        color=alt.Color("serie:N", scale=alt.Scale(domain=series, range=[colores.get(s, C["mudo"]) for s in series]), legend=None),
        order=alt.Order("orden:Q"),
        tooltip=[alt.Tooltip("cat:N", title=nombre_categoria or "Categoría"), alt.Tooltip("serie:N", title=nombre_serie or "Serie"),
                 alt.Tooltip("txt:N", title="Valor")])
    tx = alt.Chart(tot).mark_text(align="left", dx=6, fontWeight=600, fontSize=13, color=C["tinta"]).encode(
        y=eje_y, x=alt.X("val:Q", scale=escala_x), text="txt:N")
    _mostrar((b + tx).properties(height=alt.Step(alto_fila)), clave)


def columnas_tiempo(serie: pd.Series, formato=fmt_n, color: str | None = None, nombre_valor: str = "Valor", alto: int = 240,
                    clave: str | None = None, eje_expr: str = _EXPR_MILES) -> None:
    """Columnas verticales para una serie en el tiempo (índice = periodo en texto, en su orden)."""
    import altair as alt
    s = pd.to_numeric(serie, errors="coerce")
    registrar("grafico", clave or nombre_valor, [(str(k), float(v)) for k, v in s.items()])
    d = pd.DataFrame({"cat": [str(i) for i in s.index], "val": s.values})
    d["txt"] = [formato(v) for v in d["val"]]
    ch = alt.Chart(d).mark_bar(color=color or C["seguimiento"], cornerRadiusEnd=3).encode(
        x=alt.X("cat:N", sort=None, title=None, axis=alt.Axis(labelAngle=0, ticks=False)),
        y=alt.Y("val:Q", title=None, axis=alt.Axis(labelExpr=eje_expr, tickCount=5, minExtent=46)),
        tooltip=[alt.Tooltip("cat:N", title="Periodo"), alt.Tooltip("txt:N", title=nombre_valor)])
    _mostrar(ch.properties(height=alto), clave)


# ----------------------------------------------------------------------------
# Filtros
# ----------------------------------------------------------------------------
def _valor_inicial(campo: dict):
    if "defecto" in campo:
        return campo["defecto"]
    return [] if campo.get("tipo", "multi") == "multi" else (campo["opciones"][0] if campo.get("opciones") else None)


def _restablecer(campos: list[dict], extra=None) -> None:
    for c in campos:
        st.session_state[c["key"]] = _valor_inicial(c)
    if extra:
        extra()


def filtros(clave: str, campos: list[dict], por_fila: int = 4, titulo: str = "Filtros", al_restablecer=None, extra=None) -> dict:
    """Filtros de una lista, siempre con el mismo aspecto y con botón para restablecerlos.

    Cada campo: key (clave del control), etiqueta, opciones, tipo ("multi" o "uno"), defecto, formato (función para
    mostrar cada opción), ayuda, vacio (texto cuando no hay nada elegido), visible (False para omitirlo).
    Devuelve {key: valor}. Un filtro vacío significa "todos".
    """
    campos = [c for c in campos if c.get("visible", True) and (c.get("opciones") is not None)]
    # valor inicial y limpieza: si una opción guardada ya no existe (cambió otro filtro), se quita
    for c in campos:
        ini = _valor_inicial(c)
        if c["key"] not in st.session_state:
            st.session_state[c["key"]] = ini
        actual = st.session_state[c["key"]]
        if c.get("tipo", "multi") == "multi":
            validos = [v for v in (actual or []) if v in c["opciones"]]
            if validos != list(actual or []):
                st.session_state[c["key"]] = validos
        elif actual not in c["opciones"]:
            st.session_state[c["key"]] = ini if ini in c["opciones"] else (c["opciones"][0] if c["opciones"] else None)
    activos = [c for c in campos if st.session_state[c["key"]] not in ([], None, "(todos)", "(todas)")]
    cambiados = [c for c in campos if st.session_state[c["key"]] != _valor_inicial(c)]
    rotulo = titulo + (f" · {len(activos)} activo{'s' if len(activos) != 1 else ''}" if activos else " · ninguno activo")
    movil = es_movil()
    valores = {}
    with st.expander(rotulo, expanded=not movil):
        n = 1 if movil else max(1, min(por_fila, len(campos)))
        for i in range(0, len(campos), n):
            cols = st.columns(n) if n > 1 else [st.container()]
            for col, c in zip(cols, campos[i:i + n]):
                kw = dict(key=c["key"], help=c.get("ayuda"))
                if c.get("formato"):
                    kw["format_func"] = c["formato"]
                if c.get("tipo", "multi") == "multi":
                    valores[c["key"]] = col.multiselect(c["etiqueta"], c["opciones"], placeholder=c.get("vacio", "Todos"), **kw)
                else:
                    valores[c["key"]] = col.selectbox(c["etiqueta"], c["opciones"], **kw)
        if extra is not None:     # controles propios de la sección que van junto a los filtros (se restablecen con al_restablecer)
            extra()
        with _contenedor(f"v2fila_rf_{clave}"):
            c1, c2 = st.columns([1, 3])
            c1.button("Restablecer filtros", key=f"{clave}_restablecer", on_click=_restablecer, args=(campos, al_restablecer),
                      disabled=not cambiados, **ANCHO,
                      help="Vuelve a dejar los filtros como al abrir la sección")
            if cambiados:
                c2.caption("Cambiaste: " + ", ".join(c["etiqueta"].lower() for c in cambiados) + ".")
            else:
                c2.caption("Filtros como al abrir la sección. Un filtro vacío incluye todo.")
    if movil and activos:
        st.caption("Filtros activos: " + " · ".join(
            f"{c['etiqueta']}: " + (", ".join(str((c.get('formato') or str)(v)) for v in st.session_state[c['key']][:3])
                                     + ("…" if len(st.session_state[c['key']]) > 3 else "")
                                     if isinstance(st.session_state[c['key']], list) else str((c.get('formato') or str)(st.session_state[c['key']])))
            for c in activos))
    registrar("filtros", clave, {c["key"]: st.session_state[c["key"]] for c in campos})
    return valores


# ----------------------------------------------------------------------------
# Tablas
# ----------------------------------------------------------------------------
COLUMNAS_PESOS_PISTAS = ("valor", "perdida", "pérdida", "factura", "$", "pesos", "tarifa_kwh")
COLUMNAS_KWH_PISTAS = ("kwh", "consumo")
COLUMNAS_SENSIBLES = ("niu", "dirección", "direccion", "usuario")


def formato_tabla(df: pd.DataFrame, cfg: dict | None = None):
    """Igual que en la página original: columnas de pesos con $ y separador de miles; las de kWh con miles.
    Se detectan por el nombre de la columna; si ya viene column_config, se respeta. Devuelve (tabla, column_config)."""
    cfg = dict(cfg or {})
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
    return d, (cfg or None)


def _huella(df: pd.DataFrame):
    """Resumen de una tabla para comparar con la página original en las pruebas (forma, columnas y contenido)."""
    try:
        if not isinstance(df.index, pd.RangeIndex):
            df = df.reset_index()
        txt = df.astype(str).to_csv(index=False)
    except Exception:
        txt = str(df)
    import hashlib
    return {"filas": int(len(df)), "columnas": [str(c) for c in df.columns], "md5": hashlib.md5(txt.encode("utf-8")).hexdigest()}


def ocultar_identificadores() -> bool:
    return bool(st.session_state.get("v2_ocultar_ids", False))


def enmascarar(valor) -> str:
    """NIU o dirección sin mostrar el dato completo (modo presentación)."""
    t = str(valor)
    if t in ("", "—", "nan", "None", "<NA>"):
        return t
    return "•••" + t[-3:] if len(t) > 4 else "•••"


def _para_pantalla(d: pd.DataFrame) -> pd.DataFrame:
    """Celdas vacías de texto como raya (no 'None') y, en modo presentación, identificadores ocultos."""
    try:
        vacias = [c for c in d.columns if not pd.api.types.is_numeric_dtype(d[c]) and not pd.api.types.is_bool_dtype(d[c])
                  and not pd.api.types.is_datetime64_any_dtype(d[c]) and d[c].isna().any()]
        if vacias:
            d = d.copy()
            for c in vacias:
                d[c] = d[c].astype(object).where(d[c].notna(), "—")
    except Exception:
        pass
    return _enmascarar_tabla(d)


_SIN_MILES = ("niu", "año", "anio", "ciclo", "estrato", "codigo", "código", "horizonte", "cluster", "mes", "id")


def _config_numeros(d: pd.DataFrame, cfg: dict | None) -> dict | None:
    """Números con separador de miles según el idioma del navegador (en español: 24.155). No se aplica a códigos ni años."""
    if _version_streamlit() < (1, 45):
        return cfg
    cfg = dict(cfg or {})
    try:
        for c in d.columns:
            n = str(c).lower()
            if c in cfg or not pd.api.types.is_numeric_dtype(d[c]) or pd.api.types.is_bool_dtype(d[c]):
                continue
            if any(n == p or n.startswith(p + "_") or n.endswith("_" + p) for p in _SIN_MILES) or n in ("2022", "2023", "2024", "2025", "2026", "2027", "2028", "2029"):
                continue
            cfg[c] = st.column_config.NumberColumn(str(c), format="localized")
    except Exception:
        pass
    return cfg or None


def _enmascarar_tabla(d: pd.DataFrame) -> pd.DataFrame:
    if not ocultar_identificadores():
        return d
    cols = [c for c in d.columns if str(c).lower() in COLUMNAS_SENSIBLES]
    if not cols:
        return d
    d = d.copy()
    for c in cols:
        d[c] = d[c].map(enmascarar)
    return d


def tabla_simple(df: pd.DataFrame, clave: str | None = None, **kw):
    """Tabla que ya viene con el texto listo (no se le cambia el formato)."""
    registrar("tabla", clave or "", _huella(df))
    for _k, _v in ANCHO.items():
        kw.setdefault(_k, _v)
    return st.dataframe(_para_pantalla(df), **kw)


def tabla(df: pd.DataFrame, clave: str | None = None, **kw):
    """Tabla corta (resúmenes): formato de pesos y kWh, sin índice, ancho completo."""
    if df is None:
        return None
    d, cfg = formato_tabla(df, kw.pop("column_config", None))
    registrar("tabla", clave or "", _huella(d))
    for _k, _v in ANCHO.items():
        kw.setdefault(_k, _v)
    return st.dataframe(_para_pantalla(d), column_config=_config_numeros(d, cfg), **kw)


def _buscar(df: pd.DataFrame, texto: str) -> pd.DataFrame:
    """Filas donde alguna columna contiene el texto (sin distinguir mayúsculas ni tildes)."""
    q = _sin_tildes(texto.strip().lower())
    if not q:
        return df
    mask = np.zeros(len(df), dtype=bool)
    for c in df.columns:
        col = df[c]
        try:
            s = col.astype("string").fillna("").str.lower()
            s = s.str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("ascii")
            mask |= s.str.contains(q, regex=False).to_numpy(dtype=bool, na_value=False)
        except Exception:
            continue
    return df[mask]


def _sin_tildes(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")


def _ir_pagina(clave_pag: str, n: int) -> None:
    st.session_state[clave_pag] = n


def tabla_pro(df: pd.DataFrame, clave: str, prioritarias: list[str] | None = None, movil: list[str] | None = None,
              ficha=None, columna_id: str = "NIU", por_pagina: int = 25, altura: int | None = None,
              orden_claves: dict | None = None, que: str = "filas", descarga: tuple | None = None,
              boton_ficha=None, column_config: dict | None = None, buscar: bool = True, destacada: str | None = None) -> None:
    """Tabla de trabajo: búsqueda, orden, paginación, columnas prioritarias y (si se pide) ficha del cliente al elegir una fila.

    df              tabla completa, ya filtrada y en el orden recomendado (el del negocio)
    prioritarias    columnas que se ven primero; las demás aparecen con "Todas las columnas"
    movil           columnas para las tarjetas en celular (por defecto, las 6 primeras prioritarias)
    ficha           función(niu) que dibuja la ficha del cliente debajo de la tabla al elegir una fila
    orden_claves    {columna visible: Serie numérica con el mismo índice} para ordenar bien columnas que son texto ("-45 %")
    descarga        (rótulo, nombre de archivo): botón que descarga TODAS las filas (no solo la página)
    boton_ficha     función(niu) opcional que dibuja un botón extra junto al título de la ficha
    """
    if df is None:
        return
    total = len(df)
    registrar("tabla_pro", clave, _huella(formato_tabla(df, column_config)[0]))
    movil_ = es_movil()
    k_q, k_ord, k_dir, k_pp, k_pag, k_cols, k_firma = (f"{clave}_{s}" for s in ("q", "ord", "dir", "pp", "pag", "cols", "firma"))
    todas = list(df.columns)
    prioritarias = [c for c in (prioritarias or todas) if c in todas]
    hay_mas_columnas = len(prioritarias) < len(todas)

    # ---- controles: buscar + opciones (orden, columnas, filas por página)
    with _contenedor(f"v2fila_ctl_{clave}"):
        c1, c2 = st.columns([3, 2] if not movil_ else [5, 4])
        q = c1.text_input("Buscar en la tabla", key=k_q, placeholder="Buscar en la tabla (NIU, municipio, clase…)",
                          label_visibility="collapsed") if buscar and total > 8 else ""
        with c2.popover("Ordenar y columnas", **ANCHO):
            opciones_orden = ["(orden recomendado)"] + todas
            if st.session_state.get(k_ord) not in opciones_orden:
                st.session_state[k_ord] = "(orden recomendado)"
            col_orden = st.selectbox("Ordenar por", opciones_orden, key=k_ord,
                                     help="El orden recomendado es el de negocio: primero lo más importante.")
            sentido = st.radio("Sentido", ["Mayor a menor", "Menor a mayor"], horizontal=True, key=k_dir,
                               disabled=col_orden == "(orden recomendado)")
            st.session_state.setdefault(k_pp, 5 if movil_ else por_pagina)
            pp = st.selectbox("Filas por página", [5, 10, 25, 50, 100], key=k_pp)
            ver_todas = st.toggle("Todas las columnas", key=k_cols, disabled=not hay_mas_columnas,
                                  help="Por defecto se muestran las columnas más útiles para decidir.") if hay_mas_columnas else True
            ver_tarjetas = st.toggle("Ver como tarjetas", key=f"{clave}_tarj", value=True,
                                     help="En celular cada fila se muestra como una tarjeta.") if movil_ else False

    d = _buscar(df, q) if q else df
    if col_orden != "(orden recomendado)" and col_orden in d.columns:
        llave = (orden_claves or {}).get(col_orden)
        asc = sentido == "Menor a mayor"
        if llave is not None:
            d = d.loc[llave.reindex(d.index).sort_values(ascending=asc, na_position="last", kind="stable").index]
        else:
            d = d.sort_values(col_orden, ascending=asc, na_position="last", kind="stable")
    n = len(d)
    paginas = max(1, math.ceil(n / pp))
    firma = (total, q, col_orden, sentido, pp, n)
    if st.session_state.get(k_firma) != firma:     # cambió la lista: se vuelve a la primera página
        st.session_state[k_firma] = firma
        st.session_state[k_pag] = 1
    pag = int(min(max(1, st.session_state.get(k_pag, 1)), paginas))
    st.session_state[k_pag] = pag
    ini = (pag - 1) * pp
    pagina = d.iloc[ini:ini + pp]

    if n == 0:
        aviso(f"Ninguna fila contiene «{q}». Borra la búsqueda para ver las {fmt_n(total)} {que}." if q else f"No hay {que} para mostrar.", "info")
        return

    cols_ver = todas if ver_todas else prioritarias
    elegido = None
    if ver_tarjetas:
        campos = [c for c in (movil or prioritarias[:6]) if c in pagina.columns]
        fmt, _ = formato_tabla(pagina[campos])
        fmt = _para_pantalla(fmt)
        for pos, (idx, fila) in enumerate(fmt.iterrows()):
            celdas = "".join(f'<div class="{"fuerte " if c == destacada else ""}{"ancho" if len(str(fila[c])) > 26 else ""}">'
                             f'<span>{_esc(c)}</span>{_esc("—" if pd.isna(fila[c]) or str(fila[c]) in ("", "<NA>", "nan", "None") else fila[c])}</div>' for c in campos)
            _html_out(f'<div class="v2-fila">{celdas}</div>')
        if ficha is not None and columna_id in pagina.columns:
            ids = [str(x).strip() for x in pagina[columna_id]]
            k_sel = f"{clave}_sel_{pag}_{abs(hash(firma)) % 100000}"
            elegido = st.selectbox("Ver la ficha de un cliente de esta página", ids, index=None, key=k_sel,
                                   placeholder="Elige un cliente para ver su ficha",
                                   format_func=(enmascarar if ocultar_identificadores() else str))
    else:
        fmt, cfg = formato_tabla(pagina, column_config)
        fmt = _para_pantalla(fmt)
        alto = altura or min(38 * (len(pagina) + 1) + 3, 38 * 16 + 3)
        kw = dict(hide_index=True, **ANCHO, height=alto, column_config=_config_numeros(fmt, cfg), column_order=cols_ver)
        if ficha is not None and columna_id in pagina.columns:
            ev = st.dataframe(fmt.reset_index(drop=True), on_select="rerun", selection_mode="single-row",
                              key=f"tbl_{clave}_{pag}_{abs(hash(firma)) % 100000}", **kw)
            filas = []
            try:
                filas = list(ev.selection.rows)
            except Exception:
                filas = []
            filas = [f for f in filas if isinstance(f, int) and 0 <= f < len(pagina)]
            if filas:
                elegido = str(pagina.iloc[filas[0]][columna_id]).strip()
        else:
            st.dataframe(fmt.reset_index(drop=True), **kw)

    # ---- pie: conteo + paginación + descarga
    with _contenedor(f"v2fila_pie_{clave}"):
        c1, c2, c3, c4 = st.columns([5, 2, 2, 3] if not movil_ else [4, 2, 2, 1])
        fin = min(ini + pp, n)
        txt = f"{fmt_n(ini + 1)}–{fmt_n(fin)} de {fmt_n(n)} {que}" + (f" (de {fmt_n(total)})" if n != total else "")
        if paginas > 1:
            txt += f" · página {fmt_n(pag)} de {fmt_n(paginas)}"
        c1.caption(txt + (". Elige una fila para ver la ficha." if ficha is not None and not ver_tarjetas else ""))
        c2.button("Anterior", key=f"{clave}_ant", disabled=pag <= 1, on_click=_ir_pagina, args=(k_pag, pag - 1), **ANCHO)
        c3.button("Siguiente", key=f"{clave}_sig", disabled=pag >= paginas, on_click=_ir_pagina, args=(k_pag, pag + 1), **ANCHO)
        if descarga and not movil_:
            c4.download_button(descarga[0], csv_es(df), file_name=descarga[1], mime="text/csv", key=f"{clave}_dl", **ANCHO)
    if descarga and movil_:
        st.download_button(descarga[0], csv_es(df), file_name=descarga[1], mime="text/csv", key=f"{clave}_dl", **ANCHO)

    if ficha is not None and elegido:
        with tarjeta(clave=f"ficha_{clave}"):
            c1, c2 = st.columns([3, 1])
            with c1:
                encabezado(f"Cliente {enmascarar(elegido) if ocultar_identificadores() else elegido}", "Ficha del cliente elegido en la tabla")
            if boton_ficha is not None:
                with c2:
                    boton_ficha(elegido)
            ficha(elegido)
