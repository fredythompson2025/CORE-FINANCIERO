import streamlit as st
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import sqlite3
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

DB_PATH = "cartera_prestamos.db"

# ==============================
# Funciones de Base de Datos
# ==============================
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE,
        identificacion TEXT,
        direccion TEXT,
        telefono TEXT
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS prestamos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        monto REAL,
        tasa REAL,
        plazo INTEGER,
        frecuencia INTEGER,
        fecha_desembolso DATE,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prestamo_id INTEGER,
        fecha_pago DATE,
        monto REAL,
        FOREIGN KEY(prestamo_id) REFERENCES prestamos(id)
    )""")
    conn.commit()
    conn.close()

def agregar_cliente(nombre, identificacion, direccion, telefono):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO clientes (nombre, identificacion, direccion, telefono) VALUES (?,?,?,?)",
                (nombre, identificacion, direccion, telefono))
    conn.commit()
    conn.close()

def modificar_cliente(id_cliente, nombre, identificacion, direccion, telefono):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE clientes SET nombre=?, identificacion=?, direccion=?, telefono=?
        WHERE id=?
    """, (nombre, identificacion, direccion, telefono, id_cliente))
    conn.commit()
    conn.close()

def eliminar_cliente(id_cliente):
    conn = get_conn()
    cur = conn.cursor()
    # También elimina préstamos y pagos asociados
    cur.execute("DELETE FROM pagos WHERE prestamo_id IN (SELECT id FROM prestamos WHERE cliente_id = ?)", (id_cliente,))
    cur.execute("DELETE FROM prestamos WHERE cliente_id = ?", (id_cliente,))
    cur.execute("DELETE FROM clientes WHERE id=?", (id_cliente,))
    conn.commit()
    conn.close()

def obtener_clientes():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM clientes ORDER BY id DESC", conn)
    conn.close()
    return df

# ==============================
# (Aquí irían el resto de funciones para préstamos, pagos, cálculo y PDF,
#  las dejo fuera para enfocarnos en la parte solicitada de Clientes.
#  Puedes añadirlas después o pedir que te las integre completas.)

# ==============================
# Interfaz Streamlit
# ==============================
st.set_page_config("💰 Sistema Préstamos", layout="wide", page_icon="💸")
init_db()

st.markdown("<h1 style='text-align:center; color: darkblue;'>💰 Sistema de Gestión de Préstamos</h1>", unsafe_allow_html=True)
st.divider()

# Control para recargar datos clientes
if "update_clientes" not in st.session_state:
    st.session_state.update_clientes = True

def recargar_clientes():
    st.session_state.update_clientes = True

# Cargar clientes si toca
if st.session_state.update_clientes:
    df_clientes = obtener_clientes()
    st.session_state.df_clientes = df_clientes
    st.session_state.update_clientes = False
else:
    df_clientes = st.session_state.df_clientes

# Submenú horizontal Clientes
tabs = st.tabs(["Agregar", "Modificar", "Eliminar", "Buscar"])

# --- Agregar ---
with tabs[0]:
    st.markdown("### ➕ Agregar Cliente")
    with st.form("form_agregar"):
        nombre = st.text_input("Nombre completo")
        identificacion = st.text_input("Identificación")
        direccion = st.text_input("Dirección")
        telefono = st.text_input("Teléfono")
        submitted = st.form_submit_button("Agregar Cliente")
        if submitted:
            if nombre.strip() == "":
                st.error("Debe ingresar un nombre")
            else:
                agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip())
                st.success(f"Cliente '{nombre.strip()}' agregado.")
                recargar_clientes()

# --- Modificar ---
with tabs[1]:
    st.markdown("### ✏️ Modificar Cliente")
    if df_clientes.empty:
        st.info("No hay clientes para modificar")
    else:
        with st.form("form_modificar"):
            cliente_sel = st.selectbox("Selecciona cliente", df_clientes['nombre'])
            cliente = df_clientes[df_clientes['nombre'] == cliente_sel].iloc[0]
            nombre_mod = st.text_input("Nombre", cliente['nombre'])
            identificacion_mod = st.text_input("Identificación", cliente['identificacion'])
            direccion_mod = st.text_input("Dirección", cliente['direccion'])
            telefono_mod = st.text_input("Teléfono", cliente['telefono'])
            modificar_submitted = st.form_submit_button("Modificar Cliente")
            if modificar_submitted:
                modificar_cliente(cliente['id'], nombre_mod.strip(), identificacion_mod.strip(), direccion_mod.strip(), telefono_mod.strip())
                st.success(f"Cliente '{nombre_mod.strip()}' modificado.")
                recargar_clientes()

# --- Eliminar ---
with tabs[2]:
    st.markdown("### 🗑️ Eliminar Cliente")
    if df_clientes.empty:
        st.info("No hay clientes para eliminar")
    else:
        with st.form("form_eliminar"):
            cliente_sel = st.selectbox("Selecciona cliente para eliminar", df_clientes['nombre'])
            cliente = df_clientes[df_clientes['nombre'] == cliente_sel].iloc[0]
            eliminar_submitted = st.form_submit_button("Eliminar Cliente")
            if eliminar_submitted:
                eliminar_cliente(cliente['id'])
                st.success(f"Cliente '{cliente_sel}' eliminado.")
                recargar_clientes()

# --- Buscar / Reporte ---
with tabs[3]:
    st.markdown("### 📋 Reporte de Clientes")
    if df_clientes.empty:
        st.info("No hay clientes registrados.")
    else:
        st.dataframe(df_clientes.style.set_properties(**{'text-align': 'center'}))

# Aquí puedes seguir agregando el menú general para préstamos, pagos, reportes, etc.

