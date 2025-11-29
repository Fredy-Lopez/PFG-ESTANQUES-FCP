from flask import Flask, jsonify, render_template, request
import sqlite3
import os
import socket
import threading
import json
from datetime import datetime, timedelta
import time
import requests 

# ===============================
# CONFIG
# ===============================
app = Flask(__name__, template_folder="templates", static_folder="static")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "../PID/monitoreo.db")

# ===============================
# CLIMA DE OPEN WEATHER KEY
# ===============================
OWM_KEY = "7705c2d938df87040e49e60ac1d3d6d3"
LAT = -25.496960843657554 
LON = -56.45972174599361

_clima_cache = {
	"ultimo": None,
	"expira": datetime.min,
}
simul_api_calls = 0
estado_v24 = {} #variable global en flask

# ===============================
# HELPERS BD
# ===============================
def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=0.5)
    conn.row_factory = sqlite3.Row
    return conn

def init_wal():
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.commit()
        conn.close()
    except:
        pass

init_wal()

# -------------------------------
# GUARDAR NOTIFICACIONES (seguro)
# -------------------------------
def push_notificacion(tipo, mensaje):
    """Inserta una notificación sin bloquear si la BD está ocupada."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for _ in range(8):  # hasta 8 reintentos
        try:
            conn = sqlite3.connect(DB_FILE, timeout=0.3)  # timeout corto
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO notificaciones (tipo, mensaje, hora, leida)
                VALUES (?, ?, ?, 0)
            """, (tipo, mensaje, ts))
            conn.commit()
            conn.close()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(0.12)
                continue
            else:
                print("⚠️ Error inesperado en push_notificacion:", e)
                return False

    print("❌ No se pudo insertar notificación (BD ocupada).")
    return False


def safe_update(conn, query, params=()):
    """Ejecuta UPDATE con reintentos si la BD está ocupada."""
    for _ in range(8):
        try:
            cur = conn.cursor()
            cur.execute(query, params)
            conn.commit()
            return True
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                time.sleep(0.12)
                continue
            raise
    print("❌ UPDATE falló tras reintentos (BD ocupada)")
    return False


# ===============================
# TCP → V24
# ===============================
def enviar_tcp(comando):
    HOST = "127.0.0.1"
    PORT = 5010  

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect((HOST, PORT))
        sock.sendall(comando.encode())
        sock.close()
        print(f"[FLASK → V24] TCP enviado: {comando}")
        return True
    except Exception as e:
        print(f"⚠️ Error TCP desde Flask: {e}")
        return False
        
def hilo_udp_estado_v24():
    global estado_v24
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 6000))
    print("[FLASK] UDP estado escuchando en 6000...")

    while True:
        data, addr = sock.recvfrom(4096)
        try:
            estado_v24 = json.loads(data.decode())
        except:
            pass

# lanzar hilo
threading.Thread(target=hilo_udp_estado_v24, daemon=True).start()

