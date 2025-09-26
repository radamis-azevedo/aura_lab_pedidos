from flask import Flask, render_template, request, redirect, url_for, session
from babel.numbers import format_currency
from babel.dates import format_date
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from collections import defaultdict
import os

# =============================
# CONFIGURAÇÃO FLASK
# =============================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "segredo_trocar_depois")

# =============================
# CONFIGURAÇÃO GOOGLE SHEETS
# =============================
SHEET_ID_PEDIDOS = "1RbzDCYh7xaVmOxD1JLWDfpiw9HKhtw4r2zKxcmCfFsE"
SHEET_ID_CADASTROS = "1QDP8Uo71gL_T9efOqtmSc5AoBTnYA8DlpgzYbTVIhoY"

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDENTIALS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
credentials = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_PATH, scope)
client = gspread.authorize(credentials)

pedidos_ws = client.open_by_key(SHEET_ID_PEDIDOS).worksheet("PEDIDOS")
itens_ws = client.open_by_key(SHEET_ID_PEDIDOS).worksheet("PEDIDOS_ITENS")
custos_ws = client.open_by_key(SHEET_ID_PEDIDOS).worksheet("PEDIDOS_CUSTOS")
usuarios_ws = client.open_by_key(SHEET_ID_CADASTROS).worksheet("ADM_BOT")
clientes_ws = client.open_by_key(SHEET_ID_CADASTROS).worksheet("CLIENTES")

# =============================
# FUNÇÕES AUXILIARES
# =============================
def parse_float(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value).replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
        return float(cleaned)
    except Exception:
        return 0.0

def parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None

def get_itens_pedido(nr_ped):
    itens = [i for i in itens_ws.get_all_records() if str(i.get("NR_PED")) == str(nr_ped)]
    custos = [c for c in custos_ws.get_all_records() if str(c.get("NR_PED")) == str(nr_ped)]
    return itens, custos

def validar_usuario(fone, senha):
    registros = usuarios_ws.get_all_records()
    for r in registros:
        if str(r.get("FONE_ADM")).strip() == str(fone).strip() and str(r.get("SENHA")).strip() == str(senha).strip():
            return r
    return None

# =============================
# FILTROS CUSTOMIZADOS
# =============================
@app.template_filter()
def format_brl(value):
    try:
        return format_currency(float(value), "BRL", locale="pt_BR")
    except Exception:
        return value

@app.template_filter()
def format_date_br(value):
    try:
        dt = parse_date(value)
        if not dt:
            return value
        return format_date(dt, format="short", locale="pt_BR")
    except Exception:
        return value

def norm_status(s):
    return str(s or "").strip().lower()

def is_paid(v):
    s = str(v or "").strip().lower()
    return s in {"sim", "s", "yes", "y", "true", "1", "pago"}

# =============================
# LOGIN
# =============================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        fone = request.form.get("fone")
        senha = request.form.get("senha")
        user = validar_usuario(fone, senha)
        if user:
            session["usuario"] = user.get("NOME")
            return redirect(url_for("index"))
        else:
            return render_template("login.html", erro="Usuário ou senha inválidos")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.before_request
def require_login():
    rotas_livres = {"login", "static", "healthz"}
    if request.endpoint not in rotas_livres and "usuario" not in session:
        return redirect(url_for("login"))



@app.route("/healthz")
def healthz():
    return "OK", 200

# =============================
# ROTAS PRINCIPAIS
# =============================
@app.route("/")
def index():
    pedidos = pedidos_ws.get_all_records()
    clientes = clientes_ws.get_all_records()
    hoje = datetime.date.today()

    total_receber_qtd = 0
    total_receber_val = 0.0
    clientes_devedores = {}
    prazos = {"atrasados": {"qtd": 0, "val": 0.0},
              "hoje": {"qtd": 0, "val": 0.0},
              "futuros": {"qtd": 0, "val": 0.0}}
    status_map = defaultdict(lambda: {"qtd": 0, "val": 0.0})

    # Dicionário rápido de clientes
    clientes_dict = {str(c.get("NOME_CLI")).strip(): c for c in clientes}

    for p in pedidos:
        val = parse_float(p.get("VLR_PED"))
        status_original = p.get("STATUS") or "Indefinido"
        status = norm_status(status_original)
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO"))
        cliente_nome = str(p.get("CLIENTE")).strip()

        if status == "entregue" and not pago:
            total_receber_qtd += 1
            total_receber_val += val

            if cliente_nome in clientes_dict:
                dados_cli = clientes_dict[cliente_nome]
                primeiro_nome = cliente_nome.split()[0]
                sexo = str(dados_cli.get("SEXO", "")).strip().upper()
                prefixo = "Dr." if sexo == "M" else "Dra."
                cro = dados_cli.get("CRO", "—")

                if cliente_nome not in clientes_devedores:
                    clientes_devedores[cliente_nome] = {
                        "prefixo": prefixo,
                        "nome": primeiro_nome,
                        "cro": cro,
                        "total": 0.0
                    }
                clientes_devedores[cliente_nome]["total"] += val

        if prazo and status != "entregue":
            if prazo < hoje:
                prazos["atrasados"]["qtd"] += 1
                prazos["atrasados"]["val"] += val
            elif prazo == hoje:
                prazos["hoje"]["qtd"] += 1
                prazos["hoje"]["val"] += val
            else:
                prazos["futuros"]["qtd"] += 1
                prazos["futuros"]["val"] += val

        if status != "entregue":
            status_map[status_original]["qtd"] += 1
            status_map[status_original]["val"] += val

    # Recupera ordem salva do usuário
    registros = usuarios_ws.get_all_records()
    ordem_salva = None
    for r in registros:
        if r.get("NOME") == session.get("usuario"):
            ordem_salva = r.get("LAYOUT_CARDS")
            break

    # 🔹 Monta lista de clientes devedores
    clientes_sheet = client.open_by_key(SHEET_ID_CADASTROS).worksheet("CLIENTES")
    clientes_data = {c["NOME_CLI"]: c for c in clientes_sheet.get_all_records()}

    clientes_devedores = {}
    for p in pedidos:
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))
        if status == "entregue" and not pago:
            nome_cli = p.get("CLIENTE", "—")
            cli_info = clientes_data.get(nome_cli, {})
            sexo = str(cli_info.get("SEXO", "")).strip().lower()
            cro = cli_info.get("CRO", "")

            # Monta título formatado
            prefixo = "Dra." if sexo == "f" else "Dr."
            primeiro_nome = nome_cli.split()[0] if nome_cli else "Cliente"
            titulo = f"{prefixo} {primeiro_nome} - CRO {cro}"

            valor = parse_float(p.get("VLR_PED"))
            if titulo not in clientes_devedores:
                clientes_devedores[titulo] = {"titulo": titulo, "valor": 0.0}
            clientes_devedores[titulo]["valor"] += valor


    return render_template(
        "index.html",
        total_receber_qtd=total_receber_qtd,
        total_receber_val=total_receber_val,
        clientes_devedores=clientes_devedores,
        prazos=prazos,
        status_map=status_map,
        usuario=session.get("usuario"),
        ordem_salva=ordem_salva.split(",") if ordem_salva else []
    )

