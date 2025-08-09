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
    CREATE TABLE IF NOT EXISTS avales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        nombre TEXT NOT NULL,
        identificacion TEXT,
        direccion TEXT,
        telefono TEXT,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
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

def obtener_clientes():
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM clientes ORDER BY id DESC", conn)
    conn.close()
    return df

def eliminar_cliente(cliente_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM avales WHERE cliente_id = ?", (cliente_id,))
    cur.execute("DELETE FROM pagos WHERE prestamo_id IN (SELECT id FROM prestamos WHERE cliente_id=?)", (cliente_id,))
    cur.execute("DELETE FROM prestamos WHERE cliente_id = ?", (cliente_id,))
    cur.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
    conn.commit()
    conn.close()

def agregar_aval(cliente_id, nombre, identificacion, direccion, telefono):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO avales (cliente_id, nombre, identificacion, direccion, telefono) VALUES (?,?,?,?,?)",
                (cliente_id, nombre, identificacion, direccion, telefono))
    conn.commit()
    conn.close()

def obtener_avales(cliente_id):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM avales WHERE cliente_id = ? ORDER BY id DESC", conn, params=(cliente_id,))
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

# --- Diseño y UI Streamlit ---
st.set_page_config("💰 Sistema Préstamos", layout="wide", page_icon="💸")
init_db()

