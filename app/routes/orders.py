# app/routes/orders.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, date, timedelta
from app.db import db
from zoneinfo import ZoneInfo # Importado aqui para garantir
from app.utils import (
    safe_json_list, append_rows_safe, parse_br_datetime, 
    replace_detail_rows, get_row_indices_by_col, 
    slugify_status, parse_float, is_paid, norm_status,
    parse_date, to_input_datetime, to_float_safe, agrupar_consecutivas, rowcol_to_a1
)

orders_bp = Blueprint('orders', __name__)

# =====================================================
# ROTAS DE LEITURA (DETALHES, A RECEBER)
# =====================================================

@orders_bp.route("/areceber")
def areceber():
    # 1. Carrega todas as tabelas necessárias
    pedidos = db.sheets['pedidos'].get_all_records()
    itens = db.sheets['itens'].get_all_records()
    custos = db.sheets['custos'].get_all_records() # <--- FALTAVA ISSO
    
    pedidos_filtrados = []
    hoje = date.today()
    
    for p in pedidos:
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))
        
        if status == "entregue" and not pago:
            p["VLR_NUM"] = parse_float(p.get("VLR_PED"))
            
            # Cálculo de Dias Delta
            prazo = parse_date(p.get("DT_PRAZO"))
            if prazo:
                delta = (prazo - hoje).days
                p["DIAS_DELTA"] = delta
            else:
                p["DIAS_DELTA"] = None

            pedidos_filtrados.append(p)

    # 2. Anexa Itens e Custos
    for ped in pedidos_filtrados:
        # Converte para string e remove espaços para garantir o match
        ped_num = str(ped.get("NR_PED")).strip()
        
        ped["ITENS"] = [i for i in itens if str(i.get("NR_PED")).strip() == ped_num]
        ped["CUSTOS"] = [c for c in custos if str(c.get("NR_PED")).strip() == ped_num]

    from collections import defaultdict
    agrupado = defaultdict(list)
    for ped in pedidos_filtrados:
        agrupado[ped.get("CLIENTE", "—")].append(ped)

    modo_view = request.args.get('modo', 'lista')

    return render_template(
        "detalhes.html",
        filtro="A Receber",
        agrupado=agrupado,
        tipo="receber",
        usuario=session.get("usuario"),
        modo_view=modo_view
    )

@orders_bp.route("/detalhes/<tipo>/<filtro>")
def detalhes(tipo, filtro):
    pedidos = db.sheets['pedidos'].get_all_records()
    itens = db.sheets['itens'].get_all_records()
    custos = db.sheets['custos'].get_all_records()
    
    hoje = date.today()
    pedidos_filtrados = []
    
    for p in pedidos:
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO"))
        p["VLR_NUM"] = parse_float(p.get("VLR_PED"))

        # Lógica de Filtro
        include = False
        if tipo == "prazo":
            if filtro == "atrasados" and prazo and prazo < hoje and status != "entregue": include = True
            elif filtro == "hoje" and prazo and prazo == hoje and status != "entregue": include = True
            elif filtro in {"futuro", "futuros"} and prazo and prazo > hoje and status != "entregue": include = True
        elif tipo == "status" and status == norm_status(filtro): include = True
        elif tipo == "receber" and status == "entregue" and not pago: include = True
        elif tipo == "porcliente":
            if filtro == "todos": include = True
            elif filtro == "naoentregues" and status != "entregue": include = True
        elif tipo == "porstatus" and slugify_status(p.get("STATUS", "")) == filtro.lower(): include = True

        if include:
            if prazo:
                delta = (prazo - hoje).days
                p["DIAS_DELTA"] = delta
            else:
                p["DIAS_DELTA"] = None
            
            pedidos_filtrados.append(p)

    # Anexa Itens e Custos (CORRIGIDO AQUI)
    for ped in pedidos_filtrados:
        ped_num = str(ped.get("NR_PED")).strip()
        
        ped["ITENS"] = [i for i in itens if str(i.get("NR_PED")).strip() == ped_num]
        # Faltava essa linha abaixo no seu código original:
        ped["CUSTOS"] = [c for c in custos if str(c.get("NR_PED")).strip() == ped_num]

    from collections import defaultdict
    agrupado = defaultdict(list)
    for ped in pedidos_filtrados:
        agrupado[ped.get("CLIENTE", "—")].append(ped)

    modo_view = request.args.get('modo', 'lista')

    return render_template(
        "detalhes.html",
        filtro=filtro.title(),
        agrupado=agrupado,
        tipo=tipo,
        usuario=session.get("usuario"),
        modo_view=modo_view
    )


