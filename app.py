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
    cur.execute("""
    CREATE TABLE IF NOT EXISTS avales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        nombre TEXT,
        identificacion TEXT,
        direccion TEXT,
        telefono TEXT,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")
    conn.commit()
    conn.close()

def agregar_cliente(nombre, identificacion, direccion, telefono):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO clientes (nombre, identificacion, direccion, telefono) VALUES (?,?,?,?)",
        (nombre, identificacion, direccion, telefono))
    conn.commit()
    conn.close()

def eliminar_cliente(cliente_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
    conn.commit()
    conn.close()

def modificar_cliente(cliente_id, nombre, identificacion, direccion, telefono):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    UPDATE clientes SET nombre=?, identificacion=?, direccion=?, telefono=? WHERE id=?
    """, (nombre, identificacion, direccion, telefono, cliente_id))
    conn.commit()
    conn.close()

def obtener_clientes():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM clientes ORDER BY id DESC", conn)
    conn.close()
    return df

def agregar_prestamo(cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO prestamos (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso) VALUES (?,?,?,?,?,?)",
                (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso))
    conn.commit()
    conn.close()

def obtener_prestamos():
    conn = get_conn()
    df = pd.read_sql_query("""
    SELECT p.id, c.nombre as cliente, p.monto, p.tasa, p.plazo, p.frecuencia, p.fecha_desembolso
    FROM prestamos p JOIN clientes c ON p.cliente_id = c.id
    ORDER BY p.id DESC
    """, conn)
    conn.close()
    return df

def agregar_pago(prestamo_id, fecha_pago, monto):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO pagos (prestamo_id, fecha_pago, monto) VALUES (?,?,?)",
                (prestamo_id, fecha_pago, monto))
    conn.commit()
    conn.close()

def obtener_pagos(prestamo_id):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM pagos WHERE prestamo_id = ? ORDER BY fecha_pago", conn, params=(prestamo_id,))
    conn.close()
    return df

def agregar_aval(cliente_id, nombre, identificacion, direccion, telefono):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO avales (cliente_id, nombre, identificacion, direccion, telefono) VALUES (?,?,?,?,?)",
                (cliente_id, nombre, identificacion, direccion, telefono))
    conn.commit()
    conn.close()

def obtener_avales(cliente_id):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM avales WHERE cliente_id = ?", conn, params=(cliente_id,))
    conn.close()
    return df

# -- Amortización simple francés --
def calcular_cronograma(monto, tasa_anual, plazo_meses, frecuencia, fecha_desembolso):
    pagos_totales = int(plazo_meses * frecuencia / 12)
    tasa_periodo = tasa_anual / 100 / frecuencia
    if tasa_periodo == 0:
        cuota = monto / pagos_totales
    else:
        cuota = monto * (tasa_periodo / (1 - (1 + tasa_periodo) ** -pagos_totales))
    cronograma = []
    saldo = monto
    for i in range(1, pagos_totales + 1):
        interes = saldo * tasa_periodo
        amortizacion = cuota - interes
        saldo = max(0, saldo - amortizacion)
        fecha_pago = fecha_desembolso + timedelta(days=int(i * 365 / frecuencia))
        cronograma.append({
            "Periodo": i,
            "Fecha": fecha_pago,
            "Cuota": round(cuota,2),
            "Interes": round(interes,2),
            "Amortizacion": round(amortizacion,2),
            "Saldo": round(saldo,2)
        })
    return pd.DataFrame(cronograma)

def estado_cuotas(cronograma, pagos):
    cronograma = cronograma.copy()
    cronograma['Pagado'] = 0.0
    pagos_totales = pagos['monto'].sum() if not pagos.empty else 0
    restante = pagos_totales
    for idx, row in cronograma.iterrows():
        cuota = row['Cuota']
        a_pagar = min(cuota, restante)
        cronograma.at[idx, 'Pagado'] = a_pagar
        restante -= a_pagar
        if restante <= 0:
            break
    cronograma['Pendiente'] = cronograma['Cuota'] - cronograma['Pagado']
    hoy = pd.Timestamp(date.today())
    cronograma['Estado'] = cronograma.apply(lambda r: 'Vencida' if r['Fecha'] < hoy and r['Pendiente'] > 0 else 'Al día', axis=1)
    return cronograma