st.markdown("""
    <style>
    .title {
        font-size: 36px; 
        font-weight: 700; 
        color: #2C3E50; 
        text-align: center;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-size: 22px; 
        color: #34495E; 
        margin-bottom: 1rem;
    }
    .section-header {
        background-color: #2980B9;
        color: white;
        padding: 8px 15px;
        border-radius: 5px;
        margin-bottom: 1rem;
        font-weight: 600;
        font-size: 20px;
    }
    .stButton>button {
        background-color: #27AE60;
        color: white;
        font-weight: 600;
        border-radius: 8px;
        padding: 0.4rem 1.1rem;
        transition: background-color 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #219150;
        color: white;
    }
    .dataframe th {
        background-color: #3498DB !important;
        color: white !important;
        font-weight: 600 !important;
        font-size: 14px !important;
    }
    .dataframe td {
        font-size: 13px !important;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown("<h1 class='title'>💰 Sistema de Gestión de Préstamos</h1>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>Administra clientes, avales, préstamos y pagos de forma sencilla</div>", unsafe_allow_html=True)
st.divider()

menu = st.sidebar.selectbox("📋 Menú", ["Clientes", "Préstamos", "Pagos", "Reporte"])

if 'refresh' not in st.session_state:
    st.session_state['refresh'] = False

if menu == "Clientes":
    st.markdown("<div class='section-header'>👥 Clientes y Avales</div>", unsafe_allow_html=True)
    col1, col2 = st.columns([3, 5], gap="large")

    with col1:
        st.subheader("➕ Agregar Cliente")
        with st.form("form_cliente"):
            nombre = st.text_input("Nombre completo", max_chars=100)
            identificacion = st.text_input("Identificación", max_chars=20)
            direccion = st.text_area("Dirección", height=80)
            telefono = st.text_input("Teléfono", max_chars=20)
            submitted = st.form_submit_button("Agregar Cliente ➕")
            if submitted:
                if nombre.strip() == "":
                    st.error("⚠️ Debe ingresar un nombre")
                else:
                    agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip())
                    st.success(f"Cliente '{nombre.strip()}' agregado.")
                    st.session_state['refresh'] = True

        st.markdown("---")
        st.subheader("➖ Eliminar Cliente")
        clientes_df = obtener_clientes()
        if clientes_df.empty:
            st.info("No hay clientes para eliminar.")
        else:
            cliente_eliminar = st.selectbox("Selecciona cliente para eliminar", options=clientes_df['nombre'], key="elim_cliente")
            confirmar = st.checkbox(f"Confirmar eliminación de '{cliente_eliminar}'", key="confirma_elim")
            if st.button("Eliminar Cliente 🗑️") and confirmar:
                cliente_id_elim = int(clientes_df[clientes_df['nombre'] == cliente_eliminar]['id'].values[0])
                eliminar_cliente(cliente_id_elim)
                st.success(f"Cliente '{cliente_eliminar}' eliminado.")
                st.session_state['refresh'] = True

        st.markdown("---")
        st.subheader("👥 Avales")
        clientes_df = obtener_clientes()
        if clientes_df.empty:
            st.info("No hay clientes para agregar avales.")
        else:
            cliente_sel = st.selectbox("Selecciona cliente para agregar aval", options=clientes_df['nombre'], key="cliente_para_aval")
            cliente_id = int(clientes_df[clientes_df['nombre']==cliente_sel]['id'].values[0])
            with st.form("form_aval"):
                aval_nombre = st.text_input("Nombre Aval", max_chars=100)
                aval_identificacion = st.text_input("Identificación Aval", max_chars=20)
                aval_direccion = st.text_area("Dirección Aval", height=80)
                aval_telefono = st.text_input("Teléfono Aval", max_chars=20)
                submitted_aval = st.form_submit_button("Agregar Aval ➕")
                if submitted_aval:
                    if aval_nombre.strip() == "":
                        st.error("⚠️ Debe ingresar nombre del aval")
                    else:
                        agregar_aval(cliente_id, aval_nombre.strip(), aval_identificacion.strip(), aval_direccion.strip(), aval_telefono.strip())
                        st.success(f"Aval '{aval_nombre.strip()}' agregado para cliente '{cliente_sel}'.")
                        st.session_state['refresh'] = True

    with col2:
        st.subheader("📋 Clientes registrados")
        clientes_df = obtener_clientes()
        st.dataframe(clientes_df.style.format({
            "id": "{:.0f}"
        }).set_properties(**{'text-align': 'center'}), height=300)
        
        if not clientes_df.empty:
            cliente_sel2 = st.selectbox("Ver Avales de Cliente", options=clientes_df['nombre'], key="ver_avales")
            cliente_id2 = int(clientes_df[clientes_df['nombre']==cliente_sel2]['id'].values[0])
            avales_df = obtener_avales(cliente_id2)
            st.subheader(f"Avales de {cliente_sel2}")
            if avales_df.empty:
                st.info("No hay avales para este cliente.")
            else:
                st.dataframe(avales_df.style.format({
                    "id": "{:.0f}"
                }).set_properties(**{'text-align': 'center'}), height=250)

    st.divider()

elif menu == "Préstamos":
    st.markdown("<div class='section-header'>🏦 Préstamos</div>", unsafe_allow_html=True)
    df_clientes = obtener_clientes()
    if df_clientes.empty:
        st.info("📌 Agrega primero clientes.")
    else:
        col1, col2 = st.columns([2, 3], gap="medium")
        with col1:
            with st.form("form_prestamo"):
                cliente_sel = st.selectbox("Cliente", df_clientes['nombre'])
                monto = st.number_input("Monto", min_value=0.0, value=1000.0, step=100.0, format="%.2f")
                tasa = st.number_input("Tasa anual (%)", min_value=0.0, value=12.0, step=0.1, format="%.2f")
                plazo = st.number_input("Plazo (meses)", min_value=1, value=12)
                frecuencia = st.selectbox("Frecuencia de pagos por año", [12,4,2,1], index=0)
                fecha_desembolso = st.date_input("Fecha de desembolso", value=date.today())
                submitted = st.form_submit_button("🏦 Crear préstamo")
                if submitted:
                    cliente_id = int(df_clientes[df_clientes['nombre']==cliente_sel]['id'].values[0])
                    agregar_prestamo(cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso)
                    st.success(f"Préstamo creado para {cliente_sel}.")
                    st.session_state['refresh'] = True

        with col2:
            st.markdown("### 📋 Préstamos existentes")
            df_prestamos = obtener_prestamos()
            st.dataframe(df_prestamos.style.format({
                "id": "{:.0f}",
                "monto": "${:,.2f}",
                "tasa": "{:.2f}%",
                "plazo": "{} meses",
                "frecuencia": "{} pagos/año",
                "fecha_desembolso": lambda d: pd.to_datetime(d).strftime('%d-%m-%Y')
            }).set_properties(**{'text-align': 'center'}), height=400)
    st.divider()

elif menu == "Pagos":
    st.markdown("<div class='section-header'>💵 Registrar Pagos</div>", unsafe_allow_html=True)
    df_prestamos = obtener_prestamos()
    if df_prestamos.empty:
        st.info("📌 No hay préstamos.")
    else:
        prestamo_sel = st.selectbox("Selecciona préstamo", df_prestamos['id'].astype(str) + " - " + df_prestamos['cliente'])
        prestamo_id = int(prestamo_sel.split(" - ")[0])
        df_prestamo = df_prestamos[df_prestamos['id'] == prestamo_id].iloc[0]
        st.markdown(f"**Préstamo de {df_prestamo['cliente']}** - Monto: ${df_prestamo['monto']:.2f} | Tasa: {df_prestamo['tasa']:.2f}% | Plazo: {df_prestamo['plazo']} meses")
        col1, col2 = st.columns([2, 3], gap="medium")
        with col1:
            with st.form("form_pago"):
                fecha_pago = st.date_input("Fecha pago", value=date.today())
                monto_pago = st.number_input("Monto pago", min_value=0.0, value=0.0, step=10.0, format="%.2f")
                submitted = st.form_submit_button("💾 Registrar pago")
                if submitted:
                    if monto_pago <= 0:
                        st.error("Monto debe ser mayor a cero")
                    else:
                        agregar_pago(prestamo_id, fecha_pago, monto_pago)
                        st.success("Pago registrado.")
                        st.session_state['refresh'] = True

        with col2:
            pagos = obtener_pagos(prestamo_id)
            st.markdown("### 🧾 Pagos registrados")
            st.dataframe(pagos.style.format({
                "id": "{:.0f}",
                "prestamo_id": "{:.0f}",
                "fecha_pago": lambda d: pd.to_datetime(d).strftime('%d-%m-%Y'),
                "monto": "${:,.2f}"
            }).set_properties(**{'text-align': 'center'}), height=350)
    st.divider()

elif menu == "Reporte":
    st.markdown("<div class='section-header'>📊 Reporte y Cronograma</div>", unsafe_allow_html=True)
    df_prestamos = obtener_prestamos()
    if df_prestamos.empty:
        st