# =====================================================
# ROTAS DE CRIAÇÃO E EDIÇÃO
# =====================================================

@orders_bp.route("/novo_pedido", methods=["GET", "POST"])
def novo_pedido():
    if request.method == "POST":
        try:
            # Captura dados
            cliente = request.form.get("cliente", "").strip()
            paciente = request.form.get("paciente", "").strip()
            obs_ped = request.form.get("obs_ped", "").strip()
            itens = safe_json_list(request.form.get("itens_json", "[]"), "itens")
            custos = safe_json_list(request.form.get("custos_json", "[]"), "custos")
            
            # Gera ID
            pedidos_data = db.sheets['pedidos'].get_all_records()
            if pedidos_data:
                numeros = [int(p["NR_PED"]) for p in pedidos_data if str(p.get("NR_PED")).isdigit()]
                ultimo_ped = max(numeros) if numeros else 0
            else:
                ultimo_ped = 0
            novo_nr_ped = ultimo_ped + 1
            
            # Salva Pedido
            db.sheets['pedidos'].append_row([
                "", novo_nr_ped, cliente, paciente, "", "", "", "", "", "", "", "", obs_ped
            ], value_input_option="USER_ENTERED")

            # Salva Itens
            itens_rows = [[novo_nr_ped, i.get("produto"), i.get("qtde"), i.get("cor"), "", i.get("valor"), "", i.get("obs")] for i in itens]
            append_rows_safe(db.sheets['itens'], itens_rows)

            # Salva Custos
            custos_rows = [[novo_nr_ped, c.get("desc"), c.get("qtd"), c.get("valor"), "", c.get("obs")] for c in custos]
            append_rows_safe(db.sheets['custos'], custos_rows)

            # Salva Status Inicial
            dt_pedido = request.form.get("dt_pedido", "").strip()
            dt_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
            db.sheets['status'].append_row([
                novo_nr_ped, "Pedido Registrado", dt_pedido, "1", "", "", session.get("usuario"), dt_atual
            ], value_input_option="USER_ENTERED")

            flash(f"✅ Pedido #{novo_nr_ped} criado!", "sucesso")
            return jsonify({"sucesso": True, "nr_ped": novo_nr_ped})
        except Exception as e:
            return jsonify({"sucesso": False, "erro": str(e)})

    # GET: Carrega formulário
    clientes = sorted([c.get("NOME_CLI") for c in db.sheets['clientes'].get_all_records() if c.get("NOME_CLI")])
    produtos = sorted([{"PRODUTO": p.get("PRODUTO"), "VLR_CAT": p.get("VLR_CAT")} for p in db.sheets['produtos'].get_all_records() if p.get("PRODUTO")], key=lambda x: x["PRODUTO"])
    
    return render_template("pedido_form.html", modo="novo", usuario=session.get("usuario"), clientes=clientes, produtos=produtos, dt_pedido=datetime.now().strftime("%Y-%m-%dT%H:%M"))

