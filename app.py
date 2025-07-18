import os
from datetime import datetime, timedelta, date, time, timezone

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'una_clave_secreta_super_segura_y_larga_por_defecto_aqui')

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL').replace("postgres://", "postgresql://", 1) if os.getenv('DATABASE_URL') else 'sqlite:///reservas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

QUEUES = ["building", "research", "training"]

class Booking(db.Model):
    __tablename__ = 'bookings'
    id = db.Column(db.Integer, primary_key=True)
    booking_date = db.Column(db.Date, nullable=False)
    time_slot = db.Column(db.String(5), nullable=False)
    queue_type = db.Column(db.String(50), nullable=False)
    booked_by = db.Column(db.String(100), nullable=True)
    available = db.Column(db.Boolean, default=True, nullable=False)
    __table_args__ = (db.UniqueConstraint('booking_date', 'time_slot', 'queue_type', name='_booking_uc'),)

    def __repr__(self):
        return f"<Booking {self.booking_date} {self.time_slot} {self.queue_type} - Available: {self.available}, Booked By: {self.booked_by}>"

# --- Funciones de Utilidad para la Base de Datos ---

def initialize_all_slots_for_day(target_date_obj):
    for queue_name in QUEUES:
        for hour in range(24):
            time_str = f"{hour:02d}:00"
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
    bookings_data = {queue: {} for queue in QUEUES}
    all_day_bookings = Booking.query.filter_by(booking_date=target_date_obj).all()

    for booking in all_day_bookings:
        if booking.queue_type in bookings_data:
            bookings_data[booking.queue_type][booking.time_slot] = {
                "available": booking.available,
                "booked_by": booking.booked_by
            }

    for queue in QUEUES:
        # Asegurarse de que todas las horas estén presentes y ordenadas
        # Primero, crea una lista de todas las 24 horas del día
        all_hours_for_day = [f"{h:02d}:00" for h in range(24)]
        temp_bookings = {}
        for h in all_hours_for_day:
            temp_bookings[h] = bookings_data[queue].get(h, {"available": True, "booked_by": None})

        # Luego, ordénalas
        sorted_times = sorted(temp_bookings.items(), key=lambda x: datetime.strptime(x[0], "%H:%M").time())
        bookings_data[queue] = {time_str: details for time_str, details in sorted_times}

    return bookings_data


def update_daily_bookings_in_db():
    today_local = date.today()
    
    expected_dates_objs = [
        today_local,
        today_local + timedelta(days=1)
    ]

    Booking.query.filter(Booking.booking_date.notin_(expected_dates_objs)).delete(synchronize_session=False)
    db.session.commit()

    for d_obj in expected_dates_objs:
        initialize_all_slots_for_day(d_obj)

# --- Rutas de la Aplicación Web (Flask) ---

@app.route('/')
def index():
    with app.app_context():
        update_daily_bookings_in_db()

    now_utc = datetime.now(timezone.utc)
    current_hour_utc = now_utc.hour

    today_local = date.today()

    ordered_display_dates = {}

    # Procesar "Hoy"
    today_bookings = get_bookings_for_display(today_local)
    for queue in QUEUES:
        for hour_str, details in today_bookings[queue].items():
            slot_hour = int(hour_str.split(':')[0])
            if slot_hour < current_hour_utc:
                details["available"] = False
                if details["booked_by"] is None:
                    details["booked_by"] = "Pasado"
    ordered_display_dates[today_local.isoformat()] = today_bookings

    # Procesar "Mañana"
    tomorrow_local = today_local + timedelta(days=1)
    tomorrow_bookings = get_bookings_for_display(tomorrow_local)
    ordered_display_dates[tomorrow_local.isoformat()] = tomorrow_bookings
    
    # --- Lógica para 'first_in_queue' - Muestra el próximo turno tomado ---
    first_in_queue = {}
    
    # Itera sobre cada tipo de cola
    for queue_name in QUEUES:
        found_next_booked_slot = False
        
        # Iterar sobre hoy y mañana para encontrar el próximo turno tomado
        for d_obj in [today_local, tomorrow_local]:
            if found_next_booked_slot: # Si ya encontramos uno para esta cola, pasamos a la siguiente
                break

            current_day_bookings = ordered_display_dates[d_obj.isoformat()]
            for hour_str, details in current_day_bookings[queue_name].items():
                slot_time_obj = datetime.strptime(hour_str, "%H:%M").time()
                
                # Comprobar si es un slot futuro (no ha pasado todavía)
                # La hora actual en Render es UTC. La comparación debe ser consistente.
                is_future_slot = False
                if d_obj == today_local:
                    if slot_time_obj.hour >= current_hour_utc: # Para hoy, solo slots de la hora actual o futura
                        is_future_slot = True
                elif d_obj > today_local: # Para cualquier día futuro (como mañana), todos los slots son futuros
                    is_future_slot = True

                # Buscamos un slot que NO esté disponible (es decir, que esté reservado)
                # y que sea un slot futuro (no "Pasado")
                if not details["available"] and details["booked_by"] != "Pasado" and is_future_slot:
                    first_in_queue[queue_name] = {
                        "date": d_obj.isoformat(),
                        "time": hour_str,
                        "queue": queue_name,
                        "booked_by": details["booked_by"] # ¡Aquí incluimos quién lo reservó!
                    }
                    found_next_booked_slot = True
                    break # Salimos del bucle de horas para esta cola
        
        # Si no se encontró ningún turno tomado para hoy o mañana
        if not found_next_booked_slot:
            first_in_queue[queue_name] = {
                "date": "N/A",
                "time": "N/A",
                "queue": queue_name,
                "booked_by": "N/A",
                "message": "No hay turnos próximos tomados"
            }
    # --- Fin de la lógica para 'first_in_queue' ---

    return render_template(
        'index.html',
        bookings=ordered_display_dates,
        queues=QUEUES,
        today=today_local.isoformat(),
        now_utc=now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        first_in_queue=first_in_queue
    )

# --- AÑADE ESTA FUNCIÓN AQUÍ ABAJO ---
@app.route('/book', methods=['POST'])
def book_slot():
    with app.app_context():
        date_str = request.form['date']
        queue_type = request.form['queue']
        time_slot = request.form['time']
        booked_by = request.form['booked_by']

        # Validar la entrada (opcional pero recomendado)
        if not all([date_str, queue_type, time_slot, booked_by]):
            flash('Error: Todos los campos son requeridos.', 'error')
            return redirect(url_for('index'))

        try:
            booking_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # Buscar el slot en la base de datos
            slot = Booking.query.filter_by(
                booking_date=booking_date_obj,
                time_slot=time_slot,
                queue_type=queue_type
            ).first()

            if slot and slot.available:
                slot.booked_by = booked_by
                slot.available = False
                db.session.commit()
                flash(f'Slot de {time_slot} en {queue_type} para el {date_str} reservado por {booked_by}.', 'success')
            else:
                flash(f'Error: El slot de {time_slot} en {queue_type} para el {date_str} no está disponible.', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocurrió un error al reservar: {e}', 'error')
        
    return redirect(url_for('index'))

# --- FIN DE LA FUNCIÓN A AÑADIR ---


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        update_daily_bookings_in_db()

    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False') == 'True')