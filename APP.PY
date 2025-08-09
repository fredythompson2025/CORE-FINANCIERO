import streamlit as st
import sqlite3
from datetime import datetime, timedelta, date
import pandas as pd
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# -------------------- DB helpers -------------------------------------------
DB_PATH = "cartera_prestamos.db"

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
            nombre TEXT NOT NULL,
            telefono TEXT,
            email TEXT,
            observaciones TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prestamos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            monto REAL NOT NULL,
            tasa_anual REAL NOT NULL,
            plazo_meses INTEGER NOT NULL,
            frecuencia INTEGER NOT NULL, -- pagos por año (12,4,2,1)
            metodo TEXT NOT NULL,
            fecha_desembolso DATE NOT NULL,
            moneda TEXT DEFAULT 'LPS',
            descripcion TEXT,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cronograma (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prestamo_id INTEGER NOT NULL,
            periodo INTEGER NOT NULL,
            fecha_vencimiento DATE NOT NULL,
            cuota REAL NOT NULL,
            interes REAL NOT NULL,
            amortizacion REAL NOT NULL,
            saldo REAL NOT NULL,
            pagado REAL DEFAULT 0.0,
            FOREIGN KEY(prestamo_id) REFERENCES prestamos(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prestamo_id INTEGER NOT NULL,
            fecha_pago DATE NOT NULL,
            monto REAL NOT NULL,
            metodo_pago TEXT,
            observaciones TEXT,
            FOREIGN KEY(prestamo_id) REFERENCES prestamos(id)
        )
    """)
    conn.commit()
    conn.close()

# -------------------- Finanzas: amortización --------------------------------

def cuota_frances(monto, tasa_anual, n_periodos, pagos_por_anio):
    i = tasa_anual / 100 / pagos_por_anio
    if i == 0:
        cuota = monto / n_periodos
    else:
        cuota = monto * (i / (1 - (1 + i) ** (-n_periodos)))
    saldo = monto
    schedule = []
    for p in range(1, n_periodos + 1):
        interes = saldo * i
        amort = cuota - interes
        saldo = max(0, saldo - amort)
        schedule.append((p, cuota, interes, amort, saldo))
    return schedule

# -------------------- Lógica para generar cronograma ------------------------

def generar_cronograma(prestamo_id, monto, tasa_anual, plazo_meses, frecuencia, fecha_desembolso):
    conn = get_conn()
    cur = conn.cursor()
    n_periodos = int(plazo_meses * (frecuencia / 12))
    schedule = cuota_frances(monto, tasa_anual, n_periodos, frecuencia)
    dias_entre = int(round(365 / frecuencia))
    fecha = fecha_desembolso
    for (p, cuota, interes, amort, saldo) in schedule:
        fecha = fecha + timedelta(days=dias_entre)
        cur.execute("INSERT INTO cronograma (prestamo_id, periodo, fecha_vencimiento, cuota, interes, amortizacion, saldo, pagado) VALUES (?,?,?,?,?,?,?,0)",
                    (prestamo_id, p, fecha, cuota, interes, amort, saldo))
    conn.commit()
    conn.close()

# -------------------- Operaciones de negocio -------------------------------

def agregar_cliente(nombre, telefono=None, email=None, observaciones=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO clientes (nombre, telefono, email, observaciones) VALUES (?,?,?,?)",
                (nombre, telefono, email, observaciones))
    conn.commit()
    idc = cur.lastrowid
    conn.close()
    return idc

def agregar_prestamo(cliente_id, monto, tasa_anual, plazo_meses, frecuencia, metodo, fecha_desembolso, moneda='LPS', descripcion=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO prestamos (cliente_id, monto, tasa_anual, plazo_meses, frecuencia, metodo, fecha_desembolso, moneda, descripcion) VALUES (?,?,?,?,?,?,?,?,?)",
                (cliente_id, monto, tasa_anual, plazo_meses, frecuencia, metodo, fecha_desembolso, moneda, descripcion))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    # generar cronograma automático
    generar_cronograma(pid, monto, tasa_anual, plazo_meses, frecuencia, fecha_desembolso)
    return pid

def registrar_pago(prestamo_id, fecha_pago, monto, metodo_pago=None, observaciones=None):
    conn = get_conn()
    cur = conn.cursor()
    # insertar registro de pago
    cur.execute("INSERT INTO pagos (prestamo_id, fecha_pago, monto, metodo_pago, observaciones) VALUES (?,?,?,?,?)",
                (prestamo_id, fecha_pago, monto, metodo_pago, observaciones))
    conn.commit()
    # aplicar pago a cronograma: ordenar por periodo asc y rellenar pagado
    restante = monto
    cur.execute("SELECT id, cuota, pagado FROM cronograma WHERE prestamo_id=? ORDER BY periodo", (prestamo_id,))
    rows = cur.fetchall()
    for r in rows:
        if restante <= 0:
            break
        cid = r["id"]
        cuota = r["cuota"]
        pagado = r["pagado"]
        faltante = cuota - pagado
        if faltante <= 0:
            continue
        pago_a_aplicar = min(faltante, restante)
        nuevo_pagado = pagado + pago_a_aplicar
        cur.execute("UPDATE cronograma SET pagado=? WHERE id=?", (nuevo_pagado, cid))
        restante -= pago_a_aplicar
    conn.commit()
    conn.close()

# -------------------- Reportes y utilidades -------------------------------

def obtener_prestamos():
    conn = get_conn()
    df = pd.read_sql_query("SELECT p.*, c.nombre as cliente FROM prestamos p JOIN clientes c ON c.id = p.cliente_id", conn, parse_dates=["fecha_desembolso"]) 
    conn.close()
    return df

def obtener_cronograma(prestamo_id):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM cronograma WHERE prestamo_id=? ORDER BY periodo", conn, params=(prestamo_id,), parse_dates=["fecha_vencimiento"]) 
    conn.close()
    return df

def obtener_pagos(prestamo_id):
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM pagos WHERE prestamo_id=? ORDER BY fecha_pago", conn, params=(prestamo_id,), parse_dates=["fecha_pago"]) 
    conn.close()
    return df

def resumen_estado(prestamo_id):
    cron = obtener_cronograma(prestamo_id)
    hoy = pd.Timestamp(date.today())
    cron['vencida'] = cron['fecha_vencimiento'] < hoy
    cron['saldo_pendiente'] = cron['cuota'] - cron['pagado']
    total_vencido = cron.loc[cron['vencida'], 'saldo_pendiente'].sum()
    total_pendiente = cron['saldo_pendiente'].sum()
    total_pagado = cron['pagado'].sum()
    return {
        'total_vencido': float(total_vencido),
        'total_pendiente': float(total_pendiente),
        'total_pagado': float(total_pagado),
        'cronograma': cron
    }

# -------------------- Exportar a Excel / PDF ------------------------------

def exportar_excel_cronograma(df_cronograma):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_cronograma.to_excel(writer, index=False, sheet_name='Cronograma')
        workbook = writer.book
        worksheet = writer.sheets['Cronograma']
        money_fmt = workbook.add_format({'num_format': '#,##0.00'})
        date_fmt = workbook.add_format({'num_format': 'dd-mm-yyyy'})
        for i, col in enumerate(df_cronograma.columns):
            max_len = max(df_cronograma[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, max_len)
        # formatos básicos
        for idx, col in enumerate(df_cronograma.columns):
            if col.lower() in ['cuota','interes','amortizacion','saldo','pagado']:
                worksheet.set_column(idx, idx, None, money_fmt)
            if col.lower() in ['fecha_vencimiento']:
                worksheet.set_column(idx, idx, None, date_fmt)
    output.seek(0)
    return output

def exportar_pdf_cronograma(df_cronograma, cliente, prestamo_id):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    flow = []
    flow.append(Paragraph(f"Cronograma de pago - Préstamo #{prestamo_id}", styles['Title']))
    flow.append(Paragraph(f"Cliente: {cliente}", styles['Normal']))
    flow.append(Spacer(1,12))
    data = [list(df_cronograma.columns)]
    for _, row in df_cronograma.iterrows():
        data.append([row[c] if not pd.isna(row[c]) else '' for c in df_cronograma.columns])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-1),0.5,colors.grey),
        ('BACKGROUND',(0,0),(-1,0),colors.lightgrey),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE')
    ]))
    flow.append(table)
    doc.build(flow)
    buffer.seek(0)
    return buffer

# -------------------- Interfaz Streamlit ----------------------------------

init_db()
st.set_page_config(page_title="Gestión de Cartera - Préstamos", layout='wide')
st.title("Sistema de Gestión de Préstamos y Cartera")

menu = st.sidebar.selectbox("Menú", ["Resumen cartera", "Clientes", "Préstamos", "Reportes"])

if menu == 'Clientes':
    st.header("Registrar cliente")
    with st.form('form_cliente'):
        nombre = st.text_input('Nombre completo')
        telefono = st.text_input('Teléfono')
        email = st.text_input('Email')
        obs = st.text_area('Observaciones')
        if st.form_submit_button('Agregar cliente'):
            if not nombre:
                st.error('El nombre es requerido')
            else:
                cid = agregar_cliente(nombre, telefono, email, obs)
                st.success(f'Cliente agregado (id={cid})')
    # ver lista
    conn = get_conn()
    dfc = pd.read_sql_query('SELECT * FROM clientes', conn)
    conn.close()
    st.subheader('Clientes registrados')
    st.dataframe(dfc)

elif menu == 'Préstamos':
    st.header('Agregar nuevo préstamo')
    conn = get_conn()
    clientes_df = pd.read_sql_query('SELECT id, nombre FROM clientes', conn)
    conn.close()
    if clientes_df.empty:
        st.info('No hay clientes. Primero agrega clientes en la sección "Clientes".')
    else:
        with st.form('form_prestamo'):
            cliente_sel = st.selectbox('Cliente', clientes_df.set_index('id')['nombre'])
            monto = st.number_input('Monto', min_value=0.0, value=50000.0, format='%.2f')
            tasa = st.number_input('Tasa anual (%)', min_value=0.0, value=12.0, format='%.2f')
            plazo = st.number_input('Plazo (meses)', min_value=1, value=24)
            frecuencia = st.selectbox('Frecuencia de pagos por año', [12,4,2,1], index=0)
            metodo = st.selectbox('Método de amortización', ['Francés'])
            fecha_des = st.date_input('Fecha de desembolso', value=date.today())
            descripcion = st.text_area('Descripción')
            if st.form_submit_button('Crear préstamo'):
                # cliente_sel contiene nombre -> buscar id
                selected_id = int(clientes_df[clientes_df['nombre']==cliente_sel]['id'].iloc[0])
                pid = agregar_prestamo(selected_id, monto, tasa, plazo, frecuencia, metodo, fecha_des, 'LPS', descripcion)
                st.success(f'Préstamo creado (id={pid})')

    st.markdown('---')
    st.subheader('Préstamos existentes')
    prestamos_df = obtener_prestamos()
    if prestamos_df.empty:
        st.info('No hay préstamos registrados.')
    else:
        st.dataframe(prestamos_df)
        st.markdown('Selecciona un préstamo para ver detalle:')
        pid = st.number_input('ID préstamo', min_value=1, value=int(prestamos_df['id'].iloc[0]))
        if st.button('Ver detalle'):
            cron = obtener_cronograma(pid)
            pagos = obtener_pagos(pid)
            st.write('Cronograma:')
            st.dataframe(cron)
            estado = resumen_estado(pid)
            st.markdown(f"**Total pendiente:** {estado['total_pendiente']:.2f}")
            st.markdown(f"**Total vencido:** {estado['total_vencido']:.2f}")
            st.markdown(f"**Total pagado:** {estado['total_pagado']:.2f}")
            st.write('Pagos registrados:')
            st.dataframe(pagos)
            # Registrar pago
            st.markdown('Registrar nuevo pago')
            with st.form('form_pago'):
                fecha_pago = st.date_input('Fecha pago', value=date.today())
                monto_pago = st.number_input('Monto pago', min_value=0.0, value=0.0, format='%.2f')
                metodo_pago = st.text_input('Método de pago')
                obs_pago = st.text_area('Observaciones')
                if st.form_submit_button('Registrar pago'):
                    if monto_pago <= 0:
                        st.error('El monto debe ser mayor que cero')
                    else:
                        registrar_pago(pid, fecha_pago, monto_pago, metodo_pago, obs_pago)
                        st.success('Pago registrado y aplicado al cronograma')

            # Exportar
            st.markdown('Exportar cronograma')
            cron_df = cron.copy()
            cron_df['fecha_vencimiento'] = pd.to_datetime(cron_df['fecha_vencimiento']).dt.date
            excel_bytes = exportar_excel_cronograma(cron_df)
            st.download_button('Descargar Excel', data=excel_bytes, file_name=f'cronograma_{pid}.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            # PDF
            cliente_nombre = prestamos_df[prestamos_df['id']==pid]['cliente'].iloc[0]
            pdf_bytes = exportar_pdf_cronograma(cron_df, cliente_nombre, pid)
            st.download_button('Descargar PDF', data=pdf_bytes, file_name=f'cronograma_{pid}.pdf', mime='application/pdf')

elif menu == 'Reportes':
    st.header('Reportes y estado de cartera')
    prestamos_df = obtener_prestamos()
    if prestamos_df.empty:
        st.info('No hay préstamos registrados.')
    else:
        st.dataframe(prestamos_df)
        # resumen general
        resumen = []
        for pid in prestamos_df['id']:
            r = resumen_estado(pid)
            cliente = prestamos_df[prestamos_df['id']==pid]['cliente'].iloc[0]
            resumen.append({'prestamo_id': pid, 'cliente': cliente, 'vencido': r['total_vencido'], 'pendiente': r['total_pendiente'], 'pagado': r['total_pagado']})
        df_res = pd.DataFrame(resumen)
        st.subheader('Resumen por préstamo')
        st.dataframe(df_res)
        # filtros
        st.markdown('Exportar reporte general')
        if st.button('Exportar Excel reporte cartera'):
            out = BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                df_res.to_excel(writer, index=False, sheet_name='Resumen')
            out.seek(0)
            st.download_button('Descargar Excel cartera', data=out, file_name='reporte_cartera.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

else:
    st.header('Resumen cartera')
    prestamos_df = obtener_prestamos()
    if prestamos_df.empty:
        st.info('No hay préstamos registrados.')
    else:
        resumen = []
        for pid in prestamos_df['id']:
            r = resumen_estado(pid)
            cliente = prestamos_df[prestamos_df['id']==pid]['cliente'].iloc[0]
            resumen.append({'prestamo_id': pid, 'cliente': cliente, 'vencido': r['total_vencido'], 'pendiente': r['total_pendiente'], 'pagado': r['total_pagado']})
        df_res = pd.DataFrame(resumen)
        st.dataframe(df_res)
        # totales
        st.markdown(f"**Total vencido (cartera):** {df_res['vencido'].sum():.2f}")
        st.markdown(f"**Total pendiente (cartera):** {df_res['pendiente'].sum():.2f}")
        st.markdown(f"**Total pagado (cartera):** {df_res['pagado'].sum():.2f}")

st.caption('Guarda el archivo "cartera_prestamos.db" para mantener la base de datos. Recomendado: copiar respaldo regularmente.')
