from flask import Flask, render_template
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# 🔑 Conexão com Google Sheets
scope = ["https://spreadsheets.google.com/feeds",
         "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

# IDs das planilhas
SHEET_PEDIDOS_ID = "1RbzDCYh7xaVmOxD1JLWDfpiw9HKhtw4r2zKxcmCfFsE"
SHEET_CADASTROS_ID = "1QDP8Uo71gL_T9efOqtmSc5AoBTnYA8DlpgzYbTVIhoY"

# Abas principais
pedidos_ws = client.open_by_key(SHEET_PEDIDOS_ID).worksheet("PEDIDOS")
itens_ws   = client.open_by_key(SHEET_PEDIDOS_ID).worksheet("PEDIDOS_ITENS")
custos_ws  = client.open_by_key(SHEET_PEDIDOS_ID).worksheet("PEDIDOS_CUSTOS")

# Abas de cadastros
cli_apr_ws   = client.open_by_key(SHEET_CADASTROS_ID).worksheet("CLI_APR")
produtos_ws  = client.open_by_key(SHEET_CADASTROS_ID).worksheet("PRODUTOS")
clientes_ws  = client.open_by_key(SHEET_CADASTROS_ID).worksheet("CLIENTES")


# ------------------- FUNÇÃO DE APOIO -------------------
def parse_valor(valor):
    """
    Converte valores vindos da planilha para float.
    Ex: 'R$ 1.200,50' -> 1200.50
    """
    if not valor:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).replace("R$", "").replace(".", "").replace(",", ".").strip())
    except:
        return 0.0


# ------------------- FILTRO JINJA -------------------
@app.template_filter("format_currency")
def format_currency(value):
    """
    Formata valores numéricos para padrão brasileiro com R$ e vírgula.
    """
    try:
        return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return "R$ 0,00"


# ------------------- ROTAS -------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---- Pedidos por Cliente ----
@app.route("/pedidos/por-cliente")
def pedidos_por_cliente():
    pedidos = pedidos_ws.get_all_records()
    clientes = {}
    for p in pedidos:
        p["VLR_PED"] = parse_valor(p["VLR_PED"])
        cliente = p["CLIENTE"]
        clientes.setdefault(cliente, []).append(p)
    return render_template("pedidos_por_cliente.html", clientes=clientes)


# ---- Pedidos por Status ----
@app.route("/pedidos/por-status")
def pedidos_por_status():
    pedidos = pedidos_ws.get_all_records()
    status_map = {}
    for p in pedidos:
        p["VLR_PED"] = parse_valor(p["VLR_PED"])
        status = p["STATUS"]
        status_map.setdefault(status, []).append(p)
    return render_template("pedidos_por_status.html", status_map=status_map)


# ---- Clientes cadastrados ----
@app.route("/clientes")
def clientes():
    clientes_list = clientes_ws.get_all_records()
    return render_template("clientes.html", clientes=clientes_list)


# ---- Produtos do catálogo ----
@app.route("/produtos")
def produtos():
    produtos_list = produtos_ws.get_all_records()
    return render_template("produtos.html", produtos=produtos_list)


# ---- Clientes para aprovar ----
@app.route("/clientes/aprovar")
def clientes_aprovar():
    clientes_apr = cli_apr_ws.get_all_records()
    return render_template("clientes_aprovar.html", clientes=clientes_apr)


# ---- Detalhes de um pedido ----
@app.route("/pedidos/<nr_ped>")
def detalhes_pedido(nr_ped):
    pedidos = pedidos_ws.get_all_records()
    pedido = next((p for p in pedidos if str(p["NR_PED"]) == str(nr_ped)), None)
    if not pedido:
        return f"Pedido {nr_ped} não encontrado", 404

    # Itens e custos vinculados
    itens = [i for i in itens_ws.get_all_records() if str(i["NR_PED"]) == str(nr_ped)]
    custos = [c for c in custos_ws.get_all_records() if str(c["NR PEDIDO"]) == str(nr_ped)]

    # Totais tratados
    total_itens = sum([parse_valor(i["TOTAL_PROD"]) for i in itens])
    total_custos = sum([parse_valor(c["VALOR TOTAL"]) for c in custos])
    total_final = total_itens - total_custos

    return render_template(
        "pedido_detalhes.html",
        pedido=pedido,
        itens=itens,
        custos=custos,
        total_itens=total_itens,
        total_custos=total_custos,
        total_final=total_final
    )


# ------------------- MAIN -------------------
if __name__ == "__main__":
    app.run(debug=True)
