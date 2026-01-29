# app/services/finance.py
from app.db import db
from datetime import datetime
import re
import unicodedata

def safe_float(value):
    """
    Converte valores monetários para float de forma SUPER segura.
    Remove R$, espaços normais e espaços invisíveis (nbsp).
    """
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    
    # Normaliza para remover caracteres estranhos e converte para string
    text = str(value)
    # Remove R$ e normaliza espaços (incluindo \xa0 que é comum em planilhas)
    text = unicodedata.normalize("NFKD", text).replace("R$", "").replace(" ", "")
    
    # Troca pontuação brasileira
    text = text.replace(".", "").replace(",", ".")
    
    try:
        return float(text)
    except ValueError:
        return 0.0

def safe_int_id(value):
    """Extrai o número do ID (ex: '#088' -> 88)."""
    if isinstance(value, int):
        return value
    if not value:
        return 0
    clean = re.sub(r'\D', '', str(value))
    try:
        return int(clean)
    except ValueError:
        return 0

def smart_date_parse(dt_str):
    """Tenta converter a data de vários formatos."""
    if not dt_str:
        return datetime.min
    
    dt_str = str(dt_str).strip()
    formats = ['%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y', '%d-%m-%Y']
    
    for fmt in formats:
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
            
    return datetime.min

def reconciliar_pagamentos(cliente_nome):
    """
    Lógica FIFO (First-In, First-Out) com índices corrigidos e limpeza forçada.
    """
    ws_pagamentos = db.get_ws('pagamentos')
    ws_pedidos = db.get_ws('pedidos')
    
    # 1. Calcular Saldo Total Pago
    pagamentos = ws_pagamentos.get_all_values() # Usando get_all_values para segurança
    total_pago = 0.0
    
    # Índices Pagamento: A=0(Cliente), B=1(Dt), C=2(Valor)
    for row in pagamentos[1:]:
        if len(row) > 2 and str(row[0]).strip() == cliente_nome:
            total_pago += safe_float(row[2])
    
    saldo_para_baixar = total_pago

    # 2. Ler Pedidos
    rows = ws_pedidos.get_all_values()
    
    # === ÍNDICES CORRIGIDOS PELO PRINT DA PLANILHA ===
    IDX_STATUS = 0     # A: Status
    IDX_ID = 1         # B: NR_PED
    IDX_CLIENTE = 2    # C: Cliente
    IDX_DT_ENTREG = 6  # G: DT_ENTREG (Antes estava 4/E errado)
    IDX_VALOR = 7      # H: VLR_PED
    IDX_PAGO = 8       # I: PAGO

    pedidos_para_processar = []

    for i, row in enumerate(rows[1:], start=2):
        if len(row) <= IDX_PAGO: continue 
        
        row_cliente = str(row[IDX_CLIENTE]).strip()
        row_status = str(row[IDX_STATUS]).strip().upper()
        
        if row_cliente == cliente_nome and row_status == 'ENTREGUE':
            pedidos_para_processar.append({
                'row_index': i,
                'id_num': safe_int_id(row[IDX_ID]),
                'dt_entreg': row[IDX_DT_ENTREG],
                'valor': safe_float(row[IDX_VALOR]),
                'status_pago_atual': str(row[IDX_PAGO]).strip().upper()
            })

    # 3. ORDENAÇÃO: Data Entrega Crescente (Mais antigo primeiro) -> ID Crescente
    pedidos_para_processar.sort(key=lambda x: (smart_date_parse(x['dt_entreg']), x['id_num']))

    updates = [] 

    # 4. Aplica a baixa
    for pedido in pedidos_para_processar:
        valor_pedido = pedido['valor']
        row_idx = pedido['row_index']
        
        # Se o valor for 0 (erro de leitura), forçamos log para debug (opcional)
        # mas a lógica segue.
        
        if saldo_para_baixar >= (valor_pedido - 0.01):
            # TEM SALDO -> PAGA
            if pedido['status_pago_atual'] != "SIM":
                 updates.append({'range': f'I{row_idx}', 'values': [['SIM']]})
            
            saldo_para_baixar -= valor_pedido
        else:
            # ACABOU O SALDO -> LIMPA
            # Removemos a verificação "if != ''". 
            # Mandamos limpar SEMPRE se não tiver saldo, para garantir.
            updates.append({'range': f'I{row_idx}', 'values': [['']]})
            
            saldo_para_baixar = 0
    
    # 5. Executa atualização em lote
    if updates:
        try:
            ws_pedidos.batch_update(updates)
        except Exception as e:
            print(f"Erro update: {e}")
        
    return {
        "total_pago": total_pago,
        "saldo_restante": saldo_para_baixar
    }

def buscar_extrato_cliente(cliente_nome):
    ws_pagamentos = db.get_ws('pagamentos')
    ws_pedidos = db.get_ws('pedidos')

    # Pagamentos
    rows_pgtos = ws_pagamentos.get_all_values()
    pgtos_cliente = []
    
    for i, row in enumerate(rows_pgtos[1:], start=2):
        if len(row) > 2 and str(row[0]).strip() == cliente_nome:
            pgtos_cliente.append({
                'row_index': i,
                'DT_RECEB': row[1],
                'VLR_RECEB': row[2],
                'OBS': row[3] if len(row) > 3 else ""
            })
    pgtos_cliente.sort(key=lambda x: smart_date_parse(x['DT_RECEB']), reverse=True)

    # Pedidos
    rows = ws_pedidos.get_all_values()
    
    # Índices iguais ao reconciliar
    IDX_STATUS = 0
    IDX_ID = 1
    IDX_CLIENTE = 2
    IDX_PACIENTE = 3
    IDX_DT_ENTREG = 6 # Corrigido para G
    IDX_VALOR = 7
    IDX_PAGO = 8

    pedidos_cliente = []
    
    for row in rows[1:]:
        if len(row) <= IDX_PAGO: continue 

        row_cliente = str(row[IDX_CLIENTE]).strip()
        row_status = str(row[IDX_STATUS]).strip().upper()

        if row_cliente == cliente_nome and row_status == 'ENTREGUE':
            pedidos_cliente.append({
                'NR_PED': row[IDX_ID],
                'PACIENTE': row[IDX_PACIENTE],
                'DT_ENTREG': row[IDX_DT_ENTREG], # Usa Data Entrega correta
                'VLR_PED': row[IDX_VALOR],
                'PAGO': row[IDX_PAGO] if len(row) > IDX_PAGO else ""
            })

    # Ordena Visualização (Mais novo em cima)
    pedidos_cliente.sort(key=lambda x: (smart_date_parse(x['DT_ENTREG']), safe_int_id(x['NR_PED'])), reverse=True)

    total_divida = sum(safe_float(p['VLR_PED']) for p in pedidos_cliente)
    total_pago = sum(safe_float(p.get('VLR_RECEB')) for p in pgtos_cliente)

    return {
        "pedidos": pedidos_cliente,
        "pagamentos": pgtos_cliente,
        "resumo": {
            "total_divida": total_divida,   
            "total_pago": total_pago,
            "saldo_pendente": total_divida - total_pago
        }
    }