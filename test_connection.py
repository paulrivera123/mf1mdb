import ccxt
import os
from dotenv import load_dotenv

# Cargar las claves del archivo .env
load_dotenv()

def test_binance_connection():
    print("--- 🔐 PRUEBA DE CONEXIÓN A BINANCE ---")
    
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("❌ ERROR: No se encontraron las claves en el archivo .env")
        return

    try:
        # Conectamos en modo Futuros
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': secret_key,
            'options': {'defaultType': 'future'}
        })
        
        # Intentamos leer el saldo (Esto es lo que valida las llaves)
        print("📡 Conectando con Binance...")
        balance = exchange.fetch_balance()
        
        usdt_free = balance['USDT']['free']
        print(f"✅ ¡CONEXIÓN EXITOSA!")
        print(f"💰 Saldo Disponible en Futuros: {usdt_free} USDT")
        print("El bot tiene permiso para leer tu cuenta. Todo listo.")
        
    except Exception as e:
        print(f"❌ FALLO DE CONEXIÓN:")
        print(e)
        print("\nPosibles causas:")
        print("1. Las llaves aún no pasan las 24h de espera.")
        print("2. Copiaste mal la Secret Key.")
        print("3. No activaste la casilla 'Enable Futures' al crear la API.")

if __name__ == "__main__":
    test_binance_connection()