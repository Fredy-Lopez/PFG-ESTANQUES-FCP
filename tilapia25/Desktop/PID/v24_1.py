# v24

# ===============================================
# CAMBIOS Y MEJORAS v24
# ===============================================
# 
# ===============================================

import serial
import time
from simple_pid import PID
import RPi.GPIO as GPIO 
from w1thermsensor import W1ThermSensor
import socket
import statistics
import subprocess
import os
import sys
import json 

errores_activos = set()     # conjunto de códigos de error activos
codigo_error_actual = 0     # último código de error enviado o registrado

# --- NUEVO: Estados de pausa manual de PIDs ---
pid_paused_ph = False       # True = PID pH detenido hasta confirmacion externa
pid_paused_o2 = False       # True = PID O2 detenido hasta confirmacion externa

# --- PRIORIDAD DE ERRORES ---
PRIORIDAD_ERRORES = {       # entre más bajo el número, mayor prioridad (error ,prioridad)
    0: 99,                  # sin error
    13: 1,                  # logger
    14: 1,                  # apertura de puerto serial
    15: 2,                  # lectura / reconexión serial
    16: 2,                  # error genérico serial
    17: 3,                  # DS18B20
    18: 4,                  # UDP
    19: 5,                  # GPIO
    20: 6,                  # bucle principal
    1: 10, 2: 10, 3: 10, 
    4: 11, 5: 11, 6: 11,
    7: 12, 8: 12, 9: 12,
    10: 13, 11: 14, 12: 14
}

# ==============================
# INICIO AUTOMÁTICO DEL REGISTRADOR CSV
# ==============================
def iniciar_logger_csv():
    """Inicia el script logger_3.py en segundo plano."""
    ruta_logger = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logger_3.py")
    try:
        subprocess.Popen(               # Lanza el proceso en segundo plano sin bloquear el script principal
            ["python3", ruta_logger],
            stdout=subprocess.DEVNULL,  # suprime salida estándar
            stderr=subprocess.DEVNULL   # suprime mensajes de error
        )
    except Exception as e:
        errores_activos.add(13)
        pass                            # Si falla el lanzamiento, el sistema principal continúa

iniciar_logger_csv()                    # Ejecutar el logger automáticamente al iniciar el sistema principal
time.sleep(1.0)                         # breve espera para que el logger se inicialice

# ==============================
sensor_ds18b20 = W1ThermSensor()        # Inicializa sensor de temperatura DS18B20
# ==============================
# CONFIGURACION SERIAL
# ==============================

SERIAL_PORT = '/dev/ttyACM0'
BAUD_RATE = 115200 

N_MUESTRAS = 5             # Número de muestras para promedio
CONVERSION_FACTOR = {
    'A0': 0.0001875,       # ±6.144 V (sensor 0–5 V)
    'A1': 0.000125         # ±4.096 V (sensor 0–3 V)
}
CANALES = ['A0', 'A1']
ALPHA_SUAVIZADO = 0.8      # Factor de suavizado exponencial
DELAY_MUESTREO = 0.05      # segundos entre iteraciones del bucle

# Lee temperatura cada X segundos (para no bloquear el bucle en cada iteración)
TEMP_READ_INTERVAL = 5.0   # segundos

# --- Estado interno de cache de temperatura ---
_last_temp_read = 0.0 
_temp_cache = 25.0 

# ==============================
# CONFIGURACION PID
# ==============================
Kp_o2, Ki_o2, Kd_o2 = 2.0, 0.5, 0.1                     # Ganancias O2
Kp_ph_up, Ki_ph_up, Kd_ph_up = 1.5, 0.5, 0.7            # Ganancias pH Up
Kp_ph_down, Ki_ph_down, Kd_ph_down = -2.0, -0.5, -0.7   # Ganancias pH Down

# --- Setpoints ---
setpoint_o2 = 5.0  # mg/L
SETPOINT_pH = 7.5 
setpoint_ph_up = SETPOINT_pH
setpoint_ph_down = SETPOINT_pH 

# --- Banda muerta ---
DEADBAND_O2 = 0.5  # mg/L
DEADBAND_PH = 0.4  # pH

# --- Objetos PID ---
pid_o2 = PID(Kp_o2, Ki_o2, Kd_o2, setpoint=setpoint_o2)
pid_ph_up = PID(Kp_ph_up, Ki_ph_up, Kd_ph_up, setpoint=setpoint_ph_up)
pid_ph_down = PID(Kp_ph_down, Ki_ph_down, Kd_ph_down, setpoint=setpoint_ph_down)

# --- Límites de salida ---
pid_o2.output_limits = (0, 100)
pid_ph_up.output_limits = (0, 100)
pid_ph_down.output_limits = (0, 100)

# ============================== 
# CONFIGURACIÓN UDP/TCP
# ==============================
UDP_IP = "127.0.0.1"            # localhost
UDP_PORT_GUI = 5005             # Puerto destino GUI
UDP_PORT_LOGGER = 5006          # Puerto destino logger.py
UDP_PORT_FLASK = 6000 			# Puerto destino app.py flask
TCP_PORT = 5010                 # Puerto para recepción de comandos (TCP)
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp_socket.setblocking(False)   # No bloquear si no hay cliente

# --- Socket TCP para recepción de comandos desde el sitio web ---
tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
tcp_socket.bind((UDP_IP, TCP_PORT))
tcp_socket.listen(1)
tcp_socket.setblocking(False)

# ==============================
# CALIBRACION SENSOR OXIGENO (dos puntos)
# ==============================
# --- Voltajes medidos durante calibracion (mV) y temperaturas (°C) ---
CAL1_V, CAL1_T = 1600, 25 
CAL2_V, CAL2_T = 1300, 15

# --- Tabla de oxígeno saturado según temperatura (μg/L) ---
DO_Table = [ 
    14460, 14220, 13820, 13440, 13090, 12740, 12420, 12110, 11810, 11530,
    11260, 11010, 10770, 10530, 10300, 10080, 9860, 9660, 9460, 9270,
    9080, 8900, 8730, 8570, 8410, 8250, 8110, 7960, 7820, 7690,
    7560, 7430, 7300, 7180, 7070, 6950, 6840, 6730, 6630, 6530, 6410
]

# ==============================
# FUNCIONES SERIAL
# ==============================
def conectar_serial():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        time.sleep(3)
        print(f"[OK] Puerto serial abierto: {SERIAL_PORT} a {BAUD_RATE} bps")
        return ser
    except Exception as e:
        errores_activos.add(14)
        print(f"[ERROR] No se pudo abrir el puerto serial: {e}")
        return None

ser = None
while ser is None:
    ser = conectar_serial()
    if ser is None:
        print("[WARN] No hay dispositivo conectado. Reintentando en 5 segundos...")
        time.sleep(5)

def leer_linea_ultima():
    """
    Drena el buffer serial y devuelve SOLO la última línea válida disponible.
    Si no hay datos, retorna None sin bloquear el bucle.
    """
    global ser
    try:
        if ser.in_waiting == 0:
            return None  # nada que leer ahora

        last_line = None
        max_reads = 200
        reads = 0

        while ser.in_waiting > 0 and reads < max_reads:
            raw = ser.readline()
            if not raw:
                break
            linea = raw.decode('utf-8', errors='ignore').strip()
            if linea:
                last_line = linea
            reads += 1

        if not last_line:
            return None

        partes = last_line.split(',')
        if len(partes) != len(CANALES):
            return None

        valores = {canal: int(val) for canal, val in zip(CANALES, partes)}
        return valores

    except (serial.SerialException, OSError) as e:
        errores_activos.add(15)
        print(f"[ERROR] Puerto serial: {e}. Intentando reconectar...")
        try:
            ser.close()
        except:
            pass
        ser = None
        while ser is None:
            time.sleep(2)
            ser = conectar_serial()
        return None
    except Exception as e:
        errores_activos.add(16)
        print(f"[ERROR] leer_linea_ultima: {e}")
        return None