@orders_bp.route("/salvar_layout", methods=["POST"])
def salvar_layout():
    data = request.get_json()
    ordem = data.get("ordem", [])
    registros = db.sheets['usuarios'].get_all_records()
    for i, r in enumerate(registros, start=2):
        if r.get("NOME") == session["usuario"]:
            db.sheets['usuarios'].update_cell(i, 4, ",".join(ordem))
            break
    return {"ok": True}

# =============================
# EDIÇÃO DE PEDIDO
# =============================
@orders_bp.route("/editar_pedido/<nr_ped>", methods=["GET", "POST"])
def editar_pedido(nr_ped):
    # GET: Carrega dados
    if request.method == "GET":
        pedidos_data = db.sheets['pedidos'].get_all_records()
        pedido = next((p for p in pedidos_data if str(p.get("NR_PED")).strip() == str(nr_ped)), None)
        
        if not pedido:
            flash("⚠️ Pedido não encontrado.", "erro")
            return redirect(url_for("dashboard.index"))

        # Prepara listas
        itens = [r for r in db.sheets['itens'].get_all_records() if str(r.get("NR_PED")) == str(nr_ped)]
        custos = [r for r in db.sheets['custos'].get_all_records() if str(r.get("NR_PED")) == str(nr_ped)]
        
        # Formatação para view
        for i in itens:
            v = to_float_safe(i.get("VLR_COB"))
            q = to_float_safe(i.get("QTD_ITEM"))
            i["VLR_COB"] = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            i["TOTAL_VIEW"] = f"{(v*q):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            
        for c in custos:
            v = to_float_safe(c.get("VLR_UN_CUSTO"))
            q = to_float_safe(c.get("QTD_CUSTO"))
            c["VLR_UN_CUSTO"] = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            c["TOTAL_VIEW"] = f"{(v*q):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        # Data do pedido
        status_data = db.sheets['status'].get_all_records()
        registro_status = next(
            (s for s in status_data if str(s.get("NR_PED")) == str(nr_ped) and str(s.get("STATUS_HIST")).lower() == "pedido registrado"), 
            None
        )
        dt_pedido_raw = registro_status.get("DT_HR_STATUS", "") if registro_status else ""
        
        # Contexto
        context = {
            "modo": "editar",
            "nr_ped": nr_ped,
            "usuario": session.get("usuario"),
            "clientes": sorted([c.get("NOME_CLI") for c in db.sheets['clientes'].get_all_records() if c.get("NOME_CLI")]),
            "produtos": sorted([{"PRODUTO": p.get("PRODUTO"), "VLR_CAT": p.get("VLR_CAT")} for p in db.sheets['produtos'].get_all_records() if p.get("PRODUTO")], key=lambda x: x["PRODUTO"]),
            "cliente_atual": pedido.get("CLIENTE", ""),
            "paciente_atual": pedido.get("PACIENTE", ""),
            "obs_atual": pedido.get("OBS_PED", ""),
            "itens": itens,
            "custos": custos,
            "dt_pedido": to_input_datetime(dt_pedido_raw)
        }
        return render_template("pedido_form.html", **context)

    # POST: Salva edição
    try:
        cliente = request.form.get("cliente", "").strip()
        paciente = request.form.get("paciente", "").strip()
        obs_ped = request.form.get("obs_ped", "").strip()
        itens = safe_json_list(request.form.get("itens_json", "[]"), "itens")
        custos = safe_json_list(request.form.get("custos_json", "[]"), "custos")

        # Atualiza Capa (Pedido)
        values = db.sheets['pedidos'].get_all_values()
        row_indices = get_row_indices_by_col(values, 2, nr_ped)
        if row_indices:
            row_index = row_indices[0]
            db.sheets['pedidos'].batch_update([
                {"range": f"{rowcol_to_a1(row_index, 3)}", "values": [[cliente]]},
                {"range": f"{rowcol_to_a1(row_index, 4)}", "values": [[paciente]]},
                {"range": f"{rowcol_to_a1(row_index, 13)}", "values": [[obs_ped]]},
            ], value_input_option="USER_ENTERED")

        # Atualiza Itens e Custos
        itens_rows = [[nr_ped, i.get("produto"), i.get("qtde"), i.get("cor"), "", i.get("valor"), "", i.get("obs")] for i in itens]
        replace_detail_rows(db.sheets['itens'], 1, nr_ped, itens_rows)

        custos_rows = [[nr_ped, c.get("desc"), c.get("qtd"), c.get("valor"), "", c.get("obs")] for c in custos]
        replace_detail_rows(db.sheets['custos'], 1, nr_ped, custos_rows)

        flash(f"✅ Pedido #{nr_ped} atualizado!", "sucesso")
        return jsonify({"sucesso": True, "nr_ped": nr_ped})
    except Exception as e:
        return jsonify({"sucesso": False, "erro": str(e)})

