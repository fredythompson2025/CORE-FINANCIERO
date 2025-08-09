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

# ==============================
# Lógica de Cálculo
# ==============================
def calcular_cronograma(monto, tasa_anual, plazo_meses, frecuencia, fecha_desembolso):
    pagos_totales = int(plazo_meses * frecuencia / 12)
    tasa_periodo = tasa_anual / 100 / frecuencia
    if tasa_periodo == 0:
        cuota = monto / pagos_totales
    else:
        cuota = monto * (tasa_periodo / (1 - (1 + tasa_periodo) ** -pagos_totales))
    cronograma = []
    saldo = monto
    meses_por_pago = int(12 / frecuencia)

    for i in range(1, pagos_totales + 1):
        interes = saldo * tasa_periodo
        amortizacion = cuota - interes
        saldo = max(0, saldo - amortizacion)
        fecha_pago = fecha_desembolso + relativedelta(months=meses_por_pago * i)
        cronograma.append({
            "Periodo": i,
            "Fecha": fecha_pago,
            "Cuota": round(cuota, 2),
            "Interes": round(interes, 2),
            "Amortizacion": round(amortizacion, 2),
            "Saldo": round(saldo, 2)
        })
    return pd.DataFrame(cronograma)

def estado_cuotas(cronograma, pagos, dias_gracia=3):
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
    cronograma['Estado'] = cronograma.apply(
        lambda r: 'Vencida' if r['Fecha'] < (hoy - pd.Timedelta(days=dias_gracia)) and r['Pendiente'] > 0 else 'Al día',
        axis=1
    )
    return cronograma

# ==============================
# Exportación PDF
# ==============================
def exportar_pdf(df, cliente, prestamo_id):
    df_export = df.copy()
    df_export['Fecha'] = df_export['Fecha'].apply(lambda d: pd.to_datetime(d).strftime('%d-%m-%Y'))
    for col in ['Cuota', 'Interes', 'Amortizacion', 'Saldo', 'Pagado', 'Pendiente']:
        df_export[col] = df_export[col].apply(lambda x: f"${x:,.2f}")

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    flowables = [
        Paragraph(f"Cronograma de Pago - Préstamo #{prestamo_id}", styles['Title']),
        Paragraph(f"Cliente: {cliente}", styles['Normal']),
        Spacer(1, 12)
    ]
    data = [df_export.columns.to_list()]
    for _, row in df_export.iterrows():
        data.append([str(row[col]) if not pd.isna(row[col]) else '' for col in df_export.columns])
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

# ==============================
# Interfaz Streamlit
# ==============================
st.set_page_config("💰 Sistema Préstamos", layout="wide", page_icon="💸")
init_db()

st.markdown("<h1 style='text-align:center; color: darkblue;'>💰 Sistema de Gestión de Préstamos</h1>", unsafe_allow_html=True)
st.divider()

if "update_clientes" not in st.session_state:
    st.session_state.update_clientes = True
if "update_prestamos" not in st.session_state:
    st.session_state.update_prestamos = True

def recargar_clientes():
    st.session_state.update_clientes = True

def recargar_prestamos():
    st.session_state.update_prestamos = True

if st.session_state.update_clientes:
    df_clientes = obtener_clientes()
    st.session_state.df_clientes = df_clientes
    st.session_state.update_clientes = False
else:
    df_clientes = st.session_state.df_clientes

if st.session_state.update_prestamos:
    df_prestamos = obtener_prestamos()
    st.session_state.df_prestamos = df_prestamos
    st.session_state.update_prestamos = False
else:
    df_prestamos = st.session_state.df_prestamos

with st.sidebar:
    st.markdown("## 📋 Menú")
    menu = st.radio("", ["Clientes", "Préstamos", "Pagos", "Reporte"])

