# ===============================================================
# 🐟 LOGGER v3 — Ultra estable con SQLite WAL + detección inicio/fin de errores
# ===============================================================

import socket
import time
import csv
import os
import sqlite3
from datetime import datetime

# ==============================
# CONFIGURACIÓN
# ==============================
UDP_IP = "127.0.0.1"
UDP_PORT = 5006
BUFFER_SIZE = 1024
INTERVALO_REGISTRO = 5.0
DIRECTORIO = "registros_csv"
os.makedirs(DIRECTORIO, exist_ok=True)

ARCHIVO_FIJO = os.path.join(DIRECTORIO, "datos_actual.csv")
MAX_LINEAS_FIJO = 600

DB_FILE = "monitoreo.db"

# ==============================
# DICCIONARIO DE ERRORES
# ==============================
ERROR_DESCRIPCIONES = {
    1: "pH fuera de rango.",
    2: "Oxígeno disuelto fuera de rango.",
    3: "Temperatura fuera de rango.",
    4: "Lecturas de pH inválidas consecutivas.",
    5: "Lecturas de O2 inválidas consecutivas.",
    6: "Lecturas de temperatura inválidas consecutivas.",
    7: "Sensor de pH congelado.",
    8: "Sensor de O2 congelado.",
    9: "Temperatura congelada.",
    10: "Incoherencia entre O2 y temperatura.",
    11: "Fluctuación anómala pH.",
    12: "Fluctuación anómala O2.",
    13: "Error registrador.",
    14: "Error abrir serial.",
    15: "Error lectura serial.",
    16: "Error decodificación.",
    17: "Error DS18B20.",
    18: "Error enviar UDP.",
    19: "Error GPIO.",
    20: "Error general.",
}

# ==============================
# FUNCIONES AUXILIARES
# ==============================
def crear_nombre_archivo():
    fecha = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(DIRECTORIO, f"datos_{fecha}.csv")

def inicializar_archivo(nombre_archivo):
    encabezados = [
        "fecha", "hora",
        "a0", "pH", "a1", "OD",
        "PID_pH_DOWN", "PID_pH_UP", "PID_O2",
        "P_DOWN", "I_DOWN", "D_DOWN",
        "P_UP", "I_UP", "D_UP",
        "P_O2", "I_O2", "D_O2",
        "T", "t_on_down", "t_on_up", "t_on_o2",
        "codigo_error"
    ]

    if not os.path.exists(nombre_archivo):
        with open(nombre_archivo, "w", newline="") as f:
            csv.writer(f).writerow(encabezados)

def contar_lineas(nombre_archivo):
    try:
        with open(nombre_archivo, "r") as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0

def crear_socket_udp():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2.0)
    sock.bind((UDP_IP, UDP_PORT))
    return sock

# ==============================
# BASE DE DATOS
# ==============================
def inicializar_bd():
    conn = sqlite3.connect(DB_FILE, timeout=0.5)
    cur = conn.cursor()

    # Modo WAL para escritura concurrente
    cur.execute("PRAGMA journal_mode=WAL;")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS lecturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT,
        hora TEXT,
        ph REAL,
        o2 REAL,
        temp REAL,
        pid_ph_down REAL,
        pid_ph_up REAL,
        pid_o2 REAL,
        codigo_error TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS errores_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT NOT NULL,
        descripcion TEXT NOT NULL,
        hora_inicio TEXT,
        hora_fin TEXT,
        resuelto INTEGER DEFAULT 0,
        notificado_inicio INTEGER DEFAULT 0,
        notificado_fin INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notificaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL,
        mensaje TEXT NOT NULL,
        hora TEXT NOT NULL,
        leida INTEGER DEFAULT 0
    )
    """)

    conn.commit()
    conn.close()

def insertar_lectura(fila):
    try:
        conn = sqlite3.connect(DB_FILE, timeout=0.5)
        cur = conn.cursor()

        fecha, hora = fila[0], fila[1]
        ph = float(fila[3])
        o2 = float(fila[5])
        pid_ph_down = float(fila[6])
        pid_ph_up = float(fila[7])
        pid_o2 = float(fila[8])
        temp = float(fila[18])
        codigo_error = str(fila[-1])

        cur.execute("""
            INSERT INTO lecturas (fecha, hora, ph, o2, temp, pid_ph_down, pid_ph_up, pid_o2, codigo_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (fecha, hora, ph, o2, temp, pid_ph_down, pid_ph_up, pid_o2, codigo_error))

        conn.commit()
        conn.close()

    except Exception as e:
        print("[WARN BD] Error al insertar lectura:", e)