# =============================
# EXCLUSÃO COMPLETA
# =============================
@orders_bp.route("/api/excluir_pedido/<nr_ped>", methods=["DELETE"])
def excluir_pedido(nr_ped):
    try:
        excluidos = {"pedidos": 0, "itens": 0, "custos": 0, "status": 0}
        
        # Helper para deletar em lote
        def delete_in_sheet(ws_name, col_idx):
            ws = db.sheets[ws_name]
            col_vals = ws.col_values(col_idx)
            rows = [i + 1 for i, val in enumerate(col_vals) if str(val).strip() == str(nr_ped)]
            count = 0
            for grupo in agrupar_consecutivas(rows):
                ws.delete_rows(grupo[0], grupo[-1])
                count += len(grupo)
            return count

        excluidos["pedidos"] = delete_in_sheet('pedidos', 2)
        excluidos["itens"] = delete_in_sheet('itens', 1)
        excluidos["custos"] = delete_in_sheet('custos', 1)
        try:
            excluidos["status"] = delete_in_sheet('status', 1)
        except: pass

        if sum(excluidos.values()) == 0:
            return jsonify({"ok": False, "msg": "Nenhum registro encontrado."})

        return jsonify({"ok": True, "msg": f"Pedido {nr_ped} excluído!"})

    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

# Em app/routes/orders.py

@orders_bp.route("/pagamento/<nr_ped>")
def pagamento_pedido(nr_ped):
    try:
        # 1. Carrega pedidos para achar o cliente
        pedidos = db.sheets['pedidos'].get_all_records()
        
        # Busca o pedido de forma segura (comparando texto com texto e sem espaços)
        nr_alvo = str(nr_ped).strip()
        pedido = next((p for p in pedidos if str(p.get("NR_PED", "")).strip() == nr_alvo), None)
        
        if not pedido:
            flash("❌ Pedido não encontrado.", "error")
            return redirect(url_for("dashboard.index"))
        
        # 2. Pega o nome do Cliente
        cliente_nome = str(pedido.get("CLIENTE", "")).strip()

        if not cliente_nome:
            flash("⚠️ Esse pedido não tem nome de cliente cadastrado.", "warning")
            return redirect(url_for("dashboard.index"))

        # 3. REDIRECIONA para o Financeiro
        # Isso cria uma URL tipo: /financeiro/?cliente=RAFAELA...
        return redirect(url_for('finance.index', cliente=cliente_nome))

    except Exception as e:
        print(f"Erro na rota pagamento: {e}") # Log no terminal
        flash("Erro ao tentar abrir financeiro. Tente novamente.", "error")
        return redirect(url_for("dashboard.index"))

