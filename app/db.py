# app/db.py
import os
import gspread
from google.oauth2.service_account import Credentials

# Escopos necessários
SCOPES = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

class SheetsDB:
    def __init__(self):
        self.client = None
        self.sheets = {}
        
    def init_app(self, app):
        """Inicializa conexão apenas quando o app rodar"""
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
        
        # IDs das planilhas (Idealmente viriam do config.py)
        self.SHEET_ID_PEDIDOS = "1RbzDCYh7xaVmOxD1JLWDfpiw9HKhtw4r2zKxcmCfFsE"
        self.SHEET_ID_CADASTROS = "1QDP8Uo71gL_T9efOqtmSc5AoBTnYA8DlpgzYbTVIhoY"
        
        try:
            creds = Credentials.from_service_account_file(cred_path, scopes=SCOPES)
            self.client = gspread.authorize(creds)
            
            # Cachear as worksheets para não buscar toda hora
            # OBS: Em produção, cuidado com timeouts. O ideal é ter reconnect.
            self.sheets['pedidos'] = self.client.open_by_key(self.SHEET_ID_PEDIDOS).worksheet("PEDIDOS")
            self.sheets['itens'] = self.client.open_by_key(self.SHEET_ID_PEDIDOS).worksheet("PEDIDOS_ITENS")
            self.sheets['custos'] = self.client.open_by_key(self.SHEET_ID_PEDIDOS).worksheet("PEDIDOS_CUSTOS")
            self.sheets['status'] = self.client.open_by_key(self.SHEET_ID_PEDIDOS).worksheet("PEDIDOS_STATUS")
            
            self.sheets['usuarios'] = self.client.open_by_key(self.SHEET_ID_CADASTROS).worksheet("ADM_BOT")
            self.sheets['clientes'] = self.client.open_by_key(self.SHEET_ID_CADASTROS).worksheet("CLIENTES")
            self.sheets['produtos'] = self.client.open_by_key(self.SHEET_ID_CADASTROS).worksheet("PRODUTOS")
            self.sheets['cad_status'] = self.client.open_by_key(self.SHEET_ID_CADASTROS).worksheet("STATUS")
            self.sheets['pagamentos'] = self.client.open_by_key(self.SHEET_ID_PEDIDOS).worksheet("PEDIDOS_PGTOS")
            
            print("✅ Conexão com Google Sheets estabelecida!")
        except Exception as e:
            print(f"❌ Erro ao conectar no Google Sheets: {e}")
            raise e

    def get_ws(self, name):
        return self.sheets.get(name)

# Instância global para ser importada
db = SheetsDB()