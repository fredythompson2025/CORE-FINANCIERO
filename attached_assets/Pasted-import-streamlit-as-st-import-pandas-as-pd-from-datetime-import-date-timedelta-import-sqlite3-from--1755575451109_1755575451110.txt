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
    try:
        cur.execute("INSERT INTO clientes (nombre, identificacion, direccion, telefono) VALUES (?,?,?,?)",
                    (nombre, identificacion, direccion, telefono))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
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
    df = pd.read_sql_query("SELECT * FROM pagos WHERE prestamo_id = ? ORDER BY fecha_pago", conn, params=[prestamo_id])
    conn.close()
    return df

# -- Amortización simple francés --
def calcular_cronograma(monto, tasa_anual, plazo_meses, frecuencia, fecha_desembolso):
    """
    Calcula el cronograma de pagos usando el método francés
    """
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
            "Cuota": round(cuota, 2),
            "Interes": round(interes, 2),
            "Amortizacion": round(amortizacion, 2),
            "Saldo": round(saldo, 2)
        })
    
    return pd.DataFrame(cronograma)

def estado_cuotas(cronograma, pagos):
    """
    Calcula el estado de las cuotas basado en los pagos realizados
    """
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
        lambda r: 'Vencida' if r['Fecha'] < hoy and r['Pendiente'] > 0 else 'Al día', 
        axis=1
    )
    
    return cronograma

