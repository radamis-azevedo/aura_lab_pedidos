from flask import Flask, render_template, request, redirect, url_for, session, flash
from babel.numbers import format_currency
from babel.dates import format_date
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo
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
pedidos_status_ws = client.open_by_key(SHEET_ID_PEDIDOS).worksheet("PEDIDOS_STATUS")
status_ws = client.open_by_key(SHEET_ID_CADASTROS).worksheet("STATUS")

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
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
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
    rotas_livres = {"login", "static", "healthz", "debug_time","ping"}
    if request.endpoint not in rotas_livres and "usuario" not in session:
        return redirect(url_for("login"))

@app.route("/healthz")
def healthz():
    return "OK", 200
    
@app.route("/ping")
def ping():
    return "pong", 200
    


# =============================
# ROTAS PRINCIPAIS
# =============================
@app.route("/")
def index():
    pedidos = pedidos_ws.get_all_records()
    clientes = clientes_ws.get_all_records()
    hoje = date.today()

    total_receber_qtd = 0
    total_receber_val = 0.0
    prazos = {"atrasados": {"qtd": 0, "val": 0.0},
              "hoje": {"qtd": 0, "val": 0.0},
              "futuros": {"qtd": 0, "val": 0.0}}
    status_map = defaultdict(lambda: {"qtd": 0, "val": 0.0})

    # Dicionário rápido de clientes
    clientes_dict = {str(c.get("NOME_CLI")).strip(): c for c in clientes}

    # Mapa de devedores (formatado)
    clientes_devedores = {}

    for p in pedidos:
        val = parse_float(p.get("VLR_PED"))
        status_original = p.get("STATUS") or "Indefinido"
        status = norm_status(status_original)
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO"))
        cliente_nome = str(p.get("CLIENTE")).strip()

        # Card: A Receber
        if status == "entregue" and not pago:
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

        # Card: Prazos (somente não entregues)
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

        # Card: Status (somente não entregues)
        if status != "entregue":
            status_map[status_original]["qtd"] += 1
            status_map[status_original]["val"] += val

    # Recupera ordem salva do usuário (layout dos cards)
    registros = usuarios_ws.get_all_records()
    ordem_salva = None
    for r in registros:
        if r.get("NOME") == session.get("usuario"):
            ordem_salva = r.get("LAYOUT_CARDS")
            break

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
    hoje = date.today()
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
    try:
        itens, custos = get_itens_pedido(nr_ped)
        app.logger.info(f"[itens] nr_ped={nr_ped} -> itens={len(itens)} custos={len(custos)}")
        return render_template("itens_pedido.html", itens=itens, custos=custos)
    except Exception as e:
        app.logger.exception(f"Erro em /itens/{nr_ped}")
        return f"Erro interno: {e}", 500

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

# =============================
# STATUS: LISTAR / EDITAR / INCLUIR / EXCLUIR
# =============================
@app.route("/status/<nr_ped>")
def status_pedido(nr_ped):
    # Carrega todas as linhas (inclui cabeçalho)
    values = pedidos_status_ws.get_all_values()
    header = values[0] if values else []
    data_rows = values[1:] if len(values) > 1 else []

    # Mapeia nomes de coluna -> índice
    hidx = {name: i for i, name in enumerate(header)}

    def get_val(row, col):
        idx = hidx.get(col)
        return row[idx] if (idx is not None and idx < len(row)) else ""

    historico = []
    for excel_row_num, row in enumerate(data_rows, start=2):  # 2 = pula o cabeçalho
        if str(get_val(row, "NR_PED")).strip() == str(nr_ped):
            historico.append({
                "row_index": excel_row_num,  # linha REAL no Google Sheets
                "STATUS_HIST": get_val(row, "STATUS_HIST"),
                "DT_HR_STATUS": get_val(row, "DT_HR_STATUS"),
                "PRAZO_STATUS": get_val(row, "PRAZO_STATUS"),
                "DT_HR_PRAZO": get_val(row, "DT_HR_PRAZO"),
                "OBS_STATUS": get_val(row, "OBS_STATUS"),
                "USUARIO": get_val(row, "USUARIO"),
                "DATA_HORA": get_val(row, "DATA_HORA"),
            })

    # Opções de status
    status_options = status_ws.col_values(1)

    # Data/hora local para o input datetime-local
    now_str = datetime.now(ZoneInfo("America/Cuiaba")).strftime("%Y-%m-%dT%H:%M")

    return render_template(
        "status.html",
        nr_ped=nr_ped,
        historico=historico,
        status_options=status_options,
        now_str=now_str,
        usuario=session.get("usuario")
    )

@app.route("/status/<nr_ped>", methods=["POST"])
def salvar_status(nr_ped):
    novo_status = request.form.get("status")
    dt_hr_status = request.form.get("dt_hr_status")  # formato YYYY-MM-DDTHH:MM
    prazo_status = request.form.get("prazo")
    obs_status = request.form.get("obs")
    usuario = session.get("usuario")
    row_index = request.form.get("row_index")  # quando edição

    # Converte para datetime
    dt_hr_status_dt = datetime.strptime(dt_hr_status, "%Y-%m-%dT%H:%M")

    # Calcula data/hora do prazo (dias inteiros)
    dias = int(prazo_status or 0)
    dt_hr_prazo = dt_hr_status_dt + timedelta(days=dias)

    agora = datetime.now(ZoneInfo("America/Cuiaba")).strftime("%d/%m/%Y %H:%M")  # sem segundos

    if row_index:
        # Atualiza linha existente: colunas B→H
        row_index = int(row_index)
        pedidos_status_ws.update(f"B{row_index}:H{row_index}", [[
            novo_status,
            dt_hr_status_dt.strftime("%d/%m/%Y %H:%M"),
            prazo_status,
            dt_hr_prazo.strftime("%d/%m/%Y %H:%M"),
            obs_status,
            usuario,
            agora
        ]])
    else:
        # Insere nova linha completa (A→H)
        pedidos_status_ws.append_row([
            nr_ped,
            novo_status,
            dt_hr_status_dt.strftime("%d/%m/%Y %H:%M"),
            prazo_status,
            dt_hr_prazo.strftime("%d/%m/%Y %H:%M"),
            obs_status,
            usuario,
            agora
        ])

    flash("✅ Status atualizado com sucesso!", "success")
    return redirect(url_for("status_pedido", nr_ped=nr_ped))

@app.route("/status/<nr_ped>/delete/<int:row_index>", methods=["POST"])
def excluir_status(nr_ped, row_index):
    try:
        pedidos_status_ws.delete_rows(row_index)
        flash("🗑️ Histórico excluído com sucesso!", "success")
    except Exception as e:
        app.logger.error(f"Erro ao excluir histórico: {e}")
        flash("❌ Erro ao excluir histórico.", "error")
    return redirect(url_for("status_pedido", nr_ped=nr_ped))

# =============================
# DEBUG TIME (opcional)
# =============================
@app.route("/debug_time")
def debug_time():
    now_default = datetime.now()
    now_utc = datetime.now(timezone.utc)
    now_cuiaba = datetime.now(ZoneInfo("America/Cuiaba"))
    return f"""
    <h2>Diagnóstico de Horário do Servidor</h2>
    <p><b>Default (sem fuso):</b> {now_default}</p>
    <p><b>UTC:</b> {now_utc}</p>
    <p><b>Cuiabá:</b> {now_cuiaba}</p>
    """

@app.context_processor
def inject_user():
    return dict(usuario=session.get("usuario"))

# =============================
# MAIN
# =============================
if __name__ == "__main__":
    app.run(debug=True)