@orders_bp.route("/pagamento/<nr_ped>/confirmar", methods=["POST"])
def confirmar_pagamento(nr_ped):
    try:
        dt_receb = request.form.get("dt_receb")
        if not dt_receb:
            flash("⚠️ Informe a data.", "error")
            return redirect(url_for("orders.pagamento_pedido", nr_ped=nr_ped))

        try:
            dt_fmt = datetime.strptime(dt_receb, "%Y-%m-%dT%H:%M").strftime("%d/%m/%Y %H:%M")
        except:
            dt_fmt = dt_receb

        # Atualiza planilha
        values = db.sheets['pedidos'].get_all_values()
        row_indices = get_row_indices_by_col(values, 2, nr_ped)
        if row_indices:
            idx = row_indices[0]
            # Assumindo posições fixas PAGO (col 10/J) e DT_RECEB (col 11/K)
            db.sheets['pedidos'].update(f"J{idx}:K{idx}", [["Sim", dt_fmt]], value_input_option="USER_ENTERED")
            flash("💰 Pagamento confirmado!", "success")
            
        return redirect(url_for("orders.pagamento_pedido", nr_ped=nr_ped))
    except Exception as e:
        flash(f"Erro: {e}", "error")
        return redirect(url_for("orders.pagamento_pedido", nr_ped=nr_ped))

@orders_bp.route("/pagamento/<nr_ped>/reverter", methods=["POST"])
def reverter_pagamento(nr_ped):
    values = db.sheets['pedidos'].get_all_values()
    row_indices = get_row_indices_by_col(values, 2, nr_ped)
    if row_indices:
        idx = row_indices[0]
        db.sheets['pedidos'].update(f"J{idx}:K{idx}", [["", ""]], value_input_option="USER_ENTERED")
        flash("↩️ Pagamento revertido.", "success")
    return redirect(url_for("orders.pagamento_pedido", nr_ped=nr_ped))

