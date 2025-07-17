import os
import json # Todavía se usa para la lógica inicial de QUEUES si la necesitas, pero no para datos de reserva.
from datetime import datetime, timedelta, date, time, timezone

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy # Importación clave para la DB

# Intenta cargar variables de entorno desde un archivo .env si existe (solo para desarrollo local)
# Esto permite que DATABASE_URL y SECRET_KEY funcionen localmente sin configurarlas en el sistema
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass # python-dotenv no está instalado o no es necesario en producción/Render

app = Flask(__name__)

# Configura la SECRET_KEY. Prioriza la variable de entorno para producción.
# Para desarrollo, puedes poner una clave por defecto o usar .env
app.secret_key = os.getenv('SECRET_KEY', 'una_clave_secreta_super_segura_y_larga_por_defecto_aqui')

# Configura la URI de la base de datos. Render proporcionará DATABASE_URL.
# Reemplazamos 'postgres://' por 'postgresql://' si viene de Render, ya que SQLAlchemy lo prefiere.
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1) if os.getenv('DATABASE_URL') else 'sqlite:///reservas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False # Recomendado para deshabilitar el seguimiento de eventos de SQLAlchemy

db = SQLAlchemy(app) # Inicializa la extensión SQLAlchemy con tu aplicación Flask

# Definimos las colas (ej. building, research, training)
QUEUES = ["building", "research", "training"] # Asegúrate de que esto coincida con lo que esperas en el frontend

# --- Definición del Modelo de Base de Datos ---
class Booking(db.Model):
    __tablename__ = 'bookings' # Nombre de la tabla en la base de datos
    id = db.Column(db.Integer, primary_key=True)
    
    # Usamos db.Date para la fecha (solo fecha)
    booking_date = db.Column(db.Date, nullable=False)
    
    # Guardamos la hora como cadena, "HH:MM", para simplificar
    time_slot = db.Column(db.String(5), nullable=False) # ej. "09:00"
    
    queue_type = db.Column(db.String(50), nullable=False)
    
    # Campo para el nombre del reservante
    booked_by = db.Column(db.String(100), nullable=True) # Puede ser NULL si está disponible
    
    # Indicador de disponibilidad
    available = db.Column(db.Boolean, default=True, nullable=False)

    # Añadimos un índice único para evitar duplicados accidentales
    __table_args__ = (db.UniqueConstraint('booking_date', 'time_slot', 'queue_type', name='_booking_uc'),)

    def __repr__(self):
        return f"<Booking {self.booking_date} {self.time_slot} {self.queue_type} - Available: {self.available}, Booked By: {self.booked_by}>"

# --- Funciones de Utilidad para la Base de Datos ---

def initialize_all_slots_for_day(target_date_obj):
    """
    Inicializa todas las franjas horarias para un día dado en la base de datos
    si aún no existen.
    """
    for queue_name in QUEUES:
        for hour in range(24): # 00:00 a 23:00
            time_str = f"{hour:02d}:00"
            
            # Verificar si el slot ya existe
            existing_slot = Booking.query.filter_by(
                booking_date=target_date_obj,
                time_slot=time_str,
                queue_type=queue_name
            ).first()

            if not existing_slot:
                new_booking = Booking(
                    booking_date=target_date_obj,
                    time_slot=time_str,
                    queue_type=queue_name,
                    available=True,
                    booked_by=None
                )
                db.session.add(new_booking)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error al inicializar slots para {target_date_obj}: {e}")

def get_bookings_for_display(target_date_obj):
    """
    Obtiene las reservas de la base de datos para un día específico
    y las formatea para el template.
    """
    bookings_data = {queue: {} for queue in QUEUES}
    
    # Obtener todas las reservas para la fecha objetivo
    all_day_bookings = Booking.query.filter_by(booking_date=target_date_obj).all()

    # Ordenar por hora y luego por tipo de cola si es necesario, aunque el bucle siguiente lo manejará
    # Convierte la lista de objetos Booking a un diccionario fácil de usar en el template
    for booking in all_day_bookings:
        if booking.queue_type in bookings_data:
            bookings_data[booking.queue_type][booking.time_slot] = {
                "available": booking.available,
                "booked_by": booking.booked_by
            }
    
    # Asegurarse de que todas las horas estén presentes (si no estaban en DB, initialize_all_slots_for_day las añadiría)
    # y también ordenar por hora
    for queue in QUEUES:
        sorted_times = sorted(bookings_data[queue].items(), key=lambda x: datetime.strptime(x[0], "%H:%M").time())
        bookings_data[queue] = {time_str: details for time_str, details in sorted_times}
        
        # Esto es un fallback, initialize_all_slots_for_day debería asegurar que todas las 24h estén
        # Si por alguna razón faltaran, las añadiría aquí como disponibles (pero no las persistiría si no se hace commit)
        for hour in range(24):
            time_str = f"{hour:02d}:00"
            if time_str not in bookings_data[queue]:
                 bookings_data[queue][time_str] = {"available": True, "booked_by": None}
        
        sorted_times = sorted(bookings_data[queue].items(), key=lambda x: datetime.strptime(x[0], "%H:%M").time())
        bookings_data[queue] = {time_str: details for time_str, details in sorted_times}

    return bookings_data

