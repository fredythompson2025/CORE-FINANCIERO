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
    
    # Crear tabla clientes
    cur.execute("""
    CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL UNIQUE,
        identificacion TEXT,
        direccion TEXT,
        telefono TEXT
    )""")
    
    # Crear tabla prestamos
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
    
    # Agregar columnas de aval a prestamos si no existen
    try:
        cur.execute("ALTER TABLE prestamos ADD COLUMN aval_nombre TEXT")
    except sqlite3.OperationalError:
        pass  # La columna ya existe
    
    try:
        cur.execute("ALTER TABLE prestamos ADD COLUMN aval_identificacion TEXT")
    except sqlite3.OperationalError:
        pass  # La columna ya existe
        
    try:
        cur.execute("ALTER TABLE prestamos ADD COLUMN aval_telefono TEXT")
    except sqlite3.OperationalError:
        pass  # La columna ya existe
        
    # Agregar columna de tipo de amortización
    try:
        cur.execute("ALTER TABLE prestamos ADD COLUMN tipo_amortizacion TEXT DEFAULT 'capital_interes'")
    except sqlite3.OperationalError:
        pass  # La columna ya existe
    
    # Crear tabla pagos
    cur.execute("""
    CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prestamo_id INTEGER,
        fecha_pago DATE,
        monto REAL,
        FOREIGN KEY(prestamo_id) REFERENCES prestamos(id)
    )""")
    
    # Agregar columnas de tipo de abono a pagos si no existen
    try:
        cur.execute("ALTER TABLE pagos ADD COLUMN tipo_abono TEXT DEFAULT 'ambos'")
    except sqlite3.OperationalError:
        pass  # La columna ya existe
        
    try:
        cur.execute("ALTER TABLE pagos ADD COLUMN monto_capital REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # La columna ya existe
        
    try:
        cur.execute("ALTER TABLE pagos ADD COLUMN monto_interes REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # La columna ya existe
    
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

def agregar_prestamo(cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso, aval_nombre="", aval_identificacion="", aval_telefono="", tipo_amortizacion="capital_interes"):
    conn = get_conn()
    cur = conn.cursor()
    
    # Verificar qué columnas existen en la tabla prestamos
    cur.execute("PRAGMA table_info(prestamos)")
    columns_info = cur.fetchall()
    column_names = [col[1] for col in columns_info]
    
    if 'tipo_amortizacion' in column_names and 'aval_nombre' in column_names:
        # Usar la versión completa con aval y tipo de amortización
        cur.execute("INSERT INTO prestamos (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso, aval_nombre, aval_identificacion, aval_telefono, tipo_amortizacion) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso, aval_nombre, aval_identificacion, aval_telefono, tipo_amortizacion))
    elif 'aval_nombre' in column_names:
        # Usar la versión con aval pero sin tipo de amortización
        cur.execute("INSERT INTO prestamos (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso, aval_nombre, aval_identificacion, aval_telefono) VALUES (?,?,?,?,?,?,?,?,?)",
                    (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso, aval_nombre, aval_identificacion, aval_telefono))
    else:
        # Usar la versión básica
        cur.execute("INSERT INTO prestamos (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso) VALUES (?,?,?,?,?,?)",
                    (cliente_id, monto, tasa, plazo, frecuencia, fecha_desembolso))
    
    conn.commit()
    conn.close()

def obtener_prestamos():
    conn = get_conn()
    
    # Verificar qué columnas existen en la tabla prestamos
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(prestamos)")
    columns_info = cur.fetchall()
    column_names = [col[1] for col in columns_info]
    
    # Construir la consulta según las columnas disponibles
    base_select = "p.id, c.nombre as cliente, p.monto, p.tasa, p.plazo, p.frecuencia, p.fecha_desembolso"
    
    if 'aval_nombre' in column_names:
        aval_select = ", p.aval_nombre, p.aval_identificacion, p.aval_telefono"
    else:
        aval_select = ", NULL as aval_nombre, NULL as aval_identificacion, NULL as aval_telefono"
        
    if 'tipo_amortizacion' in column_names:
        amortizacion_select = ", p.tipo_amortizacion"
    else:
        amortizacion_select = ", 'capital_interes' as tipo_amortizacion"
    
    query = f"""
    SELECT {base_select}{aval_select}{amortizacion_select}
    FROM prestamos p JOIN clientes c ON p.cliente_id = c.id
    ORDER BY p.id DESC
    """
    
    df = pd.read_sql_query(query, conn)
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
    
    # Verificar qué columnas existen en la tabla pagos
    cur.execute("PRAGMA table_info(pagos)")
    columns_info = cur.fetchall()
    column_names = [col[1] for col in columns_info]
    
    if 'tipo_abono' in column_names:
        # Usar la versión completa con tipo_abono
        cur.execute("INSERT INTO pagos (prestamo_id, fecha_pago, monto, tipo_abono, monto_capital, monto_interes) VALUES (?,?,?,?,?,?)",
                    (prestamo_id, fecha_pago, monto, tipo_abono, monto_capital, monto_interes))
    else:
        # Usar la versión básica sin tipo_abono
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

def obtener_detalle_cliente(cliente_id):
    """Obtiene información completa de un cliente incluyendo todos sus préstamos y pagos"""
    conn = get_conn()
    
    # Información básica del cliente
    cliente_info = pd.read_sql_query("""
    SELECT * FROM clientes WHERE id = ?
    """, conn, params=[cliente_id])
    
    # Préstamos del cliente
    prestamos_cliente = pd.read_sql_query("""
    SELECT * FROM prestamos WHERE cliente_id = ?
    ORDER BY fecha_desembolso DESC
    """, conn, params=[cliente_id])
    
    # Todos los pagos del cliente
    pagos_cliente = pd.read_sql_query("""
    SELECT pag.*, p.monto as monto_prestamo
    FROM pagos pag 
    JOIN prestamos p ON pag.prestamo_id = p.id
    WHERE p.cliente_id = ?
    ORDER BY pag.fecha_pago DESC
    """, conn, params=[cliente_id])
    
    conn.close()
    
    return cliente_info, prestamos_cliente, pagos_cliente

def calcular_totales_cliente(cliente_id):
    """Calcula los totales de préstamos y pagos para un cliente"""
    conn = get_conn()
    
    # Total prestado
    total_prestado = pd.read_sql_query("""
    SELECT COALESCE(SUM(monto), 0) as total
    FROM prestamos WHERE cliente_id = ?
    """, conn, params=[cliente_id])['total'].iloc[0]
    
    # Total pagado, capital pagado e intereses pagados
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(pagos)")
    columns_info = cur.fetchall()
    column_names = [col[1] for col in columns_info]
    
    if 'monto_capital' in column_names and 'monto_interes' in column_names:
        # Si tenemos los campos separados
        totales_pagos = pd.read_sql_query("""
        SELECT 
            COALESCE(SUM(pag.monto), 0) as total_pagado,
            COALESCE(SUM(pag.monto_capital), 0) as capital_pagado,
            COALESCE(SUM(pag.monto_interes), 0) as interes_pagado
        FROM pagos pag 
        JOIN prestamos p ON pag.prestamo_id = p.id
        WHERE p.cliente_id = ?
        """, conn, params=[cliente_id])
    else:
        # Si solo tenemos el monto total
        totales_pagos = pd.read_sql_query("""
        SELECT 
            COALESCE(SUM(pag.monto), 0) as total_pagado,
            0 as capital_pagado,
            0 as interes_pagado
        FROM pagos pag 
        JOIN prestamos p ON pag.prestamo_id = p.id
        WHERE p.cliente_id = ?
        """, conn, params=[cliente_id])
    
    conn.close()
    
    return {
        'total_prestado': total_prestado,
        'total_pagado': totales_pagos['total_pagado'].iloc[0],
        'capital_pagado': totales_pagos['capital_pagado'].iloc[0],
        'interes_pagado': totales_pagos['interes_pagado'].iloc[0]
    }

def calcular_totales_prestamo(prestamo_id):
    """Calcula los totales de capital e intereses para un préstamo específico"""
    conn = get_conn()
    
    # Obtener información del préstamo
    prestamo_info = pd.read_sql_query("""
    SELECT monto FROM prestamos WHERE id = ?
    """, conn, params=[prestamo_id])
    
    if prestamo_info.empty:
        conn.close()
        return {
            'capital_inicial': 0,
            'total_pagado': 0,
            'capital_pagado': 0,
            'interes_pagado': 0,
            'saldo_capital': 0,
            'saldo_interes': 0
        }
    
    capital_inicial = prestamo_info['monto'].iloc[0]
    
    # Total pagado, capital pagado e intereses pagados
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(pagos)")
    columns_info = cur.fetchall()
    column_names = [col[1] for col in columns_info]
    
    if 'monto_capital' in column_names and 'monto_interes' in column_names:
        # Si tenemos los campos separados
        totales_pagos = pd.read_sql_query("""
        SELECT 
            COALESCE(SUM(monto), 0) as total_pagado,
            COALESCE(SUM(monto_capital), 0) as capital_pagado,
            COALESCE(SUM(monto_interes), 0) as interes_pagado
        FROM pagos WHERE prestamo_id = ?
        """, conn, params=[prestamo_id])
    else:
        # Si solo tenemos el monto total
        totales_pagos = pd.read_sql_query("""
        SELECT 
            COALESCE(SUM(monto), 0) as total_pagado,
            0 as capital_pagado,
            0 as interes_pagado
        FROM pagos WHERE prestamo_id = ?
        """, conn, params=[prestamo_id])
    
    conn.close()
    
    total_pagado = totales_pagos['total_pagado'].iloc[0]
    capital_pagado = totales_pagos['capital_pagado'].iloc[0]
    interes_pagado = totales_pagos['interes_pagado'].iloc[0]
    
    saldo_capital = capital_inicial - capital_pagado
    # Para calcular saldo de interés necesitaríamos el cronograma completo
    # Por ahora mostramos lo pagado
    
    return {
        'capital_inicial': capital_inicial,
        'total_pagado': total_pagado,
        'capital_pagado': capital_pagado,
        'interes_pagado': interes_pagado,
        'saldo_capital': max(0, saldo_capital),
        'saldo_interes': 0  # Requiere cálculo del cronograma
    }

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
    if st.button("📋 Detalle Cliente"):
        st.session_state['menu'] = "Detalle Cliente"
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

elif menu == "Detalle Cliente":
    st.markdown("## 📋 Detalle del Cliente")
    
    df_clientes = obtener_clientes()
    
    if df_clientes.empty:
        st.info("📌 No hay clientes registrados. Agrega clientes primero en la sección de Clientes.")
    else:
        # Selector de cliente
        cliente_options = [f"{row['nombre']} (ID: {row['id']})" for _, row in df_clientes.iterrows()]
        cliente_sel = st.selectbox("Selecciona un cliente para ver su detalle completo", cliente_options)
        cliente_id = int(cliente_sel.split('ID: ')[1].split(')')[0])
        
        # Obtener información del cliente
        cliente_info, prestamos_cliente, pagos_cliente = obtener_detalle_cliente(cliente_id)
        totales = calcular_totales_cliente(cliente_id)
        
        if not cliente_info.empty:
            cliente = cliente_info.iloc[0]
            
            # Información básica del cliente
            st.markdown("### 👤 Información Personal")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Nombre", cliente['nombre'])
            with col2:
                st.metric("Identificación", cliente['identificacion'] or "No especificada")
            with col3:
                st.metric("Teléfono", cliente['telefono'] or "No especificado")
            with col4:
                st.metric("Dirección", cliente['direccion'] or "No especificada")
            
            st.divider()
            
            # Préstamos del cliente
            st.markdown("### 🏦 Préstamos del Cliente")
            if prestamos_cliente.empty:
                st.info("Este cliente no tiene préstamos registrados.")
            else:
                df_prestamos_display = prestamos_cliente.copy()
                df_prestamos_display['monto'] = df_prestamos_display['monto'].apply(lambda x: f"${x:,.2f}")
                df_prestamos_display['tasa'] = df_prestamos_display['tasa'].apply(lambda x: f"{x}%")
                
                # Agregar información de aval si existe
                if 'aval_nombre' in df_prestamos_display.columns:
                    df_prestamos_display['tiene_aval'] = df_prestamos_display['aval_nombre'].apply(
                        lambda x: '✅ Sí' if x and str(x).strip() else '❌ No'
                    )
                    
                    columnas_mostrar = ['id', 'monto', 'tasa', 'plazo', 'fecha_desembolso', 'tiene_aval']
                    column_config = {
                        "id": "ID Préstamo",
                        "monto": "Monto",
                        "tasa": "Tasa Anual",
                        "plazo": "Plazo (meses)",
                        "fecha_desembolso": "Fecha Desembolso",
                        "tiene_aval": "¿Tiene Aval?"
                    }
                else:
                    columnas_mostrar = ['id', 'monto', 'tasa', 'plazo', 'fecha_desembolso']
                    column_config = {
                        "id": "ID Préstamo",
                        "monto": "Monto",
                        "tasa": "Tasa Anual",
                        "plazo": "Plazo (meses)",
                        "fecha_desembolso": "Fecha Desembolso"
                    }
                
                st.dataframe(
                    df_prestamos_display[columnas_mostrar],
                    use_container_width=True,
                    column_config=column_config
                )
            
            st.divider()
            
            # Historial de pagos del cliente
            st.markdown("### 💵 Historial de Pagos")
            if pagos_cliente.empty:
                st.info("Este cliente no ha realizado pagos.")
            else:
                df_pagos_display = pagos_cliente.copy()
                df_pagos_display['monto'] = df_pagos_display['monto'].apply(lambda x: f"${x:,.2f}")
                
                # Agregar información del tipo de abono si existe
                if 'tipo_abono' in df_pagos_display.columns:
                    df_pagos_display['tipo_abono_formatted'] = df_pagos_display['tipo_abono'].apply(
                        lambda x: {
                            'ambos': '💰 Capital + Interés',
                            'capital': '🏠 Solo Capital', 
                            'interes': '📈 Solo Interés'
                        }.get(str(x), '💰 Capital + Interés')
                    )
                    
                    # Mostrar montos detallados si están disponibles
                    if 'monto_capital' in df_pagos_display.columns:
                        df_pagos_display['monto_capital_fmt'] = df_pagos_display['monto_capital'].apply(lambda x: f"${x:,.2f}" if x > 0 else "-")
                        df_pagos_display['monto_interes_fmt'] = df_pagos_display['monto_interes'].apply(lambda x: f"${x:,.2f}" if x > 0 else "-")
                        
                        columnas_mostrar = ['prestamo_id', 'fecha_pago', 'monto', 'tipo_abono_formatted', 'monto_capital_fmt', 'monto_interes_fmt']
                        column_config = {
                            "prestamo_id": "ID Préstamo",
                            "fecha_pago": "Fecha Pago",
                            "monto": "Monto Total",
                            "tipo_abono_formatted": "Tipo de Abono",
                            "monto_capital_fmt": "Capital",
                            "monto_interes_fmt": "Interés"
                        }
                    else:
                        columnas_mostrar = ['prestamo_id', 'fecha_pago', 'monto', 'tipo_abono_formatted']
                        column_config = {
                            "prestamo_id": "ID Préstamo",
                            "fecha_pago": "Fecha Pago",
                            "monto": "Monto Total",
                            "tipo_abono_formatted": "Tipo de Abono"
                        }
                else:
                    columnas_mostrar = ['prestamo_id', 'fecha_pago', 'monto']
                    column_config = {
                        "prestamo_id": "ID Préstamo",
                        "fecha_pago": "Fecha Pago",
                        "monto": "Monto Total"
                    }
                
                st.dataframe(
                    df_pagos_display[columnas_mostrar],
                    use_container_width=True,
                    column_config=column_config
                )
            
            # Agregar sección de reporte detallado
            if not prestamos_cliente.empty:
                st.divider()
                st.markdown("### 📊 Reporte Detallado y Estado de Mora")
                
                # Crear reporte por cada préstamo del cliente
                for _, prestamo in prestamos_cliente.iterrows():
                    st.markdown(f"#### 🏦 Préstamo #{prestamo['id']} - ${prestamo['monto']:,.2f}")
                    
                    # Calcular cronograma para este préstamo
                    cronograma = calcular_cronograma(
                        prestamo['monto'],
                        prestamo['tasa'],
                        prestamo['plazo'],
                        prestamo['frecuencia'],
                        prestamo['fecha_desembolso']
                    )
                    
                    # Obtener pagos para este préstamo
                    pagos_prestamo = obtener_pagos(prestamo['id'])
                    
                    # Calcular estado del cronograma
                    cronograma_con_estado = estado_cuotas(cronograma, pagos_prestamo)
                    
                    # Calcular métricas del préstamo
                    total_pagado = pagos_prestamo['monto'].sum() if not pagos_prestamo.empty else 0
                    saldo_pendiente = cronograma_con_estado['Pendiente'].sum()
                    cuotas_vencidas = len(cronograma_con_estado[cronograma_con_estado['Estado'] == 'Vencida'])
                    total_cuotas = len(cronograma_con_estado)
                    cuotas_pagadas = len(cronograma_con_estado[cronograma_con_estado['Pendiente'] == 0])
                    
                    # Determinar estado de mora
                    estado_mora = "En Mora" if cuotas_vencidas > 0 else "Al Día"
                    porcentaje_pagado = (total_pagado / prestamo['monto'] * 100) if prestamo['monto'] > 0 else 0
                    
                    # Mostrar métricas del préstamo
                    col1, col2, col3, col4, col5 = st.columns(5)
                    with col1:
                        st.metric("Total Pagado", f"${total_pagado:,.2f}")
                    with col2:
                        st.metric("Saldo Pendiente", f"${saldo_pendiente:,.2f}")
                    with col3:
                        st.metric("Cuotas Pagadas", f"{cuotas_pagadas}/{total_cuotas}")
                    with col4:
                        st.metric("Cuotas Vencidas", cuotas_vencidas)
                    with col5:
                        if estado_mora == "En Mora":
                            st.error(f"🚨 {estado_mora}")
                        else:
                            st.success(f"✅ {estado_mora}")
                    
                    # Mostrar progreso
                    st.progress(min(porcentaje_pagado / 100, 1.0), text=f"Progreso del préstamo: {porcentaje_pagado:.1f}%")
                    
                    # Mostrar cronograma con estado
                    with st.expander(f"📅 Ver Cronograma Completo - Préstamo #{prestamo['id']}", expanded=False):
                        df_cronograma_display = cronograma_con_estado.copy()
                        df_cronograma_display['Cuota'] = df_cronograma_display['Cuota'].apply(lambda x: f"${x:,.2f}")
                        if 'Amortizacion' in df_cronograma_display.columns:
                            df_cronograma_display['Amortizacion'] = df_cronograma_display['Amortizacion'].apply(lambda x: f"${x:,.2f}")
                        if 'Interes' in df_cronograma_display.columns:
                            df_cronograma_display['Interes'] = df_cronograma_display['Interes'].apply(lambda x: f"${x:,.2f}")
                        df_cronograma_display['Saldo'] = df_cronograma_display['Saldo'].apply(lambda x: f"${x:,.2f}")
                        df_cronograma_display['Pendiente'] = df_cronograma_display['Pendiente'].apply(lambda x: f"${x:,.2f}" if x > 0 else "✅ Pagada")
                        
                        # Función para colorear filas según estado
                        def color_estado_cronograma(row):
                            if row['Estado'] == 'Vencida':
                                return ['background-color: #ffcccc'] * len(row)
                            elif row['Estado'] == 'Por Vencer':
                                return ['background-color: #ffffcc'] * len(row)
                            elif row['Estado'] == 'Pagada':
                                return ['background-color: #ccffcc'] * len(row)
                            else:
                                return [''] * len(row)
                        
                        styled_cronograma = df_cronograma_display.style.apply(color_estado_cronograma, axis=1)
                        st.dataframe(styled_cronograma, use_container_width=True)
                        
                        # Leyenda de colores
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.markdown("🟢 **Verde**: Cuotas pagadas")
                        with col2:
                            st.markdown("🟡 **Amarillo**: Cuotas por vencer")
                        with col3:
                            st.markdown("🔴 **Rojo**: Cuotas vencidas")
                    
                    st.markdown("---")

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
                
                # Tipo de amortización
                st.divider()
                st.markdown("#### 📊 Tipo de Amortización")
                tipo_amortizacion = st.selectbox("Tipo de cuotas", 
                                               ["capital_interes", "solo_interes"], 
                                               format_func=lambda x: {
                                                   "capital_interes": "💰 Capital + Interés (Cuotas Decrecientes)",
                                                   "solo_interes": "📈 Solo Interés (Capital al Final)"
                                               }[x])
                
                if tipo_amortizacion == "capital_interes":
                    st.info("💡 Cada cuota incluye capital e interés. El saldo disminuye con cada pago.")
                else:
                    st.info("💡 Las cuotas son solo interés. El capital se paga completo al final del plazo.")
                
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
                            aval_telefono.strip() if tiene_aval else "",
                            tipo_amortizacion
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
                df_display['tipo_amortizacion_fmt'] = df_display['tipo_amortizacion'].apply(
                    lambda x: "💰 Capital+Interés" if x == "capital_interes" else "📈 Solo Interés"
                )
                
                st.dataframe(
                    df_display[['id', 'cliente', 'monto', 'tasa', 'plazo', 'frecuencia', 'fecha_desembolso', 'tipo_amortizacion_fmt', 'tiene_aval']],
                    use_container_width=True,
                    column_config={
                        "id": "ID",
                        "cliente": "Cliente",
                        "monto": "Monto",
                        "tasa": "Tasa",
                        "plazo": "Plazo (meses)",
                        "frecuencia": "Frecuencia",
                        "fecha_desembolso": "Fecha Desembolso",
                        "tipo_amortizacion_fmt": "Tipo Amortización",
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
                # Mostrar totales generales
                st.markdown("#### 💰 Totales de Capital e Interés")
                
                # Calcular totales si existen las columnas
                if 'monto_capital' in df_todos_pagos.columns and 'monto_interes' in df_todos_pagos.columns:
                    total_capital_pagado = df_todos_pagos['monto_capital'].sum()
                    total_interes_pagado = df_todos_pagos['monto_interes'].sum()
                    total_general = df_todos_pagos['monto'].sum()
                    
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Total Pagado", f"${total_general:,.2f}")
                    with col2:
                        st.metric("Capital Pagado", f"${total_capital_pagado:,.2f}")
                    with col3:
                        st.metric("Interés Pagado", f"${total_interes_pagado:,.2f}")
                    with col4:
                        # Calcular saldo total de capital pendiente
                        conn = get_conn()
                        total_prestado = pd.read_sql_query("SELECT COALESCE(SUM(monto), 0) as total FROM prestamos", conn)['total'].iloc[0]
                        conn.close()
                        saldo_capital_total = total_prestado - total_capital_pagado
                        st.metric("Saldo Capital", f"${max(0, saldo_capital_total):,.2f}")
                else:
                    total_general = df_todos_pagos['monto'].sum()
                    st.metric("Total Pagado", f"${total_general:,.2f}")
                    st.info("💡 Para ver detalles de capital e intereses, registra nuevos pagos con el tipo especificado")
                
                st.divider()
                
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
                    
                    # Agregar columnas de capital e interés si existen
                    if 'monto_capital' in df_display_pagos.columns and 'monto_interes' in df_display_pagos.columns:
                        df_display_pagos['monto_capital_fmt'] = df_display_pagos['monto_capital'].apply(lambda x: f"${x:,.2f}" if x > 0 else "-")
                        df_display_pagos['monto_interes_fmt'] = df_display_pagos['monto_interes'].apply(lambda x: f"${x:,.2f}" if x > 0 else "-")
                        
                        columnas_mostrar = ['prestamo_id', 'cliente', 'fecha_pago', 'monto', 'tipo_abono_formatted', 'monto_capital_fmt', 'monto_interes_fmt']
                        column_config = {
                            "prestamo_id": "Préstamo ID",
                            "cliente": "Cliente", 
                            "fecha_pago": "Fecha Pago",
                            "monto": "Monto Total",
                            "tipo_abono_formatted": "Tipo de Abono",
                            "monto_capital_fmt": "Capital",
                            "monto_interes_fmt": "Interés"
                        }
                    else:
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
                
                # Agregar totales por cliente al final
                st.divider()
                st.markdown("#### 📊 Totales por Cliente")
                
                if 'monto_capital' in df_todos_pagos.columns and 'monto_interes' in df_todos_pagos.columns:
                    # Calcular totales por cliente con desglose
                    totales_cliente = df_todos_pagos.groupby('cliente').agg({
                        'monto': 'sum',
                        'monto_capital': 'sum', 
                        'monto_interes': 'sum'
                    }).reset_index()
                    
                    # Obtener total prestado por cliente y calcular saldo de capital
                    conn = get_conn()
                    prestamos_por_cliente = pd.read_sql_query("""
                    SELECT c.nombre as cliente, COALESCE(SUM(p.monto), 0) as total_prestado
                    FROM clientes c 
                    LEFT JOIN prestamos p ON c.id = p.cliente_id
                    GROUP BY c.id, c.nombre
                    """, conn)
                    conn.close()
                    
                    # Combinar datos
                    totales_completo = totales_cliente.merge(prestamos_por_cliente, on='cliente', how='left')
                    totales_completo['saldo_capital'] = totales_completo['total_prestado'] - totales_completo['monto_capital']
                    totales_completo['saldo_capital'] = totales_completo['saldo_capital'].apply(lambda x: max(0, x))
                    
                    # Formatear para mostrar
                    totales_completo['total_pagado_fmt'] = totales_completo['monto'].apply(lambda x: f"${x:,.2f}")
                    totales_completo['capital_pagado_fmt'] = totales_completo['monto_capital'].apply(lambda x: f"${x:,.2f}")
                    totales_completo['interes_pagado_fmt'] = totales_completo['monto_interes'].apply(lambda x: f"${x:,.2f}")
                    totales_completo['saldo_capital_fmt'] = totales_completo['saldo_capital'].apply(lambda x: f"${x:,.2f}")
                    
                    st.dataframe(
                        totales_completo[['cliente', 'total_pagado_fmt', 'capital_pagado_fmt', 'interes_pagado_fmt', 'saldo_capital_fmt']],
                        use_container_width=True,
                        column_config={
                            "cliente": "Cliente",
                            "total_pagado_fmt": "Total Pagado",
                            "capital_pagado_fmt": "Capital Pagado",
                            "interes_pagado_fmt": "Interés Pagado",
                            "saldo_capital_fmt": "Saldo Capital"
                        }
                    )
                else:
                    # Solo totales básicos si no hay desglose
                    totales_cliente = df_todos_pagos.groupby('cliente').agg({
                        'monto': 'sum'
                    }).reset_index()
                    
                    totales_cliente['total_pagado_fmt'] = totales_cliente['monto'].apply(lambda x: f"${x:,.2f}")
                    
                    st.dataframe(
                        totales_cliente[['cliente', 'total_pagado_fmt']],
                        use_container_width=True,
                        column_config={
                            "cliente": "Cliente",
                            "total_pagado_fmt": "Total Pagado"
                        }
                    )

elif menu == "Reporte":
    st.markdown("## 📊 Reportes y Estado de Cartera")
    
    # Pestañas para diferentes tipos de reportes
    tab1, tab2 = st.tabs(["📋 Resumen General", "📅 Cronograma Individual"])
    
    with tab1:
        st.info("💡 El resumen detallado de clientes ahora está integrado en la sección 'Detalle Cliente'. Usa esa sección para ver información completa de cada cliente incluyendo estado de mora, cronogramas y métricas.")
    
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
                styled_df = df_display_cronograma.style.map(color_estado, subset=['Estado'])
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