# =============================
# STATUS (HISTÓRICO) BLINDADO
# =============================
@orders_bp.route("/status/<nr_ped>", methods=["GET", "POST"])
def status_pedido(nr_ped):
    # --- BUSCAR HISTÓRICO COMPLETO ---
    values = db.sheets['status'].get_all_values()
    historico = []
    
    data_limite_obj = None
    data_limite_str = ""
    
    for i, row in enumerate(values[1:], start=2):
        if str(row[0]).strip() == str(nr_ped): 
            st = row[1] if len(row) > 1 else ""
            dt_str = row[2] if len(row) > 2 else ""
            
            dt_obj_row = None
            try:
                dt_obj_row = datetime.strptime(dt_str, "%d/%m/%Y %H:%M")
            except: pass

            # Se for o registro inicial, guarda a data limite
            if st.lower() == "pedido registrado":
                if dt_obj_row: 
                    data_limite_obj = dt_obj_row
                    data_limite_str = dt_obj_row.strftime("%Y-%m-%dT%H:%M")

            historico.append({
                "row_index": i,
                "STATUS_HIST": st,
                "DT_HR_STATUS": dt_str,
                "PRAZO_STATUS": row[3] if len(row) > 3 else "",
                "DT_HR_PRAZO": row[4] if len(row) > 4 else "",
                "OBS_STATUS": row[5] if len(row) > 5 else "",
                "USUARIO": row[6] if len(row) > 6 else "",
                "DATA_HORA": row[7] if len(row) > 7 else "",
                "DT_OBJ": dt_obj_row
            })

    historico.sort(key=lambda x: x['DT_OBJ'] or datetime.min)

    # --- PROCESSAR POST (SALVAR) ---
    if request.method == "POST":
        novo_status = request.form.get("status")
        dt_hr_status = request.form.get("dt_hr_status") 
        prazo = request.form.get("prazo")
        obs = request.form.get("obs")
        row_index = request.form.get("row_index") 
        
        # 1. VALIDAÇÃO: Bloquear inclusão manual de "Pedido Registrado"
        if not row_index and novo_status.lower() == "pedido registrado":
            flash("🚫 ERRO: O status 'Pedido Registrado' é automático e não pode ser incluído manualmente.", "error")
            return redirect(url_for("orders.status_pedido", nr_ped=nr_ped))

        # 2. CONVERSÃO DE DATA
        try:
            dt_obj = datetime.strptime(dt_hr_status, "%Y-%m-%dT%H:%M")
            dt_str_final = dt_obj.strftime("%d/%m/%Y %H:%M")
        except:
            flash("🚫 ERRO: Data inválida.", "error")
            return redirect(url_for("orders.status_pedido", nr_ped=nr_ped))

        # 3. VALIDAÇÃO: Linha do Tempo
        if data_limite_obj:
            eh_o_registro_inicial = False
            if row_index:
                for h in historico:
                    if str(h['row_index']) == str(row_index) and h['STATUS_HIST'].lower() == 'pedido registrado':
                        eh_o_registro_inicial = True
                        break
            
            if not eh_o_registro_inicial and dt_obj < data_limite_obj:
                 flash(f"🚫 ERRO: A data não pode ser anterior ao registro do pedido ({data_limite_obj.strftime('%d/%m/%Y %H:%M')}).", "error")
                 return redirect(url_for("orders.status_pedido", nr_ped=nr_ped))

        # Calcula prazo
        dias = int(prazo or 0)
        dt_prazo_str = (dt_obj + timedelta(days=dias)).strftime("%d/%m/%Y %H:%M") if dias > 0 else ""
        agora_str = datetime.now(ZoneInfo("America/Cuiaba")).strftime("%d/%m/%Y %H:%M")

        if row_index:
            db.sheets['status'].update(
                f"B{row_index}:H{row_index}",
                [[novo_status, dt_str_final, prazo, dt_prazo_str, obs, session.get("usuario"), agora_str]],
                value_input_option="USER_ENTERED"
            )
        else:
            db.sheets['status'].append_row(
                [nr_ped, novo_status, dt_str_final, prazo, dt_prazo_str, obs, session.get("usuario"), agora_str],
                value_input_option="USER_ENTERED"
            )
        
        flash("✅ Status atualizado!", "success")
        return redirect(url_for("orders.status_pedido", nr_ped=nr_ped))

    # --- PREPARA DADOS PARA GET ---
    cad_status = db.sheets['cad_status'].get_all_records()
    status_options = [
        r["STATUS"] for r in cad_status 
        if r.get("STATUS") and r.get("STATUS").lower() != "pedido registrado"
    ]
    status_prazo_obrig = {r["STATUS"]: r.get("PRAZO_OBRIG", "").strip() for r in cad_status}
    
    itens = [i for i in db.sheets['itens'].get_all_records() if str(i.get("NR_PED")) == str(nr_ped)]

    return render_template(
        "status.html",
        nr_ped=nr_ped,
        usuario=session.get("usuario"),
        historico=historico,
        status_options=status_options,
        status_prazo_obrig=status_prazo_obrig,
        now_str=datetime.now(ZoneInfo("America/Cuiaba")).strftime("%Y-%m-%dT%H:%M"),
        itens=itens,
        data_limite_iso=data_limite_str
    )

@orders_bp.route("/status/<nr_ped>/delete/<int:row_index>", methods=["POST"])
def excluir_status(nr_ped, row_index):
    try:
        val = db.sheets['status'].cell(row_index, 2).value 
        if val and val.lower() == "pedido registrado":
            flash("🚫 ERRO: Não é permitido excluir o 'Pedido Registrado'. Ele é a base do histórico.", "error")
        else:
            db.sheets['status'].delete_rows(row_index)
            flash("🗑️ Histórico excluído.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    
    return redirect(url_for("orders.status_pedido", nr_ped=nr_ped))

@orders_bp.route("/itens/<nr_ped>")
def itens_pedido(nr_ped):
    itens = [i for i in db.sheets['itens'].get_all_records() if str(i.get("NR_PED")) == str(nr_ped)]
    custos = [c for c in db.sheets['custos'].get_all_records() if str(c.get("NR_PED")) == str(nr_ped)]
    return render_template("itens_pedido.html", itens=itens, custos=custos)