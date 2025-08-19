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

def obtener_prestamo_detalle(prestamo_id):
    conn = get_conn()
    df = pd.read_sql_query("""
    SELECT p.*, c.nombre as cliente_nombre
    FROM prestamos p JOIN clientes c ON p.cliente_id = c.id
    WHERE p.id = ?
    """, conn, params=[prestamo_id])
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

def obtener_todos_pagos():
    conn = get_conn()
    df = pd.read_sql_query("""
    SELECT pag.*, p.monto as monto_prestamo, c.nombre as cliente
    FROM pagos pag 
    JOIN prestamos p ON pag.prestamo_id = p.id
    JOIN clientes c ON p.cliente_id = c.id
    ORDER BY pag.fecha_pago DESC
    """, conn)
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
                    identificacion_str = identificacion_mod.strip() if identificacion_mod and identificacion_mod.strip() else ""
                    direccion_str = direccion_mod.strip() if direccion_mod and direccion_mod.strip() else ""
                    telefono_str = telefono_mod.strip() if telefono_mod and telefono_mod.strip() else ""
                    modificar_cliente(cliente_mod['id'], nombre_mod.strip(), identificacion_str, direccion_str, telefono_str)
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
                        cliente_row = df_clientes[df_clientes['nombre'] == cliente_sel]
                        cliente_id = int(cliente_row['id'].iloc[0])
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
                df_display['tasa'] = df_display['tasa'].apply(lambda x: f"{x}%")
                df_display['frecuencia'] = df_display['frecuencia'].apply(
                    lambda x: 'Mensual' if x==12 else 'Trimestral' if x==4 else 'Semestral' if x==2 else 'Anual'
                )
                
                st.dataframe(
                    df_display,
                    use_container_width=True,
                    column_config={
                        "id": "ID",
                        "cliente": "Cliente",
                        "monto": "Monto",
                        "tasa": "Tasa",
                        "plazo": "Plazo (meses)",
                        "frecuencia": "Frecuencia",
                        "fecha_desembolso": "Fecha Desembolso"
                    }
                )

elif menu == "Pagos":
    st.markdown("## 💵 Pagos")
    df_prestamos = obtener_prestamos()
    
    if df_prestamos.empty:
        st.info("📌 Primero debes crear préstamos en la sección de Préstamos.")
    else:
        col1, col2 = st.columns([2, 3])
        
        with col1:
            with st.form("form_pago"):
                st.markdown("### 💵 Registrar Pago")
                prestamo_options = [f"#{row['id']} - {row['cliente']} (${row['monto']:,.2f})" 
                                  for _, row in df_prestamos.iterrows()]
                prestamo_sel = st.selectbox("Préstamo", prestamo_options)
                prestamo_id = int(prestamo_sel.split('#')[1].split(' - ')[0])
                
                fecha_pago = st.date_input("Fecha de pago", value=date.today())
                monto_pago = st.number_input("Monto del pago", min_value=0.0, value=100.0, step=10.0, format="%.2f")
                submitted = st.form_submit_button("💵 Registrar pago")
                
                if submitted:
                    if monto_pago <= 0:
                        st.error("El monto del pago debe ser mayor a 0")
                    else:
                        agregar_pago(prestamo_id, fecha_pago, monto_pago)
                        st.success(f"Pago de ${monto_pago:,.2f} registrado para el préstamo #{prestamo_id}.")
                        st.rerun()

        with col2:
            st.markdown("### 📋 Historial de Pagos")
            df_todos_pagos = obtener_todos_pagos()
            
            if df_todos_pagos.empty:
                st.info("No hay pagos registrados. Registra el primer pago usando el formulario de la izquierda.")
            else:
                df_display_pagos = df_todos_pagos.copy()
                df_display_pagos['monto'] = df_display_pagos['monto'].apply(lambda x: f"${x:,.2f}")
                
                st.dataframe(
                    df_display_pagos[['prestamo_id', 'cliente', 'fecha_pago', 'monto']],
                    use_container_width=True,
                    column_config={
                        "prestamo_id": "Préstamo ID",
                        "cliente": "Cliente",
                        "fecha_pago": "Fecha Pago",
                        "monto": "Monto"
                    }
                )