if menu == "Clientes":
    tabs = st.tabs(["Agregar", "Modificar", "Eliminar", "Buscar"])

    with tabs[0]:
        st.markdown("### ➕ Agregar Cliente")
        nombre = st.text_input("Nombre completo", key="agregar_nombre")
        identificacion = st.text_input("Identificación", key="agregar_id")
        direccion = st.text_input("Dirección", key="agregar_dir")
        telefono = st.text_input("Teléfono", key="agregar_tel")
        if st.button("Agregar Cliente"):
            if nombre.strip() == "":
                st.error("Debe ingresar un nombre")
            else:
                agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip())
                st.success(f"Cliente '{nombre.strip()}' agregado.")
                recargar_clientes()

    with tabs[1]:
        st.markdown("### ✏️ Modificar Cliente")
        if df_clientes.empty:
            st.info("No hay clientes para modificar")
        else:
            cliente_sel = st.selectbox("Selecciona cliente", df_clientes['nombre'], key="mod_cliente_select")
            cliente = df_clientes[df_clientes['nombre'] == cliente_sel].iloc[0]
            nombre_mod = st.text_input("Nombre", cliente['nombre'], key="mod_nombre")
            identificacion_mod = st.text_input("Identificación", cliente['identificacion'], key="mod_id")
            direccion_mod = st.text_input("Dirección", cliente['direccion'], key="mod_dir")
            telefono_mod = st.text_input("Teléfono", cliente['telefono'], key="mod_tel")
            if st.button("Modificar Cliente"):
                modificar_cliente(cliente['id'], nombre_mod.strip(), identificacion_mod.strip(), direccion_mod.strip(), telefono_mod.strip())
                st.success(f"Cliente '{nombre_mod.strip()}' modificado.")
                recargar_clientes()

    with tabs[2]:
        st.markdown("### 🗑️ Eliminar Cliente")
        if df_clientes.empty:
            st.info("No hay clientes para eliminar")
        else:
            cliente_sel = st.selectbox("Selecciona cliente para eliminar", df_clientes['nombre'], key="del_cliente_select")
            if st.button("Eliminar Cliente"):
                cliente = df_clientes[df_clientes['nombre'] == cliente_sel].iloc[0]
                eliminar_cliente(cliente['id'])
                st.success(f"Cliente '{cliente_sel}' eliminado.")
                recargar_clientes()

    with tabs[3]:
        st.markdown("### 📋 Reporte de Clientes")
        if df_clientes.empty:
            st.info("No hay clientes registrados.")
        else:
            st.dataframe(df_clientes.style.set_properties(**{'text-align': 'center'}))

elif menu == "Préstamos":
    st.markdown("## 🏦 Préstamos")
    if df_clientes.empty:
        st.info("📌 Agrega primero clientes.")
    else:
        col1, col2 = st.columns([2, 3])
        with col1:
            cliente_sel = st.selectbox("Cliente", df_clientes['nombre'], key="prestamo_cliente")
            monto = st.number_input("Monto", min_value=0.0, value=1000.0, step=100.0, format="%.2f", key="prestamo_monto")
            tasa = st.number_input("Tasa anual (%)", min_value=0.0, value=12.0, step=0.1, format="%.2f", key="prestamo_tasa")
            plazo = st.number_input("Plazo (meses)", min_value=1, value=12, key="prestamo_plazo")
            frecuencia = st.selectbox("Frecuencia de pagos por año", [12, 4, 2, 1], index=0, key="prestamo_frecuencia")
            fecha_desembolso = st.date_input("Fecha de desembolso", value=date.today(), key="prestamo_fecha")
            if st.button("Crear préstamo"):
                if monto <= 0 or tasa < 0:
                    st.error("Monto debe ser mayor que 0 y tasa no puede ser negativa.")
                else:
                    cliente_id = int(df_clientes[df_clientes['nombre'] == cliente_sel]['id'].values[0])
                    agregar_prestamo(cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso)
                    st.success(f"Préstamo creado para {cliente_sel}.")
                    recargar_prestamos()

        with col2:
            if df_prestamos.empty:
                st.info("No hay préstamos registrados.")
            else:
                st.markdown("### Préstamos existentes")
                st.dataframe(df_prestamos.style.format({
                    "monto": "${:,.2f}",
                    "tasa": "{:.2f}%",
                    "plazo": "{:.0f} meses",
                    "frecuencia": "{:.0f} pagos/año",
                    "fecha_desembolso": lambda d: pd.to_datetime(d).strftime('%d-%m-%Y')
                }).set_properties(**{'text-align': 'center'}))