# =============================
# DEMAIS ROTAS (detalhes, areceber, itens)
# =============================
@app.route("/detalhes/<tipo>/<filtro>")
def detalhes(tipo, filtro):
    pedidos = pedidos_ws.get_all_records()
    itens = itens_ws.get_all_records()
    hoje = datetime.date.today()
    pedidos_filtrados = []

    titulos_map = {
        ("porcliente", "naoentregues"): "Pedidos por Cliente (não entregues)",
        ("porcliente", "todos"): "Pedidos por Cliente (todos)",
        ("receber", "todos"): "Pedidos entregues pendentes de recebimento",
        ("prazo", "atrasados"): "Pedidos em atraso",
        ("prazo", "hoje"): "Pedidos para hoje",
        ("prazo", "futuro"): "Pedidos futuros",
    }
    titulo_custom = titulos_map.get((tipo, filtro), filtro.title())

    for p in pedidos:
        val = parse_float(p.get("VLR_PED"))
        p["VLR_NUM"] = val
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO"))

        if tipo == "prazo":
            if filtro == "atrasados" and prazo and prazo < hoje and status != "entregue":
                pedidos_filtrados.append(p)
            elif filtro == "hoje" and prazo and prazo == hoje and status != "entregue":
                pedidos_filtrados.append(p)
            elif filtro in {"futuro", "futuros"} and prazo and prazo > hoje and status != "entregue":
                pedidos_filtrados.append(p)

        elif tipo == "status":
            if status == norm_status(filtro):
                pedidos_filtrados.append(p)

        elif tipo == "receber":
            if status == "entregue" and not pago:
                pedidos_filtrados.append(p)

        elif tipo == "porcliente":
            if filtro == "todos":
                pedidos_filtrados.append(p)
            elif filtro == "naoentregues" and status != "entregue":
                pedidos_filtrados.append(p)

    for ped in pedidos_filtrados:
        ped_num = str(ped.get("NR_PED"))
        ped["ITENS"] = [i for i in itens if str(i.get("NR_PED")) == ped_num]

    agrupado = defaultdict(list)
    for ped in pedidos_filtrados:
        agrupado[ped.get("CLIENTE", "—")].append(ped)

    return render_template(
        "detalhes.html",
        filtro=titulo_custom,
        agrupado=agrupado,
        tipo=tipo,
        usuario=session.get("usuario")
    )

@app.route("/areceber")
def areceber():
    pedidos = pedidos_ws.get_all_records()
    pedidos_filtrados = []
    for p in pedidos:
        val = parse_float(p.get("VLR_PED"))
        p["VLR_NUM"] = val
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))
        if status == "entregue" and not pago:
            pedidos_filtrados.append(p)

    agrupado = defaultdict(list)
    for ped in pedidos_filtrados:
        agrupado[ped.get("CLIENTE", "—")].append(ped)

    return render_template(
        "detalhes.html",
        filtro="Pedidos entregues pendentes de recebimento",
        agrupado=agrupado,
        tipo="receber",
        usuario=session.get("usuario")
    )

@app.route("/itens/<nr_ped>")
def itens_pedido(nr_ped):
    itens, custos = get_itens_pedido(nr_ped)
    return render_template("itens_pedido.html", itens=itens, custos=custos)

@app.route("/salvar_layout", methods=["POST"])
def salvar_layout():
    if "usuario" not in session:
        return {"ok": False, "erro": "Não autenticado"}, 403

    data = request.get_json()
    ordem = data.get("ordem", [])

    registros = usuarios_ws.get_all_records()
    for i, r in enumerate(registros, start=2):
        if r.get("NOME") == session["usuario"]:
            usuarios_ws.update_cell(i, 4, ",".join(ordem))  # col 4 = LAYOUT_CARDS
            break

    return {"ok": True}

@app.context_processor
def inject_user():
    return dict(usuario=session.get("usuario"))

# =============================
# MAIN
# =============================
if __name__ == "__main__":
    app.run(debug=True)
