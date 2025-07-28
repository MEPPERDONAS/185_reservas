import os
from datetime import datetime, timedelta, date, time, timezone
import requests
import time
import threading

from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, or_

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'development')
DISCORD_BOT_TOKEN = os.getenv("TOKEN")
DISCORD_ANNOUNCEMENT_CHANNEL_ID = os.getenv("CANAL_AVISOS_ID")

DISCORD_CHANNELS = {
    "Welcome Channel": "1349021786217644103",
    "Rules Channel": "1349021784409772114",
    "Announcements Channel": "1349021795046654023"
}

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

class Bonus(db.Model):
    __tablename__ = 'bonuses'
    id = db.Column(db.Integer, primary_key=True)
    queue_type = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False) # e.g., "10:00"
    duration_hours = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<Bonus {self.queue_type} from {self.start_date} {self.start_time} for {self.duration_hours}h (Active: {self.active})>"

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
        all_hours_for_day = [f"{h:02d}:00" for h in range(24)]
        temp_bookings = {}
        for h in all_hours_for_day:
            temp_bookings[h] = bookings_data[queue].get(h, {"available": True, "booked_by": None})

        sorted_times = sorted(temp_bookings.items(), key=lambda x: datetime.strptime(x[0], "%H:%M").time())
        bookings_data[queue] = {time_str: details for time_str, details in sorted_times}

    return bookings_data


def update_daily_bookings_in_db():
    today_local = date.today()
    
    # Queremos mantener datos para los próximos 7 días para la visualización.
    # Así que eliminamos cualquier cosa más allá de eso.
    max_date_to_keep = today_local + timedelta(days=6) # Hoy + 6 días = 7 días en total
    
    # Obtener todas las fechas que deberíamos tener inicializadas (hoy hasta 6 días en el futuro)
    expected_dates_objs = [today_local + timedelta(days=i) for i in range(7)]

    # Eliminar reservas que estén fuera del rango de los próximos 7 días
    Booking.query.filter(Booking.booking_date > max_date_to_keep).delete(synchronize_session=False)
    db.session.commit()

    # Asegurarse de que todos los slots para los próximos 7 días estén inicializados
    for d_obj in expected_dates_objs:
        initialize_all_slots_for_day(d_obj)


# --- Rutas de la Aplicación Web (Flask) ---

@app.route('/')
def index():
    with app.app_context():
        update_daily_bookings_in_db()

    now_utc = datetime.now(timezone.utc)
    
    today_local = date.today()
    
    # Generar las fechas para los próximos 7 días
    display_dates = []
    for i in range(7):
        display_dates.append(today_local + timedelta(days=i))

    ordered_display_dates = {}

    for d_obj in display_dates:
        day_bookings = get_bookings_for_display(d_obj)
        # Marcar slots pasados como no disponibles para el día actual
        if d_obj == today_local:
            for queue in QUEUES:
                for hour_str, details in day_bookings[queue].items():
                    slot_dt_obj = datetime.combine(d_obj, datetime.strptime(hour_str, "%H:%M").time()).replace(tzinfo=timezone.utc)
                    if slot_dt_obj < now_utc:
                        details["available"] = False
                        if details["booked_by"] is None:
                            details["booked_by"] = "Pasado"
        ordered_display_dates[d_obj.isoformat()] = day_bookings

    first_in_queue = {}

    for queue_name in QUEUES:
        found_next_booked_slot = False
        for d_obj in display_dates: # Iterar por todos los días a mostrar
            if found_next_booked_slot:
                break

            current_day_bookings = ordered_display_dates[d_obj.isoformat()]
            for hour_str, details in current_day_bookings[queue_name].items():
                slot_time_obj = datetime.strptime(hour_str, "%H:%M").time()
                slot_datetime_aware = datetime.combine(d_obj, slot_time_obj).replace(tzinfo=timezone.utc)

                is_future_slot = False
                if slot_datetime_aware > now_utc:
                    is_future_slot = True

                if not details["available"] and details["booked_by"] != "Pasado" and is_future_slot:
                    first_in_queue[queue_name] = {
                        "date": d_obj.isoformat(),
                        "time": hour_str,
                        "queue": queue_name,
                        "booked_by": details["booked_by"]
                    }
                    found_next_booked_slot = True
                    break

        if not found_next_booked_slot:
            first_in_queue[queue_name] = {
                "date": "N/A",
                "time": "N/A",
                "queue": queue_name,
                "booked_by": "N/A",
                "message": "There are no upcoming shifts booked.."
            }

    active_bonuses = Bonus.query.filter(Bonus.active == True).all()

    # Ajustar bonused_slots para todos los días a mostrar
    bonused_slots = {queue: {d.isoformat(): set() for d in display_dates} for queue in QUEUES}

    bonused_queues_now = {queue: False for queue in QUEUES}

    for bonus in active_bonuses:
        bonus_start_dt = datetime.combine(bonus.start_date, datetime.strptime(bonus.start_time, "%H:%M").time()).replace(tzinfo=timezone.utc)
        bonus_end_dt = bonus_start_dt + timedelta(hours=bonus.duration_hours)

        if bonus_start_dt <= now_utc < bonus_end_dt:
            bonused_queues_now[bonus.queue_type] = True

        current_slot_dt = bonus_start_dt
        while current_slot_dt < bonus_end_dt:
            if current_slot_dt.date() in display_dates: # Verificar si la fecha del bonus está en las fechas a mostrar
                bonused_slots[bonus.queue_type][current_slot_dt.date().isoformat()].add(current_slot_dt.strftime("%H:%M"))
            current_slot_dt += timedelta(hours=1)
            # Limitar el loop para que no genere slots para días muy lejanos
            if current_slot_dt.date() > display_dates[-1]: # Si la fecha actual excede el último día a mostrar
                break


    bonuses_for_display = []
    for bonus in active_bonuses:
        bonus_start_dt = datetime.combine(bonus.start_date, datetime.strptime(bonus.start_time, "%H:%M").time()).replace(tzinfo=timezone.utc)
        bonus_end_dt = bonus_start_dt + timedelta(hours=bonus.duration_hours)

        if bonus_end_dt > now_utc:
            bonuses_for_display.append({
                "queue_type": bonus.queue_type.capitalize(),
                "start_time": bonus_start_dt.strftime("%Y-%m-%d %H:%M"),
                "end_time": bonus_end_dt.strftime("%H:%M"),
                "duration": bonus.duration_hours
            })
    bonuses_for_display.sort(key=lambda x: datetime.strptime(x['start_time'], "%Y-%m-%d %H:%M"))


    return render_template(
        'index.html',
        bookings=ordered_display_dates,
        queues=QUEUES,
        display_dates=display_dates, # Pasar la lista de objetos de fecha
        today=today_local.isoformat(),
        now_utc=now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
        first_in_queue=first_in_queue,
        bonused_slots=bonused_slots,
        bonused_queues_now=bonused_queues_now,
        bonuses_for_display=bonuses_for_display
    )

