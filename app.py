import json
import os # Importa el módulo os para acceder a variables de entorno
from datetime import datetime, timedelta, date, timezone

from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
# Obtén la SECRET_KEY de una variable de entorno. ¡ESENCIAL PARA PRODUCCIÓN!
# Si no está definida (ej. en desarrollo local), usa una por defecto.
app.secret_key = os.getenv('SECRET_KEY', 'una_clave_secreta_muy_segura_y_larga_para_desarrollo') 

DATA_FILE = 'data.json'
QUEUES = ["research", "building", "training"] # Coincide con las columnas del frontend

# --- Funciones para manejar los datos (Base de Datos JSON) ---

def load_data():
    """Carga los datos de reservas desde el archivo JSON."""
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Asegurarse de que las claves de fecha sean strings si vienen de datetime
            return {str(k): v for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {} # Retorna un diccionario vacío si el archivo no existe o está corrupto


def save_data(data):
    """Guarda los datos de reservas en el archivo JSON."""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)


def initialize_day_slots(target_date_obj):
    """Inicializa todas las franjas horarias como disponibles para un día dado."""
    slots = {}
    for queue in QUEUES:
        slots[queue] = {}
        for hour in range(24):
            # Formato HH:MM, por ejemplo "09:00", "14:00"
            time_str = f"{hour:02d}:00"
            slots[queue][time_str] = {
                "available": True,
                "booked_by": None # Puedes almacenar el nombre del reservante aquí
            }
    return slots


def update_bookings_daily():
    """
    Gestiona la rotación diaria:
    - Borra los días pasados.
    - Asegura que existan los 3 días (actual y los dos siguientes).
    """
    today_local = date.today() # Fecha local para determinar "Hoy"
    data = load_data()
    new_data = {}

    # Identificar las fechas que deberían estar en la base de datos (Hoy, Mañana, Pasado Mañana)
    # Ajustamos para mostrar solo Hoy y Mañana como se solicitó
    expected_dates_objs = [
        today_local,
        today_local + timedelta(days=1)
        # today_local + timedelta(days=2) # Eliminado para solo mostrar hoy y mañana
    ]
    
    for d_obj in expected_dates_objs:
        d_str = d_obj.isoformat()
        if d_str in data:
            new_data[d_str] = data[d_str]
        else:
            # Si el día no existe, inicializarlo
            new_data[d_str] = initialize_day_slots(d_obj)

    # Eliminar cualquier día antiguo o el "Pasado Mañana" si existiera
    keys_to_delete = [k for k in data.keys() if k not in expected_dates_objs] # Usar 'data' original para las claves a borrar
    for k in keys_to_delete:
        if k in new_data: # Asegurarse de que la clave exista antes de intentar borrar
            del new_data[k]


    save_data(new_data)
    return new_data


# --- Rutas de la Aplicación Web (Flask) ---