# ==============================
# FUNCIONES DE PROCESAMIENTO
# ==============================
def promedio_acumulador(acumulador, n_muestras):
    return {canal: suma / n_muestras for canal, suma in acumulador.items()}

def voltaje_acumulador(promedio):
    return {canal: val * CONVERSION_FACTOR[canal] for canal, val in promedio.items()}

def suavizado_exponencial(valor_actual, valor_anterior, alpha=ALPHA_SUAVIZADO):
    if valor_anterior is None:
        return valor_actual
    return alpha * valor_actual + (1 - alpha) * valor_anterior

# ==============================
# FUNCIONES DE TEMPERATURA 
# ==============================
def leer_temperatura():
    """Lee la temperatura actual del DS18B20 en °C como float."""
    try:
        temperatura = sensor_ds18b20.get_temperature()
        return temperatura
    except Exception as e:
        errores_activos.add(17)
        print(f"[ERROR] No se pudo leer DS18B20: {e}")
        return 25.0

def temperatura_a_entero(temp):
    """Convierte la temperatura float a un entero entre 0 y 40 para indexar DO_Table."""
    temp_entero = int(round(temp))
    if temp_entero < 0:
        temp_entero = 0
    elif temp_entero > 40:
        temp_entero = 40
    return temp_entero

def leer_temperatura_cached():
    """Cache de temperatura para evitar bloqueos por lectura frecuente."""
    global _last_temp_read, _temp_cache
    ahora = time.time()
    if (ahora - _last_temp_read) >= TEMP_READ_INTERVAL:
        t = leer_temperatura()
        _temp_cache = t
        _last_temp_read = ahora
    return _temp_cache

# ==============================
# CONVERSION VOLTAJE → OXIGENO DISUELTO (mg/L)
# ==============================
def voltaje_a_DO(voltaje_mv, temperatura_c):
    # --- Limitar temperatura al rango de la tabla ---
    if temperatura_c < 0:
        temperatura_c = 0
    elif temperatura_c > 40:
        temperatura_c = 40

    # --- Voltaje de saturación interpolado según la temperatura ---
    V_saturacion = ((temperatura_c - CAL2_T) * (CAL1_V - CAL2_V) / (CAL1_T - CAL2_T)) + CAL2_V

    # --- Interpolación lineal de DO_Table usando temperatura decimal ---
    lower_index = int(temperatura_c)
    upper_index = min(lower_index + 1, 40)
    fraction = temperatura_c - lower_index

    DO_lower = DO_Table[lower_index]
    DO_upper = DO_Table[upper_index]
    DO_interp = DO_lower + (DO_upper - DO_lower) * fraction  # μg/L

    # --- Ajustar según voltaje ---
    DO_ug_L = voltaje_mv * DO_interp / V_saturacion
    DO_mg_L = DO_ug_L / 1000.0
    return DO_mg_L

# ==============================
# ACTUALIZAR PID (PID Y CONTROL)
# ==============================
def actualizar_pid(pH_compensado, OD_compensado):
    global pid_paused_ph, pid_paused_o2

    # --- pH subida ---
    error_up = setpoint_ph_up - pH_compensado
    if pid_paused_ph:
        pid_ph_up.auto_mode = False
        control_ph_up = 0
    else:
        if abs(error_up) <= DEADBAND_PH:
            pid_ph_up.auto_mode = False
            control_ph_up = 0
        elif error_up > 0:
            pid_ph_up.auto_mode = True
            pid_ph_down.auto_mode = False
            control_ph_up = pid_ph_up(pH_compensado)
        else:
            pid_ph_up.auto_mode = False
            control_ph_up = 0

    # --- pH bajada ---
    error_down = pH_compensado - setpoint_ph_down
    if pid_paused_ph:
        pid_ph_down.auto_mode = False
        control_ph_down = 0
    else:
        if abs(error_down) <= DEADBAND_PH:
            pid_ph_down.auto_mode = False
            control_ph_down = 0
        elif error_down > 0:
            pid_ph_down.auto_mode = True
            pid_ph_up.auto_mode = False
            control_ph_down = pid_ph_down(pH_compensado)
        else:
            pid_ph_down.auto_mode = False
            control_ph_down = 0

    # --- O2 ---
    if pid_paused_o2:
        pid_o2.auto_mode = False
        control_o2 = 0
    else:
        if abs(OD_compensado - setpoint_o2) <= DEADBAND_O2:
            pid_o2.auto_mode = False
            control_o2 = 0
        else:
            pid_o2.auto_mode = True
            control_o2 = pid_o2(OD_compensado)

    return control_ph_down, control_ph_up, control_o2

# ==============================
# CONFIGURACION PINS RELES
# ==============================
RELAY_PIN_PH_UP = 17    # GPIO para subir ph
RELAY_PIN_PH_DOWN = 27  # GPIO para bajar ph
RELAY_PIN_O2 = 10       # GPIO para controlar O2
# --- Pines para controlar el temporizador 555 
GPIO_TRIGGER = 23 # Para disparar el temporizador 555
GPIO_RESET   = 24 # Para resetear el temporizador 555

GPIO.setmode(GPIO.BCM)
GPIO.setup(RELAY_PIN_PH_UP, GPIO.OUT)
GPIO.setup(RELAY_PIN_PH_DOWN, GPIO.OUT) 
GPIO.setup(RELAY_PIN_O2, GPIO.OUT)

GPIO.setup(GPIO_TRIGGER, GPIO.OUT)
GPIO.setup(GPIO_RESET, GPIO.OUT)

# Estado inicial seguro (todo apagado / sin disparar)
GPIO.output(RELAY_PIN_PH_UP, GPIO.LOW)
GPIO.output(RELAY_PIN_PH_DOWN, GPIO.LOW)
GPIO.output(RELAY_PIN_O2, GPIO.LOW)

# El 555 está en reposo con TRIGGER y RESET en HIGH
GPIO.output(GPIO_TRIGGER, GPIO.HIGH)
GPIO.output(GPIO_RESET, GPIO.HIGH)


# ==============================
# LÓGICA 555 – FLANCOS PARA TRIGGER Y RESET
# ==============================

# Estados previos para detectar flancos (inicialmente LOW)
prev_ph_up  = False     # False = LOW, True = HIGH
prev_ph_down = False    # igual

# ===============================
# Funciones para enviar pulsos a TRIGGER y RESET
# ===============================
def pulso_trigger():
    """Envía un pulso corto al TRIGGER (flanco descendente)."""
    GPIO.output(GPIO_TRIGGER, GPIO.LOW)
    time.sleep(0.03)
    GPIO.output(GPIO_TRIGGER, GPIO.HIGH)


def pulso_reset():
    """Envía un pulso corto al RESET (flanco descendente)."""
    GPIO.output(GPIO_RESET, GPIO.LOW)
    time.sleep(0.03)
    GPIO.output(GPIO_RESET, GPIO.HIGH)
pulso_reset() # Resetea al iniciar

