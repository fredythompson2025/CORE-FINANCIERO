import streamlit as st
import pandas as pd
import datetime
import os

# =============================
# Nombre del archivo para guardar los préstamos
# =============================
ARCHIVO = "prestamos.xlsx"

# =============================
# Función para cargar datos
# =============================
def cargar_datos():
    if os.path.exists(ARCHIVO):
        return pd.read_excel(ARCHIVO)
    else:
        return pd.DataFrame(columns=["Cliente", "Monto", "Fecha", "Estado"])

# =============================
# Función para guardar datos
# =============================
def guardar_datos(df):
    df.to_excel(ARCHIVO, index=False)

# =============================
# Inicializar datos
# =============================
if "prestamos" not in st.session_state:
    st.session_state.prestamos = cargar_datos()

# =============================
# Título de la aplicación
# =============================
st.title("💰 Sistema de Préstamos")

# =============================
# Menú lateral
# =============================
menu = st.sidebar.selectbox(
    "Menú",
    ["Registrar Préstamo", "Listar Préstamos"]
)

# =============================
# Registrar nuevo préstamo
# =============================
if menu == "Registrar Préstamo":
    st.subheader("📌 Registrar un nuevo préstamo")

    cliente = st.text_input("Nombre del Cliente")
    monto = st.number_input("Monto del Préstamo", min_value=0.0, step=100.0)
    fecha = st.date_input("Fecha", value=datetime.date.today())
    estado = st.selectbox("Estado", ["Pendiente", "Pagado"])

    if st.button("💾 Guardar"):
        if cliente.strip() and monto > 0:
            nuevo_prestamo = pd.DataFrame(
                [[cliente, monto, fecha, estado]],
                columns=["Cliente", "Monto", "Fecha", "Estado"]
            )
            st.session_state.prestamos = pd.concat(
                [st.session_state.prestamos, nuevo_prestamo],
                ignore_index=True
            )
            guardar_datos(st.session_state.prestamos)
            st.success("✅ Préstamo registrado correctamente")
            st.rerun()  # Recarga la app
        else:
            st.error("⚠️ Complete todos los campos antes de guardar")

# =============================
# Listar préstamos
# =============================
elif menu == "Listar Préstamos":
    st.subheader("📋 Lista de Préstamos")

    if st.session_state.prestamos.empty:
        st.info("📂 No hay préstamos registrados")
    else:
        st.dataframe(st.session_state.prestamos)

    # Botón para eliminar todo
    if st.button("🗑️ Borrar todos los préstamos"):
        st.session_state.prestamos = pd.DataFrame(columns=["Cliente", "Monto", "Fecha", "Estado"])
        guardar_datos(st.session_state.prestamos)
        st.success("✅ Todos los préstamos han sido eliminados")
        st.rerun()
