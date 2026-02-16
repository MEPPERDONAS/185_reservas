from app import app, db

with app.app_context():
    print("Intentando crear tablas de la base de datos...")
    db.create_all()
    print("Proceso de creación de tablas completado.")
