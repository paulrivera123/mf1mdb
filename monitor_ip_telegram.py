import requests
import time
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage?chat_id={CHAT_ID}&text={message}"
    try:
        requests.get(url)
    except Exception as e:
        print(f"Error enviando a Telegram: {e}")

# IP con la que configuraste Binance inicialmente
IP_REGISTRADA = requests.get('https://api.ipify.org').text

print(f"--- 🛰️ MONITOR MF1MDB ACTIVO ---")
send_telegram_msg(f"✅ Bot de Monitoreo MF1MDB Iniciado. IP Actual: {IP_REGISTRADA}")

def verificar_ip():
    global IP_REGISTRADA
    try:
        current_ip = requests.get('https://api.ipify.org').text
        if current_ip != IP_REGISTRADA:
            msg = f"⚠️ ¡ALERTA MF1MDB!\nTu IP ha cambiado de {IP_REGISTRADA} a {current_ip}.\nDebes actualizar Binance de inmediato."
            print(msg)
            send_telegram_msg(msg)
            # IP_REGISTRADA = current_ip # Descomenta si quieres que pare de avisar tras el primer aviso
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] Todo OK. IP: {current_ip}")
    except Exception as e:
        print(f"Error de red: {e}")

while True:
    verificar_ip()
    time.sleep(3600) # Revisa cada hora