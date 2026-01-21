import json
from datetime import datetime, date
import unicodedata
import re
from babel.numbers import format_currency
from babel.dates import format_date
from gspread.utils import rowcol_to_a1

# ==========================
# FORMATADORES E PARSERS
# ==========================

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

# Alias para manter compatibilidade
to_float_safe = parse_float 

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

def parse_br_datetime(s):
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
    """Converte datas para o formato do input HTML datetime-local (YYYY-MM-DDTHH:MM)"""
    s = (value or "").strip()
    if not s: return ""
    # Já está em ISO?
    if "-" in s and ("T" in s or " " in s):
        return s.replace(" ", "T")[:16]
    
    # Tenta BR com hora
    dt = parse_br_datetime(s)
    if dt:
        return dt.strftime("%Y-%m-%dT%H:%M")

    # Tenta só data BR
    try:
        dt2 = datetime.strptime(s, "%d/%m/%Y")
        return dt2.strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return ""

def slugify_status(s: str) -> str:
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[\s/]+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    return s

def norm_status(s):
    return str(s or "").strip().lower()

def safe_json_list(raw_value, label, logger=None):
    try:
        parsed = json.loads(raw_value or "[]")
    except json.JSONDecodeError:
        if logger:
            logger.warning(f"[JSON] Falha ao carregar {label}. Valor recebido: {raw_value!r}")
        return []
    if isinstance(parsed, list):
        return parsed
    if logger:
        logger.warning(f"[JSON] Conteúdo inválido para {label}. Esperado lista, recebido: {type(parsed).__name__}")
    return []

# MOVIDO PARA FORA (Correção do erro de importação)
def is_paid(v):
    s = str(v or "").strip().lower()
    return s in {"sim", "s", "yes", "y", "true", "1", "pago"}

# ==========================
# UTILITÁRIOS DE LISTAS E SHEETS
# ==========================

def agrupar_consecutivas(seq):
    """Agrupa números consecutivos, ex: [1, 2, 3, 5, 6] -> [[1, 3], [5, 6]] (ranges inclusivos)"""
    seq = sorted(list(set(seq))) # Garante ordenação e unicidade
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
    # Assumindo values[0] como header, dados começam em values[1] -> linha 2 do excel
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
    """
    Substitui linhas detalhe (itens/custos).
    Estratégia:
    1. Se quantidades batem: atualiza in-place (mais rápido).
    2. Se não batem: Adiciona novos no final e deleta os antigos.
    """
    values = ws.get_all_values()
    row_indices = get_row_indices_by_col(values, col_index, key_value)

    # Caso 1: Apenas deletar (se new_rows vazio)
    if not new_rows:
        # IMPORTANTE: Deletar de baixo para cima (reversed) para não mudar os índices das linhas de cima
        for grupo in reversed(agrupar_consecutivas(row_indices)):
            ws.delete_rows(grupo[0], grupo[-1])
        return

    # Caso 2: Atualização exata (mesma quantidade de linhas)
    if len(row_indices) == len(new_rows):
        batch_update_rows(ws, row_indices, new_rows)
        return

    # Caso 3: Quantidade diferente (Append + Delete)
    append_rows_safe(ws, new_rows)
    
    # Deleta os antigos (sempre usando reversed para segurança)
    for grupo in reversed(agrupar_consecutivas(row_indices)):
        ws.delete_rows(grupo[0], grupo[-1])