# app/routes/orders.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime, date, timedelta
from app.db import db
from app.utils import (
    safe_json_list, append_rows_safe, parse_br_datetime, 
    replace_detail_rows, get_row_indices_by_col, 
    slugify_status, parse_float, is_paid, norm_status,
    parse_date, to_input_datetime, to_float_safe, agrupar_consecutivas
)

orders_bp = Blueprint('orders', __name__)

# =====================================================
# ROTAS DE LEITURA (DETALHES, A RECEBER)
# =====================================================

@orders_bp.route("/areceber")
def areceber():
    pedidos = db.sheets['pedidos'].get_all_records()
    pedidos_filtrados = []
    
    for p in pedidos:
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))
        if status == "entregue" and not pago:
            p["VLR_NUM"] = parse_float(p.get("VLR_PED"))
            pedidos_filtrados.append(p)

    from collections import defaultdict
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

# Em app/routes/orders.py

@orders_bp.route("/detalhes/<tipo>/<filtro>")
def detalhes(tipo, filtro):
    pedidos = db.sheets['pedidos'].get_all_records()
    itens = db.sheets['itens'].get_all_records()
    hoje = date.today()
    pedidos_filtrados = []
    
    for p in pedidos:
        status = norm_status(p.get("STATUS"))
        pago = is_paid(p.get("PAGO"))
        prazo = parse_date(p.get("DT_PRAZO")) # Converte string para data real
        p["VLR_NUM"] = parse_float(p.get("VLR_PED"))

        # Lógica de Filtro (Mantida igual)
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
            # === NOVA LÓGICA DE DIAS RESTANTES ===
            if prazo:
                delta = (prazo - hoje).days
                p["DIAS_DELTA"] = delta # Salva o número (ex: -3, 0, 5)
            else:
                p["DIAS_DELTA"] = None
            
            pedidos_filtrados.append(p)

    # Anexa itens
    for ped in pedidos_filtrados:
        ped_num = str(ped.get("NR_PED"))
        ped["ITENS"] = [i for i in itens if str(i.get("NR_PED")) == ped_num]

    from collections import defaultdict
    agrupado = defaultdict(list)
    for ped in pedidos_filtrados:
        agrupado[ped.get("CLIENTE", "—")].append(ped)

    modo_view = request.args.get('modo', 'cards')

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
                # Filtra apenas valores numéricos para evitar erro
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

# =====================================================
# COLE ISSO NO FINAL DE app/routes/orders.py
# =====================================================

from zoneinfo import ZoneInfo
from app.utils import rowcol_to_a1

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
            return redirect(url_for("dashboard.index")) # Note: dashboard.index

        # Prepara listas
        itens = [r for r in db.sheets['itens'].get_all_records() if str(r.get("NR_PED")) == str(nr_ped)]
        custos = [r for r in db.sheets['custos'].get_all_records() if str(r.get("NR_PED")) == str(nr_ped)]
        
        # Formatação para view (Total View e inputs)
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