# -- Exportar PDF --
def exportar_pdf(df, cliente, prestamo_id):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    flowables = [Paragraph(f"Cronograma de Pago - Préstamo #{prestamo_id}", styles['Title']),
                 Paragraph(f"Cliente: {cliente}", styles['Normal']),
                 Spacer(1,12)]
    data = [df.columns.to_list()]
    for _, row in df.iterrows():
        data.append([str(row[col]) if not pd.isna(row[col]) else '' for col in df.columns])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-1),0.5,colors.grey),
        ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
    ]))
    flowables.append(table)
    doc.build(flowables)
    buffer.seek(0)
    return buffer

# -- Streamlit UI --

st.set_page_config("💰 Sistema Préstamos", layout="wide", page_icon="💸")
init_db()

st.markdown("<h1 style='text-align:center; color: darkblue;'>💰 Sistema de Gestión de Préstamos</h1>", unsafe_allow_html=True)
st.divider()

menu = st.sidebar.selectbox("📋 Menú", ["Clientes", "Préstamos", "Pagos", "Reporte"])

if 'needs_refresh' not in st.session_state:
    st.session_state['needs_refresh'] = False

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
                if not nombre.strip():
                    st.error("Debe ingresar un nombre")
                else:
                    agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip())
                    st.success(f"Cliente '{nombre.strip()}' agregado.")
                    st.session_state['needs_refresh'] = True

        with st.form("form_modificar_cliente"):
            clientes_df = obtener_clientes()
            cliente_sel = st.selectbox("Selecciona cliente para modificar", clients_df['nombre'] if not clients_df.empty else [])
            if cliente_sel:
                cliente_info = clients_df[clients_df['nombre'] == cliente_sel].iloc[0]
                mod_nombre = st.text_input("Nombre", value=cliente_info['nombre'], key="mod_nombre")
                mod_ident = st.text_input("Identificación", value=cliente_info['identificacion'], key="mod_ident")
                mod_dir = st.text_input("Dirección", value=cliente_info['direccion'], key="mod_dir")
                mod_tel = st.text_input("Teléfono", value=cliente_info['telefono'], key="mod_tel")
                mod_submit = st.form_submit_button("✏️ Modificar Cliente")
                if mod_submit:
                    modificar_cliente(cliente_info['id'], mod_nombre.strip(), mod_ident.strip(), mod_dir.strip(), mod_tel.strip())
                    st.success(f"Cliente '{mod_nombre.strip()}' modificado.")
                    st.session_state['needs_refresh'] = True

        with st.form("form_eliminar_cliente"):
            clientes_df = obtener_clientes()
            cliente_sel_del = st.selectbox("Selecciona cliente para eliminar", clientes_df['nombre'] if not clientes_df.empty else [])
            del_submit = st.form_submit_button("🗑️ Eliminar Cliente")
            if del_submit and cliente_sel_del:
                cliente_info = clientes_df[clientes_df['nombre'] == cliente_sel_del].iloc[0]
                eliminar_cliente(cliente_info['id'])
                st.success(f"Cliente '{cliente_sel_del}' eliminado.")
                st.session_state['needs_refresh'] = True

    with col2:
        st.markdown("### 📋 Clientes registrados")
        df_clientes = obtener_clientes()
        st.dataframe(df_clientes.style.format({"id": "{:.0f}"}).set_properties(**{'text-align': 'center'}))
    st.divider()

elif menu == "Préstamos":
    # Aquí iría el código para préstamos igual que antes
    pass
elif menu == "Pagos":
    # Aquí iría el código para pagos igual que antes
    pass
elif menu == "Reporte":
    # Aquí iría el código para reporte igual que antes
    pass

if st.session_state['needs_refresh']:
    st.session_state['needs_refresh'] = False
    st.experimental_rerun()