def logica_temporizador_555(ph_up_on, ph_down_on):
    """
    Detecta flancos ascendentes y descendentes en pH Up y pH Down.
    Maneja TRIGGER y RESET del 555 según la lógica real del circuito.
    """
    global prev_ph_up, prev_ph_down

    # --- Señales actuales ---
    current_up = ph_up_on     # True o False
    current_down = ph_down_on

    # ========================================
    #   1) FLANCO ASCENDENTE → RESET
    # ========================================
    if current_up and not prev_ph_up:
        pulso_reset()

    if current_down and not prev_ph_down:
        pulso_reset()

    # ========================================
    #   2) FLANCO DESCENDENTE → TRIGGER
    # ========================================
    if prev_ph_up and not current_up:
        pulso_trigger()

    if prev_ph_down and not current_down:
        pulso_trigger()

    # Actualizar estados previos
    prev_ph_up = current_up
    prev_ph_down = current_down


# ==============================
# CONFIGURACIÓN DEL CONTROL MANUAL Y SEGURIDAD DE pH
# ==============================
# --- Parámetros ajustables ---
CAUDAL_BOMBA_ML_MIN = 70.0                  # Caudal nominal de las bombas (ml/min)
TIEMPO_MAX_O2 = 300.0                       # Tiempo máximo de activación manual del O2 (segundos)
DOSIFICACIONES_PH_UP = [10.0, 20.0, 40.0]   # Volúmenes predefinidos para subir el pH (ml)
DOSIFICACIONES_PH_DOWN = [10.0, 20.0, 40.0] # Volúmenes predefinidos para bajar el pH (ml)
COOLDOWN_PH_SEG = 3600                      # Tiempo mínimo entre dosificaciones (1 hora)

# --- Límites de variación permitidos ---
DELTA_PH_MAX_HORA = 0.10                    # Máximo cambio permitido por hora
DELTA_PH_MAX_DIA = 0.50                     # Máximo cambio permitido por día

# --- Variables de estado ---
tareas_manual = []                          # Lista de acciones manuales pendientes o en curso
ultimo_ph_up = 0.0                          # Hora (timestamp) de la última dosificación pH↑
ultimo_ph_down = 0.0                        # Hora (timestamp) de la última dosificación pH↓
bloqueo_seguridad_ph = False                # True = Bloqueo por exceso de variación de pH

# ==============================
# CICLOS Y UMBRALES DE ACTUACION (en segundos)
# ==============================
CICLO_PH_UP = 2.0
CICLO_PH_DOWN = 2.0
CICLO_O2 = 2.0

MIN_ACTUACION_PH_UP = 0.2
MIN_ACTUACION_PH_DOWN = 0.2
MIN_ACTUACION_O2 = 0.2

inicio_ciclo_ph_up = time.time()
inicio_ciclo_ph_down = time.time()
inicio_ciclo_o2 = time.time()

def pin_en_tarea_manual(pin):
    """
    Devuelve True si el pin está siendo usado por alguna tarea manual
    (pH↑, pH↓ u O2).
    """
    return any(t["pin"] == pin for t in tareas_manual)


def control_por_tiempo(salida_pid, inicio_ciclo, ciclo, pin, min_actuacion=0.0):
    """
    Controla el relé por tiempo proporcional a la salida PID.
    Devuelve el nuevo inicio de ciclo y el tiempo de activación (s).
    """
    try:
        tiempo_on = (salida_pid / 100.0) * ciclo
        if tiempo_on < min_actuacion:
            tiempo_on = 0
        tiempo_transcurrido = time.time() - inicio_ciclo
        if tiempo_transcurrido >= ciclo:
            inicio_ciclo += ciclo
            tiempo_transcurrido -= ciclo
        if tiempo_transcurrido < tiempo_on:
            GPIO.output(pin, GPIO.HIGH)
        else:
            GPIO.output(pin, GPIO.LOW)
        return inicio_ciclo, tiempo_on
    except Exception as e:
        errores_activos.add(19)
        print(f"[ERROR GPIO] {e}")
        return inicio_ciclo, 0

# ==============================
# PROCESAR LECTURAS
# ==============================
def procesar_lectura(lectura, acumulador, contador):
    for canal in CANALES:
        acumulador[canal] += lectura[canal]
    contador += 1
    if contador >= N_MUESTRAS:
        promedio = promedio_acumulador(acumulador, N_MUESTRAS)
        acumulador = {canal: 0 for canal in CANALES}
        contador = 0
        return promedio, True, acumulador, contador
    return None, False, acumulador, contador

# ==============================
# CONVERTIR Y COMPENSAR LECTURAS
# ==============================
def convertir_y_compensar(promedio, voltaje_suavizado):
    voltaje = voltaje_acumulador(promedio)
    for canal in CANALES:
        voltaje_suavizado[canal] = suavizado_exponencial(
            voltaje[canal],
            voltaje_suavizado[canal]
        )
    voltaje_a0 = voltaje_suavizado['A0']
    voltaje_a1 = voltaje_suavizado['A1']
    temperatura_float = leer_temperatura_cached()
    temperatura_actual = temperatura_a_entero(temperatura_float)
    OD_compensado = voltaje_a_DO(voltaje_a1 * 1000, temperatura_float)
    T_kelvin = temperatura_actual + 273.15
    a25 = -5.7
    b = 21.34
    aT = a25 * (T_kelvin / 298.15)
    pH_compensado = aT * voltaje_a0 + b
    return voltaje_a0, voltaje_a1, pH_compensado, OD_compensado, temperatura_float, voltaje_suavizado

# ==============================
# MOSTRAR DATOS EN CONSOLA
# ==============================
def mostrar_datos_consola(voltaje_a0, voltaje_a1, pH_compensado, OD_compensado,
                          control_ph_down, control_ph_up, control_o2,
                          pid_ph_up, pid_ph_down, pid_o2, temperatura_float, ser, errores_udp_str):
    p_up, i_up, d_up = pid_ph_up.components
    p_down, i_down, d_down = pid_ph_down.components
    p_o2, i_o2, d_o2 = pid_o2.components
    '''print(
        f"a0:{voltaje_a0:.2f},pH:{pH_compensado:.2f},a1:{voltaje_a1:.2f},O2:{OD_compensado:.2f},"
        f"o_pH_down:{control_ph_down:.2f},o_pH_up:{control_ph_up:.2f},o_O2:{control_o2:.2f}"
        f"[pH UP] P:{p_up:.2f},I:{i_up:.2f},D:{d_up:.2f}"
        f"[pH DOWN] P:{p_down:.2f},I:{i_down:.2f},D:{d_down:.2f}"
        f"[O2] P:{p_o2:.2f},I:{i_o2:.2f},D:{d_o2:.2f},"
        f"T:{temperatura_float:.1f}°C,Error:{errores_udp_str}"
    )'''
    #print(f"[DEBUG] in_waiting={ser.in_waiting}")

    print(
            f"a0:{voltaje_a0:.2f},pH:{pH_compensado:.2f},a1:{voltaje_a1:.2f},O2:{OD_compensado:.2f},"
            f"o_pH_down:{control_ph_down:.2f},o_pH_up:{control_ph_up:.2f},o_O2:{control_o2:.2f},"
            f"T:{temperatura_float:.1f}°C,Error:{errores_udp_str}"
        )