def send_discord_notification(message, channel_id=None, max_retries=3):
    """Envía un mensaje al canal de Discord especificado o al canal de anuncios por defecto, con manejo de Rate Limits."""
    if not DISCORD_BOT_TOKEN:
        print("Error: TOKEN de Discord no configurado en variables de entorno.")
        return

    target_channel_id = channel_id if channel_id else DISCORD_ANNOUNCEMENT_CHANNEL_ID
    if not target_channel_id:
        print("Error: ID del canal de anuncios de Discord no configurado.")
        return
    # --- DEBUGGING TEMPORAL (¡ELIMINAR ESTO DESPUÉS!) ---
    print(f"DEBUG: Longitud del TOKEN: {len(DISCORD_BOT_TOKEN) if DISCORD_BOT_TOKEN else 0}")
    print(f"DEBUG: Canal de Discord a usar: {target_channel_id}")
    # --- FIN DEBUGGING TEMPORAL ---
    
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "content": message
    }
    url = f"https://discord.com/api/v10/channels/{target_channel_id}/messages"

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print(f"Notificación de Discord enviada exitosamente en intento {attempt + 1}: {message}")
            return

        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 429:
                retry_after = http_err.response.headers.get('Retry-After')
                wait_time = float(retry_after) / 1000 if retry_after else 1
                print(f"Error 429 (Too Many Requests). Esperando {wait_time:.2f} segundos antes de reintentar... (Intento {attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                print(f"Error HTTP al enviar notificación de Discord: {http_err}")
                break
        except requests.exceptions.ConnectionError as conn_err:
            print(f"Error de conexión al enviar notificación de Discord: {conn_err}")
            break
        except Exception as e:
            print(f"Error inesperado al enviar notificación de Discord: {e}")
            break
    else:
        print(f"Falló el envío de la notificación de Discord después de {max_retries} intentos: {message}")


@app.route('/book', methods=['POST'])
def book_slot():
    with app.app_context():
        date_str = request.form['date']
        queue_type = request.form['queue']
        time_slot = request.form['time']
        
        # Consideración: Idealmente, booked_by debería venir de la sesión del usuario si está logueado.
        # Por ahora, usamos el valor del formulario, asumiendo que es un identificador único.
        booked_by = request.form['booked_by'] 

        if not all([date_str, queue_type, time_slot, booked_by]):
            flash('Error: Todos los campos son requeridos.', 'error')
            return redirect(url_for('index'))

        try:
            booking_date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            # 1. Verificar si el usuario ya tiene una reserva activa en OTRA cola para la misma fecha y hora.
            existing_conflict_booking = Booking.query.filter(
                Booking.booked_by == booked_by,                 # Mismo usuario
                Booking.booking_date == booking_date_obj,       # Misma fecha
                Booking.time_slot == time_slot,                 # Misma hora
                Booking.queue_type != queue_type,               # PERO en una cola DIFERENTE
                Booking.available == False                      # Y que la reserva existente esté ocupada/activa
            ).first()

            if existing_conflict_booking:
                flash(f'You already have an active booking for **{date_str} at {time_slot}** in the **{existing_conflict_booking.queue_type.capitalize()}** queue. '
                      'You cannot book multiple queues at the same time.', 'error')
                return redirect(url_for('index'))
            
            # 2. Verificar la disponibilidad del slot actual
            slot = Booking.query.filter_by(
                booking_date=booking_date_obj,
                time_slot=time_slot,
                queue_type=queue_type
            ).first()

            if slot and slot.available:
                slot.booked_by = booked_by
                slot.available = False
                db.session.commit()
                flash(f'Slot {time_slot} in {queue_type.capitalize()} for {date_str} successfully booked by {booked_by}.', 'success')
                
                message = (
                    f"📢  **New Booking!**\n"
                    f"👤 **[ {booked_by} ]** \nhas booked a slot for **{queue_type.capitalize()}** "
                    f"on: \n**{date_str} at {time_slot} UTC**."
                )
                thread = threading.Thread(target=send_discord_notification, args=(message,))
                thread.start()
            else:
                flash(f'Error: El slot de {time_slot} en {queue_type.capitalize()} para el {date_str} no está disponible o ya fue reservado.', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Ocurrió un error al reservar: {e}', 'error')
            
    return redirect(url_for('index'))

@app.route('/admin')
def admin_panel():
    """
    Muestra un panel de administración con todas las reservas.
    """
    if 'username' not in session or session.get('role') != 'admin':
        flash('Access denied. Only administrators can access.', 'error')
        return redirect(url_for('login'))

    with app.app_context():
        now_utc = datetime.now(timezone.utc)
        current_date_utc = now_utc.date()
        current_time_utc_str = now_utc.strftime('%H:%M')

        # Mostrar todas las reservas futuras y las de hoy que no han pasado
        all_bookings = Booking.query.filter(
            and_(
                Booking.available == False, # Solo reservas ocupadas
                or_(
                    Booking.booking_date > current_date_utc, # Fechas futuras
                    and_(
                        Booking.booking_date == current_date_utc, # O fecha de hoy
                        Booking.time_slot >= current_time_utc_str # Y hora actual o futura
                    )
                )
            )
        ).order_by(Booking.booking_date, Booking.time_slot).all()
        
    return render_template('admin.html', all_bookings=all_bookings, queues=QUEUES)


@app.route('/admin/delete/<int:booking_id>', methods=['POST'])
def delete_booking(booking_id):
    """
    Borra una reserva específica de la base de datos.
    """
    if 'username' not in session or session.get('role') != 'admin':
        flash('Access denied. Only administrators can access.', 'error')
        return redirect(url_for('login'))

    with app.app_context():
        booking_to_delete = Booking.query.get_or_404(booking_id) 
        try:
            db.session.delete(booking_to_delete)
            db.session.commit()
            flash(f'Booking ID {booking_id} deleted successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error deleting the booking: {e}', 'error')
    return redirect(url_for('admin_panel'))


@app.route('/admin/edit/<int:booking_id>', methods=['GET', 'POST'])
def edit_booking(booking_id):
    """
    Muestra un formulario para editar una reserva y procesa la actualización.
    """
    if 'username' not in session or session.get('role') != 'admin':
        flash('Access denied. Only administrators can access.', 'error')
        return redirect(url_for('login'))

    with app.app_context():
        booking_to_edit = Booking.query.get_or_404(booking_id)

        if request.method == 'POST':
            booking_to_edit.booked_by = request.form['booked_by']
            booking_to_edit.available = ('available' in request.form)

            try:
                db.session.commit()
                flash(f'Reserva ID {booking_id} actualizada exitosamente.', 'success')
                return redirect(url_for('admin_panel'))
            except Exception as e:
                db.session.rollback()
                flash(f'Error updating the booking: {e}', 'error')
        
        return render_template('edit_booking.html', booking=booking_to_edit, queues=QUEUES)

@app.route('/admin/bonuses', methods=['GET', 'POST'])
def manage_bonuses():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Access denied. Only administrators can access.', 'error')
        return redirect(url_for('login'))

    with app.app_context():
        if request.method == 'POST':
            queue_type = request.form['queue_type']
            start_date_str = request.form['start_date']
            
            start_hour_selected = request.form['start_time']
            start_time_formatted = f"{start_hour_selected}:00"

            duration_hours = int(request.form['duration_hours'])

            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                
                if duration_hours <= 0:
                    flash('Error: Duration must be at least 1 hour.', 'error')
                    return redirect(url_for('manage_bonuses'))

                new_bonus = Bonus(
                    queue_type=queue_type,
                    start_date=start_date,
                    start_time=start_time_formatted, 
                    duration_hours=duration_hours,
                    active=True
                )
                db.session.add(new_bonus)
                db.session.commit()
                flash('Bonus added successfully.', 'success')
                
                bonus_start_dt_utc = datetime.combine(start_date, datetime.strptime(start_time_formatted, "%H:%M").time()).replace(tzinfo=timezone.utc)
                bonus_end_dt_utc = bonus_start_dt_utc + timedelta(hours=duration_hours)

                message = (
                    f"✨ **Bonus Activated!** The **{queue_type.capitalize()}** queue "
                    f"will have a bonus from **{start_date_str} at {start_time_formatted} UTC** "
                    f"for **{duration_hours} hour(s)** (until {bonus_end_dt_utc.strftime('%H:%M')} UTC)."
                )
                thread = threading.Thread(target=send_discord_notification, args=(message,))
                thread.start()

            except ValueError:
                flash('Error: Invalid start date format.', 'error')
                db.session.rollback()
            except Exception as e:
                db.session.rollback()
                flash(f'An error occurred while adding the bonus: {e}', 'error')
            return redirect(url_for('manage_bonuses'))

        all_bonuses = Bonus.query.order_by(Bonus.start_date, Bonus.start_time).all()
        return render_template('manage_bonuses.html', bonuses=all_bonuses, queues=QUEUES)
    
@app.route('/send_discord_message', methods=['GET', 'POST'])
def send_discord_message():
    if 'username' not in session or session.get('role') != 'admin':
        flash('Access denied. Only administrators can access.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        channel_id = request.form.get('channel_id')
        message_content = request.form.get('message_content')

        if not channel_id or not message_content:
            flash('Please fill in all fields.', 'error')
            return redirect(url_for('send_discord_message'))

        formatted_message = (
            f"👑** Administration Message **👑\n"
            f"{message_content}"
        )

        try:
            thread = threading.Thread(target=send_discord_notification, args=(formatted_message, channel_id))
            thread.start()
            flash('Message sent to Discord successfully!', 'success')
        except Exception as e:
            flash(f'An error occurred while sending the message to Discord: {e}', 'error')

        return redirect(url_for('send_discord_message'))

    return render_template('send_discord_message.html', channels=DISCORD_CHANNELS)

@app.route('/admin/bonuses/toggle/<int:bonus_id>', methods=['POST'])
def toggle_bonus_active(bonus_id):
    if 'username' not in session or session.get('role') != 'admin':
        flash('Access denied. Only administrators can access.', 'error')
        return redirect(url_for('login'))

    with app.app_context():
        bonus = Bonus.query.get_or_404(bonus_id)
        bonus.active = not bonus.active
        try:
            db.session.commit()
            flash(f'Bonus status for ID {bonus_id} changed to {"active" if bonus.active else "inactive"}.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error changing bonus status: {e}', 'error')
    return redirect(url_for('manage_bonuses'))

@app.route('/admin/bonuses/delete/<int:bonus_id>', methods=['POST'])
def delete_bonus(bonus_id):
    if 'username' not in session or session.get('role') != 'admin':
        flash('Access denied. Only administrators can access.', 'error')
        return redirect(url_for('login'))

    with app.app_context():
        bonus_to_delete = Bonus.query.get_or_404(bonus_id)
        try:
            db.session.delete(bonus_to_delete)
            db.session.commit()
            flash(f'Bonus ID {bonus_id} deleted successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error al eliminar bonificación: {e}', 'error')
    return redirect(url_for('manage_bonuses'))


USERS = {
    "admin": {"password": "adminpassword", "role": "admin"},
    "user1": {"password": "userpassword", "role": "user"}
}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = USERS.get(username)

        if user and user['password'] == password:
            session['username'] = username
            session['role'] = user['role']
            flash('Login successful!', 'success')
            if user['role'] == 'admin':
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('index'))
        else:
            flash('Incorrect username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    session.pop('role', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        update_daily_bookings_in_db()

    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('FLASK_DEBUG', 'False') == 'True')