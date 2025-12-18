from . import create_app

# Objeto que utilizará gunicorn / Render
app = create_app()

if __name__ == "__main__":
    # Para correr en local: python -m atr_api.wsgi
    app.run(host="0.0.0.0", port=5000)
