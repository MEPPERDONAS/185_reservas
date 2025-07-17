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
    
    # --- Lógica para 'first_in_queue' ---
    # Inicializa el diccionario para almacenar la primera reserva disponible por cola
    first_in_queue = {}
    
    # Itera sobre cada tipo de cola
    for queue_name in QUEUES:
        found_first = False
        # Primero busca en los bookings de HOY
        for hour_str, details in ordered_display_dates[today_local.isoformat()][queue_name].items():
            slot_time = datetime.strptime(hour_str, "%H:%M").time()
            
            # Convierte la hora actual UTC a un objeto time para comparar con slot_time
            # Ojo: la hora actual en Render es UTC. Si tus slots son siempre en hora local,
            # asegúrate de que la comparación de "pasado" sea consistente.
            # Aquí, solo consideramos slots futuros para "first_in_queue"
            
            if details["available"] and (today_local > date.today() or slot_time.hour >= current_hour_utc):
                first_in_queue[queue_name] = {
                    "date": today_local.isoformat(),
                    "time": hour_str,
                    "queue": queue_name
                }
                found_first = True
                break # Salimos del bucle de horas para esta cola
        
        # Si no se encontró ninguna disponible para hoy, busca en los bookings de MAÑANA
        if not found_first:
            for hour_str, details in ordered_display_dates[tomorrow_local.isoformat()][queue_name].items():
                if details["available"]:
                    first_in_queue[queue_name] = {
                        "date": tomorrow_local.isoformat(),
                        "time": hour_str,
                        "queue": queue_name
                    }
                    found_first = True
                    break # Salimos del bucle de horas para esta cola
        
        # Si aún no se encontró nada (ej. todo reservado), asigna un valor por defecto
        if not found_first:
            first_in_queue[queue_name] = {
                "date": "N/A",
                "time": "N/A",
                "queue": queue_name,
                "message": "No hay slots disponibles"
            }
    # --- Fin de la lógica para 'first_in_queue' ---


    return render_template(
        'index.html',
        bookings=ordered_display_dates,
        queues=QUEUES,
        today=today_local.isoformat(),
        now_utc=now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        first_in_queue=first_in_queue # <-- ¡Aquí pasamos la nueva variable!
    )

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        update_daily_bookings_in_db()

    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False') == 'True')