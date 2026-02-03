# app/db.py
import os
import gspread
from google.oauth2.service_account import Credentials

# Escopos necessários para acessar planilhas e drive
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

class SheetsDB:
    def __init__(self):
        self.client = None
        self.sheets = {}
        
    def init_app(self, app):
        """Inicializa conexão ao rodar o app, detectando ambiente (Local ou Cloud Run)"""
        
        # --- LÓGICA DE CREDENCIAIS HÍBRIDA ---
        # 1. Caminho no Cloud Run (Volume montado em /app/secrets)
        cloud_secret_path = "/app/secrets/credentials.json"
        # 2. Caminho Local (Na raiz do projeto)
        local_path = "credentials.json"

        if os.path.exists(cloud_secret_path):
            cred_path = cloud_secret_path
            print(f"🚀 [DB] Ambiente Cloud Run detectado. Usando: {cred_path}")
        else:
            cred_path = local_path
            print(f"🏠 [DB] Ambiente Local detectado. Usando: {cred_path}")
        
        # IDs das planilhas
        self.SHEET_ID_PEDIDOS = "1RbzDCYh7xaVmOxD1JLWDfpiw9HKhtw4r2zKxcmCfFsE"
        self.SHEET_ID_CADASTROS = "1QDP8Uo71gL_T9efOqtmSc5AoBTnYA8DlpgzYbTVIhoY"
        
        try:
            # Autenticação
            creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
            self.client = gspread.authorize(creds)
            
            # --- MAPEAMENTO DAS ABAS (WORKSHEETS) ---
            print("🔄 [DB] Conectando às planilhas...")
            
            # Planilha Principal (PEDIDOS)
            sheet_pedidos = self.client.open_by_key(self.SHEET_ID_PEDIDOS)
            self.sheets['pedidos'] = sheet_pedidos.worksheet("PEDIDOS")
            self.sheets['itens'] = sheet_pedidos.worksheet("PEDIDOS_ITENS")
            self.sheets['custos'] = sheet_pedidos.worksheet("PEDIDOS_CUSTOS")
            self.sheets['status'] = sheet_pedidos.worksheet("PEDIDOS_STATUS")
            self.sheets['pagamentos'] = sheet_pedidos.worksheet("PEDIDOS_PGTOS")

            # Planilha Secundária (CADASTROS)
            sheet_cadastros = self.client.open_by_key(self.SHEET_ID_CADASTROS)
            self.sheets['usuarios'] = sheet_cadastros.worksheet("ADM_BOT")
            self.sheets['clientes'] = sheet_cadastros.worksheet("CLIENTES")
            self.sheets['produtos'] = sheet_cadastros.worksheet("PRODUTOS")
            self.sheets['cad_status'] = sheet_cadastros.worksheet("STATUS")
            
            print("✅ [DB] Conexão com Google Sheets estabelecida com sucesso!")
            
        except FileNotFoundError:
            print(f"❌ [DB] ERRO FATAL: Arquivo de credenciais não encontrado em: {cred_path}")
            # Em produção, isso vai derrubar o container e gerar log de erro, o que é bom para debug
            raise 
        except Exception as e:
            print(f"❌ [DB] Erro ao conectar no Google Sheets: {e}")
            raise e

    def get_ws(self, name):
        """Retorna a worksheet já carregada pelo nome"""
        if name not in self.sheets:
            print(f"⚠️ [DB] Aviso: Tentativa de acessar planilha inexistente '{name}'")
            return None
        return self.sheets.get(name)

# Instância global para ser importada
db = SheetsDB()