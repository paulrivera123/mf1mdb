import requests
import time
from datetime import datetime

# Guardamos la IP con la que configuraste Binance
IP_INICIAL = requests.get('https://api.ipify.org').text

print(f"--- 🛰️ MONITOR DE CONEXIÓN MF1MDB ---")
print(f"IP Registrada: {IP_INICIAL}")
print("El script verificará cambios cada hora...")

def verificar_cambio_ip():
    global IP_INICIAL
    try:
        current_ip = requests.get('https://api.ipify.org').text
        if current_ip != IP_INICIAL:
            print(f"\n⚠️ ¡ALERTA! Tu IP ha cambiado.")
            print(f"Vieja: {IP_INICIAL} -> Nueva: {current_ip}")
            print("Debes actualizarla en la whitelist de Binance para que el bot siga operando.")
            # Aquí podrías actualizar IP_INICIAL si decides que ya la registraste en Binance
            # IP_INICIAL = current_ip 
        else:
            print(f"[{datetime.now().strftime('%H:%M')}] Conexión estable. IP: {current_ip}")
    except Exception as e:
        print(f"Error de red: {e}")

while True:
    verificar_cambio_ip()
    # Espera 1 hora (3600 segundos) para la siguiente revisión
    time.sleep(3600)