@app.route('/')
def index():
    """Muestra la página principal con las colas de los dos días (Hoy y Mañana)."""
    # Asegurarse de que los datos estén actualizados con los días correctos
    bookings_data = update_bookings_daily()

    # Obtener la fecha y hora actual en UTC para marcar slots pasados y encontrar el siguiente en cola
    now_utc = datetime.now(timezone.utc)
    current_hour_utc = now_utc.hour
    
    today_local = date.today() # Esta es la fecha local para determinar "Hoy", "Mañana", etc.

    ordered_display_dates = {}
    first_in_queue_data = {queue: None for queue in QUEUES} # Para almacenar el primero en cada cola

    # Loop para los 2 días: Hoy, Mañana
    for i in range(2): # Cambiado a range(2) para Hoy y Mañana
        current_date_obj = today_local + timedelta(days=i)
        date_str = current_date_obj.isoformat()
        
        # Obtener los datos del día, o inicializarlos si no existen (aunque update_bookings_daily ya lo hizo)
        day_bookings = bookings_data.get(date_str, initialize_day_slots(current_date_obj))

        # Solo marcar horas pasadas para "hoy" (el primer día del loop)
        if i == 0: # Este es "hoy"
            for queue in QUEUES:
                for hour_str, details in day_bookings[queue].items():
                    slot_hour = int(hour_str.split(':')[0])
                    # Si la hora del slot es menor que la hora actual UTC
                    if slot_hour < current_hour_utc:
                        details["available"] = False # Marcar como no disponible
                        if details["booked_by"] is None:
                            details["booked_by"] = "Pasado" # Opcional: indicar que pasó el tiempo
        
        ordered_display_dates[date_str] = day_bookings

        # Lógica para encontrar el "primero en la cola" para cada categoría
        for queue in QUEUES:
            if first_in_queue_data[queue] is None: # Si aún no hemos encontrado uno para esta cola
                for hour in range(24):
                    time_str = f"{hour:02d}:00"
                    slot_details = day_bookings[queue][time_str]
                    
                    # Crear un objeto datetime para comparar con la hora actual
                    slot_datetime_str = f"{date_str} {time_str}"
                    # Convertir a datetime sin zona horaria para la comparación
                    slot_datetime = datetime.strptime(slot_datetime_str, "%Y-%m-%d %H:%M")

                    # Si el slot está reservado y no es "Pasado" y es en el futuro
                    if not slot_details["available"] and \
                       slot_details["booked_by"] != "Pasado" and \
                       slot_datetime > now_utc.replace(tzinfo=None): # Comparar datetimes naive
                        
                        first_in_queue_data[queue] = {
                            "date": current_date_obj.strftime("%d/%m/%Y"), # Formato más amigable
                            "time": time_str,
                            "booked_by": slot_details["booked_by"]
                        }
                        break # Salir del bucle de horas, ya encontramos el primero para esta cola
            
    return render_template(
        'index.html',
        bookings=ordered_display_dates,
        queues=QUEUES,
        today=today_local.isoformat(),
        now_utc=now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"), # Solo para depuración o información
        first_in_queue=first_in_queue_data # Pasamos los datos del primero en cola al template
    )


@app.route('/book', methods=['POST'])
def book_slot():
    """Maneja la reserva de una franja horaria."""
    date_str = request.form['date']
    queue_type = request.form['queue']
    time_slot = request.form['time']
    booked_by_name = request.form.get('booked_by', '').strip()

    if not booked_by_name:
        flash('El nombre es obligatorio para realizar la reserva.', 'error')
        print("Error: El nombre es obligatorio.")
        return redirect(url_for('index'))

    data = load_data()

    # Verificar si el slot existe y está disponible antes de reservar
    if date_str in data and \
       queue_type in data[date_str] and \
       time_slot in data[date_str][queue_type] and \
       data[date_str][queue_type][time_slot]["available"]:
        
        data[date_str][queue_type][time_slot]["booked_by"] = booked_by_name
        data[date_str][queue_type][time_slot]["available"] = False
        save_data(data)
        flash(f'¡Reserva exitosa para {booked_by_name} en {date_str} a las {time_slot}!', 'success')
        print(f"Reserva exitosa: {date_str} - {queue_type} - {time_slot} por {booked_by_name}")
    else:
        flash(f'Error: No se pudo reservar el slot {time_slot}. Posiblemente ya reservado o inválido.', 'error')
        print(f"Error: No se pudo reservar el slot {date_str} - {queue_type} - {time_slot}. Posiblemente ya reservado o inválido.")
    
    return redirect(url_for('index'))


if __name__ == '__main__':
    # Obtén el puerto de la variable de entorno PORT, o usa 5000 por defecto
    port = int(os.getenv('PORT', 5000))
    # Render necesita que la aplicación escuche en 0.0.0.0
    app.run(host='0.0.0.0', port=port, debug=False) # Deshabilita debug en producción