def update_daily_bookings_in_db():
    """
    Gestiona la persistencia diaria en la base de datos:
    - Borra los días que ya no son relevantes.
    - Asegura que existan los slots para hoy y mañana.
    """
    today_local = date.today()
    
    # Fechas que deben estar en la base de datos
    expected_dates_objs = [
        today_local,
        today_local + timedelta(days=1)
    ]
    expected_date_strs = [d.isoformat() for d in expected_dates_objs]

    # Eliminar reservas de días que ya pasaron o no son "Hoy" ni "Mañana"
    # Convertimos a string para comparar con booking_date de la DB
    Booking.query.filter(Booking.booking_date.notin_(expected_dates_objs)).delete(synchronize_session=False)
    db.session.commit()

    # Asegurarse de que los slots para Hoy y Mañana existan en la DB
    for d_obj in expected_dates_objs:
        initialize_all_slots_for_day(d_obj)


# --- Rutas de la Aplicación Web (Flask) ---

@app.route('/')
def index():
    """Muestra la página principal con las colas de los dos días (Hoy y Mañana)."""
    
    # Asegúrate de que la base de datos tenga los slots correctos para hoy y mañana
    with app.app_context(): # Se requiere app_context para operaciones de DB fuera de un request
        update_daily_bookings_in_db()

    # Obtener la fecha y hora actual en UTC para marcar slots pasados
    now_utc = datetime.now(timezone.utc)
    current_hour_utc = now_utc.hour # Hora actual UTC

    today_local = date.today() # Fecha actual local para la interfaz

    ordered_display_dates = {}

    # Procesar "Hoy"
    today_bookings = get_bookings_for_display(today_local)
    # Marcar horas pasadas para "Hoy"
    for queue in QUEUES:
        for hour_str, details in today_bookings[queue].items():
            slot_hour = int(hour_str.split(':')[0])
            # Compara con la hora actual UTC
            if slot_hour < current_hour_utc:
                details["available"] = False
                if details["booked_by"] is None: # Si no estaba reservado y ya pasó
                    details["booked_by"] = "Pasado" 
    ordered_display_dates[today_local.isoformat()] = today_bookings

    # Procesar "Mañana"
    tomorrow_local = today_local + timedelta(days=1)
    tomorrow_bookings = get_bookings_for_display(tomorrow_local)
    ordered_display_dates[tomorrow_local.isoformat()] = tomorrow_bookings
    
    return render_template(
        'index.html',
        bookings=ordered_display_dates,
        queues=QUEUES,
        today=today_local.isoformat(),
        now_utc=now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
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
        return redirect(url_for('index'))

    # Convierte la fecha string a objeto date para la DB
    booking_date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

    # Busca el slot en la base de datos
    slot_to_book = Booking.query.filter_by(
        booking_date=booking_date_obj,
        queue_type=queue_type,
        time_slot=time_slot
    ).first()

    if slot_to_book and slot_to_book.available:
        # Verifica también que no sea un slot pasado (solo para hoy)
        now_utc = datetime.now(timezone.utc)
        current_hour_utc = now_utc.hour
        
        if booking_date_obj == date.today() and int(time_slot.split(':')[0]) < current_hour_utc:
            flash(f'Error: No se pudo reservar el slot {time_slot}. Ya ha pasado.', 'error')
            return redirect(url_for('index'))

        slot_to_book.booked_by = booked_by_name
        slot_to_book.available = False
        
        try:
            db.session.commit()
            flash(f'¡Reserva exitosa para {booked_by_name} en {date_str} a las {time_slot}!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al guardar la reserva: {e}', 'error')
            print(f"Error al guardar la reserva: {e}")
    else:
        flash(f'Error: No se pudo reservar el slot {time_slot}. Posiblemente ya reservado o inválido.', 'error')
    
    return redirect(url_for('index'))


# --- Inicialización de la Aplicación ---
if __name__ == '__main__':
    # Asegúrate de crear las tablas de la DB antes de iniciar la app
    # Esto es crucial para la primera ejecución o si el esquema cambia
    with app.app_context():
        db.create_all()
        # Puedes añadir una inicialización de datos aquí si es la primera vez que se ejecuta
        # o si quieres asegurar que los días actuales estén en la DB al iniciar el server
        update_daily_bookings_in_db()

    port = int(os.getenv('PORT', 5000))
    # En producción, debug debe ser False
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False') == 'True')