from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.db import db

# === ESSA LINHA É ONDE O ERRO ESTÁ RECLAMANDO ===
auth_bp = Blueprint('auth', __name__)

def validar_usuario(fone, senha):
    usuarios_ws = db.sheets['usuarios']
    registros = usuarios_ws.get_all_records()
    for r in registros:
        if str(r.get("FONE_ADM")).strip() == str(fone).strip() and str(r.get("SENHA")).strip() == str(senha).strip():
            return r
    return None

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        fone = request.form.get("fone")
        senha = request.form.get("senha")
        user = validar_usuario(fone, senha)
        if user:
            session["usuario"] = user.get("NOME")
            return redirect(url_for("dashboard.index"))
        else:
            return render_template("login.html", erro="Usuário ou senha inválidos")
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))