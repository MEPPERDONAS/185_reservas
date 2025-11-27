import os
from datetime import datetime, timedelta, date, time, timezone
import requests
import time  # noqa: F811
import threading
from flask_migrate import Migrate
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, or_

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "development")
DISCORD_BOT_TOKEN = os.getenv("TOKEN")

DISCORD_CHANNELS = {
    "[SOL] General Channel": "1339362327593488506",
    "[SOL] Rules Channel": "1339366090244886611",
    "[SOL] Announcements Channel": "1349021795046654023",
    "QUEUEChannel": "1349021795046654023",
}
DISCORD_ANNOUNCEMENT_CHANNEL_ID = DISCORD_CHANNELS.get("QUEUEChannel")

app.config["SQLALCHEMY_DATABASE_URI"] = (
    os.getenv("DATABASE_URL").replace("postgres://", "postgresql://", 1)
    if os.getenv("DATABASE_URL")
    else "sqlite:///reservas.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

QUEUES = ["building", "research", "training"]


class WeeklyEvent(db.Model):
    __tablename__ = "weekly_events"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    monday = db.Column(db.String(255), nullable=True)
    tuesday = db.Column(db.String(255), nullable=True)
    wednesday = db.Column(db.String(255), nullable=True)
    thursday = db.Column(db.String(255), nullable=True)
    friday = db.Column(db.String(255), nullable=True)
    saturday = db.Column(db.String(255), nullable=True)
    sunday = db.Column(db.String(255), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    reminder_time = db.Column(db.String(5), nullable=True, default="00:00")
    last_sent_date = db.Column(db.Date, nullable=True)
    active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<WeeklyEvent {self.name} from {self.start_date} to {self.end_date} (Active: {self.active}) at {self.reminder_time}>"


class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    booking_date = db.Column(db.Date, nullable=False)
    time_slot = db.Column(db.String(5), nullable=False)
    queue_type = db.Column(db.String(50), nullable=False)
    booked_by = db.Column(db.String(100), nullable=True)
    available = db.Column(db.Boolean, default=True, nullable=False)
    __table_args__ = (
        db.UniqueConstraint(
            "booking_date", "time_slot", "queue_type", name="_booking_uc"
        ),
    )

    def __repr__(self):
        return f"<Booking {self.booking_date} {self.time_slot} {self.queue_type} - Available: {self.available}, Booked By: {self.booked_by}>"


class Bonus(db.Model):
    __tablename__ = "bonuses"
    id = db.Column(db.Integer, primary_key=True)
    queue_type = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    duration_hours = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f"<Bonus {self.queue_type} from {self.start_date} {self.start_time} for {self.duration_hours}h (Active: {self.active})>"


def initialize_all_slots_for_day(target_date_obj):
    for queue_name in QUEUES:
        for hour in range(24):
            time_str = f"{hour:02d}:00"
            existing_slot = Booking.query.filter_by(
                booking_date=target_date_obj, time_slot=time_str, queue_type=queue_name
            ).first()

            if not existing_slot:
                new_booking = Booking(
                    booking_date=target_date_obj,
                    time_slot=time_str,
                    queue_type=queue_name,
                    available=True,
                    booked_by=None,
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
                "booked_by": booking.booked_by,
                "id": booking.id,
            }

    for queue in QUEUES:
        all_hours_for_day = [f"{h:02d}:00" for h in range(24)]
        temp_bookings = {}
        for h in all_hours_for_day:
            temp_bookings[h] = bookings_data[queue].get(
                h, {"available": True, "booked_by": None}
            )

        sorted_times = sorted(
            temp_bookings.items(), key=lambda x: datetime.strptime(x[0], "%H:%M").time()
        )
        bookings_data[queue] = {time_str: details for time_str, details in sorted_times}

    return bookings_data


def update_daily_bookings_in_db():
    today_local = date.today()
    max_date_to_keep = today_local + timedelta(days=6)
    expected_dates_objs = [today_local + timedelta(days=i) for i in range(7)]
    Booking.query.filter(Booking.booking_date > max_date_to_keep).delete(
        synchronize_session=False
    )
    db.session.commit()

    for d_obj in expected_dates_objs:
        initialize_all_slots_for_day(d_obj)


def send_discord_notification(message, channel_id=None, max_retries=3):
    if not DISCORD_BOT_TOKEN:
        print("Error: TOKEN de Discord no configurado en variables de entorno.")
        return

    target_channel_id = channel_id if channel_id else DISCORD_ANNOUNCEMENT_CHANNEL_ID
    if not target_channel_id:
        print("Error: ID del canal de anuncios de Discord no configurado.")
        return

    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"content": message}
    url = f"https://discord.com/api/v10/channels/{target_channel_id}/messages"

    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            print(
                f"Notificación de Discord enviada exitosamente en intento {attempt + 1}: {message} al canal: {target_channel_id}"
            )
            return

        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 429:
                retry_after = http_err.response.headers.get("Retry-After")
                wait_time = float(retry_after) / 1000 if retry_after else 1
                print(
                    f"Error 429 (Too Many Requests). Esperando {wait_time:.2f} segundos antes de reintentar... (Intento {attempt + 1}/{max_retries})"
                )
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
        print(
            f"Falló el envío de la notificación de Discord después de {max_retries} intentos: {message}"
        )


def check_and_send_weekly_event_reminders():
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    current_time_obj = now_utc.time().replace(second=0, microsecond=0)
    weekday = today.weekday()

    active_events = WeeklyEvent.query.filter(
        WeeklyEvent.active,
        WeeklyEvent.start_date <= today,
        WeeklyEvent.end_date >= today,
    ).all()

    for active_event in active_events:
        day_messages = [
            active_event.monday,
            active_event.tuesday,
            active_event.wednesday,
            active_event.thursday,
            active_event.friday,
            active_event.saturday,
            active_event.sunday,
        ]

        message_for_today = day_messages[weekday]

        try:
            reminder_time_from_db = datetime.strptime(
                active_event.reminder_time, "%H:%M"
            ).time()

            if message_for_today and reminder_time_from_db <= current_time_obj:
                if (
                    active_event.last_sent_date is None
                    or active_event.last_sent_date < today
                ):
                    message = (
                        f"🔔 **Recordatorio de Evento @everyone : {active_event.name}**\n"
                        f"**Día de hoy ({today.strftime('%A')}):** {message_for_today}"
                    )

                    kvk_channel_id = DISCORD_CHANNELS.get("[SOL] KVK Events Channel")
                    if kvk_channel_id:
                        send_discord_notification(message, kvk_channel_id)
                        active_event.last_sent_date = today
                        db.session.commit()
                    else:
                        print(
                            "Error: 'KVK Events Channel' no está configurado en DISCORD_CHANNELS."
                        )
        except ValueError:
            print(
                f"Error: Formato de hora inválido para el evento {active_event.name}. Se esperaba HH:MM."
            )


@app.route("/")
def index():
    with app.app_context():
        now_utc = datetime.now(timezone.utc)
        today_local = date.today()

        display_dates = []
        for i in range(7):
            display_dates.append(today_local + timedelta(days=i))

        ordered_display_dates = {}

        for d_obj in display_dates:
            day_bookings = get_bookings_for_display(d_obj)
            for queue in QUEUES:
                for hour_str, details in day_bookings[queue].items():
                    slot_dt_obj = datetime.combine(
                        d_obj, datetime.strptime(hour_str, "%H:%M").time()
                    ).replace(tzinfo=timezone.utc)

                    if slot_dt_obj <= now_utc < (slot_dt_obj + timedelta(hours=1)):
                        details["is_current"] = True
                    else:
                        details["is_current"] = False

                    if (slot_dt_obj + timedelta(hours=1)) < now_utc:
                        details["is_past"] = True
                    else:
                        details["is_past"] = False

                    if details["is_past"] and details["booked_by"] is None:
                        details["booked_by"] = "Pasado"
                        details["available"] = False

            ordered_display_dates[d_obj.isoformat()] = day_bookings

        current_in_queue = {}
        for queue_name in QUEUES:
            found_current_booked_slot = False
            for d_obj in display_dates:
                if found_current_booked_slot:
                    break

                current_day_bookings = ordered_display_dates.get(d_obj.isoformat(), {})

                for hour_str, details in current_day_bookings.get(
                    queue_name, {}
                ).items():
                    slot_time_obj = datetime.strptime(hour_str, "%H:%M").time()

                    slot_datetime_aware_start = datetime.combine(
                        d_obj, slot_time_obj
                    ).replace(tzinfo=timezone.utc)
                    slot_datetime_aware_end = slot_datetime_aware_start + timedelta(
                        hours=1
                    )

                    is_currently_active = (
                        slot_datetime_aware_start <= now_utc < slot_datetime_aware_end
                    )

                    if (
                        not details["available"]
                        and details["booked_by"] != "Pasado"
                        and is_currently_active
                    ):
                        current_in_queue[queue_name] = {
                            "date": d_obj.isoformat(),
                            "time": hour_str,
                            "queue": queue_name,
                            "booked_by": details["booked_by"],
                        }
                        found_current_booked_slot = True
                        break

            if not found_current_booked_slot:
                current_in_queue[queue_name] = {
                    "date": "N/A",
                    "time": "N/A",
                    "queue": queue_name,
                    "booked_by": "N/A",
                    "message": "There are no active shifts booked.",
                }

        active_bonuses = Bonus.query.filter(Bonus.active).all()
        bonused_slots = {
            queue: {d.isoformat(): set() for d in display_dates} for queue in QUEUES
        }
        bonused_queues_now = {queue: False for queue in QUEUES}

        for bonus in active_bonuses:
            bonus_start_dt = datetime.combine(
                bonus.start_date, datetime.strptime(bonus.start_time, "%H:%M").time()
            ).replace(tzinfo=timezone.utc)
            bonus_end_dt = bonus_start_dt + timedelta(hours=bonus.duration_hours)

            if bonus_start_dt <= now_utc < bonus_end_dt:
                bonused_queues_now[bonus.queue_type] = True

            current_slot_dt = bonus_start_dt
            while current_slot_dt < bonus_end_dt:
                if current_slot_dt.date() in display_dates:
                    bonused_slots[bonus.queue_type][
                        current_slot_dt.date().isoformat()
                    ].add(current_slot_dt.strftime("%H:%M"))
                current_slot_dt += timedelta(hours=1)
                if current_slot_dt.date() > display_dates[-1]:
                    break

        bonuses_for_display = []
        for bonus in active_bonuses:
            bonus_start_dt = datetime.combine(
                bonus.start_date, datetime.strptime(bonus.start_time, "%H:%M").time()
            ).replace(tzinfo=timezone.utc)
            bonus_end_dt = bonus_start_dt + timedelta(hours=bonus.duration_hours)

            if bonus_end_dt > now_utc:
                bonuses_for_display.append(
                    {
                        "queue_type": bonus.queue_type.capitalize(),
                        "start_time": bonus_start_dt.strftime("%Y-%m-%d %H:%M"),
                        "end_time": bonus_end_dt.strftime("%H:%M"),
                        "duration": bonus.duration_hours,
                    }
                )
        bonuses_for_display.sort(
            key=lambda x: datetime.strptime(x["start_time"], "%Y-%m-%d %H:%M")
        )

        return render_template(
            "index.html",
            bookings=ordered_display_dates,
            queues=QUEUES,
            display_dates=display_dates,
            today=today_local.isoformat(),
            now_utc=now_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
            current_in_queue=current_in_queue,
            bonused_slots=bonused_slots,
            bonused_queues_now=bonused_queues_now,
            bonuses_for_display=bonuses_for_display,
            session=session,
        )


@app.route("/find_closest_slot", methods=["POST"])
def find_closest_slot():
    days_input = request.form.get("days", type=int)
    hours_input = request.form.get("hours", type=int)
    minutes_input = request.form.get("minutes", type=int)

    if days_input is None or hours_input is None or minutes_input is None:
        return jsonify(
            {
                "success": False,
                "message": "Por favor, ingresa todos los valores (días, horas, minutos).",
            }
        ), 400

    if (
        not isinstance(days_input, int)
        or not isinstance(hours_input, int)
        or not isinstance(minutes_input, int)
    ):
        return jsonify(
            {"success": False, "message": "Los valores deben ser números enteros."}
        ), 400

    now_utc = datetime.now(timezone.utc)
    target_datetime_utc = now_utc + timedelta(
        days=days_input, hours=hours_input, minutes=minutes_input
    )
    target_datetime_rounded = target_datetime_utc.replace(second=0, microsecond=0)

    return jsonify(
        {
            "success": True,
            "date": target_datetime_rounded.date().isoformat(),
            "time": target_datetime_rounded.strftime("%H:%M"),
            "message": f"The approximate slot will be on [{target_datetime_rounded.date().isoformat()}] at [{target_datetime_rounded.strftime('%H:%M')}] UTC.",
            "timestamp_utc": target_datetime_rounded.timestamp(),
        }
    )


@app.route("/book", methods=["POST"])
def book_slot():
    with app.app_context():
        date_str = request.form["date"]
        queue_type = request.form["queue"]
        time_slot = request.form["time"]

        booked_by = request.form.get("booked_by")

        if not all([date_str, queue_type, time_slot, booked_by]):
            flash("Error: Todos los campos son requeridos.", "error")
            return redirect(url_for("index"))

        try:
            booking_date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()

            initialize_all_slots_for_day(booking_date_obj)

            existing_conflict_booking = Booking.query.filter(
                Booking.booked_by == booked_by,
                Booking.booking_date == booking_date_obj,
                Booking.time_slot == time_slot,
                Booking.queue_type != queue_type,
                not Booking.available,
            ).first()

            if existing_conflict_booking:
                flash(
                    f"Ya tienes una reserva activa para {date_str} a las {time_slot} en la cola de {existing_conflict_booking.queue_type.capitalize()}. "
                    "No puedes reservar varias colas a la vez.",
                    "error",
                )
                return redirect(url_for("index"))

            # Paso 2: Intentamos realizar una actualización atómica.
            updated_count = Booking.query.filter_by(
                booking_date=booking_date_obj,
                time_slot=time_slot,
                queue_type=queue_type,
                available=True,  # Solo actualizamos si el slot está marcado como disponible
            ).update({"booked_by": booked_by, "available": False})

            db.session.commit()

            if updated_count == 1:
                flash(
                    f"Slot on {queue_type.capitalize()} booked by\n[{booked_by}]",
                    "success",
                )

                message = (
                    f"👤 **[{booked_by}]** \nHas booked a slot "
                    f"for **{queue_type.capitalize()}** on:**{date_str} at {time_slot} UTC**\n."
                    f"https://one85-reservas.onrender.com"
                )
                thread = threading.Thread(
                    target=send_discord_notification, args=(message,)
                )
                thread.start()
            else:
                slot = Booking.query.filter_by(
                    booking_date=booking_date_obj,
                    time_slot=time_slot,
                    queue_type=queue_type,
                ).first()

                if not slot:
                    flash(
                        f"Error: El slot de {time_slot} en {queue_type.capitalize()} para el {date_str} no existe. Por favor, revisa la función de inicialización de slots.",
                        "error",
                    )
                elif not slot.available:
                    # El slot existe, pero ya está reservado.
                    flash(
                        f"Error: El slot de {time_slot} en {queue_type.capitalize()} para el {date_str} ya está reservado por {slot.booked_by}.",
                        "error",
                    )
                else:
                    flash(
                        f"Error: No se pudo reservar el slot de {time_slot} en {queue_type.capitalize()} para el {date_str} por una razón desconocida.",
                        "error",
                    )

        except Exception as e:
            db.session.rollback()
            print(f"Ocurrió un error en la reserva: {e}")
            flash(f"Ocurrió un error al reservar: {e}", "error")

    return redirect(url_for("index"))


@app.route("/cancel_booking", methods=["POST"])
def cancel_booking():
    booking_id = request.form.get("booking_id", type=int)
    booked_by_user = request.form.get("booked_by_user")

    if not booking_id or not booked_by_user:
        return jsonify(
            {"success": False, "message": "Missing booking ID or user name."}
        ), 400

    with app.app_context():
        booking_to_cancel = Booking.query.get(booking_id)

        if not booking_to_cancel:
            return jsonify({"success": False, "message": "Booking not found."}), 404

        if booking_to_cancel.booked_by != booked_by_user:
            return jsonify(
                {
                    "success": False,
                    "message": "You are not authorized to cancel this booking.",
                }
            ), 403

        booking_dt_obj = datetime.combine(
            booking_to_cancel.booking_date,
            datetime.strptime(booking_to_cancel.time_slot, "%H:%M").time(),
        ).replace(tzinfo=timezone.utc)
        now_utc = datetime.now(timezone.utc)
        if booking_dt_obj <= now_utc:
            return jsonify(
                {
                    "success": False,
                    "message": "Cannot cancel a slot that has already passed.",
                }
            ), 400

        try:
            booking_to_cancel.available = True
            booking_to_cancel.booked_by = None
            db.session.commit()

            message = (
                f"🚫 **Booking Cancelled!**\n"
                f"👤 **[ {booked_by_user} ]** \nhas cancelled their booking for **{booking_to_cancel.queue_type.capitalize()}** "
                f"on: \n**{booking_to_cancel.booking_date.isoformat()} at {booking_to_cancel.time_slot} UTC**."
            )
            thread = threading.Thread(target=send_discord_notification, args=(message,))
            thread.start()

            return jsonify(
                {"success": True, "message": "Booking successfully cancelled."}
            ), 200
        except Exception as e:
            db.session.rollback()
            print(f"Error cancelling booking: {e}")
            return jsonify(
                {"success": False, "message": f"Server error: {str(e)}"}
            ), 500


USERS = {
    "admin": {"password": "admin185", "role": "admin"},
    "user1": {"password": "userpassword", "role": "user"},
}


@app.shell_context_processor
def make_shell_context():
    return dict(db=db)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = USERS.get(username)

        if user and user["password"] == password:
            session["username"] = username
            session["role"] = user["role"]
            flash("Login successful!", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_panel"))
            else:
                return redirect(url_for("index"))
        else:
            flash("Incorrect username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("username", None)
    session.pop("role", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/admin")
def admin_panel():
    if "username" not in session or session.get("role") != "admin":
        flash("Access denied. Only administrators can access.", "error")
        return redirect(url_for("login"))

    with app.app_context():
        now_utc = datetime.now(timezone.utc)
        current_date_utc = now_utc.date()
        current_time_utc_str = now_utc.strftime("%H:%M")

        all_bookings = (
            Booking.query.filter(
                and_(
                    not Booking.available,
                    or_(
                        Booking.booking_date > current_date_utc,
                        and_(
                            Booking.booking_date == current_date_utc,
                            Booking.time_slot >= current_time_utc_str,
                        ),
                    ),
                )
            )
            .order_by(Booking.booking_date, Booking.time_slot)
            .all()
        )

    return render_template("admin.html", all_bookings=all_bookings, queues=QUEUES)


@app.route("/admin/delete/<int:booking_id>", methods=["POST"])
def delete_booking(booking_id):
    if "username" not in session or session.get("role") != "admin":
        flash("Access denied. Only administrators can access.", "error")
        return redirect(url_for("login"))

    with app.app_context():
        booking_to_delete = Booking.query.get_or_404(booking_id)
        try:
            db.session.delete(booking_to_delete)
            db.session.commit()
            flash(f"Booking ID {booking_id} deleted successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error deleting the booking: {e}", "error")
    return redirect(url_for("admin_panel"))


@app.route("/admin/edit/<int:booking_id>", methods=["GET", "POST"])
def edit_booking(booking_id):
    if "username" not in session or session.get("role") != "admin":
        flash("Access denied. Only administrators can access.", "error")
        return redirect(url_for("login"))

    with app.app_context():
        booking_to_edit = Booking.query.get_or_404(booking_id)

        if request.method == "POST":
            booking_to_edit.booked_by = request.form["booked_by"]
            booking_to_edit.available = "available" in request.form

            try:
                db.session.commit()
                flash(f"Reserva ID {booking_id} actualizada exitosamente.", "success")
                return redirect(url_for("admin_panel"))
            except Exception as e:
                db.session.rollback()
                flash(f"Error updating the booking: {e}", "error")

        return render_template(
            "edit_booking.html", booking=booking_to_edit, queues=QUEUES
        )


@app.route("/admin/bonuses", methods=["GET", "POST"])
def manage_bonuses():
    if "username" not in session or session.get("role") != "admin":
        flash("Access denied. Only administrators can access.", "error")
        return redirect(url_for("login"))

    with app.app_context():
        if request.method == "POST":
            queue_type = request.form["queue_type"]
            start_date_str = request.form["start_date"]

            start_hour_selected = request.form["start_time"]
            start_time_formatted = f"{start_hour_selected}:00"

            duration_hours = int(request.form["duration_hours"])

            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()

                if duration_hours <= 0:
                    flash("Error: Duration must be at least 1 hour.", "error")
                    return redirect(url_for("manage_bonuses"))

                new_bonus = Bonus(
                    queue_type=queue_type,
                    start_date=start_date,
                    start_time=start_time_formatted,
                    duration_hours=duration_hours,
                    active=True,
                )
                db.session.add(new_bonus)
                db.session.commit()
                flash("Bonus added successfully.", "success")

                bonus_start_dt_utc = datetime.combine(
                    start_date, datetime.strptime(start_time_formatted, "%H:%M").time()
                ).replace(tzinfo=timezone.utc)
                bonus_end_dt_utc = bonus_start_dt_utc + timedelta(hours=duration_hours)

                message = (
                    f"✨ **Bonus Activated!** The **{queue_type.capitalize()}** queue "
                    f"will have a bonus from **{start_date_str} at {start_time_formatted} UTC** "
                    f"for **{duration_hours} hour(s)** (until {bonus_end_dt_utc.strftime('%H:%M')} UTC)."
                )
                thread = threading.Thread(
                    target=send_discord_notification, args=(message,)
                )
                thread.start()

            except ValueError:
                flash("Error: Invalid start date format.", "error")
                db.session.rollback()
            except Exception as e:
                db.session.rollback()
                flash(f"An error occurred while adding the bonus: {e}", "error")
            return redirect(url_for("manage_bonuses"))

        all_bonuses = Bonus.query.order_by(Bonus.start_date, Bonus.start_time).all()
        return render_template(
            "manage_bonuses.html", bonuses=all_bonuses, queues=QUEUES
        )


@app.route("/send_discord_message", methods=["GET", "POST"])
def send_discord_message():
    if "username" not in session or session.get("role") != "admin":
        flash("Access denied. Only administrators can access.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        channel_id = request.form.get("channel_id")
        message_content = request.form.get("message_content")

        if not channel_id or not message_content:
            flash("Please fill in all fields.", "error")
            return redirect(url_for("send_discord_message"))

        formatted_message = f"👑** Administration Message **👑\n{message_content}"

        try:
            thread = threading.Thread(
                target=send_discord_notification, args=(formatted_message, channel_id)
            )
            thread.start()
            flash("Message sent to Discord successfully!", "success")
        except Exception as e:
            flash(
                f"An error occurred while sending the message to Discord: {e}", "error"
            )

        return redirect(url_for("send_discord_message"))

    return render_template("send_discord_message.html", channels=DISCORD_CHANNELS)


@app.route("/admin/bonuses/toggle/<int:bonus_id>", methods=["POST"])
def toggle_bonus_active(bonus_id):
    if "username" not in session or session.get("role") != "admin":
        flash("Access denied. Only administrators can access.", "error")
        return redirect(url_for("login"))

    with app.app_context():
        bonus = Bonus.query.get_or_404(bonus_id)
        bonus.active = not bonus.active
        try:
            db.session.commit()
            flash(
                f"Bonus status for ID {bonus_id} changed to {'active' if bonus.active else 'inactive'}.",
                "success",
            )
        except Exception as e:
            db.session.rollback()
            flash(f"Error changing bonus status: {e}", "error")
    return redirect(url_for("manage_bonuses"))


@app.route("/admin/bonuses/delete/<int:bonus_id>", methods=["POST"])
def delete_bonus(bonus_id):
    if "username" not in session or session.get("role") != "admin":
        flash("Access denied. Only administrators can access.", "error")
        return redirect(url_for("login"))

    with app.app_context():
        bonus_to_delete = Bonus.query.get_or_404(bonus_id)
        try:
            db.session.delete(bonus_to_delete)
            db.session.commit()
            flash(f"Bonus ID {bonus_id} deleted successfully.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error al eliminar bonificación: {e}", "error")
    return redirect(url_for("manage_bonuses"))


@app.route("/admin/weekly_events", methods=["GET", "POST"])
def manage_weekly_events():
    if "username" not in session or session.get("role") != "admin":
        flash("Acceso denegado. Solo los administradores pueden acceder.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form["name"]
        monday = request.form["monday"]
        tuesday = request.form["tuesday"]
        wednesday = request.form["wednesday"]
        thursday = request.form["thursday"]
        friday = request.form["friday"]
        saturday = request.form["saturday"]
        sunday = request.form["sunday"]
        start_date_str = request.form["start_date"]
        end_date_str = request.form["end_date"]
        reminder_time_str = request.form["reminder_time"]

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            datetime.strptime(reminder_time_str, "%H:%M").time()

            if start_date > end_date:
                flash(
                    "Error: La fecha de inicio no puede ser posterior a la fecha de fin.",
                    "error",
                )
                return redirect(url_for("manage_weekly_events"))

            new_event = WeeklyEvent(
                name=name,
                monday=monday,
                tuesday=tuesday,
                wednesday=wednesday,
                thursday=thursday,
                friday=friday,
                saturday=saturday,
                sunday=sunday,
                start_date=start_date,
                end_date=end_date,
                reminder_time=reminder_time_str,
                active=True,
            )
            db.session.add(new_event)
            db.session.commit()
            flash("Evento semanal creado exitosamente.", "success")
            message = (
                f"🎉 **¡Nuevo Evento Semanal Programado!**\n"
                f"**Nombre:** {name}\n"
                f"**Duración:** desde {start_date_str} hasta {end_date_str}"
            )
            thread = threading.Thread(target=send_discord_notification, args=(message,))
            thread.start()

        except ValueError:
            flash("Error: Formato de fecha u hora inválido.", "error")
            db.session.rollback()
        except Exception as e:
            db.session.rollback()
            flash(f"Ocurrió un error al crear el evento: {e}", "error")

        return redirect(url_for("manage_weekly_events"))

    all_weekly_events = WeeklyEvent.query.order_by(WeeklyEvent.start_date.desc()).all()
    return render_template("manage_weekly_events.html", events=all_weekly_events)


@app.route("/admin/weekly_events/toggle/<int:event_id>", methods=["POST"])
def toggle_weekly_event_active(event_id):
    if "username" not in session or session.get("role") != "admin":
        flash("Acceso denegado. Solo los administradores pueden acceder.", "error")
        return redirect(url_for("login"))

    with app.app_context():
        event = WeeklyEvent.query.get_or_404(event_id)
        event.active = not event.active
        try:
            db.session.commit()
            flash(
                f"Estado del evento ID {event_id} cambiado a {'activo' if event.active else 'inactivo'}.",
                "success",
            )
        except Exception as e:
            db.session.rollback()
            flash(f"Error al cambiar el estado del evento: {e}", "error")
    return redirect(url_for("manage_weekly_events"))


@app.route("/admin/weekly_events/delete/<int:event_id>", methods=["POST"])
def delete_weekly_event(event_id):
    if "username" not in session or session.get("role") != "admin":
        flash("Acceso denegado. Solo los administradores pueden acceder.", "error")
        return redirect(url_for("login"))

    with app.app_context():
        event_to_delete = WeeklyEvent.query.get_or_404(event_id)
        try:
            db.session.delete(event_to_delete)
            db.session.commit()
            flash(f"Evento ID {event_id} eliminado exitosamente.", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Error al eliminar el evento: {e}", "error")
    return redirect(url_for("manage_weekly_events"))


def start_reminder_thread():
    print("Iniciando el hilo de recordatorios de eventos semanales...")
    while True:
        with app.app_context():
            check_and_send_weekly_event_reminders()
        time.sleep(60)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    reminder_thread = threading.Thread(target=start_reminder_thread, daemon=True)
    reminder_thread.start()
    port = int(os.getenv("PORT", 5000))
    app.run(
        host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "False") == "True"
    )