# ==============================
# ENVIAR DATOS VIA UDP
# ==============================
def enviar_datos_udp(voltaje_a0, voltaje_a1, pH_compensado, OD_compensado,
                     control_ph_down, control_ph_up, control_o2,
                     pid_ph_up, pid_ph_down, pid_o2, temperatura_float,
                     tiempo_on_up, tiempo_on_down, tiempo_on_o2, errores_udp_str):
    """Envía los datos en formato CSV mediante UDP, incluyendo tiempos de activación."""
    p_up, i_up, d_up = pid_ph_up.components
    p_down, i_down, d_down = pid_ph_down.components
    p_o2, i_o2, d_o2 = pid_o2.components

    mensaje = (
        f"{voltaje_a0:.4f},{pH_compensado:.4f},{voltaje_a1:.4f},{OD_compensado:.4f},"
        f"{control_ph_down:.2f},{control_ph_up:.2f},{control_o2:.2f},"
        f"{p_down:.4f},{i_down:.4f},{d_down:.4f},"
        f"{p_up:.4f},{i_up:.4f},{d_up:.4f},"
        f"{p_o2:.4f},{i_o2:.4f},{d_o2:.4f},"
        f"{temperatura_float:.2f},"
        f"{tiempo_on_down:.3f},{tiempo_on_up:.3f},{tiempo_on_o2:.3f},"
        f"{errores_udp_str}"
    ).encode("utf-8")

    try:
        udp_socket.sendto(mensaje, (UDP_IP, UDP_PORT_GUI))      # Enviar a GUI
        udp_socket.sendto(mensaje, (UDP_IP, UDP_PORT_LOGGER))   # Enviar al registrador
    except Exception as e:
        errores_activos.add(18)
        print(f"[WARN UDP] No se pudo enviar el paquete: {e}")
# ==============================
# ENVIAR DATOS VIA UDP A FLASK
# ==============================
def enviar_estado_udp_flask(estado_json):
    try:
        udp_socket.sendto(estado_json.encode(), (UDP_IP, UDP_PORT_FLASK))
    except Exception as e:
        print("[WARN UDP → Flask]", e)

# ==============================
# RECEPCIÓN DE COMANDOS TCP [EXTENDIDA]
# ==============================
def escuchar_confirmacion_tcp():
    """
    Escucha comandos externos por TCP para reanudar o pausar PIDs,
    y ejecutar acciones manuales seguras mediante códigos numéricos.
      - 1 = reanudar PID pH
      - 2 = reanudar PID O2
      - 3 = reanudar ambos
      - 4 = desactivar PID pH
      - 5 = desactivar PID O2
      - 6 = detener todos los actuadores manuales
      - 7 <tiempo> = activar aireadores (O2) por <tiempo> segundos
      - 8 <preset> = dosificar pH↑ (según volumen predefinido)
      - 9 <preset> = dosificar pH↓ (según volumen predefinido)
    """
    global pid_paused_ph, pid_paused_o2                       # estados de pausa de PIDs
    global ultimo_ph_up, ultimo_ph_down, bloqueo_seguridad_ph # cooldown y bloqueo seguridad
    global prev_ph_down, prev_ph_up                     # estados previos para 555

    try:
        conn = None
        try:
            conn, addr = tcp_socket.accept()   # Acepta conexión entrante (no bloqueante)
            conn.settimeout(1.0)               # Recv con timeout para evitar bloqueos
            data = conn.recv(1024)             # Recibe el comando enviado por el cliente
            if not data:                       # Si no hay datos, cerrar conexión
                conn.close()
                return
            comando = data.decode().strip()    # Convierte los bytes a texto
            conn.close()                       # Cierra la conexión TCP luego de recibir el comando
        except BlockingIOError:
            return

        partes = comando.split()               # Divide el comando en partes (separado por espacios)
        codigo = partes[0]                     # Toma el codigo de comando 
        valor = partes[1] if len(partes) > 1 else None # Toma el valor adicional si existe
        ahora = time.time()                    # tiempo actual

        # --- Reanudar PIDs ---
        if codigo == "1":
            pid_paused_ph = False
            print("[TCP] Reanudado PID pH")

        elif codigo == "2":
            pid_paused_o2 = False
            print("[TCP] Reanudado PID O2")

        elif codigo == "3":
            pid_paused_ph = False
            pid_paused_o2 = False
            print("[TCP] Reanudados ambos PID")

        # 4 = Desactivar PID de pH
        elif codigo == "4":
            pid_ph_up.auto_mode = False
            pid_ph_down.auto_mode = False
            pid_paused_ph = True
            print("[TCP] PID de pH desactivado manualmente.")

        # 5 = Desactivar PID de O2
        elif codigo == "5":
            pid_o2.auto_mode = False
            pid_paused_o2 = True
            print("[TCP] PID de O2 desactivado manualmente.")

        # 6 = STOP (parcial o total)
        elif codigo == "6":

			# Si viene con un parámetro, decidir acción
            modo = str(valor) if valor is not None else "0"

			# ----------------------------
			# 6 1 → Detener SOLO aireador
			# ----------------------------
            if modo == "1":
                GPIO.output(RELAY_PIN_O2, GPIO.LOW)
            # eliminar tareas O2 activas
                tareas_manual[:] = [t for t in tareas_manual if t["tipo"] != "O2"]
                print("[MANUAL] Aireadores detenidos (6 1).")
                return

			# ----------------------------
			# 6 2 → PARADA DE EMERGENCIA
			# ----------------------------
            if modo == "2":
                GPIO.output(RELAY_PIN_O2, GPIO.LOW)
                GPIO.output(RELAY_PIN_PH_UP, GPIO.LOW)
                GPIO.output(RELAY_PIN_PH_DOWN, GPIO.LOW)
                GPIO.output(GPIO_TRIGGER, GPIO.HIGH)
                pulso_reset()
                prev_ph_up = False
                prev_ph_down = False

                tareas_manual.clear()

                # Mantener PIDs en manual pero quietos
                pid_o2.auto_mode = False
                pid_ph_up.auto_mode = False
                pid_ph_down.auto_mode = False

                pid_paused_o2 = True
                pid_paused_ph = True

                print("[EMERGENCIA] Parada TOTAL — todos los actuadores apagados (6 2).")
                return

            # Si el usuario manda solo "6" → tratar como parada total
            GPIO.output(RELAY_PIN_O2, GPIO.LOW)
            GPIO.output(RELAY_PIN_PH_UP, GPIO.LOW)
            GPIO.output(RELAY_PIN_PH_DOWN, GPIO.LOW)
            GPIO.output(GPIO_TRIGGER, GPIO.HIGH)
            pulso_reset()
            
            prev_ph_up = False
            prev_ph_down = False

            tareas_manual.clear()
            pid_o2.auto_mode = False
            pid_ph_up.auto_mode = False
            pid_ph_down.auto_mode = False

            pid_paused_o2 = True
            pid_paused_ph = True

            print("[MANUAL] '6' recibido sin parámetro → parada total por seguridad.")


        # 7 = Activar O2 manualmente por <tiempo> segundos
        elif codigo == "7" and valor:                # Formato de recepción "7 30" para 30 segundos
            try:
                tiempo = float(valor)                # Convierte valor a float
            except:
                print("[MANUAL] Valor de tiempo inválido para O2.")
                return
            tiempo = min(max(tiempo, 0.0), TIEMPO_MAX_O2) # limitar al máximo
            pid_o2.auto_mode = False                      # desactivar PID O2
            pid_paused_o2 = True                          # pausar PID O2
            if any(t["pin"] == RELAY_PIN_O2 for t in tareas_manual): # Verificar si ya hay una tarea activa
                print("[MANUAL] O2 ya tiene una tarea activa. Comando ignorado.")
                return
            tareas_manual.append({
                "tipo": "O2",                             # tipo de tarea
                "pin": RELAY_PIN_O2,                      # pin a activar
                "t_fin": ahora + tiempo                   # tiempo de finalización (tiempo actual + duración)
            })
            print(f"[MANUAL] Aireador activado durante {tiempo:.1f} segundos.")

        # 8 = Dosificación pH↑ (preset)
        elif codigo == "8" and valor: # formato de recepción "8 1" para preset 1
            if bloqueo_seguridad_ph:  # Verificar si el sistema está bloqueado por seguridad
                print("[MANUAL] Bloqueo de seguridad pH activo. Comando rechazado.")
                return
            try:
                preset = int(valor)   # convertir a entero
            except:
                print("[MANUAL] Preset no válido para pH↑.")
                return
            if not (0 <= preset < len(DOSIFICACIONES_PH_UP)):   # Verificar que el numero de preset esté en rango
                print("[MANUAL] Preset fuera de rango para pH↑.")
                return
            if ahora - ultimo_ph_up < COOLDOWN_PH_SEG:          # Verificar cooldown
                espera = COOLDOWN_PH_SEG - (ahora - ultimo_ph_up)
                print(f"[MANUAL] pH↑ en enfriamiento ({espera/60:.1f} min restantes).")
                return
                
            # 🔒 Cooldown cruzado – si pH↓ está en cooldown también bloquear
            if ahora - ultimo_ph_down < COOLDOWN_PH_SEG:
                espera = COOLDOWN_PH_SEG - (ahora - ultimo_ph_down)
                print(f"[MANUAL] pH↑ bloqueado por cooldown de pH↓ ({espera/60:.1f} min restantes).")
                return

            ml = DOSIFICACIONES_PH_UP[preset]          # volumen a dosificar (ml)
            duracion = ml_a_segundos(ml)               # Convertir ml a segundos
            pid_ph_up.auto_mode = False                # Desactivar PID de pH↑
            pid_ph_down.auto_mode = False              # Desactivar PID de pH↓
            pid_paused_ph = True                       # Pausar PID de pH
            if any(t["pin"] == RELAY_PIN_PH_UP for t in tareas_manual): # Verificar si ya hay una tarea activa
                print("[MANUAL] pH↑ ya tiene una tarea activa. Comando ignorado.")
                return
            tareas_manual.append({
                "tipo": "pH↑",                         # Tipo de tarea
                "pin": RELAY_PIN_PH_UP,                # Pin a activar
                "t_fin": ahora + duracion              # Tiempo de finalización
            })
            ultimo_ph_up = ahora                       # Actualizar tiempo de última dosificación
            print(f"[MANUAL] pH↑ preset {preset} → {ml:.1f} ml ({duracion:.1f}s).")

        # 9 = Dosificación pH↓ (analogo al anterior) 
        elif codigo == "9" and valor: 
            if bloqueo_seguridad_ph:
                print("[MANUAL] Bloqueo de seguridad pH activo. Comando rechazado.")
                return
            try:
                preset = int(valor)
            except:
                print("[MANUAL] Preset no válido para pH↓.")
                return
            if not (0 <= preset < len(DOSIFICACIONES_PH_DOWN)):
                print("[MANUAL] Preset fuera de rango para pH↓.")
                return
            if ahora - ultimo_ph_down < COOLDOWN_PH_SEG:
                espera = COOLDOWN_PH_SEG - (ahora - ultimo_ph_down)
                print(f"[MANUAL] pH↓ en enfriamiento ({espera/60:.1f} min restantes).")
                return
                
            # Bloqueo cruzado: si pH↑ está en cooldown, bloquear pH↓ también
            if ahora - ultimo_ph_up < COOLDOWN_PH_SEG:
                espera = COOLDOWN_PH_SEG - (ahora - ultimo_ph_up)
                print(f"[MANUAL] pH↓ bloqueado por cooldown de pH↑ ({espera/60:.1f} min restantes).")
                return


            ml = DOSIFICACIONES_PH_DOWN[preset]
            duracion = ml_a_segundos(ml)
            pid_ph_up.auto_mode = False
            pid_ph_down.auto_mode = False
            pid_paused_ph = True
            if any(t["pin"] == RELAY_PIN_PH_DOWN for t in tareas_manual):
                print("[MANUAL] pH↓ ya tiene una tarea activa. Comando ignorado.")
                return
            tareas_manual.append({
                "tipo": "pH↓",
                "pin": RELAY_PIN_PH_DOWN,
                "t_fin": ahora + duracion
            })
            ultimo_ph_down = ahora
            print(f"[MANUAL] pH↓ preset {preset} → {ml:.1f} ml ({duracion:.1f}s).")

    except Exception as e:
        print(f"[WARN TCP] {e}")

