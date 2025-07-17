# init_db.py
from app import app, db

# Aseguramos que se ejecute dentro del contexto de la aplicación Flask
# Esto es necesario para que SQLAlchemy sepa a qué aplicación y base de datos se refiere
with app.app_context():
    print("Intentando crear tablas de la base de datos...")
    db.create_all() # Esto creará las tablas si no existen (es idempotente)
    print("Proceso de creación de tablas completado.")