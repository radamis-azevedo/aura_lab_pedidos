#!/bin/bash
set -e

cd /home/auralab/apps/aura_lab_pedidos

git pull origin main

source venv/bin/activate
pip install -r requirements.txt

sudo systemctl restart aura_pedidos.service
sudo systemctl status aura_pedidos.service --no-pager -l
