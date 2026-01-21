from flask import Flask, render_template, request, redirect, url_for, session, flash, session, jsonify
from babel.numbers import format_currency
from babel.dates import format_date
from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from collections import defaultdict
from gspread.utils import rowcol_to_a1
import pytz
import os
import json
import unicodedata, re


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
produtos_ws = client.open_by_key(SHEET_ID_CADASTROS).worksheet("PRODUTOS")
status_ws = client.open_by_key(SHEET_ID_PEDIDOS).worksheet("PEDIDOS_STATUS")
cad_status_ws = client.open_by_key(SHEET_ID_CADASTROS).worksheet("STATUS")

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

def safe_json_list(raw_value, label):
    try:
        parsed = json.loads(raw_value or "[]")
    except json.JSONDecodeError:
        app.logger.warning(f"[JSON] Falha ao carregar {label}. Valor recebido: {raw_value!r}")
        return []
    if isinstance(parsed, list):
        return parsed
    app.logger.warning(f"[JSON] Conteúdo inválido para {label}. Esperado lista, recebido: {type(parsed).__name__}")
    return []

def agrupar_consecutivas(seq):
    seq = sorted(seq)
    if not seq:
        return []
    grupos, grupo = [], [seq[0]]
    for i in seq[1:]:
        if i == grupo[-1] + 1:
            grupo.append(i)
        else:
            grupos.append(grupo)
            grupo = [i]
    grupos.append(grupo)
    return grupos

def get_row_indices_by_col(values, col_index, target_value):
    indices = []
    for i, row in enumerate(values[1:], start=2):
        val = row[col_index - 1] if col_index - 1 < len(row) else ""
        if str(val).strip() == str(target_value):
            indices.append(i)
    return indices

def append_rows_safe(ws, rows):
    if rows:
        ws.append_rows(rows, value_input_option="USER_ENTERED")

def batch_update_rows(ws, row_indices, rows):
    if not row_indices or not rows:
        return
    col_count = max(len(r) for r in rows)
    data = []
    for row_index, row_vals in zip(row_indices, rows):
        padded = row_vals + [""] * (col_count - len(row_vals))
        start = rowcol_to_a1(row_index, 1)
        end = rowcol_to_a1(row_index, col_count)
        data.append({"range": f"{start}:{end}", "values": [padded]})
    ws.batch_update(data, value_input_option="USER_ENTERED")

def replace_detail_rows(ws, col_index, key_value, new_rows):
    values = ws.get_all_values()
    row_indices = get_row_indices_by_col(values, col_index, key_value)

    if not new_rows:
        for grupo in agrupar_consecutivas(row_indices):
            ws.delete_rows(grupo[0], grupo[-1])
        return

    if len(row_indices) == len(new_rows):
        batch_update_rows(ws, row_indices, new_rows)
        return

    append_rows_safe(ws, new_rows)
    for grupo in agrupar_consecutivas(row_indices):
        ws.delete_rows(grupo[0], grupo[-1])

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

def parse_br_datetime(s):
    """Aceita 'dd/mm/aaaa HH:MM' e também 'dd/mm/aaaa HH:MM:SS'."""
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None

def to_input_datetime(value: str) -> str:
    """
    Converte datas vindas do Sheets para o formato aceitável pelo <input type="datetime-local"> (YYYY-MM-DDTHH:MM).
    Aceita:
      - 'dd/mm/yyyy HH:MM' ou 'dd/mm/yyyy HH:MM:SS'
      - 'yyyy-mm-ddTHH:MM' (já pronto)
      - 'yyyy-mm-dd HH:MM' (com espaço)
      - 'dd/mm/yyyy' (sem hora -> assume 00:00)
    Retorna '' se não der para converter.
    """
    s = (value or "").strip()
    if not s:
        return ""
    # Já está em ISO?
    if "-" in s and ("T" in s or " " in s):
        return s.replace(" ", "T")[:16]

    # Tenta BR com hora
    dt = parse_br_datetime(s)
    if dt:
        return dt.strftime("%Y-%m-%dT%H:%M")

    # Tenta só data BR
    try:
        from datetime import datetime
        dt2 = datetime.strptime(s, "%d/%m/%Y")
        return dt2.strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return ""

def to_float_safe(v):
    """
    Converte valores vindos da planilha (ex: 'R$ 1.234,56') em float.
    Se vier vazio, 'None', 'undefined', etc., retorna 0.0.
    """
    try:
        if v is None:
            return 0.0
        s = str(v).strip()
        # remove R$, espaços e separadores de milhar
        s = s.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
        return float(s) if s else 0.0
    except Exception:
        return 0.0


def load_historico_with_row(nr_ped):
    """Carrega o histórico do pedido com row_index REAL da planilha e datas parseadas."""
    values = status_ws.get_all_values()  # inclui cabeçalho
    if not values:
        return [], {}

    header = values[0]
    data_rows = values[1:]
    hidx = {name: i for i, name in enumerate(header)}

    def val(row, col):
        i = hidx.get(col)
        return row[i] if (i is not None and i < len(row)) else ""

    historico = []
    for excel_row_num, row in enumerate(data_rows, start=2):
        if str(val(row, "NR_PED")).strip() == str(nr_ped):
            dt_ini_txt = val(row, "DT_HR_STATUS")
            historico.append({
                "row_index": excel_row_num,
                "STATUS_HIST": val(row, "STATUS_HIST"),
                "DT_HR_STATUS": dt_ini_txt,
                "DT_HR_STATUS_DT": parse_br_datetime(dt_ini_txt),
                "PRAZO_STATUS": val(row, "PRAZO_STATUS"),
                "DT_HR_PRAZO": val(row, "DT_HR_PRAZO"),
                "OBS_STATUS": val(row, "OBS_STATUS"),
                "USUARIO": val(row, "USUARIO"),
                "DATA_HORA": val(row, "DATA_HORA"),
            })
    # Também devolve o dicionário de colunas (útil para outras operações)
    return historico, hidx

def get_status_requirements():
    """
    Lê a aba CADASTROS->STATUS (col A = STATUS, col B = PRAZO_OBRIG [S/N]).
    Retorna dict: { "Nome do Status": True/False }
    """
    vals = status_ws.get_all_values()  # inclui cabeçalho
    req = {}
    if not vals:
        return req
    # Supõe: linha 1 = cabeçalho (STATUS | PRAZO_OBRIG)
    for i, row in enumerate(vals[1:], start=2):
        nome = (row[0] if len(row) > 0 else "").strip()
        obr = (row[1] if len(row) > 1 else "").strip().upper()
        if nome:
            req[nome] = (obr == "S")
    return req

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
# ROTA PRINCIPAL: DASHBOARD /INDEX
# =============================
import unicodedata, re
from collections import defaultdict
from datetime import date

