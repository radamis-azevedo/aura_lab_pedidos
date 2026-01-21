from flask import Blueprint, render_template, session, redirect, url_for
from collections import defaultdict
from datetime import date
from app.db import db
from app.utils import parse_float, parse_date, slugify_status

# Cria o Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

def is_paid(v):
    s = str(v or "").strip().lower()
    return s in {"sim", "s", "yes", "y", "true", "1", "pago"}

@dashboard_bp.route("/")
def index():
    if "usuario" not in session:
        return redirect(url_for("auth.login"))

    hoje = date.today()

    # Carrega dados via db
    pedidos = db.sheets['pedidos'].get_all_records()
    clientes = db.sheets['clientes'].get_all_records()
    cad_status = db.sheets['cad_status'].get_all_records()

    # Busca layout do usuário
    usuarios_ws = db.sheets['usuarios']
    ordem_salva = None
    for r in usuarios_ws.get_all_records():
        if r.get("NOME") == session.get("usuario"):
            layout = r.get("LAYOUT_CARDS", "")
            ordem_salva = layout.split(",") if layout else []
            break

    # Índices e Mapas
    clientes_dict = {str(c.get("NOME_CLI")).strip(): c for c in clientes}
    prazo_map = {str(s.get("STATUS")).strip(): str(s.get("PRAZO_OBRIG", "N")).strip().upper() for s in cad_status}
    ord_map = {str(s.get("STATUS")).strip(): int(str(s.get("ORD_CARD", "999")) or "999") for s in cad_status}

    # Acumuladores
    total_receber_qtd = 0
    total_receber_val = 0.0
    clientes_devedores = {}
    prazos = {"atrasados": {"qtd": 0, "val": 0.0}, "hoje": {"qtd": 0, "val": 0.0}, "futuros": {"qtd": 0, "val": 0.0}}
    resumo_status = defaultdict(lambda: {"qtd": 0, "val": 0.0})

    # Processamento
    for p in pedidos:
        cliente_nome = str(p.get("CLIENTE") or "").strip()
        status = str(p.get("STATUS") or "Indefinido").strip()
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO"))
        val = parse_float(p.get("VLR_PED"))

        # A Receber
        if status.lower() == "entregue" and not pago:
            total_receber_qtd += 1
            total_receber_val += val
            dados_cli = clientes_dict.get(cliente_nome, {})
            sexo = str(dados_cli.get("SEXO", "")).strip().lower()
            cro = dados_cli.get("CRO", "")
            prefixo = "Dra." if sexo == "f" else "Dr."
            primeiro_nome = cliente_nome.split()[0] if cliente_nome else "Cliente"
            titulo = f"{prefixo} {primeiro_nome} - CRO {cro}"
            
            if titulo not in clientes_devedores:
                clientes_devedores[titulo] = {"titulo": titulo, "valor": 0.0}
            clientes_devedores[titulo]["valor"] += val

        # Prazos
        if prazo and status.lower() != "entregue":
            if prazo < hoje:
                prazos["atrasados"]["qtd"] += 1
                prazos["atrasados"]["val"] += val
            elif prazo == hoje:
                prazos["hoje"]["qtd"] += 1
                prazos["hoje"]["val"] += val
            else:
                prazos["futuros"]["qtd"] += 1
                prazos["futuros"]["val"] += val

        resumo_status[status]["qtd"] += 1
        resumo_status[status]["val"] += val

    # Monta Cards
    cards_por_status = {"Com Prazo": [], "Aguardando Cliente/Dentista": []}
    for st, dados in resumo_status.items():
        if dados["qtd"] == 0: continue
        grupo = "Com Prazo" if prazo_map.get(st, "N") == "S" else "Aguardando Cliente/Dentista"
        cards_por_status[grupo].append({
            "status": st, 
            "qtd": dados["qtd"], 
            "val": dados["val"], 
            "ord": ord_map.get(st, 999), 
            "slug": slugify_status(st)
        })

    for g in cards_por_status:
        cards_por_status[g].sort(key=lambda x: (x["ord"], x["status"].lower()))

    return render_template("index.html", 
        usuario=session.get("usuario"),
        total_receber_qtd=total_receber_qtd,
        total_receber_val=total_receber_val,
        clientes_devedores=clientes_devedores,
        prazos=prazos,
        cards_por_status=cards_por_status,
        ordem_salva=ordem_salva or []
    )