elif menu == "Reporte":
    st.markdown("## 📊 Reportes y Cronogramas")
    df_prestamos = obtener_prestamos()
    
    if df_prestamos.empty:
        st.info("📌 No hay préstamos para generar reportes. Crea préstamos primero.")
    else:
        # Selector de préstamo
        prestamo_options = [f"#{row['id']} - {row['cliente']} (${row['monto']:,.2f})" 
                          for _, row in df_prestamos.iterrows()]
        prestamo_sel = st.selectbox("Selecciona un préstamo para ver su cronograma", prestamo_options)
        prestamo_id = int(prestamo_sel.split('#')[1].split(' - ')[0])
        
        # Obtener detalles del préstamo
        df_prestamo_detalle = obtener_prestamo_detalle(prestamo_id)
        if not df_prestamo_detalle.empty:
            prestamo = df_prestamo_detalle.iloc[0]
            
            # Mostrar información del préstamo
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Cliente", prestamo['cliente_nombre'])
            with col2:
                st.metric("Monto", f"${prestamo['monto']:,.2f}")
            with col3:
                st.metric("Tasa Anual", f"{prestamo['tasa']}%")
            with col4:
                st.metric("Plazo", f"{prestamo['plazo']} meses")
            
            st.divider()
            
            # Calcular cronograma
            cronograma = calcular_cronograma(
                prestamo['monto'], 
                prestamo['tasa'], 
                prestamo['plazo'], 
                prestamo['frecuencia'],
                prestamo['fecha_desembolso']
            )
            
            # Obtener pagos realizados
            pagos_realizados = obtener_pagos(prestamo_id)
            
            # Calcular estado de cuotas
            cronograma_con_estado = estado_cuotas(cronograma, pagos_realizados)
            
            # Mostrar estadísticas
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                cuotas_pagadas = len(cronograma_con_estado[cronograma_con_estado['Pendiente'] == 0])
                st.metric("Cuotas Pagadas", cuotas_pagadas)
            with col2:
                cuotas_vencidas = len(cronograma_con_estado[cronograma_con_estado['Estado'] == 'Vencida'])
                st.metric("Cuotas Vencidas", cuotas_vencidas)
            with col3:
                total_pagado = pagos_realizados['monto'].sum() if not pagos_realizados.empty else 0
                st.metric("Total Pagado", f"${total_pagado:,.2f}")
            with col4:
                saldo_pendiente = cronograma_con_estado['Pendiente'].sum()
                st.metric("Saldo Pendiente", f"${saldo_pendiente:,.2f}")
            
            st.divider()
            
            # Mostrar cronograma con estado
            st.markdown("### 📅 Cronograma de Pagos")
            
            # Aplicar colores según el estado
            def color_estado(val):
                if val == 'Vencida':
                    return 'background-color: #ffcccc'
                elif val == 'Al día':
                    return 'background-color: #ccffcc'
                return ''
            
            df_display_cronograma = cronograma_con_estado.copy()
            df_display_cronograma['Cuota'] = df_display_cronograma['Cuota'].apply(lambda x: f"${x:,.2f}")
            df_display_cronograma['Interes'] = df_display_cronograma['Interes'].apply(lambda x: f"${x:,.2f}")
            df_display_cronograma['Amortizacion'] = df_display_cronograma['Amortizacion'].apply(lambda x: f"${x:,.2f}")
            df_display_cronograma['Saldo'] = df_display_cronograma['Saldo'].apply(lambda x: f"${x:,.2f}")
            df_display_cronograma['Pagado'] = df_display_cronograma['Pagado'].apply(lambda x: f"${x:,.2f}")
            df_display_cronograma['Pendiente'] = df_display_cronograma['Pendiente'].apply(lambda x: f"${x:,.2f}")
            
            # Mostrar tabla con estilos
            styled_df = df_display_cronograma.style.applymap(color_estado, subset=['Estado'])
            st.dataframe(styled_df, use_container_width=True)
            
            # Botón para exportar PDF
            st.divider()
            col1, col2, col3 = st.columns([1, 1, 1])
            with col2:
                if st.button("📄 Exportar Cronograma a PDF", use_container_width=True):
                    pdf_buffer = exportar_pdf(cronograma_con_estado, prestamo['cliente_nombre'], prestamo_id)
                    st.download_button(
                        label="⬇️ Descargar PDF",
                        data=pdf_buffer.getvalue(),
                        file_name=f"cronograma_prestamo_{prestamo_id}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
            
            # Resumen de pagos realizados
            if not pagos_realizados.empty:
                st.divider()
                st.markdown("### 💵 Historial de Pagos Realizados")
                df_pagos_display = pagos_realizados.copy()
                df_pagos_display['monto'] = df_pagos_display['monto'].apply(lambda x: f"${x:,.2f}")
                st.dataframe(
                    df_pagos_display,
                    use_container_width=True,
                    column_config={
                        "id": "ID Pago",
                        "prestamo_id": "ID Préstamo",
                        "fecha_pago": "Fecha Pago",
                        "monto": "Monto"
                    }
                )

# Footer
st.divider()
st.markdown("<p style='text-align:center; color: gray;'>💰 Sistema de Gestión de Préstamos - Desarrollado con Streamlit</p>", unsafe_allow_html=True)
