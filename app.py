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
        aval_nombre TEXT,
        aval_identificacion TEXT,
        aval_telefono TEXT,
        FOREIGN KEY(cliente_id) REFERENCES clientes(id)
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prestamo_id INTEGER,
        fecha_pago DATE,
        monto REAL,
        tipo_abono TEXT DEFAULT 'ambos',
        monto_capital REAL DEFAULT 0,
        monto_interes REAL DEFAULT 0,
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

def agregar_prestamo(cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso, aval_nombre="", aval_identificacion="", aval_telefono=""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO prestamos (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso, aval_nombre, aval_identificacion, aval_telefono) VALUES (?,?,?,?,?,?,?,?,?)",
                (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso, aval_nombre, aval_identificacion, aval_telefono))
    conn.commit()
    conn.close()

def obtener_prestamos():
    conn = get_conn()
    df = pd.read_sql_query("""
    SELECT p.id, c.nombre as cliente, p.monto, p.tasa, p.plazo, p.frecuencia, p.fecha_desembolso, 
           p.aval_nombre, p.aval_identificacion, p.aval_telefono
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

def agregar_pago(prestamo_id, fecha_pago, monto, tipo_abono="ambos", monto_capital=0, monto_interes=0):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO pagos (prestamo_id, fecha_pago, monto, tipo_abono, monto_capital, monto_interes) VALUES (?,?,?,?,?,?)",
                (prestamo_id, fecha_pago, monto, tipo_abono, monto_capital, monto_interes))
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

def obtener_resumen_todos_clientes():
    """
    Obtiene un resumen completo de todos los clientes con sus préstamos, pagos y estado de mora
    """
    conn = get_conn()
    df = pd.read_sql_query("""
    SELECT 
        c.id as cliente_id,
        c.nombre as cliente,
        c.identificacion,
        c.telefono,
        p.id as prestamo_id,
        p.monto as monto_prestamo,
        p.tasa,
        p.plazo,
        p.frecuencia,
        p.fecha_desembolso,
        COALESCE(SUM(pag.monto), 0) as total_pagado
    FROM clientes c
    LEFT JOIN prestamos p ON c.id = p.cliente_id
    LEFT JOIN pagos pag ON p.id = pag.prestamo_id
    GROUP BY c.id, c.nombre, c.identificacion, c.telefono, p.id, p.monto, p.tasa, p.plazo, p.frecuencia, p.fecha_desembolso
    ORDER BY c.nombre, p.id
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
    hoy = date.today()
    
    def determinar_estado(row):
        fecha_vencimiento = row['Fecha']
        if isinstance(fecha_vencimiento, pd.Timestamp):
            fecha_vencimiento = fecha_vencimiento.date()
        return 'Vencida' if fecha_vencimiento < hoy and row['Pendiente'] > 0 else 'Al día'
    
    cronograma['Estado'] = cronograma.apply(determinar_estado, axis=1)
    
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
    st.markdown("## 👥 Gestión de Clientes")
    
    # Pestañas para las diferentes acciones
    tab1, tab2, tab3 = st.tabs(["➕ Agregar Cliente", "✏️ Modificar Cliente", "🗑️ Eliminar Cliente"])
    
    # Obtener clientes una sola vez para usar en todas las pestañas
    df_clientes = obtener_clientes()
    
    with tab1:
        st.markdown("### ➕ Agregar Nuevo Cliente")
        with st.form("form_cliente"):
            col1, col2 = st.columns(2)
            with col1:
                nombre = st.text_input("Nombre completo", placeholder="Ej: Juan Pérez")
                identificacion = st.text_input("Identificación", placeholder="Ej: 12345678")
            with col2:
                direccion = st.text_input("Dirección", placeholder="Ej: Calle 123 #45-67")
                telefono = st.text_input("Teléfono", placeholder="Ej: +57 300 123 4567")
            
            submitted = st.form_submit_button("➕ Agregar Cliente", use_container_width=True)
            
            if submitted:
                if nombre.strip() == "":
                    st.error("Debe ingresar un nombre")
                else:
                    if agregar_cliente(nombre.strip(), identificacion.strip(), direccion.strip(), telefono.strip()):
                        st.success(f"Cliente '{nombre.strip()}' agregado exitosamente.")
                        st.rerun()
                    else:
                        st.error("Error: Ya existe un cliente con ese nombre.")

    with tab2:
        st.markdown("### ✏️ Modificar Cliente Existente")
        if df_clientes.empty:
            st.info("No hay clientes registrados para modificar. Agrega clientes primero.")
        else:
            with st.form("form_modificar_cliente"):
                cliente_mod_sel = st.selectbox("Selecciona el cliente a modificar", df_clientes['nombre'])
                cliente_mod = df_clientes[df_clientes['nombre'] == cliente_mod_sel].iloc[0]
                
                col1, col2 = st.columns(2)
                with col1:
                    nombre_mod = st.text_input("Nombre", value=cliente_mod['nombre'], key="mod_nombre")
                    identificacion_mod = st.text_input("Identificación", value=str(cliente_mod['identificacion'] or ""), key="mod_ident")
                with col2:
                    direccion_mod = st.text_input("Dirección", value=str(cliente_mod['direccion'] or ""), key="mod_dir")
                    telefono_mod = st.text_input("Teléfono", value=str(cliente_mod['telefono'] or ""), key="mod_tel")
                
                modificar_submitted = st.form_submit_button("💾 Guardar Cambios", use_container_width=True)
                
                if modificar_submitted:
                    identificacion_str = identificacion_mod.strip() if identificacion_mod and identificacion_mod.strip() else ""
                    direccion_str = direccion_mod.strip() if direccion_mod and direccion_mod.strip() else ""
                    telefono_str = telefono_mod.strip() if telefono_mod and telefono_mod.strip() else ""
                    modificar_cliente(cliente_mod['id'], nombre_mod.strip(), identificacion_str, direccion_str, telefono_str)
                    st.success(f"Cliente '{nombre_mod.strip()}' modificado exitosamente.")
                    st.rerun()

    with tab3:
        st.markdown("### 🗑️ Eliminar Cliente")
        if df_clientes.empty:
            st.info("No hay clientes registrados para eliminar.")
        else:
            with st.form("form_eliminar_cliente"):
                cliente_del_sel = st.selectbox("Selecciona el cliente a eliminar", df_clientes['nombre'], key="del_cliente")
                cliente_del = df_clientes[df_clientes['nombre'] == cliente_del_sel].iloc[0]
                
                st.warning(f"⚠️ Esta acción eliminará permanentemente al cliente: **{cliente_del_sel}**")
                st.write("**Información del cliente:**")
                st.write(f"- **ID:** {cliente_del['id']}")
                st.write(f"- **Identificación:** {cliente_del['identificacion'] or 'No especificada'}")
                st.write(f"- **Dirección:** {cliente_del['direccion'] or 'No especificada'}")
                st.write(f"- **Teléfono:** {cliente_del['telefono'] or 'No especificado'}")
                
                col1, col2, col3 = st.columns([1, 1, 1])
                with col2:
                    eliminar_submitted = st.form_submit_button("🗑️ Confirmar Eliminación", type="secondary", use_container_width=True)
                
                if eliminar_submitted:
                    eliminar_cliente(cliente_del['id'])
                    st.success(f"Cliente '{cliente_del_sel}' eliminado exitosamente.")
                    st.rerun()
    
    # Mostrar tabla de clientes registrados
    st.divider()
    st.markdown("### 📋 Lista de Clientes Registrados")
    
    if df_clientes.empty:
        st.info("No hay clientes registrados. Usa la pestaña 'Agregar Cliente' para comenzar.")
    else:
        # Mostrar estadísticas
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Clientes", len(df_clientes))
        with col2:
            clientes_con_identificacion = len(df_clientes[df_clientes['identificacion'].notna() & (df_clientes['identificacion'] != "")])
            st.metric("Con Identificación", clientes_con_identificacion)
        with col3:
            clientes_con_telefono = len(df_clientes[df_clientes['telefono'].notna() & (df_clientes['telefono'] != "")])
            st.metric("Con Teléfono", clientes_con_telefono)
        with col4:
            clientes_con_direccion = len(df_clientes[df_clientes['direccion'].notna() & (df_clientes['direccion'] != "")])
            st.metric("Con Dirección", clientes_con_direccion)
        
        # Tabla de clientes
        st.dataframe(
            df_clientes,
            use_container_width=True,
            column_config={
                "id": "ID",
                "nombre": "Nombre Completo",
                "identificacion": "Identificación",
                "direccion": "Dirección",
                "telefono": "Teléfono"
            }
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
                
                # Información básica del préstamo
                col1, col2 = st.columns(2)
                with col1:
                    cliente_sel = st.selectbox("Cliente", df_clientes['nombre'])
                    monto = st.number_input("Monto", min_value=0.0, value=1000.0, step=100.0, format="%.2f")
                    tasa = st.number_input("Tasa anual (%)", min_value=0.0, value=12.0, step=0.1, format="%.2f")
                
                with col2:
                    plazo = st.number_input("Plazo (meses)", min_value=1, value=12)
                    frecuencia = st.selectbox("Frecuencia de pagos por año", [12, 4, 2, 1], index=0, 
                                            format_func=lambda x: f"{x} pagos/año ({'Mensual' if x==12 else 'Trimestral' if x==4 else 'Semestral' if x==2 else 'Anual'})")
                    fecha_desembolso = st.date_input("Fecha de desembolso", value=date.today())
                
                # Sección de aval
                st.divider()
                st.markdown("#### 👥 Información del Aval (Opcional)")
                tiene_aval = st.checkbox("¿Este préstamo requiere aval?")
                
                aval_nombre = ""
                aval_identificacion = ""
                aval_telefono = ""
                
                if tiene_aval:
                    col1, col2 = st.columns(2)
                    with col1:
                        aval_nombre = st.text_input("Nombre completo del aval", placeholder="Ej: María García")
                        aval_identificacion = st.text_input("Identificación del aval", placeholder="Ej: 87654321")
                    with col2:
                        aval_telefono = st.text_input("Teléfono del aval", placeholder="Ej: +57 300 987 6543")
                        st.info("💡 El aval es quien garantiza el pago del préstamo en caso de incumplimiento.")
                
                submitted = st.form_submit_button("🏦 Crear préstamo", use_container_width=True)
                
                if submitted:
                    if monto <= 0:
                        st.error("El monto debe ser mayor a 0")
                    elif tiene_aval and not aval_nombre.strip():
                        st.error("Si requiere aval, debe ingresar el nombre del aval")
                    else:
                        cliente_row = df_clientes[df_clientes['nombre'] == cliente_sel]
                        cliente_id = int(cliente_row['id'].iloc[0])
                        
                        agregar_prestamo(
                            cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso,
                            aval_nombre.strip() if tiene_aval else "",
                            aval_identificacion.strip() if tiene_aval else "",
                            aval_telefono.strip() if tiene_aval else ""
                        )
                        
                        aval_info = f" con aval: {aval_nombre}" if tiene_aval else " sin aval"
                        st.success(f"Préstamo creado para {cliente_sel}{aval_info}.")
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
                df_display['tiene_aval'] = df_display['aval_nombre'].apply(
                    lambda x: "✅ Sí" if x and str(x).strip() else "❌ No"
                )
                
                st.dataframe(
                    df_display[['id', 'cliente', 'monto', 'tasa', 'plazo', 'frecuencia', 'fecha_desembolso', 'tiene_aval']],
                    use_container_width=True,
                    column_config={
                        "id": "ID",
                        "cliente": "Cliente",
                        "monto": "Monto",
                        "tasa": "Tasa",
                        "plazo": "Plazo (meses)",
                        "frecuencia": "Frecuencia",
                        "fecha_desembolso": "Fecha Desembolso",
                        "tiene_aval": "Aval"
                    }
                )
                
                # Mostrar información detallada del aval si existe
                st.markdown("#### 👥 Información de Avales")
                prestamos_con_aval = df_prestamos[df_prestamos['aval_nombre'].notna() & (df_prestamos['aval_nombre'] != "")]
                if not prestamos_con_aval.empty:
                    df_avales = prestamos_con_aval[['id', 'cliente', 'aval_nombre', 'aval_identificacion', 'aval_telefono']].copy()
                    st.dataframe(
                        df_avales,
                        use_container_width=True,
                        column_config={
                            "id": "Préstamo ID",
                            "cliente": "Cliente",
                            "aval_nombre": "Nombre del Aval",
                            "aval_identificacion": "Identificación",
                            "aval_telefono": "Teléfono"
                        }
                    )
                else:
                    st.info("No hay préstamos con aval registrados.")

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
                
                # Selección de préstamo
                prestamo_options = [f"#{row['id']} - {row['cliente']} (${row['monto']:,.2f})" 
                                  for _, row in df_prestamos.iterrows()]
                prestamo_sel = st.selectbox("Préstamo", prestamo_options)
                prestamo_id = int(prestamo_sel.split('#')[1].split(' - ')[0])
                
                # Información básica del pago
                col1, col2 = st.columns(2)
                with col1:
                    fecha_pago = st.date_input("Fecha de pago", value=date.today())
                    monto_pago = st.number_input("Monto total del pago", min_value=0.0, value=100.0, step=10.0, format="%.2f")
                
                with col2:
                    tipo_abono = st.selectbox("Tipo de abono", 
                                            ["ambos", "capital", "interes"],
                                            format_func=lambda x: {
                                                "ambos": "💰 Capital e Interés (Normal)",
                                                "capital": "🏠 Solo Capital",
                                                "interes": "📈 Solo Interés"
                                            }[x])
                
                # Desglose manual si el usuario lo desea
                st.divider()
                st.markdown("#### 📊 Desglose del Pago")
                
                if tipo_abono == "ambos":
                    st.info("💡 Se aplicará automáticamente: primero a interés, luego a capital")
                    desglose_manual = st.checkbox("¿Deseas especificar el desglose manualmente?")
                    
                    monto_capital = 0
                    monto_interes = 0
                    
                    if desglose_manual:
                        col1, col2 = st.columns(2)
                        with col1:
                            monto_interes = st.number_input("Monto para interés", min_value=0.0, value=0.0, step=10.0, format="%.2f")
                        with col2:
                            monto_capital = st.number_input("Monto para capital", min_value=0.0, value=0.0, step=10.0, format="%.2f")
                        
                        if monto_interes + monto_capital != monto_pago and (monto_interes > 0 or monto_capital > 0):
                            diferencia = monto_pago - (monto_interes + monto_capital)
                            if diferencia > 0:
                                st.warning(f"⚠️ Faltan ${diferencia:,.2f} por asignar")
                            else:
                                st.warning(f"⚠️ Hay ${abs(diferencia):,.2f} de exceso en el desglose")
                
                elif tipo_abono == "capital":
                    st.info("💡 Todo el pago se aplicará únicamente al capital del préstamo")
                    monto_capital = monto_pago
                    monto_interes = 0
                
                else:  # tipo_abono == "interes"
                    st.info("💡 Todo el pago se aplicará únicamente a los intereses del préstamo")
                    monto_capital = 0
                    monto_interes = monto_pago
                
                submitted = st.form_submit_button("💵 Registrar pago", use_container_width=True)
                
                if submitted:
                    if monto_pago <= 0:
                        st.error("El monto del pago debe ser mayor a 0")
                    elif tipo_abono == "ambos" and desglose_manual and (monto_interes + monto_capital != monto_pago):
                        st.error("El desglose manual debe sumar exactamente el monto total del pago")
                    else:
                        # Si es "ambos" sin desglose manual, usar el monto total
                        if tipo_abono == "ambos" and not desglose_manual:
                            monto_capital = 0
                            monto_interes = 0
                        
                        agregar_pago(prestamo_id, fecha_pago, monto_pago, tipo_abono, monto_capital, monto_interes)
                        
                        # Mensaje de confirmación detallado
                        if tipo_abono == "ambos":
                            if desglose_manual:
                                st.success(f"Pago registrado: ${monto_pago:,.2f} (Interés: ${monto_interes:,.2f}, Capital: ${monto_capital:,.2f})")
                            else:
                                st.success(f"Pago registrado: ${monto_pago:,.2f} (Se aplicará automáticamente)")
                        elif tipo_abono == "capital":
                            st.success(f"Pago a capital registrado: ${monto_pago:,.2f}")
                        else:
                            st.success(f"Pago a interés registrado: ${monto_pago:,.2f}")
                        
                        st.rerun()

        with col2:
            st.markdown("### 📋 Historial de Pagos")
            df_todos_pagos = obtener_todos_pagos()
            
            if df_todos_pagos.empty:
                st.info("No hay pagos registrados. Registra el primer pago usando el formulario de la izquierda.")
            else:
                df_display_pagos = df_todos_pagos.copy()
                df_display_pagos['monto'] = df_display_pagos['monto'].apply(lambda x: f"${x:,.2f}")
                
                # Agregar información del tipo de abono si existe
                if 'tipo_abono' in df_display_pagos.columns:
                    df_display_pagos['tipo_abono_formatted'] = df_display_pagos['tipo_abono'].apply(
                        lambda x: {
                            'ambos': '💰 Capital + Interés',
                            'capital': '🏠 Solo Capital', 
                            'interes': '📈 Solo Interés'
                        }.get(str(x), '💰 Capital + Interés')
                    )
                    
                    columnas_mostrar = ['prestamo_id', 'cliente', 'fecha_pago', 'monto', 'tipo_abono_formatted']
                    column_config = {
                        "prestamo_id": "Préstamo ID",
                        "cliente": "Cliente", 
                        "fecha_pago": "Fecha Pago",
                        "monto": "Monto",
                        "tipo_abono_formatted": "Tipo de Abono"
                    }
                else:
                    columnas_mostrar = ['prestamo_id', 'cliente', 'fecha_pago', 'monto']
                    column_config = {
                        "prestamo_id": "Préstamo ID",
                        "cliente": "Cliente",
                        "fecha_pago": "Fecha Pago",
                        "monto": "Monto"
                    }
                
                st.dataframe(
                    df_display_pagos[columnas_mostrar],
                    use_container_width=True,
                    column_config=column_config
                )

elif menu == "Reporte":
    st.markdown("## 📊 Reportes y Estado de Cartera")
    
    # Pestañas para diferentes tipos de reportes
    tab1, tab2 = st.tabs(["📋 Resumen General", "📅 Cronograma Individual"])
    
    with tab1:
        st.markdown("### 📋 Resumen de Todos los Clientes")
        
        df_resumen = obtener_resumen_todos_clientes()
        
        if df_resumen.empty:
            st.info("📌 No hay préstamos registrados para generar reportes.")
        else:
            # Calcular resumen general
            resumen_general = []
            
            for _, row in df_resumen.iterrows():
                if pd.notna(row['prestamo_id']):  # Solo si tiene préstamos
                    # Calcular cronograma para este préstamo
                    cronograma = calcular_cronograma(
                        row['monto_prestamo'], 
                        row['tasa'], 
                        row['plazo'], 
                        row['frecuencia'],
                        row['fecha_desembolso']
                    )
                    
                    # Obtener pagos para este préstamo
                    pagos = obtener_pagos(row['prestamo_id'])
                    
                    # Calcular estado
                    cronograma_con_estado = estado_cuotas(cronograma, pagos)
                    
                    # Calcular métricas
                    total_prestamo = row['monto_prestamo']
                    total_pagado = row['total_pagado']
                    saldo_pendiente = cronograma_con_estado['Pendiente'].sum()
                    cuotas_vencidas = len(cronograma_con_estado[cronograma_con_estado['Estado'] == 'Vencida'])
                    total_cuotas = len(cronograma_con_estado)
                    cuotas_pagadas = len(cronograma_con_estado[cronograma_con_estado['Pendiente'] == 0])
                    
                    # Determinar estado de mora
                    estado_mora = "En Mora" if cuotas_vencidas > 0 else "Al Día"
                    
                    resumen_general.append({
                        'Cliente': row['cliente'],
                        'Identificación': row['identificacion'] or 'No especificada',
                        'Teléfono': row['telefono'] or 'No especificado',
                        'Préstamo ID': row['prestamo_id'],
                        'Monto Prestado': total_prestamo,
                        'Total Pagado': total_pagado,
                        'Saldo Pendiente': saldo_pendiente,
                        'Cuotas Pagadas': f"{cuotas_pagadas}/{total_cuotas}",
                        'Cuotas Vencidas': cuotas_vencidas,
                        'Estado': estado_mora,
                        'Porcentaje Pagado': (total_pagado / total_prestamo * 100) if total_prestamo > 0 else 0
                    })
            
            if resumen_general:
                df_resumen_final = pd.DataFrame(resumen_general)
                
                # Mostrar estadísticas generales
                st.markdown("#### 📊 Estadísticas Generales")
                col1, col2, col3, col4, col5 = st.columns(5)
                
                with col1:
                    total_clientes = len(df_resumen_final)
                    st.metric("Total Clientes", total_clientes)
                
                with col2:
                    clientes_al_dia = len(df_resumen_final[df_resumen_final['Estado'] == 'Al Día'])
                    st.metric("Clientes Al Día", clientes_al_dia)
                
                with col3:
                    clientes_mora = len(df_resumen_final[df_resumen_final['Estado'] == 'En Mora'])
                    st.metric("Clientes En Mora", clientes_mora)
                
                with col4:
                    total_prestado = df_resumen_final['Monto Prestado'].sum()
                    st.metric("Total Prestado", f"${total_prestado:,.2f}")
                
                with col5:
                    total_recaudado = df_resumen_final['Total Pagado'].sum()
                    st.metric("Total Recaudado", f"${total_recaudado:,.2f}")
                
                st.divider()
                
                # Tabla de resumen con colores
                st.markdown("#### 📋 Detalle por Cliente")
                
                def color_estado_mora(val):
                    if val == 'En Mora':
                        return 'background-color: #ffcccc'
                    elif val == 'Al Día':
                        return 'background-color: #ccffcc'
                    return ''
                
                # Formatear números para mostrar
                df_display = df_resumen_final.copy()
                df_display['Monto Prestado'] = df_display['Monto Prestado'].apply(lambda x: f"${x:,.2f}")
                df_display['Total Pagado'] = df_display['Total Pagado'].apply(lambda x: f"${x:,.2f}")
                df_display['Saldo Pendiente'] = df_display['Saldo Pendiente'].apply(lambda x: f"${x:,.2f}")
                df_display['Porcentaje Pagado'] = df_display['Porcentaje Pagado'].apply(lambda x: f"{x:.1f}%")
                
                # Aplicar estilos
                styled_df = df_display.style.applymap(color_estado_mora, subset=['Estado'])
                st.dataframe(styled_df, use_container_width=True)
                
                # Filtros por estado
                st.divider()
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("#### 🚨 Clientes En Mora")
                    clientes_mora_df = df_display[df_display['Estado'] == 'En Mora']
                    if not clientes_mora_df.empty:
                        st.dataframe(
                            clientes_mora_df[['Cliente', 'Teléfono', 'Cuotas Vencidas', 'Saldo Pendiente']],
                            use_container_width=True
                        )
                    else:
                        st.success("¡Excelente! No hay clientes en mora.")
                
                with col2:
                    st.markdown("#### ✅ Clientes Al Día")
                    clientes_al_dia_df = df_display[df_display['Estado'] == 'Al Día']
                    if not clientes_al_dia_df.empty:
                        st.dataframe(
                            clientes_al_dia_df[['Cliente', 'Porcentaje Pagado', 'Saldo Pendiente']],
                            use_container_width=True
                        )
                    else:
                        st.info("No hay clientes al día actualmente.")
    
    with tab2:
        st.markdown("### 📅 Cronograma Individual de Préstamo")
        
        df_prestamos = obtener_prestamos()
        
        if df_prestamos.empty:
            st.info("📌 No hay préstamos para generar cronogramas individuales.")
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
