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

# -- DB helpers --
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
    try:
        cur.execute("INSERT INTO clientes (nombre, identificacion, direccion, telefono) VALUES (?,?,?,?)",
                    (nombre, identificacion, direccion, telefono))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True

def modificar_cliente(id_cliente, nombre, identificacion, direccion, telefono):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE clientes SET nombre=?, identificacion=?, direccion=?, telefono=?
            WHERE id=?
        """, (nombre, identificacion, direccion, telefono, id_cliente))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    return True

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

# -- Amortización simple francés --
def calcular_cronograma(monto, tasa_anual, plazo_meses, frecuencia, fecha_desembolso):
    pagos_totales = int(plazo_meses * frecuencia / 12)
    tasa_periodo = tasa_anual / 100 / frecuencia
    if pagos_totales == 0:
        return pd.DataFrame()  # evitar división por cero
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
        meses_a_sumar = int(12 / frecuencia)
        fecha_pago = fecha_desembolso + relativedelta(months=meses_a_sumar * i)
        cronograma.append({
            "Periodo": i,
            "Fecha": fecha_pago,
            "Cuota": round(cuota, 2),
            "Interes": round(interes, 2),
            "Amortizacion": round(amortizacion, 2),
            "Saldo": round(saldo, 2)
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
    flowables = [
        Paragraph(f"Cronograma de Pago - Préstamo #{prestamo_id}", styles['Title']),
        Paragraph(f"Cliente: {cliente}", styles['Normal']),
        Spacer(1, 12)
    ]
    data = [df.columns.to_list()]
    for _, row in df.iterrows():
        data.append([str(row[col]) if not pd.isna(row[col]) else '' for col in df.columns])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
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

menu = st.sidebar.radio("📋 Menú", ["Clientes", "Préstamos", "Pagos", "Reporte"])

if menu == "Clientes":
    st.markdown("## 👥 Clientes")
    col1, col2 = st.columns([2, 3])
    with col1:
        with st.form("form_cliente"):
            st.markdown("### ➕ Agregar Cliente")
            nombre = st.text_input("Nombre completo", placeholder="Ej: Juan Pérez")
            identificacion = st.text_input("Identificación")
            direccion = st.text_input("Dirección")
            telefono = st.text_input("Teléfono")
            submitted = st.form_submit_button("Agregar Cliente")
            if submitted:
                if nombre.strip() == "":
                    st.error("Debe ingresar un nombre.")
                else:
                    agregado = agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip())
                    if agregado:
                        st.success(f"Cliente '{nombre.strip()}' agregado.")
                    else:
                        st.error("Ya existe un cliente con ese nombre.")

        with st.form("form_modificar_cliente"):
            st.markdown("### ✏️ Modificar Cliente")
            df_clientes_mod = obtener_clientes()
            if df_clientes_mod.empty:
                st.info("No hay clientes para modificar.")
            else:
                cliente_mod_sel = st.selectbox("Selecciona cliente para modificar", df_clientes_mod['nombre'])
                cliente_mod = df_clientes_mod[df_clientes_mod['nombre'] == cliente_mod_sel].iloc[0]
                nombre_mod = st.text_input("Nombre", value=cliente_mod['nombre'], key="mod_nombre")
                identificacion_mod = st.text_input("Identificación", value=cliente_mod['identificacion'], key="mod_ident")
                direccion_mod = st.text_input("Dirección", value=cliente_mod['direccion'], key="mod_dir")
                telefono_mod = st.text_input("Teléfono", value=cliente_mod['telefono'], key="mod_tel")
                modificar_submitted = st.form_submit_button("Modificar Cliente")
                if modificar_submitted:
                    if nombre_mod.strip() == "":
                        st.error("El nombre no puede estar vacío.")
                    else:
                        modificado = modificar_cliente(cliente_mod['id'], nombre_mod.strip(), identificacion_mod.strip(), direccion_mod.strip(), telefono_mod.strip())
                        if modificado:
                            st.success(f"Cliente '{nombre_mod.strip()}' modificado.")
                        else:
                            st.error("Error: ya existe un cliente con ese nombre.")

        with st.form("form_eliminar_cliente"):
            st.markdown("### 🗑️ Eliminar Cliente")
            df_clientes_del = obtener_clientes()
            if df_clientes_del.empty:
                st.info("No hay clientes para eliminar.")
            else:
                cliente_del_sel = st.selectbox("Selecciona cliente para eliminar", df_clientes_del['nombre'], key="del_cliente")
                eliminar_submitted = st.form_submit_button("Eliminar Cliente")
                if eliminar_submitted:
                    if st.confirm(f"¿Estás seguro de eliminar al cliente '{cliente_del_sel}'? Esta acción no se puede deshacer."):
                        cliente_del = df_clientes_del[df_clientes_del['nombre'] == cliente_del_sel].iloc[0]
                        eliminar_cliente(cliente_del['id'])
                        st.success(f"Cliente '{cliente_del_sel}' eliminado.")
                    else:
                        st.info("Eliminación cancelada.")

    with col2:
        st.markdown("### 📋 Clientes registrados")
        df_clientes = obtener_clientes()
        st.dataframe(df_clientes.style.format({"id": "{:.0f}"}).set_properties(**{'text-align': 'center'}))

    st.divider()

elif menu == "Préstamos":
    st.markdown("## 🏦 Préstamos")
    df_clientes = obtener_clientes()
    if df_clientes.empty:
        st.info("📌 Agrega primero clientes.")
    else:
        col1, col2 = st.columns([2, 3])
        with col1:
            with st.form("form_prestamo"):
                st.markdown("### ➕ Crear Préstamo")
                cliente_sel = st.selectbox("Cliente", df_clientes['nombre'])
                monto = st.number_input("Monto", min_value=0.01, value=1000.0, step=100.0, format="%.2f")
                tasa = st.number_input("Tasa anual (%)", min_value=0.0, value=12.0, step=0.1, format="%.2f")
                plazo = st.number_input("Plazo (meses)", min_value=1, value=12)
                frecuencia = st.selectbox("Frecuencia de pagos por año", [12, 4, 2, 1], index=0)
                fecha_desembolso = st.date_input("Fecha de desembolso", value=date.today())
                submitted = st.form_submit_button("Crear préstamo")
                if submitted:
                    if monto <= 0:
                        st.error("El monto debe ser mayor a cero.")
                    elif tasa < 0:
                        st.error("La tasa no puede ser negativa.")
                    elif plazo <= 0:
                        st.error("El plazo debe ser mayor que cero.")
                    else:
                        cliente_id = int(df_clientes[df_clientes['nombre'] == cliente_sel]['id'].values[0])
                        agregar_prestamo(cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso)
                        st.success(f"Préstamo creado para {cliente_sel}.")

        with col2:
            st.markdown("### 📋 Préstamos existentes")
            df_prestamos = obtener_prestamos()
            if df_prestamos.empty:
                st.info("No hay préstamos registrados.")
            else:
                st.dataframe(df_prestamos.style.format({
                    "id": "{:.0f}",
                    "monto": "${:,.2f}",
                    "tasa": "{:.2f}%",
                    "plazo": "{:.0f} meses",
                    "frecuencia": "{:.0f} pagos/año",
                    "fecha_desembolso": lambda d: pd.to_datetime(d).strftime('%d-%m-%Y')
                }).set_properties(**{'text-align': 'center'}))
    st.divider()

elif menu == "Pagos":
    st.markdown("## 💵 Registrar Pagos")
    df_prestamos = obtener_prestamos()
    if df_prestamos.empty:
        st.info("📌 No hay préstamos.")
    else:
        prestamo_sel = st.selectbox("Selecciona préstamo", df_prestamos['id'].astype(str) + " - " + df_prestamos['cliente'])
        prestamo_id = int(prestamo_sel.split(" - ")[0])
        df_prestamo = df_prestamos[df_prestamos['id'] == prestamo_id].iloc[0]
        st.markdown(f"**Préstamo de {df_prestamo['cliente']}** - Monto: ${df_prestamo['monto']:.2f} | Tasa: {df_prestamo['tasa']:.2f}% | Plazo: {df_prestamo['plazo']} meses")
        col1, col2 = st.columns([2, 3])
        with col1:
            with st.form("form_pago"):
                st.markdown("### 💾 Registrar pago")
                fecha_pago = st.date_input("Fecha pago", value=date.today())
                monto_pago = st.number_input("Monto pago", min_value=0.01, value=0.0, step=10.0, format="%.2f")
                submitted = st.form_submit_button("Registrar pago")
                if submitted:
                    if monto_pago <= 0:
                        st.error("Monto debe ser mayor a cero.")
                    else:
                        # Validar que no pague más del saldo pendiente
                        cronograma = calcular_cronograma(
                            df_prestamo['monto'],
                            df_prestamo['tasa'],
                            df_prestamo['plazo'],
                            df_prestamo['frecuencia'],
                            pd.to_datetime(df_prestamo['fecha_desembolso']).date()
                        )
                        pagos = obtener_pagos(prestamo_id)
                        cron_estado = estado_cuotas(cronograma, pagos)
                        saldo_pendiente = cron_estado['Pendiente'].sum()
                        if monto_pago > saldo_pendiente:
                            st.error(f"El monto excede el saldo pendiente (${saldo_pendiente:.2f}).")
                        else:
                            agregar_pago(prestamo_id, fecha_pago, monto_pago)
                            st.success("Pago registrado.")

        with col2:
            pagos = obtener_pagos(prestamo_id)
            st.markdown("### 🧾 Pagos registrados")
            if pagos.empty:
                st.info("No hay pagos registrados.")
            else:
                st.dataframe(pagos.style.format({
                    "id": "{:.0f}",
                    "prestamo_id": "{:.0f}",
                    "fecha_pago": lambda d: pd.to_datetime(d).strftime('%d-%m-%Y'),
                    "monto": "${:,.2f}"
                }).set_properties(**{'text-align': 'center'}))
    st.divider()

elif menu == "Reporte":
    st.markdown("## 📊 Reporte y Cronograma")
    df_prestamos = obtener_prestamos()
    if df_prestamos.empty:
        st.info("📌 No hay préstamos.")
    else:
        prestamo_sel = st.selectbox("Selecciona préstamo", df_prestamos['id'].astype(str) + " - " + df_prestamos['cliente'])
        prestamo_id = int(prestamo_sel.split(" - ")[0])
        df_prestamo = df_prestamos[df_prestamos['id'] == prestamo_id].iloc[0]

        cronograma = calcular_cronograma(
            df_prestamo['monto'],
            df_prestamo['tasa'],
            df_prestamo['plazo'],
            df_prestamo['frecuencia'],
            pd.to_datetime(df_prestamo['fecha_desembolso']).date()
        )
        pagos = obtener_pagos(prestamo_id)
        cron_estado = estado_cuotas(cronograma, pagos)

        # Formato condicional para colores
        def color_estado(row):
            if row['Estado'] == 'Vencida':
                return ['background-color: #f8d7da'] * len(row)
            else:
                return ['background-color: #d4edda'] * len(row)

        st.dataframe(cron_estado.style.format({
            "Periodo": "{:.0f}",
            "Fecha": lambda d: pd.to_datetime(d).strftime('%d-%m-%Y'),
            "Cuota": "${:,.2f}",
            "Interes": "${:,.2f}",
            "Amortizacion": "${:
