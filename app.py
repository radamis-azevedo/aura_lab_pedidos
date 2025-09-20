from flask import Flask, render_template
from babel.numbers import format_currency
from babel.dates import format_date
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from collections import defaultdict
import os

app = Flask(__name__)

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

# =============================
# FUNÇÕES AUXILIARES
# =============================
def parse_float(value):
    """Converte strings como 'R$ 1.234,56' para float"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        cleaned = str(value)
        cleaned = cleaned.replace("R$", "").replace(" ", "")
        cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)
    except Exception:
        return 0.0

def parse_date(value):
    """Tenta converter múltiplos formatos comuns de data para datetime.date."""
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
    # Se vier como número do Google Sheets (serial), ignore para simplicidade
    return None

def get_itens_pedido(nr_ped):
    """Retorna itens vinculados a um pedido"""
    nr_ped = str(nr_ped).strip()
    itens = itens_ws.get_all_records()
    itens_filtrados = []
    for i in itens:
        nr_item = str(i.get("NR_PED") or i.get("NR PED") or "").strip()
        if nr_item == nr_ped:
            itens_filtrados.append(i)
    return itens_filtrados

# =============================
# FILTROS CUSTOMIZADOS
# =============================
@app.template_filter()
def format_brl(value):
    """Formata valores em Real Brasileiro (R$ 1.234,56)"""
    try:
        return format_currency(float(value), "BRL", locale="pt_BR")
    except Exception:
        return value

@app.template_filter()
def format_date_br(value):
    """Formata datas no padrão brasileiro DD/MM/AAAA, aceitando vários formatos de entrada."""
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
# ROTAS
# =============================
@app.route("/")
def index():
    pedidos = pedidos_ws.get_all_records()

    hoje = datetime.date.today()

    # Totais a receber: status 'Pendente de Entrega' e não pago
    total_receber_qtd = 0
    total_receber_val = 0.0

    # Prazos reais
    prazos = {"atrasados": {"qtd": 0, "val": 0.0},
              "hoje": {"qtd": 0, "val": 0.0},
              "futuros": {"qtd": 0, "val": 0.0}}

    # Status
    status_map = defaultdict(lambda: {"qtd": 0, "val": 0.0})

    for p in pedidos:
        val = parse_float(p.get("VLR_PED"))
        status_original = p.get("STATUS") or "Indefinido"
        status = norm_status(status_original)
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO"))

        # A receber: entregues e não pagos
        if status == "entregue" and not pago:
            total_receber_qtd += 1
            total_receber_val += val

        # Prazos (ignora os já entregues)
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

        # Status agregados (usamos o texto original para exibir)
        if status != "entregue":
            status_map[status_original]["qtd"] += 1
            status_map[status_original]["val"] += val

    return render_template(
        "index.html",
        total_receber_qtd=total_receber_qtd,
        total_receber_val=total_receber_val,
        prazos=prazos,
        status_map=status_map
    )

@app.route("/detalhes/<tipo>/<filtro>")
def detalhes(tipo, filtro):
    pedidos = pedidos_ws.get_all_records()
    itens = itens_ws.get_all_records()  # <-- busca de itens da aba PEDIDOS_ITENS
    hoje = datetime.date.today()
    pedidos_filtrados = []

    for p in pedidos:
        val = parse_float(p.get("VLR_PED"))
        p["VLR_NUM"] = val
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO"))

        # --- MANTÉM SUA LÓGICA DE FILTRO (ajustada conforme já combinamos) ---
        if tipo == "prazo":
            if filtro == "atrasados" and prazo and prazo < hoje and status != "entregue":
                pedidos_filtrados.append(p)
            elif filtro == "hoje" and prazo and prazo == hoje and status != "entregue":
                pedidos_filtrados.append(p)
            elif filtro in {"futuro", "futuros"} and prazo and prazo > hoje and status != "entregue":
                pedidos_filtrados.append(p)

        elif tipo == "status":
            if status == norm_status(filtro) and status != "entregue":
                pedidos_filtrados.append(p)

        elif tipo == "receber":
            # A receber = Entregue e NÃO pago
            if status == "entregue" and not pago:
                pedidos_filtrados.append(p)

    # 🔹 Anexa os itens correspondentes a cada pedido filtrado
    for ped in pedidos_filtrados:
        ped_num = str(ped.get("NR_PED"))
        ped["ITENS"] = [i for i in itens if str(i.get("NR_PED")) == ped_num]

    # Agrupa por cliente para o template
    agrupado = defaultdict(list)
    for ped in pedidos_filtrados:
        agrupado[ped.get("CLIENTE", "—")].append(ped)

    return render_template("detalhes.html", filtro=filtro, agrupado=agrupado, tipo=tipo)

@app.route("/areceber")
def pedidos_a_receber():
    pedidos = pedidos_ws.get_all_records()
    pedidos_filtrados = []

    for p in pedidos:
        val = parse_float(p.get("VLR_PED"))
        p["VLR_NUM"] = val
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))

        # Pedidos a receber = entregues e não pagos
        if status == "entregue" and not pago:
            pedidos_filtrados.append(p)

    # Agrupar por cliente
    agrupado = defaultdict(list)
    for ped in pedidos_filtrados:
        agrupado[ped.get("CLIENTE", "—")].append(ped)

    return render_template(
        "detalhes.html",
        filtro="PEDIDOS ENTREGUES PENDENTES DE RECEBIMENTO",
        agrupado=agrupado,
        tipo="receber"   # 🔹 aqui está o segredo
    )

@app.route("/itens/<nr_ped>")
def itens_pedido(nr_ped):
    # Busca os itens vinculados ao pedido usando a função auxiliar
    itens = get_itens_pedido(nr_ped)

    # Renderiza apenas a tabela de itens
    return render_template("itens_pedido.html", itens=itens)


if __name__ == "__main__":
    app.run(debug=True)