# =============================
# PAGAMENTO
# =============================
@orders_bp.route("/pagamento/<nr_ped>", methods=["GET", "POST"])
def pagamento_pedido(nr_ped):
    # Localiza pedido
    pedidos = db.sheets['pedidos'].get_all_records()
    pedido = next((p for p in pedidos if str(p.get("NR_PED")) == str(nr_ped)), None)
    
    if not pedido:
        flash("❌ Pedido não encontrado.", "error")
        return redirect(url_for("dashboard.index"))

    # Confirmação via POST (Formulário simples) ou GET
    if request.method == "POST":
        # Nota: A lógica complexa foi movida para as rotas específicas abaixo
        # mantendo compatibilidade com forms antigos se houver
        pass

    return render_template(
        "pagamento.html",
        nr_ped=nr_ped,
        pago=is_paid(pedido.get("PAGO")),
        dt_receb=pedido.get("DT_RECEB"),
        usuario=session.get("usuario")
    )

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
            # Ajuste conforme sua planilha se mudou
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
# STATUS (HISTÓRICO)
# =============================
@orders_bp.route("/status/<nr_ped>", methods=["GET", "POST"])
def status_pedido(nr_ped):
    if request.method == "POST":
        # Salvar novo status
        novo_status = request.form.get("status")
        dt_hr_status = request.form.get("dt_hr_status") # ISO
        prazo = request.form.get("prazo")
        obs = request.form.get("obs")
        row_index = request.form.get("row_index") # Se for edição
        
        try:
            dt_obj = datetime.strptime(dt_hr_status, "%Y-%m-%dT%H:%M")
            dt_str = dt_obj.strftime("%d/%m/%Y %H:%M")
        except:
            flash("Data inválida", "error")
            return redirect(url_for("orders.status_pedido", nr_ped=nr_ped))

        # Calcula prazo
        dias = int(prazo or 0)
        dt_prazo_str = (dt_obj + timedelta(days=dias)).strftime("%d/%m/%Y %H:%M") if dias > 0 else ""
        agora_str = datetime.now(ZoneInfo("America/Cuiaba")).strftime("%d/%m/%Y %H:%M")

        if row_index:
            db.sheets['status'].update(
                f"B{row_index}:H{row_index}",
                [[novo_status, dt_str, prazo, dt_prazo_str, obs, session.get("usuario"), agora_str]],
                value_input_option="USER_ENTERED"
            )
        else:
            db.sheets['status'].append_row(
                [nr_ped, novo_status, dt_str, prazo, dt_prazo_str, obs, session.get("usuario"), agora_str],
                value_input_option="USER_ENTERED"
            )
        
        flash("Status atualizado!", "success")
        return redirect(url_for("orders.status_pedido", nr_ped=nr_ped))

    # GET: Listar
    values = db.sheets['status'].get_all_values()
    # Pula header (row 1)
    historico = []
    for i, row in enumerate(values[1:], start=2):
        if str(row[0]).strip() == str(nr_ped): # Col 0 = NR_PED
            # Mapeamento seguro de colunas pelo índice
            def get_col(idx): return row[idx] if idx < len(row) else ""
            historico.append({
                "row_index": i,
                "STATUS_HIST": get_col(1),
                "DT_HR_STATUS": get_col(2),
                "PRAZO_STATUS": get_col(3),
                "DT_HR_PRAZO": get_col(4),
                "OBS_STATUS": get_col(5),
                "USUARIO": get_col(6),
                "DATA_HORA": get_col(7)
            })

    # Cadastros para o dropdown
    cad_status = db.sheets['cad_status'].get_all_records()
    status_options = [r["STATUS"] for r in cad_status if r.get("STATUS")]
    status_prazo_obrig = {r["STATUS"]: r.get("PRAZO_OBRIG", "").strip() for r in cad_status}
    
    # Itens para visualização rápida
    itens = [i for i in db.sheets['itens'].get_all_records() if str(i.get("NR_PED")) == str(nr_ped)]

    return render_template(
        "status.html",
        nr_ped=nr_ped,
        usuario=session.get("usuario"),
        historico=historico,
        status_options=status_options,
        status_prazo_obrig=status_prazo_obrig,
        now_str=datetime.now(ZoneInfo("America/Cuiaba")).strftime("%Y-%m-%dT%H:%M"),
        itens=itens
    )

@orders_bp.route("/status/<nr_ped>/delete/<int:row_index>", methods=["POST"])
def excluir_status(nr_ped, row_index):
    try:
        # Validação simples
        val = db.sheets['status'].cell(row_index, 2).value # Col B = Status
        if val and val.lower() == "pedido registrado":
            flash("⚠️ Não pode excluir o registro inicial.", "error")
        else:
            db.sheets['status'].delete_rows(row_index)
            flash("Histórico excluído.", "success")
    except Exception as e:
        flash(f"Erro: {e}", "error")
    
    return redirect(url_for("orders.status_pedido", nr_ped=nr_ped))

# Rota para ver itens (modal ou pagina separada)
@orders_bp.route("/itens/<nr_ped>")
def itens_pedido(nr_ped):
    itens = [i for i in db.sheets['itens'].get_all_records() if str(i.get("NR_PED")) == str(nr_ped)]
    custos = [c for c in db.sheets['custos'].get_all_records() if str(c.get("NR_PED")) == str(nr_ped)]
    return render_template("itens_pedido.html", itens=itens, custos=custos)