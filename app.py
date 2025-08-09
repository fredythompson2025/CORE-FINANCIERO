import streamlit as st
import pandas as pd
from datetime import date, timedelta
import sqlite3
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

DB_PATH = "cartera_prestamos.db"

# -- DB helpers --
def get_conn():
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
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
    # Eliminar pagos y préstamos relacionados primero para evitar errores de FK
    cur.execute("DELETE FROM pagos WHERE prestamo_id IN (SELECT id FROM prestamos WHERE cliente_id=?)", (id_cliente,))
    cur.execute("DELETE FROM prestamos WHERE cliente_id=?", (id_cliente,))
    cur.execute("DELETE FROM clientes WHERE id=?", (id_cliente,))
    conn.commit()
    conn.close()

def obtener_clientes():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM clientes ORDER BY id DESC", conn)
    conn.close()
    return df

# (Aquí incluir las funciones para préstamos, pagos, cronograma, exportar PDF como las tienes)

# -- Streamlit UI --

st.set_page_config("💰 Sistema Préstamos", layout="wide", page_icon="💸")
init_db()

st.markdown("<h1 style='text-align:center; color: darkblue;'>💰 Sistema de Gestión de Préstamos</h1>", unsafe_allow_html=True)
st.divider()

# Menú con botones en la sidebar
if 'menu' not in st.session_state:
    st.session_state['menu'] = "Clientes"

with st.sidebar:
    st.markdown("## 📋 Menú")
    if st.button("👥 Clientes"):
        st.session_state['menu'] = "Clientes"
    if st.button("🏦 Préstamos"):
        st.session_state['menu'] = "Préstamos"
    if st.button("💵 Pagos"):
        st.session_state['menu'] = "Pagos"
    if st.button("📊 Reporte"):
        st.session_state['menu'] = "Reporte"

menu = st.session_state['menu']

if 'refresh' not in st.session_state:
    st.session_state['refresh'] = False

if menu == "Clientes":
    st.markdown("## 👥 Clientes")
    col1, col2 = st.columns([2, 3])
    with col1:
        with st.form("form_cliente"):
            nombre = st.text_input("Nombre completo", placeholder="Ej: Juan Pérez")
            identificacion = st.text_input("Identificación")
            direccion = st.text_input("Dirección")
            telefono = st.text_input("Teléfono")
            submitted = st.form_submit_button("➕ Agregar Cliente")
            if submitted:
                if nombre.strip() == "":
                    st.error("Debe ingresar un nombre")
                else:
                    agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip())
                    st.success(f"Cliente '{nombre.strip()}' agregado.")
                    st.session_state['refresh'] = True

        with st.form("form_modificar_cliente"):
            st.markdown("### ✏️ Modificar Cliente")
            df_clientes_mod = obtener_clientes()
            if not df_clientes_mod.empty:
                cliente_mod_sel = st.selectbox("Selecciona cliente para modificar", df_clientes_mod['nombre'])
                cliente_mod = df_clientes_mod[df_clientes_mod['nombre'] == cliente_mod_sel].iloc[0]
                nombre_mod = st.text_input("Nombre", value=cliente_mod['nombre'], key="mod_nombre")
                identificacion_mod = st.text_input("Identificación", value=cliente_mod['identificacion'], key="mod_ident")
                direccion_mod = st.text_input("Dirección", value=cliente_mod['direccion'], key="mod_dir")
                telefono_mod = st.text_input("Teléfono", value=cliente_mod['telefono'], key="mod_tel")
                modificar_submitted = st.form_submit_button("💾 Modificar Cliente")
                if modificar_submitted:
                    modificar_cliente(cliente_mod['id'], nombre_mod.strip(), identificacion_mod.strip(), direccion_mod.strip(), telefono_mod.strip())
                    st.success(f"Cliente '{nombre_mod.strip()}' modificado.")
                    st.session_state['refresh'] = True
            else:
                st.info("No hay clientes para modificar.")

        with st.form("form_eliminar_cliente"):
            st.markdown("### 🗑️ Eliminar Cliente")
            df_clientes_del = obtener_clientes()
            if not df_clientes_del.empty:
                cliente_del_sel = st.selectbox("Selecciona cliente para eliminar", df_clientes_del['nombre'], key="del_cliente")
                cliente_del = df_clientes_del[df_clientes_del['nombre'] == cliente_del_sel].iloc[0]
                eliminar_submitted = st.form_submit_button("🗑️ Eliminar Cliente")
                if eliminar_submitted:
                    try:
                        eliminar_cliente(cliente_del['id'])
                        st.success(f"Cliente '{cliente_del_sel}' eliminado junto con sus préstamos y pagos.")
                        st.session_state['refresh'] = True
                    except Exception as e:
                        st.error(f"Error al eliminar cliente: {e}")
            else:
                st.info("No hay clientes para eliminar.")

    with col2:
        st.markdown("### 📋 Clientes registrados")
        df_clientes = obtener_clientes()
        st.dataframe(df_clientes.style.format({"id": "{:.0f}"}).set_properties(**{'text-align': 'center'}))

    st.divider()

# Aquí mantén el resto del código para "Préstamos", "Pagos" y "Reporte" igual que antes.

# Refrescar si necesario
if st.session_state.get('refresh', False):
    st.session_state['refresh'] = False
    try:
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Error durante recarga de página: {e}")