# ==============================
# ACTUALIZAR ACTUADORES
# ==============================
def actualizar_actuadores(control_ph_up, control_ph_down, control_o2,
                          inicio_ciclo_ph_up, inicio_ciclo_ph_down, inicio_ciclo_o2):
    """
    Actualiza los relés de pH↑, pH↓ y O2 según:
      - Salidas PID (modo automático)
      - Tareas manuales (si las hay, tienen prioridad y el PID NO toca ese pin)
    Además, actualiza la lógica del temporizador 555 en base al estado real
    de los relés de pH.
    """

    # ---- pH UP ----
    if not pin_en_tarea_manual(RELAY_PIN_PH_UP):
        # Solo si NO hay tarea manual para este pin, aplica el PWM del PID
        inicio_ciclo_ph_up, tiempo_on_up = control_por_tiempo(
            control_ph_up,
            inicio_ciclo_ph_up,
            CICLO_PH_UP,
            RELAY_PIN_PH_UP,
            MIN_ACTUACION_PH_UP
        )
    else:
        # Hay una tarea manual activa → NO tocar el pin desde el PID
        tiempo_on_up = 0.0

    # ---- pH DOWN ----
    if not pin_en_tarea_manual(RELAY_PIN_PH_DOWN):
        inicio_ciclo_ph_down, tiempo_on_down = control_por_tiempo(
            control_ph_down,
            inicio_ciclo_ph_down,
            CICLO_PH_DOWN,
            RELAY_PIN_PH_DOWN,
            MIN_ACTUACION_PH_DOWN
        )
    else:
        tiempo_on_down = 0.0

    # ---- O2 ----
    if not pin_en_tarea_manual(RELAY_PIN_O2):
        inicio_ciclo_o2, tiempo_on_o2 = control_por_tiempo(
            control_o2,
            inicio_ciclo_o2,
            CICLO_O2,
            RELAY_PIN_O2,
            MIN_ACTUACION_O2
        )
    else:
        tiempo_on_o2 = 0.0

    # ---------------------------------------------
    #  LÓGICA DEL 555 (se ejecuta SIEMPRE)
    #  - Lee el estado real actual de los relés, ya
    #    sea por manual o por automático.
    # ---------------------------------------------
    ph_up_on = GPIO.input(RELAY_PIN_PH_UP) == GPIO.HIGH
    ph_down_on = GPIO.input(RELAY_PIN_PH_DOWN) == GPIO.HIGH

    logica_temporizador_555(ph_up_on, ph_down_on)

    # Retornar tiempos (como antes)
    return (
        inicio_ciclo_ph_up,
        inicio_ciclo_ph_down,
        inicio_ciclo_o2,
        tiempo_on_up,
        tiempo_on_down,
        tiempo_on_o2,
    )