def registrar_cambios_de_error(nuevos, resueltos, ahora):
    ts = ahora.strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = sqlite3.connect(DB_FILE, timeout=0.5)
        cur = conn.cursor()

        # Nuevos errores
        for c in nuevos:
            desc = ERROR_DESCRIPCIONES.get(c, f"Error desconocido ({c})")
            cur.execute("""
                INSERT INTO errores_log (codigo, descripcion, hora_inicio)
                VALUES (?, ?, ?)
            """, (str(c), desc, ts))

        # Errores resueltos
        for c in resueltos:
            cur.execute("""
                UPDATE errores_log
                SET hora_fin = ?
                WHERE codigo = ? AND hora_fin IS NULL
            """, (ts, str(c)))

        conn.commit()
        conn.close()

    except Exception as e:
        print("[WARN BD] Error registrando cambios de error:", e)

# ==============================
# PROCESO PRINCIPAL
# ==============================
def registrar_datos():
    inicializar_bd()

    nombre_actual = crear_nombre_archivo()
    inicializar_archivo(nombre_actual)
    inicializar_archivo(ARCHIVO_FIJO)

    ultimo_error = set()
    ultimo_registro = 0
    datos_ultima_muestra = None
    sock = None

    while True:

        # Rotación diaria
        nombre_nuevo = crear_nombre_archivo()
        if nombre_nuevo != nombre_actual:
            nombre_actual = nombre_nuevo
            inicializar_archivo(nombre_actual)

        if sock is None:
            try:
                sock = crear_socket_udp()
            except:
                time.sleep(2)
                continue

        try:
            data, _ = sock.recvfrom(BUFFER_SIZE)
            partes = data.decode().strip().split(",")

            if len(partes) == 21:
                datos_ultima_muestra = partes

        except socket.timeout:
            pass

        except Exception:
            try: sock.close()
            except: pass
            sock = None
            continue

        if time.time() - ultimo_registro >= INTERVALO_REGISTRO and datos_ultima_muestra:

            ahora = datetime.now()
            fecha = ahora.strftime("%Y-%m-%d")
            hora = ahora.strftime("%H:%M:%S")

            fila = [fecha, hora] + datos_ultima_muestra

            try:
                # CSV diario
                with open(nombre_actual, "a", newline="") as f:
                    csv.writer(f).writerow(fila)

                # CSV fijo rotativo
                if contar_lineas(ARCHIVO_FIJO) >= MAX_LINEAS_FIJO:
                    inicializar_archivo(ARCHIVO_FIJO)

                with open(ARCHIVO_FIJO, "a", newline="") as f:
                    csv.writer(f).writerow(fila)

                # =========================
                # MANEJO DE ERRORES
                # =========================
                codigo_error = fila[-1]
                actual = set()

                if codigo_error != "0":
                    actual = {int(x) for x in codigo_error.split("|") if x.isdigit()}

                nuevos = actual - ultimo_error
                resueltos = ultimo_error - actual

                if nuevos or resueltos:
                    registrar_cambios_de_error(nuevos, resueltos, ahora)

                ultimo_error = actual

                insertar_lectura(fila)

            except Exception as e:
                print("[WARN] Registro fallido:", e)

            ultimo_registro = time.time()

        time.sleep(0.1)

if __name__ == "__main__":
    registrar_datos()