elif menu == "Pagos":
    st.markdown("## 💵 Registrar Pagos")
    if df_prestamos.empty:
        st.info("📌 No hay préstamos.")
    else:
        prestamo_sel = st.selectbox("Selecciona préstamo", df_prestamos['id'].astype(str) + " - " + df_prestamos['cliente'])
        prestamo_id = int(prestamo_sel.split(" - ")[0])
        df_prestamo = df_prestamos[df_prestamos['id'] == prestamo_id].iloc[0]
        st.markdown(f"**Préstamo de {df_prestamo['cliente']}** - Monto: ${df_prestamo['monto']:.2f} | Tasa: {df_prestamo['tasa']:.2f}% | Plazo: {df_prestamo['plazo']} meses")

        fecha_pago = st.date_input("Fecha pago", value=date.today(), key="pago_fecha")
        monto_pago = st.number_input("Monto pago", min_value=0.0, value=0.0, step=10.0, format="%.2f", key="pago_monto")
        if st.button("Registrar pago"):
            if monto_pago <= 0:
                st.error("Monto debe ser mayor a cero")
            else:
                agregar_pago(prestamo_id, fecha_pago, monto_pago)
                st.success("Pago registrado.")

        pagos = obtener_pagos(prestamo_id)
        if pagos.empty:
            st.info("No hay pagos registrados para este préstamo.")
        else:
            st.markdown("### Pagos registrados")
            st.dataframe(pagos.style.format({
                "fecha_pago": lambda d: pd.to_datetime(d).strftime('%d-%m-%Y'),
                "monto": "${:,.2f}"
            }).set_properties(**{'text-align': 'center'}))

elif menu == "Reporte":
    st.markdown("## 📊 Reporte y Cronograma")
    if df_prestamos.empty:
        st.info("📌 No hay préstamos.")
    else:
        prestamo_sel = st.selectbox("Selecciona préstamo", df_prestamos['id'].astype(str) + " - " + df_prestamos['cliente'])
        prestamo_id = int(prestamo_sel.split(" - ")[0])
        df_prestamo = df_prestamos[df_prestamos['id'] == prestamo_id].iloc[0]

        if st.button("Generar cronograma"):
            cronograma = calcular_cronograma(
                df_prestamo['monto'],
                df_prestamo['tasa'],
                df_prestamo['plazo'],
                df_prestamo['frecuencia'],
                pd.to_datetime(df_prestamo['fecha_desembolso']).date()
            )
            pagos = obtener_pagos(prestamo_id)
            cron_estado = estado_cuotas(cronograma, pagos)

            st.dataframe(cron_estado.style.format({
                "Periodo": "{:.0f}",
                "Fecha": lambda d: pd.to_datetime(d).strftime('%d-%m-%Y'),
                "Cuota": "${:,.2f}",
                "Interes": "${:,.2f}",
                "Amortizacion": "${:,.2f}",
                "Saldo": "${:,.2f}",
                "Pagado": "${:,.2f}",
                "Pendiente": "${:,.2f}",
                "Estado": "{}"
            }).set_properties(**{'text-align': 'center'}))

            pdf_buffer = exportar_pdf(cron_estado, df_prestamo['cliente'], prestamo_id)
            st.download_button(
                label="📄 Descargar Cronograma PDF",
                data=pdf_buffer,
                file_name=f"Cronograma_Prestamo_{prestamo_id}.pdf",
                mime="application/pdf"
            )