# ==============================
# FUNCIONES AUXILIARES DEL CONTROL MANUAL Y SEGURIDAD DE pH [NUEVO]
# ==============================
def ml_a_segundos(ml):
    """
    Convierte una cantidad de mililitros en el tiempo (segundos)
    que debe permanecer activa la bomba, en base al caudal nominal.
    """
    return (ml / CAUDAL_BOMBA_ML_MIN) * 60.0

def monitorear_seguridad_ph(ph_actual):
    """
    Supervisa la variación del pH a lo largo del tiempo.
    Si el cambio supera los límites establecidos por hora o por día,
    activa el bloqueo de seguridad e inhabilita el PID y el control manual de pH.
    """
    global bloqueo_seguridad_ph, pid_paused_ph

    # Inicialización de referencias la primera vez que se llama
    if not hasattr(monitorear_seguridad_ph, "ph_base_hora"): # corroborar si es la primera llamada
        monitorear_seguridad_ph.ph_base_hora = ph_actual     # valor base hora
        monitorear_seguridad_ph.ph_base_dia = ph_actual      # valor base día
        monitorear_seguridad_ph.t_base_hora = time.time()    # tiempo base hora
        monitorear_seguridad_ph.t_base_dia = time.time()     # tiempo base día
        return

    ahora = time.time()   # tiempo actual

    # --- Control por hora ---
    if ahora - monitorear_seguridad_ph.t_base_hora >= 3600:                 # verifica cada hora 
        variacion_h = abs(ph_actual - monitorear_seguridad_ph.ph_base_hora) # variación en la última hora
        if variacion_h > DELTA_PH_MAX_HORA and not bloqueo_seguridad_ph:    # si supera el límite
            bloqueo_seguridad_ph = True                                     # activar bloqueo
            pid_paused_ph = True                                            # pausar PID pH
            print(f"[SEGURIDAD pH] Límite horario superado ({variacion_h:.2f}) → bloqueo activado.")
        monitorear_seguridad_ph.ph_base_hora = ph_actual                    # actualizar base hora
        monitorear_seguridad_ph.t_base_hora = ahora                         # actualizar tiempo base hora

    # --- Control por día (analogo al anterior) ---
    if ahora - monitorear_seguridad_ph.t_base_dia >= 86400:  # verifica cada día 
        variacion_d = abs(ph_actual - monitorear_seguridad_ph.ph_base_dia)
        if variacion_d > DELTA_PH_MAX_DIA and not bloqueo_seguridad_ph:
            bloqueo_seguridad_ph = True
            pid_paused_ph = True
            print(f"[SEGURIDAD pH] Límite diario superado ({variacion_d:.2f}) → bloqueo activado.")
        monitorear_seguridad_ph.ph_base_dia = ph_actual
        monitorear_seguridad_ph.t_base_dia = ahora

# ==============================
# PROCESADOR DE TAREAS MANUALES (NO BLOQUEANTE) [NUEVO]
# ==============================
def procesar_tareas_manuales(tiempo_actual):
    """
    Supervisa las tareas manuales activas.
    Si el tiempo de activación ha finalizado, apaga el relé correspondiente.
    Mientras una tarea esté activa, el PID asociado permanece desactivado.
    """
    global tareas_manual

    tareas_activas = []          # Lista temporal para mantener solo las tareas en curso

    for tarea in tareas_manual:  # Recorre las tareas activas
        tipo = tarea["tipo"]     # 'pH_UP', 'pH_DOWN' o 'O2'
        pin = tarea["pin"]       # Pin GPIO asociado
        fin = tarea["t_fin"]     # Tiempo de finalización

        # Si el relé aún no está encendido
        ''' 
        Solo se ejecuta una vez por tarea en el primer ciclo despues de 
        crearla, en los siguientes ciclos el rele ya esta activado, asi 
        que esta linea se salta automaticamente
        '''
        if GPIO.input(pin) == GPIO.LOW: 
            GPIO.output(pin, GPIO.HIGH)
            print(f"[MANUAL] {tipo} activado.")

        # Verifica si ya transcurrió el tiempo asignado
        '''
        Si ya paso el tiempo, se apaga el rele y se imprime finalizado 
        '''
        if tiempo_actual >= fin:
            GPIO.output(pin, GPIO.LOW)
            print(f"[MANUAL] {tipo} finalizado.")
        else:
            tareas_activas.append(tarea) # si todavia no terminó se vuelve a guardar en tareas_activas

    tareas_manual = tareas_activas  # Actualiza la lista con las tareas que siguen en ejecución

# ==============================
# GESTIONAR PIDS SEGUN ERRORES
# ==============================
def gestionar_pids_por_error(errores_activos):
    global pid_paused_ph, pid_paused_o2
    global prev_ph_up, prev_ph_down
    errores_ph = {1, 4, 7, 11} 
    errores_o2 = {2, 5, 8, 12}
    errores_temp = {3, 6, 9, 10}

    # --- pH ---
    if errores_activos & errores_ph:
        pid_ph_up.auto_mode = False
        pid_ph_down.auto_mode = False
        GPIO.output(RELAY_PIN_PH_UP, GPIO.LOW)
        GPIO.output(RELAY_PIN_PH_DOWN, GPIO.LOW)
        GPIO.output(GPIO_TRIGGER, GPIO.HIGH)
        pulso_reset()
        prev_ph_up = False
        prev_ph_down = False
        pid_paused_ph = True
    elif not pid_paused_ph:
        pid_ph_up.auto_mode = True
        pid_ph_down.auto_mode = True

    # --- O2 ---
    if errores_activos & errores_o2:
        pid_o2.auto_mode = False
        GPIO.output(RELAY_PIN_O2, GPIO.LOW)
        GPIO.output(GPIO_TRIGGER, GPIO.HIGH)
        pulso_reset()
        prev_ph_down = False
        prev_ph_up = False
        pid_paused_o2 = True
    elif not pid_paused_o2:
        pid_o2.auto_mode = True

    # --- Temperatura ---
    if errores_activos & errores_temp:
        pid_ph_up.auto_mode = False
        pid_ph_down.auto_mode = False
        pid_o2.auto_mode = False
        GPIO.output(RELAY_PIN_PH_UP, GPIO.LOW)
        GPIO.output(RELAY_PIN_PH_DOWN, GPIO.LOW)
        GPIO.output(RELAY_PIN_O2, GPIO.LOW)
        GPIO.output(GPIO_TRIGGER, GPIO.HIGH)
        pulso_reset()
        prev_ph_up = False
        prev_ph_down = False
        pid_paused_ph = True
        pid_paused_o2 = True

# ==============================
# DETECCIÓN DE FALLOS EN SENSORES 
# (inválidos → rango → congelado → fluctuación → coherencia)
# ==============================
codigo_error_actual = 0                                  # 0 = sin error

def _es_num(x):                                          # verifica si x es un número válido (no None, no NaN)
    return isinstance(x, (int, float)) and not (x != x)  # descarta NaN