#Registrar tabla acciones_manual si no existe
def init_tabla_acciones_manual():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS acciones_manual (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            hora TEXT NOT NULL,
            accion TEXT NOT NULL,
            descripcion TEXT NOT NULL,
            valor TEXT,
            estanque INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()

# Llamalo al iniciar la app
init_tabla_acciones_manual()

# Registrar acción manual
def registrar_accion_manual(accion, descripcion, valor=None, estanque=1):
    ahora = datetime.now()
    fecha = ahora.strftime("%Y-%m-%d")
    hora = ahora.strftime("%H:%M:%S")

    conn = get_db()
    conn.execute("""
        INSERT INTO acciones_manual (fecha, hora, accion, descripcion, valor, estanque)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (fecha, hora, accion, descripcion, valor, estanque))
    conn.commit()
    conn.close()


def interpretar_cmd(cmd):
    """
    Recibe el comando EXACTO enviado desde el frontend.
    Devuelve:
        accion_interna (string para BD)
        descripcion    (texto bonito para historial)
        valor          (por ejemplo '20 mL' o '30 s')
    """

    partes = cmd.split()

    # ======================================================================
    # COMANDOS SIN PARÁMETRO
    # ======================================================================
    if cmd == "1":
        return ("pid_ph_play", "PID de pH reanudado", None)

    if cmd == "2":
        return ("pid_o2_play", "PID de O₂ reanudado", None)

    if cmd == "3":
        return ("pid_ambos_play", "PID de pH y O₂ reanudados", None)

    if cmd == "4":
        return ("pid_ph_pause", "PID de pH pausado (modo manual)", None)

    if cmd == "5":
        return ("pid_o2_pause", "PID de O₂ pausado (modo manual)", None)

    if cmd == "6":
        return ("todos_off", "Todos los actuadores detenidos (modo manual)", None)

    # ======================================================================
    # COMANDOS CON PARÁMETRO
    # ======================================================================

    if len(partes) == 2:
        op, val = partes

        # pH ↑ — cal viva
        if op == "8":
            ml_map = {"0": "10 mL", "1": "20 mL", "2": "40 mL"}
            ml = ml_map.get(val, val)
            return ("dosificacion_ph_up", f"Dosificación pH↑ ({ml})", ml)

        # pH ↓ — ácido
        if op == "9":
            ml_map = {"0": "10 mL", "1": "20 mL", "2": "40 mL"}
            ml = ml_map.get(val, val)
            return ("dosificacion_ph_down", f"Dosificación pH↓ ({ml})", ml)

        # Aireador tiempo
        if op == "7":
            segundos = int(val)
            return ("aireador_on", f"Aireador encendido por {segundos} s", f"{segundos} s")

        # Extensiones del comando 6
        if op == "6" and val == "1":
            return ("aireador_off", "Aireador apagado manualmente", None)

        if op == "6" and val == "2":
            return ("parada_emergencia", "PARADA DE EMERGENCIA: Todos los actuadores apagados", None)

    # ======================================================================
    # DESCONOCIDO
    # ======================================================================
    return ("desconocido", f"Comando manual desconocido: {cmd}", cmd)


# ===============================
# UI PRINCIPAL
# ===============================
@app.route("/")
def index():
    return render_template("mobile.html")


# ===============================
# API: Última lectura sensores
# ===============================
@app.route("/api/sensores")
def api_sensores():
    conn = get_db()
    row = conn.execute("""
        SELECT ph, o2, temp, codigo_error
        FROM lecturas
        ORDER BY id DESC LIMIT 1
    """).fetchone()
    conn.close()

    if not row:
        return jsonify({"ph": None, "o2": None, "temp": None, "error": 0})

    return jsonify({
        "ph": row["ph"],
        "o2": row["o2"],
        "temp": row["temp"],
        "error": row["codigo_error"]
    })
    
# ===============================
# API: CLIMA REAL + CACHÉ OPENWEATHER
# ===============================
@app.route("/api/clima")
def api_clima():
    global simul_api_calls, _clima_cache

    ahora = datetime.now()

    # Si el cache sigue válido → devolvemos lo almacenado
    if ahora < _clima_cache["expira"]:
        return jsonify({
            "fuente": "cache",
            "api_calls": simul_api_calls,
            "data": _clima_cache["ultimo"]
        })

    # Intentar llamar a OpenWeather
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?lat={LAT}&lon={LON}&appid={OWM_KEY}&units=metric&lang=es"
        )

        r = requests.get(url, timeout=3)
        weather = r.json()

        # Convertir viento de m/s → km/h
        try:
            if "wind" in weather and "speed" in weather["wind"]:
                weather["wind"]["speed"] = round(weather["wind"]["speed"] * 3.6, 2)
        except:
            pass

        simul_api_calls += 1

        # Guardar en caché por 4 minutos
        _clima_cache["ultimo"] = weather
        _clima_cache["expira"] = ahora + timedelta(minutes=4)

        return jsonify({
            "fuente": "openweather",
            "api_calls": simul_api_calls,
            "data": weather
        })

    except Exception as e:
        print("⚠️ ERROR consultando OpenWeather:", e)

        # Si falla: devolver cache previo
        if _clima_cache["ultimo"] is not None:
            return jsonify({
                "fuente": "fallback-cache",
                "api_calls": simul_api_calls,
                "data": _clima_cache["ultimo"]
            })

        # Sin cache → devolver algo mínimo para no romper el frontend
        return jsonify({
            "fuente": "fallback",
            "api_calls": simul_api_calls,
            "data": {
                "name": "Clima no disponible",
                "main": {"temp": 0, "humidity": 0},
                "wind": {"speed": 0}
            }
        })


# ===============================
# API: Errores pendientes (multiusuario)
# ===============================
@app.route("/api/errores_pendientes")
def api_errores_pendientes():
    conn = get_db()
    cur = conn.cursor()

    # ====== 1. Notificar comienzos de error ======
    nuevos = cur.execute("""
        SELECT id, codigo, descripcion
        FROM errores_log
        WHERE hora_inicio IS NOT NULL AND notificado_inicio = 0
    """).fetchall()

    for r in nuevos:
        ok = push_notificacion(
            "error",
            f"⚠️ Error [{r['codigo']}] {r['descripcion']} detectado"
        )
        if ok:
            cur.execute("""
                UPDATE errores_log
                SET notificado_inicio = 1
                WHERE id = ?
            """, (r["id"],))
            conn.commit()

    # ====== 2. Notificar errores resueltos ======
    resueltos = cur.execute("""
        SELECT id, codigo, descripcion
        FROM errores_log
        WHERE hora_fin IS NOT NULL AND notificado_fin = 0
    """).fetchall()

    for r in resueltos:
        ok = push_notificacion(
            "resuelto",
            f"✔️ Error [{r['codigo']}] {r['descripcion']} resuelto"
        )
        if ok:
            cur.execute("""
                UPDATE errores_log
                SET notificado_fin = 1
                WHERE id = ?
            """, (r["id"],))
            conn.commit()

    # ====== 3. Enviar errores pendientes para la UI ======
    rows = cur.execute("""
        SELECT id, codigo, descripcion, hora_inicio, hora_fin
        FROM errores_log
        WHERE resuelto = 0
        ORDER BY hora_inicio ASC
    """).fetchall()

    conn.close()

    if not rows:
        return jsonify({
            "hay_error": False,
            "errores": [],
            "hay_activos": False,
            "todos_resueltos": True,
            "reiniciar_ph": False,
            "reiniciar_o2": False
        })

    errores = []
    hay_activos = False
    rein_ph = False
    rein_o2 = False

    PID_PH = {1, 4, 7, 11}
    PID_O2 = {2, 5, 8, 12}
    PID_TEMP = {3, 6, 9, 10, 17, 20}

    for r in rows:
        codigo = int(r["codigo"])
        errores.append({
            "id": r["id"],
            "codigo": codigo,
            "descripcion": r["descripcion"],
            "hora_inicio": r["hora_inicio"],
            "hora_fin": r["hora_fin"]
        })

        if r["hora_fin"] is None:
            hay_activos = True

        if codigo in PID_PH:
            rein_ph = True
        if codigo in PID_O2:
            rein_o2 = True
        if codigo in PID_TEMP:
            rein_ph = True
            rein_o2 = True

    return jsonify({
        "hay_error": True,
        "errores": errores,
        "hay_activos": hay_activos,
        "todos_resueltos": not hay_activos,
        "reiniciar_ph": rein_ph,
        "reiniciar_o2": rein_o2
    })


# ===============================
# API: Reiniciar PIDs
# ===============================
@app.route("/api/reiniciar_pids", methods=["POST"])
def api_reiniciar_pids():
    data = request.json
    rein_ph = bool(data.get("reiniciar_ph", False))
    rein_o2 = bool(data.get("reiniciar_o2", False))

    ok_tcp = True

    if rein_ph and rein_o2:
        ok_tcp &= enviar_tcp("3")
    elif rein_ph:
        ok_tcp &= enviar_tcp("1")
    elif rein_o2:
        ok_tcp &= enviar_tcp("2")

    if not ok_tcp:
        return jsonify({"ok": False, "msg": "tcp_fail"}), 500

    # ====== Actualizar BD ======
    conn = sqlite3.connect(DB_FILE, timeout=0.3)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    PID_PH = ('1', '4', '7', '11')
    PID_O2 = ('2', '5', '8', '12')
    PID_TEMP = ('3', '6', '9', '10', '17', '20')

    if rein_ph:
        safe_update(conn, """
            UPDATE errores_log
            SET hora_fin = ?, resuelto = 1
            WHERE codigo IN (?, ?, ?, ?) AND resuelto = 0
        """, (ts, *PID_PH))

    if rein_o2:
        safe_update(conn, """
            UPDATE errores_log
            SET hora_fin = ?, resuelto = 1
            WHERE codigo IN (?, ?, ?, ?) AND resuelto = 0
        """, (ts, *PID_O2))

    if rein_ph or rein_o2:
        safe_update(conn, """
            UPDATE errores_log
            SET hora_fin = ?, resuelto = 1
            WHERE codigo IN (?, ?, ?, ?, ?, ?) AND resuelto = 0
        """, (ts, *PID_TEMP))

    conn.close()

    # ====== Notificación de reinicio ======
    if rein_ph and rein_o2:
        push_notificacion("reinicio", "🔄 Reinicio de PID pH y O₂ ejecutado")
    elif rein_ph:
        push_notificacion("reinicio", "🔄 PID de pH reiniciado")
    elif rein_o2:
        push_notificacion("reinicio", "🔄 PID de O₂ reiniciado")

    return jsonify({"ok": True})


# =======================================
# API: Enviar comandos TCP → v24 (control manual)
# =======================================
@app.route("/api/tcp_send", methods=["POST"])
def api_tcp_send():
    data = request.json
    cmd = data.get("cmd", "").strip()

    if not cmd:
        return jsonify({"ok": False, "msg": "comando vacío"}), 400

    # =====================================================
    #   1) INTERPRETAR COMANDO Y REGISTRAR ACCIÓN MANUAL
    # =====================================================
    try:
        accion_interna, descripcion, valor = interpretar_cmd(cmd)

        registrar_accion_manual(
            accion=accion_interna,
            descripcion=descripcion,
            valor=valor,
            estanque=1   # fijo por ahora
        )

    except Exception as e:
        print("❌ Error registrando acción manual:", e)
        # pero dejamos continuar, no queremos romper el comando TCP

    # =====================================================
    #   2) ENVIAR COMANDO REALMENTE POR TCP
    # =====================================================
    ok = enviar_tcp(cmd)

    # =====================================================
    #   3) RESPUESTA AL FRONTEND
    # =====================================================
    return jsonify({"ok": ok})


# =======================================
# API: RECIBIR ESTADO DE V24
# =======================================
@app.route("/api/estado_v24")
def api_estado_v24():
    return jsonify(estado_v24)

# ===============================
# API: Historial lecturas
# ===============================
@app.route("/api/historial")
def api_historial():
    conn = get_db()
    rows = conn.execute("""
        SELECT fecha, hora, ph, o2, temp, codigo_error
        FROM lecturas
        ORDER BY id DESC LIMIT 200
    """).fetchall()
    conn.close()

    data = [{
        "fecha": r["fecha"],
        "hora": r["hora"],
        "ph": r["ph"],
        "o2": r["o2"],
        "temp": r["temp"],
        "error": r["codigo_error"]
    } for r in rows]

    return jsonify(data)
    
    
@app.route("/api/historial_filtros")
def api_historial_filtros():
    tipo = request.args.get("tipo", "lecturas")       # lecturas | manuales | notificaciones
    periodo = request.args.get("periodo", "dia")      # dia | mes | año | rango
    modo = request.args.get("modo", "tabla")          # tabla | grafica

    fecha = request.args.get("fecha")                 # YYYY-MM-DD
    mes = request.args.get("mes")                     # YYYY-MM
    año = request.args.get("año")                     # YYYY
    desde = request.args.get("desde")                 # YYYY-MM-DD
    hasta = request.args.get("hasta")                 # YYYY-MM-DD

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # =====================================================
    #   CONSTRUCCIÓN DEL FILTRO BASE (para lecturas/manuales)
    # =====================================================
    date_filter = None
    params = []

    if periodo == "dia" and fecha:
        date_filter = "fecha = ?"
        params.append(fecha)

    elif periodo == "mes" and mes:
        date_filter = "fecha LIKE ?"
        params.append(f"{mes}-%")

    elif periodo == "año" and año:
        date_filter = "fecha LIKE ?"
        params.append(f"{año}-%")

    elif periodo == "rango" and desde and hasta:
        date_filter = "fecha BETWEEN ? AND ?"
        params.extend([desde, hasta])

    # =====================================================
    #   MODO: GRÁFICA → SOLO LECTURAS + AGRUPACIONES
    # =====================================================
    if modo == "grafica":

        # No graficamos manuales ni notificaciones → vacío
        if tipo != "lecturas":
            conn.close()
            return jsonify([])

        # -------------------------
        # 1) Lecturas crudas
        # -------------------------
        q = """
            SELECT fecha, hora, ph, o2, temp
            FROM lecturas
        """
        if date_filter:
            q += f" WHERE {date_filter}"
        q += " ORDER BY fecha ASC, hora ASC"

        rows = cur.execute(q, params).fetchall()

        if not rows:
            conn.close()
            return jsonify([])

        lecturas = [
            {
                "fecha": r["fecha"],
                "hora": r["hora"],
                "ph": float(r["ph"]),
                "o2": float(r["o2"]),
                "temp": float(r["temp"]),
            }
            for r in rows
        ]

        # -------------------------
        # 2) Helpers de agrupación
        # -------------------------
        from datetime import datetime as dt

        def k_hora(f, h):
            return f"{f} {h[:2]}:00"

        def k_dia(f, h):
            return f

        def k_mes(f, h):
            return f[:7]

        def k_anio(f, h):
            return f[:4]

        def agrupar(fn):
            grupos = {}

            for r in lecturas:
                key = fn(r["fecha"], r["hora"])
                g = grupos.setdefault(key, {"sum_ph": 0, "sum_o2": 0, "sum_temp": 0, "n": 0})
                g["sum_ph"] += r["ph"]
                g["sum_o2"] += r["o2"]
                g["sum_temp"] += r["temp"]
                g["n"] += 1

            res = []
            for key in sorted(grupos.keys()):
                g = grupos[key]
                res.append({
                    "categoria": "lectura",
                    "fecha": key.split(" ")[0],
                    "hora": key.split(" ")[1] if " " in key else "",
                    "ph": round(g["sum_ph"] / g["n"], 2),
                    "o2": round(g["sum_o2"] / g["n"], 2),
                    "temp": round(g["sum_temp"] / g["n"], 2),
                    "label": key,
                })

            return res

        # -------------------------
        #     AGRUPACIONES
        # -------------------------
        if periodo == "dia":
            # → promedio por hora
            data = agrupar(k_hora)

        elif periodo == "mes":
            # → promedio por día
            data = agrupar(k_dia)

        elif periodo == "año":
            # → promedio por mes
            data = agrupar(k_mes)

        elif periodo == "rango" and desde and hasta:
            # duración del rango
            try:
                d1 = dt.strptime(desde, "%Y-%m-%d")
                d2 = dt.strptime(hasta, "%Y-%m-%d")
                ndias = (d2 - d1).days + 1
            except:
                ndias = 9999

            if ndias <= 31:
                data = agrupar(k_dia)
            elif ndias <= 365 * 3:
                data = agrupar(k_mes)
            else:
                data = agrupar(k_anio)
        else:
            data = agrupar(k_dia)

        conn.close()
        return jsonify(data)

    # =====================================================
    #   MODO TABLA — CONSULTAS INDEPENDIENTES
    # =====================================================
    consultas = []  # cada elemento será: (query, params)

    # ---------------------------
    # LECTURAS
    # ---------------------------
    if tipo == "lecturas":
        q = """
            SELECT fecha, hora, 'lectura' AS categoria,
                   ph, o2, temp, codigo_error, 1 AS estanque
            FROM lecturas
        """
        if date_filter:
            q += f" WHERE {date_filter}"
            consultas.append((q, params.copy()))
        else:
            consultas.append((q + " ORDER BY fecha DESC, hora DESC LIMIT 500", []))

    # ---------------------------
    # ACCIONES MANUALES
    # ---------------------------
    if tipo == "manuales":
        q = """
            SELECT fecha, hora, 'manual' AS categoria,
                   descripcion, valor, accion, estanque
            FROM acciones_manual
        """
        if date_filter:
            q += f" WHERE {date_filter}"
            consultas.append((q, params.copy()))
        else:
            consultas.append((q + " ORDER BY fecha DESC, hora DESC LIMIT 500", []))

    # ---------------------------
    # NOTIFICACIONES (especial)
    # ---------------------------
    if tipo == "notificaciones":
        # NOTIFICACIONES NECESITAN FILTRO PROPIO (hora tiene datetime completo)
        q = """
            SELECT 
                substr(hora, 1, 10) AS fecha,
                substr(hora, 12) AS hora,
                'notificacion' AS categoria,
                mensaje,
                tipo,
                leida,
                1 AS estanque
            FROM notificaciones
        """

        # FILTRO ESPECIAL PARA NOTIFICACIONES
        if periodo == "dia" and fecha:
            q += " WHERE substr(hora, 1, 10) = ?"
            consultas.append((q, [fecha]))

        elif periodo == "mes" and mes:
            q += " WHERE substr(hora, 1, 7) = ?"
            consultas.append((q, [mes]))

        elif periodo == "año" and año:
            q += " WHERE substr(hora, 1, 4) = ?"
            consultas.append((q, [año]))

        elif periodo == "rango" and desde and hasta:
            q += " WHERE substr(hora, 1, 10) BETWEEN ? AND ?"
            consultas.append((q, [desde, hasta]))

        else:
            consultas.append((q, []))

    # =====================================================
    #   PAGINACIÓN PARA TABLA
    # =====================================================
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 30))
    offset = (page - 1) * limit

    # Obtener datos completos en memoria
    final_data = []
    for q, p in consultas:
        final_data.extend([dict(r) for r in cur.execute(q, p).fetchall()])

    # Ordenar todo por fecha/hora descendente
    def sort_key(x):
        f = x.get("fecha", "")
        h = x.get("hora", "")
        return (f, h)

    final_data.sort(key=sort_key, reverse=True)

    # Total de filas y páginas
    total_items = len(final_data)
    total_pages = max(1, (total_items + limit - 1) // limit)

    # Cortar solo la página actual
    page_data = final_data[offset : offset + limit]

    conn.close()

    # Devolver datos con información de paginación
    return jsonify({
        "page": page,
        "pages": total_pages,
        "limit": limit,
        "total": total_items,
        "data": page_data
    })



# ===============================
# API: Notificaciones
# ===============================
@app.route("/api/notificaciones")
def api_notificaciones():
    conn = get_db()
    rows = conn.execute("""
        SELECT id, tipo, mensaje, hora, leida
        FROM notificaciones
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()
    conn.close()

    return jsonify([
        {
            "id": r["id"],
            "tipo": r["tipo"],
            "mensaje": r["mensaje"],
            "hora": r["hora"],
            "leida": r["leida"]
        }
        for r in rows
    ])


@app.route("/api/notificaciones_no_leidas")
def api_notificaciones_no_leidas():
    conn = get_db()
    row = conn.execute("""
        SELECT COUNT(*) AS cnt
        FROM notificaciones
        WHERE leida = 0
    """).fetchone()
    conn.close()

    return jsonify({"pendientes": row["cnt"]})


@app.route("/api/notificaciones_marcar_leidas", methods=["POST"])
def api_notificaciones_marcar_leidas():
    conn = get_db()
    conn.execute("UPDATE notificaciones SET leida = 1 WHERE leida = 0")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})
    
@app.route("/api/notificacion_sistema", methods=["POST"])
def api_notificacion_sistema():
    data = request.json
    tipo = data.get("tipo", "sistema")
    mensaje = data.get("mensaje", "Evento del sistema")

    push_notificacion(tipo, mensaje)
    return jsonify({"ok": True})



