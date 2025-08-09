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
    # Puedes añadir tablas prestamos y pagos igual que antes si quieres
    conn.commit()
    conn.close()

def agregar_cliente(nombre, identificacion, direccion, telefono):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO clientes (nombre, identificacion, direccion, telefono)
        VALUES (?, ?, ?, ?)
    """, (nombre, identificacion, direccion, telefono))
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
    cur.execute("DELETE FROM clientes WHERE id=?", (id_cliente,))
    conn.commit()
    conn.close()

def obtener_clientes():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM clientes ORDER BY id DESC", conn)
    conn.close()
    return df

# -- Streamlit UI --

st.set_page_config("💰 Sistema Préstamos", layout="wide", page_icon="💸")
init_db()

st.markdown("<h1 style='text-align:center; color: darkblue;'>💰 Sistema de Gestión de Clientes</h1>", unsafe_allow_html=True)
st.divider()

if 'refresh' not in st.session_state:
    st.session_state['refresh'] = False

# Formulario para agregar cliente
st.markdown("## ➕ Agregar Cliente")
with st.form("form_agregar_cliente"):
    nombre = st.text_input("Nombre completo")
    identificacion = st.text_input("Identificación")
    direccion = st.text_input("Dirección")
    telefono = st.text_input("Teléfono")
    submitted = st.form_submit_button("Agregar Cliente")
    if submitted:
        if nombre.strip() == "":
            st.error("El nombre es obligatorio")
        else:
            agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip())
            st.success(f"Cliente '{nombre.strip()}' agregado correctamente.")
            st.session_state['refresh'] = True

st.divider()

# Mostrar clientes
df_clientes = obtener_clientes()

if df_clientes.empty:
    st.info("No hay clientes registrados.")
else:
    st.markdown("## 👥 Clientes Registrados")
    st.dataframe(df_clientes.style.set_properties(**{'text-align': 'center'}))

    # Editar cliente
    with st.expander("✏️ Modificar Cliente"):
        id_mod = st.selectbox("Selecciona cliente a modificar", df_clientes['id'].astype(str) + " - " + df_clientes['nombre'])
        id_mod_val = int(id_mod.split(" - ")[0])
        cliente_mod = df_clientes[df_clientes['id'] == id_mod_val].iloc[0]

        with st.form("form_modificar_cliente"):
            nombre_mod = st.text_input("Nombre completo", value=cliente_mod['nombre'])
            identificacion_mod = st.text_input("Identificación", value=cliente_mod['identificacion'] if cliente_mod['identificacion'] else "")
            direccion_mod = st.text_input("Dirección", value=cliente_mod['direccion'] if cliente_mod['direccion'] else "")
            telefono_mod = st.text_input("Teléfono", value=cliente_mod['telefono'] if cliente_mod['telefono'] else "")
            submitted_mod = st.form_submit_button("Modificar Cliente")
            if submitted_mod:
                if nombre_mod.strip() == "":
                    st.error("El nombre es obligatorio")
                else:
                    modificar_cliente(id_mod_val, nombre_mod.strip(), identificacion_mod.strip(), direccion_mod.strip(), telefono_mod.strip())
                    st.success(f"Cliente '{nombre_mod.strip()}' modificado correctamente.")
                    st.session_state['refresh'] = True

    st.divider()

    # Eliminar cliente
    with st.expander("🗑️ Eliminar Cliente"):
        id_del = st.selectbox("Selecciona cliente a eliminar", df_clientes['id'].astype(str) + " - " + df_clientes['nombre'])
        id_del_val = int(id_del.split(" - ")[0])
        nombre_del = df_clientes[df_clientes['id'] == id_del_val]['nombre'].values[0]
        if st.button(f"Eliminar cliente '{nombre_del}'"):
            eliminar_cliente(id_del_val)
            st.success(f"Cliente '{nombre_del}' eliminado correctamente.")
            st.session_state['refresh'] = True

# Control para refrescar sin error
if st.session_state.get('refresh', False):
    st.session_state['refresh'] = False
    st.experimental_rerun()