# -- Exportar PDF --
def exportar_pdf(df, cliente, prestamo_id):
    """
    Genera un PDF con el cronograma de pagos
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    
    flowables = [
        Paragraph(f"Cronograma de Pago - Préstamo #{prestamo_id}", styles['Title']),
        Paragraph(f"Cliente: {cliente}", styles['Normal']),
        Spacer(1, 12)
    ]
    
    # Preparar datos para la tabla
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
            submitted = st.form_submit_button("➕ Agregar Cliente")
            
            if submitted:
                if nombre.strip() == "":
                    st.error("Debe ingresar un nombre")
                else:
                    if agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip()):
                        st.success(f"Cliente '{nombre.strip()}' agregado.")
                        st.rerun()
                    else:
                        st.error("Error: Ya existe un cliente con ese nombre.")

        df_clientes_actions = obtener_clientes()
        if not df_clientes_actions.empty:
            with st.form("form_modificar_cliente"):
                st.markdown("### ✏️ Modificar Cliente")
                cliente_mod_sel = st.selectbox("Selecciona cliente para modificar", df_clientes_actions['nombre'])
                cliente_mod = df_clientes_actions[df_clientes_actions['nombre'] == cliente_mod_sel].iloc[0]
                nombre_mod = st.text_input("Nombre", value=cliente_mod['nombre'], key="mod_nombre")
                identificacion_mod = st.text_input("Identificación", value=str(cliente_mod['identificacion'] or ""), key="mod_ident")
                direccion_mod = st.text_input("Dirección", value=str(cliente_mod['direccion'] or ""), key="mod_dir")
                telefono_mod = st.text_input("Teléfono", value=str(cliente_mod['telefono'] or ""), key="mod_tel")
                modificar_submitted = st.form_submit_button("💾 Modificar Cliente")
                
                if modificar_submitted:
                    modificar_cliente(cliente_mod['id'], nombre_mod.strip(), identificacion_mod.strip(), direccion_mod.strip(), telefono_mod.strip())
                    st.success(f"Cliente '{nombre_mod.strip()}' modificado.")
                    st.rerun()

            with st.form("form_eliminar_cliente"):
                st.markdown("### 🗑️ Eliminar Cliente")
                cliente_del_sel = st.selectbox("Selecciona cliente para eliminar", df_clientes_actions['nombre'], key="del_cliente")
                cliente_del = df_clientes_actions[df_clientes_actions['nombre'] == cliente_del_sel].iloc[0]
                eliminar_submitted = st.form_submit_button("🗑️ Eliminar Cliente", type="secondary")
                
                if eliminar_submitted:
                    eliminar_cliente(cliente_del['id'])
                    st.success(f"Cliente '{cliente_del_sel}' eliminado.")
                    st.rerun()

    with col2:
        st.markdown("### 📋 Clientes registrados")
        df_clientes = obtener_clientes()
        
        if df_clientes.empty:
            st.info("No hay clientes registrados. Agrega el primer cliente usando el formulario de la izquierda.")
        else:
            st.dataframe(
                df_clientes,
                use_container_width=True
            )

elif menu == "Préstamos":
    st.markdown("## 🏦 Préstamos")
    df_clientes = obtener_clientes()
    
    if df_clientes.empty:
        st.info("📌 Primero debes agregar clientes en la sección de Clientes.")
    else:
        col1, col2 = st.columns([2, 3])
        
        with col1:
            with st.form("form_prestamo"):
                st.markdown("### 🏦 Crear Préstamo")
                cliente_sel = st.selectbox("Cliente", df_clientes['nombre'])
                monto = st.number_input("Monto", min_value=0.0, value=1000.0, step=100.0, format="%.2f")
                tasa = st.number_input("Tasa anual (%)", min_value=0.0, value=12.0, step=0.1, format="%.2f")
                plazo = st.number_input("Plazo (meses)", min_value=1, value=12)
                frecuencia = st.selectbox("Frecuencia de pagos por año", [12, 4, 2, 1], index=0, 
                                        format_func=lambda x: f"{x} pagos/año ({'Mensual' if x==12 else 'Trimestral' if x==4 else 'Semestral' if x==2 else 'Anual'})")
                fecha_desembolso = st.date_input("Fecha de desembolso", value=date.today())
                submitted = st.form_submit_button("🏦 Crear préstamo")
                
                if submitted:
                    if monto <= 0:
                        st.error("El monto debe ser mayor a 0")
                    else:
                        cliente_id = int(df_clientes[df_clientes['nombre'] == cliente_sel]['id'].values[0])
                        agregar_prestamo(cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso)
                        st.success(f"Préstamo creado para {cliente_sel}.")
                        st.rerun()

        with col2:
            st.markdown("### 📋 Préstamos existentes")
            df_prestamos = obtener_prestamos()
            
            if df_prestamos.empty:
                st.info("No hay préstamos registrados. Crea el primer préstamo usando el formulario de la izquierda.")
            else:
                # Format the dataframe for better display
                df_display = df_prestamos.copy()
                df_display['monto'] = df_display['monto'].apply(lambda x: f"${x:,.2f}")
                df_display['tasa'] = df_display['tasa'].apply(lambda x: f"{x:.2f}%")
                df_display['plazo'] = df_display['plazo'].apply(lambda x: f"{x:.0f} meses")
                df_display['frecuencia'] = df_display['frecuencia'].apply(lambda x: f"{x:.0f} pagos/año")
                df_display['fecha_desembolso'] = pd.to_datetime(df_display['fecha_desembolso']).dt.strftime('%d-%m-%Y')
                
                st.dataframe(df_display, use_container_width=True)

elif menu == "Pagos":
    st.markdown("## 💵 Registrar Pagos")
    df_prestamos = obtener_prestamos()
    
    if df_prestamos.empty:
        st.info("📌 No hay préstamos registrados. Primero crea un préstamo en la sección de Préstamos.")
    else:
        prestamo_options = df_prestamos['id'].astype(str) + " - " + df_prestamos['cliente']
        prestamo_sel = st.selectbox("Selecciona préstamo", prestamo_options)
        prestamo_id = int(prestamo_sel.split(" - ")[0])
        df_prestamo = df_prestamos[df_prestamos['id'] == prestamo_id].iloc[0]
        
        st.markdown(f"**Préstamo de {df_prestamo['cliente']}** - Monto: ${df_prestamo['monto']:,.2f} | Tasa: {df_prestamo['tasa']:.2f}% | Plazo: {df_prestamo['plazo']:.0f} meses")
        
        col1, col2 = st.columns([2, 3])
        
        with col1:
            with st.form("form_pago"):
                st.markdown("### 💾 Registrar Pago")
                fecha_pago = st.date_input("Fecha pago", value=date.today())
                monto_pago = st.number_input("Monto pago", min_value=0.0, value=0.0, step=10.0, format="%.2f")
                submitted = st.form_submit_button("💾 Registrar pago")
                
                if submitted:
                    if monto_pago <= 0:
                        st.error("El monto del pago debe ser mayor a 0")
                    else:
                        agregar_pago(prestamo_id, fecha_pago, monto_pago)
                        st.success(f"Pago de ${monto_pago:.2f} registrado.")
                        st.rerun()

        with col2:
            st.markdown("### 📋 Cronograma y Estado")
            # Obtener cronograma y pagos
            cronograma = calcular_cronograma(
                df_prestamo['monto'], 
                df_prestamo['tasa'], 
                df_prestamo['plazo'], 
                df_prestamo['frecuencia'], 
                pd.to_datetime(df_prestamo['fecha_desembolso']).date()
            )
            pagos = obtener_pagos(prestamo_id)
            cronograma_estado = estado_cuotas(cronograma, pagos)
            
            # Format dates for display
            cronograma_display = cronograma_estado.copy()
            cronograma_display['Fecha'] = pd.to_datetime(cronograma_display['Fecha']).dt.strftime('%d-%m-%Y')
            
            st.dataframe(cronograma_display, use_container_width=True)
            
            # Mostrar resumen
            total_pagado = pagos['monto'].sum() if not pagos.empty else 0
            total_cuotas = cronograma['Cuota'].sum()
            pendiente = total_cuotas - total_pagado
            
            st.markdown("### 📊 Resumen")
            col_res1, col_res2, col_res3 = st.columns(3)
            with col_res1:
                st.metric("Total Pagado", f"${total_pagado:,.2f}")
            with col_res2:
                st.metric("Total Préstamo", f"${total_cuotas:,.2f}")
            with col_res3:
                st.metric("Pendiente", f"${pendiente:,.2f}")

elif menu == "Reporte":
    st.markdown("## 📊 Reportes")
    df_prestamos = obtener_prestamos()
    
    if df_prestamos.empty:
        st.info("📌 No hay préstamos para generar reportes.")
    else:
        prestamo_options = df_prestamos['id'].astype(str) + " - " + df_prestamos['cliente']
        prestamo_sel = st.selectbox("Selecciona préstamo para reporte", prestamo_options)
        prestamo_id = int(prestamo_sel.split(" - ")[0])
        df_prestamo = df_prestamos[df_prestamos['id'] == prestamo_id].iloc[0]
        
        st.markdown(f"### Reporte del Préstamo #{prestamo_id} - {df_prestamo['cliente']}")
        
        # Calcular cronograma y estado
        cronograma = calcular_cronograma(
            df_prestamo['monto'], 
            df_prestamo['tasa'], 
            df_prestamo['plazo'], 
            df_prestamo['frecuencia'], 
            pd.to_datetime(df_prestamo['fecha_desembolso']).date()
        )
        pagos = obtener_pagos(prestamo_id)
        cronograma_estado = estado_cuotas(cronograma, pagos)
        
        # Mostrar cronograma
        cronograma_display = cronograma_estado.copy()
        cronograma_display['Fecha'] = pd.to_datetime(cronograma_display['Fecha']).dt.strftime('%d-%m-%Y')
        
        st.dataframe(cronograma_display, use_container_width=True)
        
        # Botón para descargar PDF
        if st.button("📄 Descargar PDF"):
            pdf_buffer = exportar_pdf(cronograma_display, df_prestamo['cliente'], prestamo_id)
            st.download_button(
                label="💾 Descargar Cronograma PDF",
                data=pdf_buffer,
                file_name=f"cronograma_prestamo_{prestamo_id}_{df_prestamo['cliente'].replace(' ', '_')}.pdf",
                mime="application/pdf"
            )
        
        # Estadísticas del préstamo
        st.markdown("### 📈 Estadísticas del Préstamo")
        
        total_pagado = pagos['monto'].sum() if not pagos.empty else 0
        total_cuotas = cronograma['Cuota'].sum()
        total_interes = cronograma['Interes'].sum()
        total_amortizacion = cronograma['Amortizacion'].sum()
        pendiente = total_cuotas - total_pagado
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Monto Original", f"${df_prestamo['monto']:,.2f}")
            st.metric("Total Pagado", f"${total_pagado:,.2f}")
        
        with col2:
            st.metric("Total Intereses", f"${total_interes:,.2f}")
            st.metric("Total Amortización", f"${total_amortizacion:,.2f}")
        
        with col3:
            st.metric("Total a Pagar", f"${total_cuotas:,.2f}")
            st.metric("Pendiente", f"${pendiente:,.2f}")
        
        with col4:
            progreso = (total_pagado / total_cuotas) * 100 if total_cuotas > 0 else 0
            st.metric("Progreso", f"{progreso:.1f}%")
            
            # Cuotas vencidas
            cuotas_vencidas = len(cronograma_estado[cronograma_estado['Estado'] == 'Vencida'])
            st.metric("Cuotas Vencidas", cuotas_vencidas)
        
        # Historial de pagos
        if not pagos.empty:
            st.markdown("### 💰 Historial de Pagos")
            pagos_display = pagos.copy()
            pagos_display['fecha_pago'] = pd.to_datetime(pagos_display['fecha_pago']).dt.strftime('%d-%m-%Y')
            pagos_display['monto'] = pagos_display['monto'].apply(lambda x: f"${x:,.2f}")
            st.dataframe(pagos_display, use_container_width=True)

st.divider()
st.markdown("<p style='text-align:center; color: gray;'>💰 Sistema de Gestión de Préstamos - Versión 1.0</p>", unsafe_allow_html=True)
