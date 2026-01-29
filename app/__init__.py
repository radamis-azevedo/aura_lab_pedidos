# app/__init__.py
from flask import Flask
from .db import db
from babel.dates import format_date
import os
from .routes.orders import orders_bp
from .routes.finance import finance_bp

def create_app():
    app = Flask(__name__)
    
    # Configuração
    app.secret_key = os.environ.get("SECRET_KEY", "segredo_trocar_depois")
    
    # Inicializa Banco de Dados (Sheets)
    with app.app_context():
        db.init_app(app)
    
    # === REGISTRO DE FILTROS (Jinja2) ===
    from .utils import parse_date, format_currency, parse_float
    
    @app.template_filter("format_brl")
    def format_brl(value):
        try:
            return format_currency(float(value), "BRL", locale="pt_BR")
        except: return value

    @app.template_filter("format_date_br")
    def format_date_br(value):
        try:
            dt = parse_date(value)
            if not dt:
                return value
            return format_date(dt, format="short", locale="pt_BR")
        except Exception:
            return value

    # === REGISTRO DE BLUEPRINTS ===
    from .routes.auth import auth_bp
    from .routes.dashboard import dashboard_bp
    from .routes.orders import orders_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(finance_bp)
    
    return app