def verificar_sensores(pH, OD, T):
    """
    Retorna un conjunto de códigos de error activos (pudiendo coexistir varios).
    Ejemplo: {4, 5} si fallan simultáneamente los sensores de pH y O2.
    Mecanismos:
      1) Rango físico válido
      2) Lecturas inválidas consecutivas (None/NaN)
      3) Valor "congelado" (solo pH y O2; T excluida para evitar falsos positivos)
      4) Coherencia física básica: T↑ y O2↑ (>10%) simultáneo
      5) None inmediato cuenta como inválido
      6) Fluctuación anómala (sensor desconectado)
    """
    errores = set()                    # conjunto de errores activos
    st = verificar_sensores.__dict__   # almacena estado entre llamadas

    # --- Límites físicos ---
    PH_MIN, PH_MAX = 0.0, 14.0  # rango pH válido
    O2_MIN, O2_MAX = 0.0, 20.0  # rango O2 en mg/L
    T_MIN,  T_MAX  = 0.0, 40.0  # rango T en °C

    # --- Parámetros de estabilidad / consecutivos ---
    N_MAX_FALLAS = 4            # Inválidos consecutivos
    N_HIST, N_HIST_T = 50, 200  # Ventana histórica para detectar "congelado" ( pH/O2 , T )
    VAR_MIN_PH = 0.001          # Variación mínima esperada en pH
    VAR_MIN_O2 = 0.001          # Variación mínima esperada en O2
    VAR_MIN_T = 0.001           # Variación mínima esperada en T
    FLUC_UMBRAL_PH = 1.2        # Umbral de desviación estándar para detectar fluctuación anómala en pH
    FLUC_UMBRAL_O2 = 1.2        # Umbral de desviación estándar para detectar fluctuación anómala en O2

    # --- Estado persistente (historial y contadores) ---
    if "hist" not in st:                            # inicialización única
        st["hist"] = {"pH": [], "O2": [], "T": []}  # historial de lecturas
        st["bad"]  = {"pH": 0,  "O2": 0,  "T": 0}   # contadores de inválidos consecutivos

    # --- Mecanismo 5 + 2: None/NaN e inválidos consecutivos ---
    for name, val in (("pH", pH), ("O2", OD), ("T", T)): 
        if not _es_num(val):             # None o NaN -> suma contador
            st["bad"][name] += 1         # contador de inválidos consecutivos
        else:
            st["bad"][name] = 0          # resetea contador si es válido

    if st["bad"]["pH"] >= N_MAX_FALLAS:
        errores.add(4)                   # pH inválidos consecutivos
    if st["bad"]["O2"] >= N_MAX_FALLAS:
        errores.add(5)                   # O2 inválidos consecutivos
    if st["bad"]["T"] >= N_MAX_FALLAS:
        errores.add(6)                   # T inválidos consecutivos

    # Si alguno es None/NaN pero aún no llegó al umbral, no seguimos evaluando ese canal
    if not (_es_num(pH) and _es_num(OD) and _es_num(T)):
        if not _es_num(pH): errores.add(4)
        if not _es_num(OD): errores.add(5)
        if not _es_num(T):  errores.add(6)
        return errores

    # --- Mecanismo 1: Rango físico ---
    if not (PH_MIN <= pH <= PH_MAX):
        errores.add(1)  # pH fuera de rango
    if not (O2_MIN <= OD <= O2_MAX):
        errores.add(2)  # O2 fuera de rango
    if not (T_MIN <= T <= T_MAX):
        errores.add(3)  # T fuera de rango

    # --- Mecanismo 3: Valor "congelado" (solo pH y O2; T excluida) ---
    st["hist"]["pH"].append(pH)
    st["hist"]["O2"].append(OD)
    st["hist"]["T"].append(T)
    if len(st["hist"]["pH"]) > N_HIST: st["hist"]["pH"].pop(0) 
    if len(st["hist"]["O2"]) > N_HIST: st["hist"]["O2"].pop(0)
    if len(st["hist"]["T"])  > N_HIST_T: st["hist"]["T"].pop(0)

    if len(st["hist"]["pH"]) == N_HIST:
        if (max(st["hist"]["pH"]) - min(st["hist"]["pH"])) < VAR_MIN_PH: # se calcula la diferencia max-min
            errores.add(7)  # pH "congelado"

    if len(st["hist"]["O2"]) == N_HIST:
        if (max(st["hist"]["O2"]) - min(st["hist"]["O2"])) < VAR_MIN_O2: # se calcula la diferencia max-min
            errores.add(8)  # O2 "congelado"

    if len(st["hist"]["T"]) == N_HIST_T:
        if (max(st["hist"]["T"]) - min(st["hist"]["T"])) < VAR_MIN_T:    # se calcula la diferencia max-min
            errores.add(9)  # T "congelada"

    # --- Mecanismo 6: Fluctuación anómala (sensor desconectado) ---
    # Si la desviación estándar en la ventana supera un umbral, se asume entrada flotante
    try:
        if len(st["hist"]["pH"]) >= 10:
            std_ph = statistics.pstdev(st["hist"]["pH"])
            if std_ph > FLUC_UMBRAL_PH:     # Umbral de fluctuación anómala (ajustable)
                errores.add(11)             # Fluctuación anómala pH

        if len(st["hist"]["O2"]) >= 10:
            std_o2 = statistics.pstdev(st["hist"]["O2"])
            if std_o2 > FLUC_UMBRAL_O2:     # Umbral de fluctuación anómala (ajustable)
                errores.add(12)             # Fluctuación anómala O2
    except statistics.StatisticsError:
        pass

    # --- Mecanismo 4: Coherencia física básica ---
    # Regla simple: si T sube y O2 sube más de 10% respecto a la lectura previa -> inconsistente
    if len(st["hist"]["T"]) >= 2 and len(st["hist"]["O2"]) >= 2:
        if T > st["hist"]["T"][-2] and OD > (st["hist"]["O2"][-2] * 1.10):
            errores.add(10)  # incoherencia T/OD

    # --- Sin error ---
    if not errores:
        errores.add(0)
    return errores

# ==============================
# FILTRO DE PRIORIDAD DE ERRORES
# ==============================
def filtrar_errores_prioritarios(errores):
    """
    Devuelve un subconjunto de errores activos, priorizando los más críticos.
    """
    if not errores: # ningún error activo
        return {0}

    # --- Si hay error serial o logger, ignora todos los de sensores ---
    if {13, 14, 15, 16} & errores:               # Obtenemos la intersección entre ambos conjuntos (errores críticos ,errores activos)
        return {min({13, 14, 15, 16} & errores)} # se devuelve el error de mayor prioridad (el numero más bajo de prioridad)

    # --- Si hay error DS18B20, mantiene solo ese y los de comunicación ---
    '''
        -Si hay un error de DS18B20 mientras que hay errores secundarios se conserva 
        con ellos en el conjunto de errores activos.
    '''
    if 17 in errores:
        return {17} | ({18, 19, 20} & errores)   # Se hace la unión de conjuntos

    # --- Si hay errores de sensores (pH, O₂, T), se mantienen simultáneos ---
    '''
        -Si existen errores simultáneos de sensores, se mantienen, 
        excepto en los casos de redundancia (1 y 11) o (2 y 12).
    '''
    sensores = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12} & errores # Solo devuelve los errores de sensores

    # --- Si hay conflictos como (1 y 11) o (2 y 12) ---
    ''' -Si existe (1 y 2) y viceversa (mantener)
        -Si existe (11 y 12) y viceversa (mantener)
        -Si existe (11 y 1) juntos, eliminar 1 (redundancia)
        -Si existe (12 y 2) juntos, eliminar 2 (redundancia)
        -Si existe (1 y 12) o (2 y 11) juntos, mantener ambos (no hay redundancia)
        -Si existe (10 y 12) juntos, eliminar 10 (redundancia)
    '''
    if 11 in sensores and 1 in sensores:  # Si hay ambos errores de pH se descarta el error 1
        sensores.discard(1)
    if 12 in sensores and 2 in sensores:  # Si hay ambos errores de O2 se descarta el error 2
        sensores.discard(2)
    if 12 in sensores and 10 in sensores: # Si hay incoherencia T/O2 y fluctuación anómala O2, descarta incoherencia
        sensores.discard(10)

    # --- Mantener errores de comunicación secundarios ---
    '''
        -Si hay errores secundarios de forma simultanea se mantienen en 
        el conjunto de errores activos.
    '''
    secundarios = {18, 19, 20} & errores  # Si hay simultáneamente errores de comunicación se mantienen

    return sensores | secundarios 

