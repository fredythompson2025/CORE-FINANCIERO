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
    # Borrar pagos asociados
    cur.execute("DELETE FROM pagos WHERE prestamo_id IN (SELECT id FROM prestamos WHERE cliente_id = ?)", (id_cliente,))
    # Borrar préstamos asociados
    cur.execute("DELETE FROM prestamos WHERE cliente_id = ?", (id_cliente,))
    # Borrar cliente
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

# -- Exportar PDF --
def exportar_pdf(df, cliente, prestamo_id):
    df_export = df.copy()
    # Formateo de columnas
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
