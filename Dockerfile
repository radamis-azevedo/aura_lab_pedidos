FROM python:3.12-slim

# Evita arquivos .pyc e logs presos no buffer
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instala dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código
COPY . .

# Comando de execução padrão do Cloud Run
# 'exec' garante que o gunicorn receba os sinais de parada corretamente
# --bind :$PORT faz ele ouvir na porta que o Google mandar
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 run:app