# ==============================
# BUCLE PRINCIPAL 
# ==============================
acumulador = {canal: 0 for canal in CANALES}
contador = 0
voltaje_suavizado = {canal: None for canal in CANALES}
ultima_actividad = time.time()       # Inicializar watchdog interno
try:
    while True:
        t0 = time.time()             # marca temporal inicio de ciclo
        escuchar_confirmacion_tcp()  # Revisa si llegó alguna orden externa de reanudación
        # --- Reconexión preventiva si 'ser' está caído ---
        if ser is None:
            print("[WARN] Serial no disponible. Intentando reconectar...")
            ser = conectar_serial()
            if ser is None:
                time.sleep(2)
                continue  # reintentar sin caer
            else:
                errores_activos.clear()  # puerto reconectado, limpiar errores

        # --- Acceso seguro a in_waiting ---
        try:
            if ser.in_waiting > 150:
                print(f"[WARN] Buffer saturado ({ser.in_waiting} bytes). Reiniciando buffer...")
                ser.reset_input_buffer()
        except (AttributeError, serial.SerialException, OSError) as e:
            # Algo pasó con el puerto; marcamos error y forzamos reconexión
            errores_activos.add(15)
            print(f"[ERROR] Acceso a puerto serial: {e}. Forzando reconexión...")
            # --- Desactivar PIDs ante error crítico de comunicación ---
            pid_ph_up.auto_mode = False
            pid_ph_down.auto_mode = False
            pid_o2.auto_mode = False
            GPIO.output(RELAY_PIN_PH_UP, GPIO.LOW)
            GPIO.output(RELAY_PIN_PH_DOWN, GPIO.LOW)
            GPIO.output(RELAY_PIN_O2, GPIO.LOW)
            GPIO.output(GPIO_TRIGGER, GPIO.HIGH)
            pulso_reset()
            prev_ph_up = False
            prev_ph_down = False
            try:
                ser.close()
            except:
                pass
            ser = None

            errores_filtrados = filtrar_errores_prioritarios(errores_activos)
            errores_udp_str = "|".join(str(e) for e in sorted(errores_filtrados))
            try:
                enviar_datos_udp(
                    0, 0, 0, 0,    # voltajes y lecturas nulas
                    0, 0, 0,       # controles
                    pid_ph_up, pid_ph_down, pid_o2,
                    25.0,          # temperatura dummy
                    0, 0, 0,       # tiempos de actuación
                    errores_udp_str
                )
            except:
                pass
            time.sleep(2)
            continue  # seguir vivo, reintentar

        # --- Resto de la iteración protegido ---
        try:
            lectura = leer_linea_ultima()
            if lectura is None:
                time.sleep(DELAY_MUESTREO)
                continue

            promedio, listo, acumulador, contador = procesar_lectura(lectura, acumulador, contador)
            if not listo:
                time.sleep(DELAY_MUESTREO)
                continue

            voltaje_a0, voltaje_a1, pH_compensado, OD_compensado, temperatura_float, voltaje_suavizado = convertir_y_compensar(promedio, voltaje_suavizado)

            monitorear_seguridad_ph(pH_compensado)

            errores_activos = verificar_sensores(pH_compensado, OD_compensado, temperatura_float)
            gestionar_pids_por_error(errores_activos)

            errores_filtrados = filtrar_errores_prioritarios(errores_activos)
            errores_udp_str = "|".join(str(e) for e in sorted(errores_filtrados)) if errores_filtrados else "0"
            codigo_error_actual = min(errores_filtrados) if errores_filtrados else 0

            control_ph_down, control_ph_up, control_o2 = actualizar_pid(pH_compensado, OD_compensado)

            mostrar_datos_consola(voltaje_a0, voltaje_a1, pH_compensado, OD_compensado,
                                  control_ph_down, control_ph_up, control_o2,
                                  pid_ph_up, pid_ph_down, pid_o2, temperatura_float,
                                  ser, errores_udp_str)
            
            procesar_tareas_manuales(time.time())

            (inicio_ciclo_ph_up, inicio_ciclo_ph_down, inicio_ciclo_o2,
             tiempo_on_up, tiempo_on_down, tiempo_on_o2) = actualizar_actuadores(
                control_ph_up, control_ph_down, control_o2,
                inicio_ciclo_ph_up, inicio_ciclo_ph_down, inicio_ciclo_o2
            )

            enviar_datos_udp(voltaje_a0, voltaje_a1, pH_compensado, OD_compensado,
                             control_ph_down, control_ph_up, control_o2,
                             pid_ph_up, pid_ph_down, pid_o2, temperatura_float,
                             tiempo_on_up, tiempo_on_down, tiempo_on_o2,
                             errores_udp_str)
            
            
            # ===== ENVIAR ESTADO COMPLETO AL FLASK =====
            estado = {
                "pid_paused_ph": pid_paused_ph,
                "pid_paused_o2": pid_paused_o2,
                "bloqueo_ph": bloqueo_seguridad_ph,
                "ultimo_ph_up": ultimo_ph_up,
                "ultimo_ph_down": ultimo_ph_down,
                "cooldown": COOLDOWN_PH_SEG,
                "tareas": tareas_manual,
                "timestamp": time.time()
            }

            estado_json = json.dumps(estado)
            enviar_estado_udp_flask(estado_json)

            
            # --- Watchdog interno: reinicio automático si no hay actividad ---
            # Si no se ha completado una iteración normal en más de 20 segundos,
            # se asume que el programa está bloqueado y se reinicia automáticamente.
            if (time.time() - ultima_actividad) > 20: 
                print("[WATCHDOG] Sin actividad. Reiniciando programa...")
                os.execv(sys.executable, ['python3'] + sys.argv)

            # Actualizar marca de tiempo de última actividad (cada ciclo exitoso)
            ultima_actividad = time.time()

            # --- Mantener ciclo de muestreo constante ---
            t0 += DELAY_MUESTREO    # siguiente marca temporal objetivo
            dt = t0 - time.time()   # tiempo restante hasta la siguiente iteración
            if dt > 0:              # dormir solo si queda tiempo
                time.sleep(dt)

        except Exception as e:
            # Cualquier error de la iteración NO debe terminar el proceso
            errores_activos.add(20)
            print(f"[ERROR BUCLE - iteración] {e}")
            time.sleep(0.5)
            continue

except KeyboardInterrupt:
    print("\n[SALIDA] Usuario interrumpió ejecución.")
finally:
    try:
        tcp_socket.close()
        if ser:
            ser.close()
    except:
        pass
    try:
        udp_socket.close()
    except:
        pass
    GPIO.cleanup()
    print("[INFO] Recursos liberados correctamente.")
