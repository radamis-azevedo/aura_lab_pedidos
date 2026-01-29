# app/routes/finance.py
from flask import Blueprint, render_template, request, flash, redirect, url_for
from app.db import db
from app.services.finance import reconciliar_pagamentos, buscar_extrato_cliente
from datetime import datetime

finance_bp = Blueprint('finance', __name__, url_prefix='/financeiro')

@finance_bp.route('/', methods=['GET', 'POST'])
def index():
    # 1. CARREGAR E LIMPAR LISTA DE CLIENTES (Sempre executa)
    try:
        # Pega coluna 3 (C), remove cabeçalho, remove vazios e espaços
        clientes_raw = db.get_ws('pedidos').col_values(3)
        clientes_set = {str(c).strip() for c in clientes_raw[1:] if c and str(c).strip()}
        clientes = sorted(list(clientes_set))
    except Exception as e:
        print(f"Erro ao carregar clientes: {e}")
        clientes = []

    dados = None
    cliente_atual = None

    # 2. VERIFICAR SE VEIO CLIENTE PELA URL (Redirecionamento após salvar/excluir)
    # Isso resolve o problema de perder o estado
    if request.args.get('cliente'):
        cliente_atual = request.args.get('cliente')

    # 3. VERIFICAR SE VEIO DO FORMULÁRIO (Seleção no Dropdown)
    if request.method == 'POST':
        
        # CASO A: Selecionou no Dropdown
        if 'selecionar_cliente' in request.form:
            cliente_atual = request.form.get('cliente')

        # CASO B: Registrou Pagamento
        elif 'registrar_pagamento' in request.form:
            cliente_atual = request.form.get('cliente_hidden')
            valor_str = request.form.get('valor')
            data = request.form.get('data')
            obs = request.form.get('obs')

            try:
                # 1. TRATAMENTO DA DATA
                if data:
                    data_obj = datetime.strptime(data, '%Y-%m-%d')
                    data_fmt = data_obj.strftime('%d/%m/%Y')
                else:
                    data_fmt = datetime.now().strftime('%d/%m/%Y')

                # 2. TRATAMENTO NUMÉRICO (Salvar como float, não texto)
                # Remove pontos de milhar e troca vírgula por ponto
                if valor_str:
                    valor_limpo = valor_str.replace('.', '').replace(',', '.')
                    valor_float = float(valor_limpo)
                else:
                    valor_float = 0.0

                # 3. SALVAR NO SHEETS
                # value_input_option='USER_ENTERED' é crucial para o Sheets reconhecer o número
                ws_pagamentos = db.get_ws('pagamentos')
                ws_pagamentos.append_row(
                    [cliente_atual, data_fmt, valor_float, obs], 
                    value_input_option='USER_ENTERED'
                )
                
                flash(f"Pagamento de R$ {valor_str} registrado!", "success")
                
                # Reconcilia (Baixa as dívidas antigas)
                reconciliar_pagamentos(cliente_atual)

                return redirect(url_for('finance.index', cliente=cliente_atual))

            except Exception as e:
                flash(f"Erro ao salvar: {e}", "error")

    # 4. SE TEM UM CLIENTE DEFINIDO, BUSCA OS DADOS
    if cliente_atual and cliente_atual in clientes:
        try:
            # Garante que o reconciliation rode para mostrar dados frescos
            # (Opcional: pode comentar a linha abaixo se ficar lento)
            reconciliar_pagamentos(cliente_atual) 
            
            dados = buscar_extrato_cliente(cliente_atual)
        except Exception as e:
            flash(f"Erro ao buscar dados: {e}", "error")
            dados = None

    return render_template('financeiro.html', clientes=clientes, dados=dados, cliente_atual=cliente_atual)

@finance_bp.route('/excluir_pagamento', methods=['POST'])
def excluir_pagamento():
    row_index = request.form.get('row_index')
    cliente = request.form.get('cliente_hidden')
    
    if row_index:
        try:
            # Deleta a linha
            db.get_ws('pagamentos').delete_rows(int(row_index))
            flash("Pagamento excluído com sucesso!", "success")
            
            # Recalcula o saldo
            reconciliar_pagamentos(cliente)
            
        except Exception as e:
            flash(f"Erro ao excluir: {e}", "error")
    
    # REDIRECIONA para o index passando o cliente
    # Assim o index carrega a lista de clientes limpa novamente
    return redirect(url_for('finance.index', cliente=cliente))