def slugify_status(s: str) -> str:
    s = str(s or "").strip().lower()
    # remove acentos
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # troca espaços e barras por hífen e limpa caracteres estranhos
    s = re.sub(r"[\s/]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    return s

@app.route("/")
def index():
    hoje = date.today()

    # 1) Carregamento único das abas
    pedidos = pedidos_ws.get_all_records()
    clientes = clientes_ws.get_all_records()
    cad_status = cad_status_ws.get_all_records()

    # 2) Índices auxiliares
    clientes_dict = {str(c.get("NOME_CLI")).strip(): c for c in clientes}
    prazo_map = {str(s.get("STATUS")).strip(): str(s.get("PRAZO_OBRIG", "N")).strip().upper()
                 for s in cad_status}
    ord_map = {str(s.get("STATUS")).strip(): int(str(s.get("ORD_CARD", "999")) or "999")
               for s in cad_status}

    # 3) Acumuladores dos cards
    total_receber_qtd = 0
    total_receber_val = 0.0
    clientes_devedores = {}
    prazos = {
        "atrasados": {"qtd": 0, "val": 0.0},
        "hoje": {"qtd": 0, "val": 0.0},
        "futuros": {"qtd": 0, "val": 0.0},
    }
    resumo_status = defaultdict(lambda: {"qtd": 0, "val": 0.0})

    # 4) Loop dos pedidos
    for p in pedidos:
        cliente_nome = str(p.get("CLIENTE") or "").strip()
        status = str(p.get("STATUS") or "Indefinido").strip()
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO"))
        val = parse_float(p.get("VLR_PED"))

        # 💰 A receber (Entregue e não pago)
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

        # ⏳ Prazos (somente não entregues)
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

        # 📊 Por Status (resumo apenas dos status que existem nos pedidos)
        resumo_status[status]["qtd"] += 1
        resumo_status[status]["val"] += val

    # 5) Monta grupos “Com Prazo” e “Aguardando...”, já com ORD_CARD e SLUG
    cards_por_status = {
        "Com Prazo": [],
        "Aguardando Cliente/Dentista": []
    }

    for st, dados in resumo_status.items():
        if dados["qtd"] == 0:
            continue
        grupo = "Com Prazo" if prazo_map.get(st, "N") == "S" else "Aguardando Cliente/Dentista"
        cards_por_status[grupo].append({
            "status": st,
            "qtd": dados["qtd"],
            "val": dados["val"],
            "ord": ord_map.get(st, 999),
            "slug": slugify_status(st),
        })

    # Ordena por ORD_CARD (ord) e depois por nome (tie-break)
    for g in cards_por_status:
        cards_por_status[g].sort(key=lambda x: (x["ord"], x["status"].lower()))

    # 6) Ordem de cards salva pelo usuário
    ordem_salva = None
    for r in usuarios_ws.get_all_records():
        if r.get("NOME") == session.get("usuario"):
            ordem_salva = r.get("LAYOUT_CARDS")
            break

    return render_template(
        "index.html",
        usuario=session.get("usuario"),
        total_receber_qtd=total_receber_qtd,
        total_receber_val=total_receber_val,
        clientes_devedores=clientes_devedores,
        prazos=prazos,
        cards_por_status=cards_por_status,
        ordem_salva=ordem_salva.split(",") if ordem_salva else []
    )

    
# Ajuste o fuso horário para Cuiabá
tz = pytz.timezone("America/Cuiaba")

# =====================================================
# ROTA: NOVO PEDIDO (corrigida e padronizada)
# =====================================================

@app.route("/novo_pedido", methods=["GET", "POST"])
def novo_pedido():
    try:
        if request.method == "POST":
            cliente = request.form.get("cliente", "").strip()
            paciente = request.form.get("paciente", "").strip()
            obs_ped = request.form.get("obs_ped", "").strip()
            itens = safe_json_list(request.form.get("itens_json", "[]"), "itens")
            custos = safe_json_list(request.form.get("custos_json", "[]"), "custos")

            # ==============================
            # 🆕 GERA NOVO NÚMERO DE PEDIDO
            # ==============================
            pedidos_data = pedidos_ws.get_all_records()
            if pedidos_data:
                ultimo_ped = max([int(p["NR_PED"]) for p in pedidos_data if str(p.get("NR_PED")).isdigit()] or [0])
            else:
                ultimo_ped = 0
            novo_nr_ped = ultimo_ped + 1

            # ==============================
            # 🗓️ USUÁRIO E DATA/HORA ATUAL
            # ==============================
            usuario = session.get("usuario")
            dt_atual = datetime.now().strftime("%d/%m/%Y %H:%M")

            # ==============================
            # 🧾 INSERE NA ABA PEDIDOS
            # ==============================
            pedidos_ws.append_row([
                "",  # STATUS (calculado)
                novo_nr_ped, cliente, paciente,
                "", "", "", "",  # DT_PED, DT_PRAZO, DT_ENTREG, VLR_PED                
                "", "", "", "",  # PAGO, DT_RECEB, CUST_TERC, VLR_FINAL
                obs_ped
            ], value_input_option="USER_ENTERED")

            # ==============================
            # 📦 INSERE ITENS
            # ==============================
            itens_rows = [
                [
                    novo_nr_ped,
                    item.get("produto", ""),
                    item.get("qtde", ""),
                    item.get("cor", ""),
                    "",                       # VLR_CAT (calculado)
                    item.get("valor", ""),    # VLR_COB
                    "",                       # TOTAL_PROD (calculado)
                    item.get("obs", "")
                ]
                for item in itens
            ]
            append_rows_safe(itens_ws, itens_rows)

            # ==============================
            # 💰 INSERE CUSTOS
            # ==============================
            custos_rows = [
                [
                    novo_nr_ped,
                    custo.get("desc", ""),
                    custo.get("qtd", ""),
                    custo.get("valor", ""),
                    "",                       # VLR_TOT_CUSTO (calculado)
                    custo.get("obs", "")
                ]
                for custo in custos
            ]
            append_rows_safe(custos_ws, custos_rows)

            # ==============================
            # 📋 REGISTRA STATUS INICIAL
            # ==============================
            dt_pedido = request.form.get("dt_pedido", "").strip()
            try:
                status_ws.append_row([
                    novo_nr_ped,
                    "Pedido Registrado",
                    dt_pedido,
                    "1",
                    "",
                    "",
                    usuario,
                    dt_atual
                ], value_input_option="USER_ENTERED")
                app.logger.info(f"[NOVO_PEDIDO] Status inicial 'Pedido Registrado' criado para {novo_nr_ped}")
            except Exception as e:
                app.logger.warning(f"[NOVO_PEDIDO] Falha ao registrar status inicial: {e}")

            # ✅ RETORNO PARA O FRONTEND EXIBIR POPUP
            flash(f"✅ Pedido #{novo_nr_ped} registrado com sucesso!", "sucesso")
            return jsonify({"sucesso": True, "nr_ped": novo_nr_ped})

        # =====================================================
        # 🟢 MODO GET → CARREGA FORMULÁRIO
        # =====================================================
        clientes = sorted([c.get("NOME_CLI") for c in clientes_ws.get_all_records() if c.get("NOME_CLI")])
        produtos = sorted(
            [{"PRODUTO": p.get("PRODUTO", ""), "VLR_CAT": p.get("VLR_CAT", "")}
             for p in produtos_ws.get_all_records() if p.get("PRODUTO")],
            key=lambda x: x["PRODUTO"]
        )

        context = {
            "modo": "novo",
            "nr_ped": "",
            "usuario": session.get("usuario"),
            "clientes": clientes,
            "produtos": produtos,
            "cliente_atual": "",
            "paciente_atual": "",
            "obs_atual": "",
            "itens": [],
            "custos": [],
            "dt_pedido": datetime.now().strftime("%Y-%m-%dT%H:%M")
        }

        return render_template("pedido_form.html", **context)

    except Exception as e:
        import traceback
        app.logger.error(f"Erro em /novo_pedido: {e}\n{traceback.format_exc()}")
        flash(f"❌ Erro ao carregar o formulário: {e}", "erro")
        return redirect(url_for("index"))

# =============================
# DEMAIS ROTAS (detalhes, areceber, itens)
# =============================

def slugify_status(s: str) -> str:
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[\s/]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    return s

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

        # ============== FILTROS EXISTENTES ==================
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

        # ============== NOVO FILTRO: POR STATUS (slug) ==================
        elif tipo == "porstatus":
            # compara slug do status do pedido com slug vindo da URL
            if slugify_status(p.get("STATUS", "")) == filtro.lower():
                pedidos_filtrados.append(p)

    # adiciona itens correspondentes
    for ped in pedidos_filtrados:
        ped_num = str(ped.get("NR_PED"))
        ped["ITENS"] = [i for i in itens if str(i.get("NR_PED")) == ped_num]

    # agrupa por cliente (reuso do mesmo HTML)
    agrupado = defaultdict(list)
    for ped in pedidos_filtrados:
        agrupado[ped.get("CLIENTE", "—")].append(ped)

    # título especial para o tipo 'porstatus'
    if tipo == "porstatus" and pedidos_filtrados:
        titulo_custom = f"Pedidos com status: {pedidos_filtrados[0].get('STATUS')}"

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
    usuario = session.get("usuario")

    # 🧾 Carrega todas as linhas da planilha de STATUS
    values = status_ws.get_all_values()
    header = values[0] if values else []
    data_rows = values[1:] if len(values) > 1 else []

    # 🔹 Mapeia nomes de coluna -> índice
    hidx = {name: i for i, name in enumerate(header)}

    def get_val(row, col):
        idx = hidx.get(col)
        return row[idx] if (idx is not None and idx < len(row)) else ""

    # 🔹 Monta lista do histórico do pedido
    historico = []
    for excel_row_num, row in enumerate(data_rows, start=2):  # 2 = pula cabeçalho
        if str(get_val(row, "NR_PED")).strip() == str(nr_ped):
            historico.append({
                "row_index": excel_row_num,
                "STATUS_HIST": get_val(row, "STATUS_HIST"),
                "DT_HR_STATUS": get_val(row, "DT_HR_STATUS"),
                "PRAZO_STATUS": get_val(row, "PRAZO_STATUS"),
                "DT_HR_PRAZO": get_val(row, "DT_HR_PRAZO"),
                "OBS_STATUS": get_val(row, "OBS_STATUS"),
                "USUARIO": get_val(row, "USUARIO"),
                "DATA_HORA": get_val(row, "DATA_HORA"),
            })

    # 🔹 Carrega cadastro de status e suas obrigatoriedades
    cadastros = cad_status_ws.get_all_records()
    status_options = [r["STATUS"] for r in cadastros if r.get("STATUS")]
    status_prazo_obrig = {r["STATUS"]: r.get("PRAZO_OBRIG", "").strip() for r in cadastros}

    # 🔹 Carrega os itens do pedido
    itens = [
        i for i in itens_ws.get_all_records()
        if str(i.get("NR_PED")).strip() == str(nr_ped)
    ]

    # 🔹 Data/hora local para campos datetime-local
    now_str = datetime.now(ZoneInfo("America/Cuiaba")).strftime("%Y-%m-%dT%H:%M")

    return render_template(
        "status.html",
        nr_ped=nr_ped,
        usuario=usuario,
        historico=historico,
        status_options=status_options,
        status_prazo_obrig=status_prazo_obrig,
        now_str=now_str,
        itens=itens
    )

@app.route("/status/<nr_ped>", methods=["POST"])
def salvar_status(nr_ped):
    novo_status = request.form.get("status")
    dt_hr_status = request.form.get("dt_hr_status")  # YYYY-MM-DDTHH:MM
    prazo_status = request.form.get("prazo")
    obs_status = request.form.get("obs")
    usuario = session.get("usuario")
    row_index = request.form.get("row_index")

    # Converte Data/Hora recebida
    try:
        dt_hr_status_dt = datetime.strptime(dt_hr_status, "%Y-%m-%dT%H:%M")
    except Exception:
        flash("⚠️ Data/Hora inválida.", "error")
        return redirect(url_for("status_pedido", nr_ped=nr_ped))

    # Strings formatadas para salvar no Sheets
    dt_hr_status_str = dt_hr_status_dt.strftime("%d/%m/%Y %H:%M")
    dias = int(prazo_status or 0)
    dt_hr_prazo_str = (dt_hr_status_dt + timedelta(days=dias)).strftime("%d/%m/%Y %H:%M")
    agora_str = datetime.now(ZoneInfo("America/Cuiaba")).strftime("%d/%m/%Y %H:%M")

    # === Validações (mantém o que você já tinha acima) ===
    values = status_ws.get_all_values()
    header = values[0] if values else []
    data_rows = values[1:] if len(values) > 1 else []
    hidx = {name: i for i, name in enumerate(header)}

    def get_val(row, col):
        idx = hidx.get(col)
        return row[idx] if (idx is not None and idx < len(row)) else ""

    historico = []
    for excel_row_num, row in enumerate(data_rows, start=2):
        if str(get_val(row, "NR_PED")).strip() == str(nr_ped):
            dt_val = get_val(row, "DT_HR_STATUS")
            try:
                dt_val = datetime.strptime(dt_val, "%d/%m/%Y %H:%M")
            except Exception:
                dt_val = None
            historico.append({
                "row_index": excel_row_num,
                "STATUS_HIST": get_val(row, "STATUS_HIST"),
                "DT_HR_STATUS": dt_val
            })

    historico = sorted(historico, key=lambda x: x["DT_HR_STATUS"] or datetime.min)

    # 1) Pedido Registrado não pode ser duplicado
    if novo_status.strip().lower() == "pedido registrado" and not row_index:
        flash("⚠️ O status 'Pedido Registrado' já existe e não pode ser duplicado.", "error")
        return redirect(url_for("status_pedido", nr_ped=nr_ped))

    # 2) Ordem cronológica
    if row_index:
        row_index = int(row_index)
        atual = next((h for h in historico if h["row_index"] == row_index), None)
        idx = historico.index(atual) if atual else -1

        if idx > 0 and dt_hr_status_dt < historico[idx-1]["DT_HR_STATUS"]:
            flash(f"⚠️ Data/Hora Início deve ser >= do status anterior ({historico[idx-1]['STATUS_HIST']}).", "error")
            return redirect(url_for("status_pedido", nr_ped=nr_ped))

        if idx < len(historico)-1 and dt_hr_status_dt > historico[idx+1]["DT_HR_STATUS"]:
            flash(f"⚠️ Data/Hora Início deve ser <= do status seguinte ({historico[idx+1]['STATUS_HIST']}).", "error")
            return redirect(url_for("status_pedido", nr_ped=nr_ped))
    else:
        if historico and dt_hr_status_dt < historico[-1]["DT_HR_STATUS"]:
            flash(f"⚠️ Data/Hora Início deve ser >= do último status ({historico[-1]['STATUS_HIST']}).", "error")
            return redirect(url_for("status_pedido", nr_ped=nr_ped))

    # 3) Prazo obrigatório
    obrigs = cad_status_ws.get_all_records()
    obrig_map = {str(r["STATUS"]).strip(): str(r.get("PRAZO_OBRIG", "N")).upper() for r in obrigs}
    if obrig_map.get(novo_status, "N") == "S" and not prazo_status:
        flash(f"⚠️ O status '{novo_status}' exige preenchimento do prazo (dias).", "error")
        return redirect(url_for("status_pedido", nr_ped=nr_ped))

    # === Persistência ===
    if row_index:
        status_ws.update(
            f"B{row_index}:H{row_index}",
            [[
                novo_status,
                dt_hr_status_str,
                prazo_status,
                "", #DT_HR_PRAZO
                obs_status,
                usuario,
                agora_str
            ]],
            value_input_option="USER_ENTERED"
        )
        flash("✏️ Status atualizado com sucesso!", "success")
    else:
        status_ws.append_row([
            nr_ped,
            novo_status,
            dt_hr_status_str,
            prazo_status,
            "", #DT_HR_PRAZO
            obs_status,
            usuario,
            agora_str
        ], value_input_option="USER_ENTERED")
        flash("✅ Novo status incluído com sucesso!", "success")

    return redirect(url_for("status_pedido", nr_ped=nr_ped))



@app.route("/status/<nr_ped>/delete/<int:row_index>", methods=["POST"])
def excluir_status(nr_ped, row_index):
    try:
        row = status_ws.row_values(row_index)  # lê a linha completa
        status_nome = row[1].strip().lower() if len(row) > 1 else ""

        if status_nome == "pedido registrado":
            flash("⚠️ O status 'Pedido Registrado' não pode ser excluído.", "error")
        else:
            status_ws.delete_rows(row_index)
            flash("🗑️ Histórico excluído com sucesso!", "success")

    except Exception as e:
        app.logger.error(f"Erro ao excluir histórico: {e}")
        flash("❌ Erro ao excluir histórico.", "error")

    return redirect(url_for("status_pedido", nr_ped=nr_ped))
    
# =============================
# PAGAMENTO (Confirmar / Reverter)
# =============================
@app.route("/pagamento/<nr_ped>", methods=["GET", "POST"])
def pagamento_pedido(nr_ped):
    try:
        # === Localiza o pedido na planilha ===
        pedidos = pedidos_ws.get_all_records()
        pedido = next((p for p in pedidos if str(p.get("NR_PED")) == str(nr_ped)), None)

        if not pedido:
            flash("❌ Pedido não encontrado.", "error")
            return redirect(url_for("index"))

        pago = str(pedido.get("PAGO", "")).strip().upper() == "SIM"
        dt_receb = str(pedido.get("DT_RECEB", "")).strip()

        if request.method == "POST":
            acao = request.form.get("acao")
            data_pgto = request.form.get("data_pgto")
            usuario = session.get("usuario", "desconhecido")

            # === Localiza a linha exata do pedido no Sheets ===
            valores = pedidos_ws.get_all_values()
            header = valores[0] if valores else []
            data_rows = valores[1:]
            hidx = {name: i for i, name in enumerate(header)}

            linha_encontrada = None
            for idx, row in enumerate(data_rows, start=2):
                if str(row[hidx.get("NR_PED", 1)]) == str(nr_ped):
                    linha_encontrada = idx
                    break

            if not linha_encontrada:
                flash("❌ Não foi possível localizar o pedido na planilha.", "error")
                return redirect(url_for("index"))

            # === Registrar pagamento ===
            if acao == "confirmar":
                if not data_pgto:
                    flash("⚠️ Informe a data do recebimento.", "error")
                    return redirect(url_for("pagamento_pedido", nr_ped=nr_ped))

                try:
                    dt_obj = datetime.strptime(data_pgto, "%Y-%m-%d")
                    dt_pgto_fmt = dt_obj.strftime("%d/%m/%Y")
                except Exception:
                    flash("⚠️ Data inválida.", "error")
                    return redirect(url_for("pagamento_pedido", nr_ped=nr_ped))

                pedidos_ws.update_cell(linha_encontrada, hidx["PAGO"] + 1, "SIM")
                pedidos_ws.update_cell(linha_encontrada, hidx["DT_RECEB"] + 1, dt_pgto_fmt)
                flash(f"💰 Pagamento do pedido #{nr_ped} confirmado em {dt_pgto_fmt}.", "success")

            # === Reverter pagamento ===
            elif acao == "reverter":
                pedidos_ws.update_cell(linha_encontrada, hidx["PAGO"] + 1, "")
                pedidos_ws.update_cell(linha_encontrada, hidx["DT_RECEB"] + 1, "")
                flash(f"↩️ Pagamento do pedido #{nr_ped} foi revertido.", "warning")

            return redirect(url_for("detalhes", tipo="porcliente", filtro="todos"))

        # === GET ===
        return render_template(
            "pagamento.html",
            nr_ped=nr_ped,
            pago=pago,
            dt_receb=dt_receb,
            usuario=session.get("usuario")
        )

    except Exception as e:
        app.logger.error(f"Erro em /pagamento/{nr_ped}: {e}")
        flash("❌ Erro ao carregar tela de pagamento.", "error")
        return redirect(url_for("index"))


@app.route("/pagamento/<nr_ped>/confirmar", methods=["POST"])
def confirmar_pagamento(nr_ped):
    """Confirma o pagamento e grava PAGO = 'Sim' + DT_RECEB na planilha."""
    try:
        dt_receb = request.form.get("dt_receb")
        if not dt_receb:
            flash("⚠️ Informe a data/hora do recebimento.", "error")
            return redirect(url_for("pagamento_pedido", nr_ped=nr_ped))

        # Converte para dd/mm/aaaa HH:MM
        try:
            dt_receb_fmt = datetime.strptime(dt_receb, "%Y-%m-%dT%H:%M").strftime("%d/%m/%Y %H:%M")
        except Exception:
            dt_receb_fmt = dt_receb

        # Localiza linha do pedido
        values = pedidos_ws.get_all_values()
        header = values[0]
        hidx = {h: i for i, h in enumerate(header)}

        for i, row in enumerate(values[1:], start=2):
            if str(row[hidx.get("NR_PED")]).strip() == str(nr_ped):
                # Atualiza colunas PAGO e DT_RECEB
                col_pago = hidx.get("PAGO") + 1
                col_dtreceb = hidx.get("DT_RECEB") + 1
                pedidos_ws.update(f"{chr(64+col_pago)}{i}", "Sim")
                pedidos_ws.update(f"{chr(64+col_dtreceb)}{i}", dt_receb_fmt)
                flash("💰 Pagamento confirmado com sucesso!", "success")
                break

        return redirect(url_for("pagamento_pedido", nr_ped=nr_ped))

    except Exception as e:
        app.logger.error(f"Erro ao confirmar pagamento: {e}")
        flash("❌ Erro ao confirmar pagamento.", "error")
        return redirect(url_for("pagamento_pedido", nr_ped=nr_ped))


@app.route("/pagamento/<nr_ped>/reverter", methods=["POST"])
def reverter_pagamento(nr_ped):
    """Reverte o pagamento (PAGO = '', DT_RECEB = '')."""
    try:
        values = pedidos_ws.get_all_values()
        header = values[0]
        hidx = {h: i for i, h in enumerate(header)}

        for i, row in enumerate(values[1:], start=2):
            if str(row[hidx.get("NR_PED")]).strip() == str(nr_ped):
                col_pago = hidx.get("PAGO") + 1
                col_dtreceb = hidx.get("DT_RECEB") + 1
                pedidos_ws.update(f"{chr(64+col_pago)}{i}", "")
                pedidos_ws.update(f"{chr(64+col_dtreceb)}{i}", "")
                flash("↩️ Pagamento revertido com sucesso!", "success")
                break

        return redirect(url_for("pagamento_pedido", nr_ped=nr_ped))

    except Exception as e:
        app.logger.error(f"Erro ao reverter pagamento: {e}")
        flash("❌ Erro ao reverter pagamento.", "error")
        return redirect(url_for("pagamento_pedido", nr_ped=nr_ped))
   
   
# =====================================================
# ROTA: EDITAR PEDIDO (PADRONIZADA CONFORME PLANILHA)
# =====================================================
@app.route("/editar_pedido/<nr_ped>", methods=["GET", "POST"])
def editar_pedido(nr_ped):
    try:
        pedidos_data = pedidos_ws.get_all_records()
        pedido = next((p for p in pedidos_data if str(p.get("NR_PED")).strip() == str(nr_ped)), None)
        if not pedido:
            flash("⚠️ Pedido não encontrado.", "erro")
            return redirect(url_for("index"))

        # =====================================================
        # 🟢 PROCESSAMENTO DE EDIÇÃO
        # =====================================================
        if request.method == "POST":
            cliente = request.form.get("cliente", "").strip()
            paciente = request.form.get("paciente", "").strip()
            obs_ped = request.form.get("obs_ped", "").strip()
            itens = safe_json_list(request.form.get("itens_json", "[]"), "itens")
            custos = safe_json_list(request.form.get("custos_json", "[]"), "custos")
            dt_pedido = request.form.get("dt_pedido", "").strip()

            # Localiza a linha do pedido no Sheets
            pedidos_values = pedidos_ws.get_all_values()
            row_indices = get_row_indices_by_col(pedidos_values, 2, nr_ped)
            if not row_indices:
                flash("⚠️ Linha do pedido não localizada na planilha.", "erro")
                return redirect(url_for("index"))
            row_index = row_indices[0]

            # =====================================================
            # 🟡 ATUALIZAÇÃO DOS DADOS PRINCIPAIS
            # (Somente colunas não calculadas)
            # =====================================================
            pedidos_ws.batch_update(
                [
                    {"range": f"{rowcol_to_a1(row_index, 3)}", "values": [[cliente]]},
                    {"range": f"{rowcol_to_a1(row_index, 4)}", "values": [[paciente]]},
                    {"range": f"{rowcol_to_a1(row_index, 13)}", "values": [[obs_ped]]},
                ],
                value_input_option="USER_ENTERED"
            )

            # =====================================================
            # 🟢 ITENS DO PEDIDO
            # =====================================================
            itens_rows = [
                [
                    nr_ped,
                    item.get("produto", ""),  # PRODUTO
                    item.get("qtde", ""),     # QTD_ITEM
                    item.get("cor", ""),      # COR
                    "",                       # VLR_CAT (calculada)
                    item.get("valor", ""),    # VLR_COB
                    "",                       # TOTAL_PROD (calculada)
                    item.get("obs", "")       # OBS_ITEM
                ]
                for item in itens
            ]
            replace_detail_rows(itens_ws, 1, nr_ped, itens_rows)

            # =====================================================
            # 🟢 CUSTOS (TERCEIRIZAÇÃO)
            # =====================================================
            custos_rows = [
                [
                    nr_ped,
                    custo.get("desc", ""),     # DESC_CUSTO
                    custo.get("qtd", ""),      # QTD_CUSTO
                    custo.get("valor", ""),    # VLR_UN_CUSTO
                    "",                        # VLR_TOT_CUSTO (calculada)
                    custo.get("obs", "")       # OBS_CUSTO
                ]
                for custo in custos
            ]
            replace_detail_rows(custos_ws, 1, nr_ped, custos_rows)

            # ✅ Após salvar tudo
            flash(f"✅ Pedido #{nr_ped} atualizado com sucesso!", "sucesso")
            return jsonify({"sucesso": True, "nr_ped": nr_ped})


        # =====================================================
        # 🟢 MODO GET → CARREGA DADOS
        # =====================================================
        clientes = sorted([c.get("NOME_CLI") for c in clientes_ws.get_all_records() if c.get("NOME_CLI")])
        produtos = sorted(
            [{"PRODUTO": p.get("PRODUTO", ""), "VLR_CAT": p.get("VLR_CAT", "")}
             for p in produtos_ws.get_all_records() if p.get("PRODUTO")],
            key=lambda x: x["PRODUTO"].lower()
        )

        # Itens e custos
        itens = [r for r in itens_ws.get_all_records() if str(r.get("NR_PED")) == str(nr_ped)]
        custos = [r for r in custos_ws.get_all_records() if str(r.get("NR_PED")) == str(nr_ped)]

        # Lê a aba PEDIDOS_STATUS e procura o "Pedido Registrado"
        status_data = status_ws.get_all_records()
        registro_status = next(
            (s for s in status_data
             if str(s.get("NR_PED")).strip() == str(nr_ped)
             and str(s.get("STATUS_HIST", "")).strip().lower() == "pedido registrado"),
            None
        )

        # Tenta pegar a data diretamente do DT_HR_STATUS
        dt_pedido_raw = registro_status.get("DT_HR_STATUS", "") if registro_status else ""
        
        # Normaliza para o formato do input datetime-local
        dt_pedido_input = to_input_datetime(dt_pedido_raw)
        
        def safe_dict(d):
            return {k: ("" if v in (None, "undefined", "None") else str(v)) for k, v in d.items()}

        pedido_limpo = safe_dict(pedido)

        # normaliza e adiciona campo TOTAL_VIEW calculado
        itens_limpos = []
        for i in itens:
            item = safe_dict(i)
            # normaliza o valor
            valor_cob = to_float_safe(item.get("VLR_COB"))
            qtd_item = to_float_safe(item.get("QTD_ITEM"))
            # recria os campos limpos
            item["VLR_COB"] = f"{valor_cob:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            item["TOTAL_VIEW"] = f"{(valor_cob * qtd_item):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            itens_limpos.append(item)

        custos_limpos = []
        for c in custos:
            custo = safe_dict(c)
            valor_unit = to_float_safe(custo.get("VLR_UN_CUSTO"))
            qtd_custo = to_float_safe(custo.get("QTD_CUSTO"))
            custo["VLR_UN_CUSTO"] = f"{valor_unit:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            custo["TOTAL_VIEW"] = f"{(valor_unit * qtd_custo):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            custos_limpos.append(custo)

        app.logger.info(f"[DEBUG PEDIDO {nr_ped}] Cliente={pedido_limpo.get('CLIENTE')}, "
                        f"Paciente={pedido_limpo.get('PACIENTE')}, "
                        f"Itens={len(itens_limpos)}, Custos={len(custos_limpos)}")

        context = {
            "modo": "editar",
            "nr_ped": nr_ped,
            "usuario": session.get("usuario"),
            "clientes": clientes,
            "produtos": produtos,
            "cliente_atual": pedido_limpo.get("CLIENTE", ""),
            "paciente_atual": pedido_limpo.get("PACIENTE", ""),
            "obs_atual": pedido_limpo.get("OBS_PED", ""),
            "itens": itens_limpos,
            "custos": custos_limpos,
            "dt_pedido": dt_pedido_input
        }

        return render_template("pedido_form.html", **context)

    except Exception as e:
        import traceback
        app.logger.error(f"Erro em /editar_pedido/{nr_ped}: {e}\n{traceback.format_exc()}")
        flash(f"❌ Erro ao carregar o pedido: {e}", "erro")
        return redirect(url_for("index"))
    

# =====================================================
# ROTA: EXCLUIR PEDIDO COMPLETO (otimizada e robusta)
# =====================================================
@app.route("/api/excluir_pedido/<nr_ped>", methods=["DELETE"])
def excluir_pedido(nr_ped):
    try:
        app.logger.info(f"[EXCLUIR_PEDIDO] Iniciando exclusão do pedido {nr_ped}")

        excluidos = {"pedidos": 0, "itens": 0, "custos": 0, "status": 0}

        # ---------------------------
        # 🧾 ABA PEDIDOS
        # ---------------------------
        col_nr_ped = pedidos_ws.col_values(2)
        linhas_pedidos = [i + 1 for i, val in enumerate(col_nr_ped) if str(val).strip() == str(nr_ped)]
        for grupo in agrupar_consecutivas(linhas_pedidos) if linhas_pedidos else []:
            pedidos_ws.delete_rows(grupo[0], grupo[-1])
            excluidos["pedidos"] += len(grupo)

        # ---------------------------
        # 📦 ABA PEDIDOS_ITENS
        # ---------------------------
        col_nr_item = itens_ws.col_values(1)
        linhas_itens = [i + 1 for i, val in enumerate(col_nr_item) if str(val).strip() == str(nr_ped)]
        for grupo in agrupar_consecutivas(linhas_itens) if linhas_itens else []:
            itens_ws.delete_rows(grupo[0], grupo[-1])
            excluidos["itens"] += len(grupo)

        # ---------------------------
        # 💰 ABA PEDIDOS_CUSTOS
        # ---------------------------
        col_nr_custo = custos_ws.col_values(1)
        linhas_custos = [i + 1 for i, val in enumerate(col_nr_custo) if str(val).strip() == str(nr_ped)]
        for grupo in agrupar_consecutivas(linhas_custos) if linhas_custos else []:
            custos_ws.delete_rows(grupo[0], grupo[-1])
            excluidos["custos"] += len(grupo)

        # ---------------------------
        # 📋 ABA PEDIDOS_STATUS
        # ---------------------------
        try:
            col_nr_status = status_ws.col_values(1)
            linhas_status = [i + 1 for i, val in enumerate(col_nr_status) if str(val).strip() == str(nr_ped)]
            for grupo in agrupar_consecutivas(linhas_status) if linhas_status else []:
                status_ws.delete_rows(grupo[0], grupo[-1])
                excluidos["status"] += len(grupo)
        except Exception as e:
            app.logger.warning(f"[EXCLUIR_PEDIDO] Aba PEDIDOS_STATUS não acessível: {e}")

        total_excluidos = sum(excluidos.values())
        if total_excluidos == 0:
            msg = f"⚠️ Nenhum registro encontrado para o pedido {nr_ped}."
            app.logger.warning(f"[EXCLUIR_PEDIDO] {msg}")
            return jsonify({"ok": False, "msg": msg})

        msg = (
            f"Pedido {nr_ped} excluído com sucesso! "
            f"(PEDIDOS: {excluidos['pedidos']} | ITENS: {excluidos['itens']} | "
            f"CUSTOS: {excluidos['custos']} | STATUS: {excluidos['status']})"
        )
        app.logger.info(f"[EXCLUIR_PEDIDO] ✅ {msg}")

        return jsonify({"ok": True, "msg": msg})

    except Exception as e:
        import traceback
        erro = traceback.format_exc()
        app.logger.error(f"[EXCLUIR_PEDIDO] ❌ Erro ao excluir {nr_ped}: {e}\n{erro}")
        return jsonify({"ok": False, "msg": f"Erro ao excluir o pedido: {e}"})


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
