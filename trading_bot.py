import ccxt
import csv
import pandas as pd
import pandas_ta as ta
import time
import schedule
import json 
import os
import sys
import requests
from dotenv import load_dotenv
from datetime import datetime
import brain_ia  

# --- 1. CONFIGURACIÓN Y CLAVES ---
load_dotenv()
API_KEY = os.getenv('BINANCE_API_KEY')
SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')
ADMIN_PASSWORD = os.getenv('BOT_PASSWORD') # Contraseña del Kill Switch

# --- CARTERA ---
WATCHLIST = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XAU/USDT', # Las Reinas
    'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'LINK/USDT', 'POL/USDT', # Ecosistemas
    'XRP/USDT', 'LTC/USDT', 'BCH/USDT', 'NEAR/USDT', 'XLM/USDT', # Pagos y Velocidad
    'DOGE/USDT', '1000SHIB/USDT', '1000PEPE/USDT', 'FET/USDT', 'RENDER/USDT' # Volatilidad e IA
] 
TIMEFRAME = '15m'
LEVERAGE = 10
RISK_PER_TRADE = 0.02  # 2% Riesgo por operación

# --- REGLAS DE SALIDA ---
TAKE_PROFIT_PCT = 0.03  # Ganar 3%
STOP_LOSS_PCT = 0.015   # Perder máx 1.5%

# --- 2. FUNCIONES DE APOYO Y MEMORIA ---
ARCHIVO_MEMORIA = "historial_bot.json"
ultimo_update_id = 0 # Para rastrear los clics en Telegram

# Estado global de seguridad para el Kill Switch
estado_seguridad = {
    "esperando_password": False,
    "accion_pendiente": "",
    "chat_id_esperando": None
}

def cargar_memoria():
    if os.path.exists(ARCHIVO_MEMORIA):
        with open(ARCHIVO_MEMORIA, 'r') as f:
            return json.load(f)
    return {"ganancia_global": 0.0, "exitos_globales": 0, "errores_globales": 0}

def guardar_memoria(datos):
    with open(ARCHIVO_MEMORIA, 'w') as f:
        json.dump(datos, f)

# Inicializamos la memoria global al arrancar
memoria_global = cargar_memoria()

def send_telegram_alert(mensaje, incluir_botones=False):
    token = os.getenv('TELEGRAM_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat_id: return
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "Markdown"}
    
    if incluir_botones:
        # Botones acomodados en pares para no saturar la pantalla del celular
        teclado = {
            "inline_keyboard": [
                [{"text": "📊 Resumen de Hoy", "callback_data": "btn_hoy"}, {"text": "🌍 Resumen Global", "callback_data": "btn_global"}],
                [{"text": "🛑 Vender todo", "callback_data": "btn_vender"}, {"text": "☠️ Desactivar bot", "callback_data": "btn_apagar"}]
            ]
        }
        payload["reply_markup"] = json.dumps(teclado)
        
    try:
        requests.post(url, json=payload, timeout=5)
    except: pass

def initialize_exchange():
    return ccxt.binance({
        'apiKey': API_KEY,
        'secret': SECRET_KEY,
        'options': {'defaultType': 'future'},
        'enableRateLimit': True
    })

def cerrar_todas_las_posiciones():
    try:
        exchange = initialize_exchange()
        posiciones = exchange.fetch_positions()
        cerradas = 0
        for pos in posiciones:
            amt = float(pos['info']['positionAmt'])
            symbol = pos['symbol']
            if amt != 0:
                side = 'sell' if amt > 0 else 'buy'
                # Parche de seguridad: reduceOnly asegura que NUNCA abra una posición inversa por accidente
                exchange.create_order(symbol, 'market', side, abs(amt), params={'reduceOnly': True})
                cerradas += 1
        return True, f"✅ Éxito. Se cerraron {cerradas} posiciones abiertas a precio de mercado."
    except Exception as e:
        return False, f"❌ Error crítico cerrando posiciones: {str(e)}"

def escuchar_botones_telegram():
    global ultimo_update_id, estado_seguridad
    token = os.getenv('TELEGRAM_TOKEN')
    if not token: return
    
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {"offset": ultimo_update_id + 1, "timeout": 1}
    try:
        respuesta = requests.get(url, params=params).json()
        if respuesta.get("ok"):
            for resultado in respuesta["result"]:
                ultimo_update_id = resultado["update_id"]
                
                # A. Capturar texto si el bot está esperando la contraseña
                if "message" in resultado and "text" in resultado["message"]:
                    chat_id = resultado["message"]["chat"]["id"]
                    mensaje_id = resultado["message"]["message_id"]
                    texto = resultado["message"]["text"]
                    
                    if estado_seguridad["esperando_password"] and str(chat_id) == str(estado_seguridad["chat_id_esperando"]):
                        # 1. Borrar el mensaje con la clave por seguridad
                        requests.post(f"https://api.telegram.org/bot{token}/deleteMessage", json={"chat_id": chat_id, "message_id": mensaje_id})
                        
                        # 2. Validar clave
                        if texto == ADMIN_PASSWORD:
                            send_telegram_alert("✅ Contraseña verificada. Ejecutando protocolo de emergencia, espera...")
                            exito, msj_resultado = cerrar_todas_las_posiciones()
                            send_telegram_alert(msj_resultado)
                            
                            if exito and estado_seguridad["accion_pendiente"] == "apagar":
                                send_telegram_alert("🔌 Apagando sistema principal. El bot dejará de operar ahora.")
                                sys.exit(0) # Apaga el script de Python
                        else:
                            send_telegram_alert("❌ Contraseña incorrecta. Protocolo abortado.")
                        
                        # 3. Resetear el estado de seguridad
                        estado_seguridad["esperando_password"] = False
                        estado_seguridad["accion_pendiente"] = ""
                        estado_seguridad["chat_id_esperando"] = None

                # B. Capturar clics en los botones
                if "callback_query" in resultado:
                    datos_boton = resultado["callback_query"]["data"]
                    chat_id = resultado["callback_query"]["message"]["chat"]["id"]
                    
                    if datos_boton == "btn_hoy":
                        enviar_resumen_diario(resetear=False)
                    elif datos_boton == "btn_global":
                        enviar_resumen_global()
                    elif datos_boton in ["btn_vender", "btn_apagar"]:
                        # Activar el modo espera de contraseña
                        estado_seguridad["esperando_password"] = True
                        estado_seguridad["accion_pendiente"] = "apagar" if datos_boton == "btn_apagar" else "vender"
                        estado_seguridad["chat_id_esperando"] = chat_id
                        
                        accion_str = "🛑 Vender Todo" if datos_boton == "btn_vender" else "☠️ Desactivar Bot"
                        send_telegram_alert(f"⚠️ ALERTA DE SEGURIDAD: Has solicitado {accion_str}.\n\nPor favor, escribe tu contraseña de administrador para confirmar:")

    except Exception:
        pass # Ignoramos errores leves de red para no frenar el bot

def registrar_datos_csv(activo, precio, rsi, slope, accion, saldo):
    archivo = 'historial_operaciones.csv'
    cabecera = ['Fecha', 'Activo', 'Precio', 'RSI', 'Slope', 'Accion', 'Saldo_Actual']
    datos = [datetime.now().strftime('%Y-%m-%d %H:%M:%S'), activo, precio, round(rsi, 2), round(slope, 2), accion, round(saldo, 2)]
    
    if not os.path.exists(archivo):
        with open(archivo, 'w', newline='') as f:
            csv.writer(f).writerow(cabecera)
    with open(archivo, 'a', newline='') as f:
        csv.writer(f).writerow(datos)

# --- 3. LÓGICA DE TRADING ---

def execute_trade(exchange, symbol, side, price):
    try:
        # A. CALCULAR TAMAÑO
        balance = float(exchange.fetch_balance()['total']['USDT'])
        amount_usd = balance * RISK_PER_TRADE * LEVERAGE 
        if amount_usd < 12: amount_usd = 12
        amount_crypto = amount_usd / price
        
        try: exchange.set_leverage(LEVERAGE, symbol)
        except: pass
            
        # B. ENTRAR AL MERCADO
        tipo_operacion = "LONG 🟢" if side == 'buy' else "SHORT 🔴"
        print(f"🚀 Ejecutando {tipo_operacion} en {symbol}...")
        
        order = exchange.create_market_order(symbol, side, amount_crypto)
        entry_price = float(order['average']) if order['average'] else price
        amount_filled = float(order['filled'])
        
        msg = f"🚀 {tipo_operacion} EN {symbol}\nEntrada: {entry_price}\nInversión: ${round(amount_usd, 2)}"
        send_telegram_alert(msg)
        registrar_datos_csv(symbol, entry_price, 0, 0, f"ENTRY {side.upper()}", balance)

        # C. CÁLCULO DE SALIDAS
        if side == 'buy':
            tp_price = entry_price * (1 + TAKE_PROFIT_PCT)
            sl_price = entry_price * (1 - STOP_LOSS_PCT)
            exit_side = 'sell'
        else:
            tp_price = entry_price * (1 - TAKE_PROFIT_PCT)
            sl_price = entry_price * (1 + STOP_LOSS_PCT)
            exit_side = 'buy'

        tp_price = float(exchange.price_to_precision(symbol, tp_price))
        sl_price = float(exchange.price_to_precision(symbol, sl_price))

        # D. COLOCAR TRAMPAS DE SALIDA
        exchange.create_order(symbol, 'LIMIT', exit_side, amount_filled, tp_price, params={'reduceOnly': True})
        exchange.create_order(symbol, 'STOP_MARKET', exit_side, amount_filled, params={'stopPrice': sl_price, 'reduceOnly': True})

        send_telegram_alert(f"🛡️ Protecciones ({symbol}):\nTP: {tp_price}\nSL: {sl_price}")
        
    except Exception as e:
        msg = f"❌ Error operando {symbol}: {e}"
        print(msg)
        send_telegram_alert(msg)

def analizar_activo(exchange, symbol):
    try:
        # --- PARCHE DE SEGURIDAD V5.1: Verificar si ya hay posición ---
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            if float(pos['contracts']) > 0:
                print(f"⚠️ Posición abierta en {symbol}. Saltando.")
                return 

        # 1. Obtener Datos
        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=1000)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 2. Indicadores
        df['EMA_200'] = ta.ema(df['close'], length=200)
        df['RSI'] = ta.rsi(df['close'], length=14)
        df['EMA_Slope'] = df['EMA_200'] - df['EMA_200'].shift(5)
        
        current = df.iloc[-2]
        precio = current['close']
        rsi = current['RSI']
        slope = current['EMA_Slope']
        balance = float(exchange.fetch_balance()['total']['USDT'])

        print(f"[{datetime.now().strftime('%H:%M')}] {symbol} | RSI: {round(rsi, 2)} | Slope: {round(slope, 2)}")
        
        # 3. Detectar Oportunidades
        long_cond = (precio > current['EMA_200']) and (rsi < 33) and (slope > 0)
        short_cond = (precio < current['EMA_200']) and (rsi > 67) and (slope < 0)

        if long_cond or short_cond:
            direccion = 'buy' if long_cond else 'sell'
            
            # --- INTELIGENCIA ARTIFICIAL ---
            nombre_activo = "Bitcoin"
            if "ETH" in symbol: nombre_activo = "Ethereum"
            if "SOL" in symbol: nombre_activo = "Solana"
            if "XAU" in symbol: nombre_activo = "Gold"
            
            print(f"--- 🧠 Analizando noticias de {nombre_activo}... ---")
            score = brain_ia.get_crypto_sentiment(nombre_activo)
            
            ia_aprueba = False
            if direccion == 'buy' and score >= -0.05: ia_aprueba = True
            if direccion == 'sell' and score <= 0.15: ia_aprueba = True 
            
            if ia_aprueba:
                print(f"✅ IA APRUEBA (Score: {round(score, 3)}).")
                execute_trade(exchange, symbol, direccion, precio)
            else:
                print(f"🛑 IA DETUVO operación en {symbol} (Score: {round(score, 3)})")

    except Exception as e:
        print(f"⚠️ Error {symbol}: {e}")

# --- VARIABLES GLOBALES PARA RASTREO ---
posiciones_abiertas_rastreo = set()
ganancia_diaria = 0.0
operaciones_exito = 0
operaciones_error = 0

def enviar_resumen_global():
    memoria = cargar_memoria()
    mensaje = (
        f"🌍 *RESUMEN GLOBAL HISTÓRICO*\n\n"
        f"📈 *Ganancia Neta:* {'+' if memoria['ganancia_global'] >= 0 else ''}{memoria['ganancia_global']:.2f} USDT\n"
        f"✅ *Total Éxitos:* {memoria['exitos_globales']}\n"
        f"❌ *Total Errores:* {memoria['errores_globales']}\n"
        f"🔄 *Operaciones Totales:* {memoria['exitos_globales'] + memoria['errores_globales']}"
    )
    send_telegram_alert(mensaje, incluir_botones=True)

def enviar_resumen_diario(resetear=True):
    global ganancia_diaria, operaciones_exito, operaciones_error
    try:
        exchange = initialize_exchange()
        balance = exchange.fetch_balance()
        usdt_total = balance['total'].get('USDT', 0.0)
        usdt_libre = balance['free'].get('USDT', 0.0)
        
        mensaje = (
            f"📊 *RESUMEN DIARIO DE OPERACIONES*\n\n"
            f"💰 *Saldo Total:* {usdt_total:.2f} USDT\n"
            f"🔓 *Saldo Disponible:* {usdt_libre:.2f} USDT\n"
            f"📈 *Ganancia Hoy:* {'+' if ganancia_diaria >= 0 else ''}{ganancia_diaria:.2f} USDT\n"
            f"✅ *Operaciones Ganadas:* {operaciones_exito}\n"
            f"❌ *Operaciones Perdidas (SL):* {operaciones_error}\n"
            f"🔄 *Total Movimientos:* {operaciones_exito + operaciones_error}"
        )
        
        # Solo incluye botones si fue una petición manual (no el resumen de las 10 PM)
        send_telegram_alert(mensaje, incluir_botones=not resetear)
        
        if resetear:
            ganancia_diaria = 0.0
            operaciones_exito = 0
            operaciones_error = 0
    except Exception as e:
        print(f"⚠️ Error al generar resumen: {e}")

def ciclo_maestro():
    global posiciones_abiertas_rastreo, ganancia_diaria, operaciones_exito, operaciones_error, memoria_global
    print(f"--- Escaneando Mercado ---")
    try:
        exchange = initialize_exchange()
        
        # 1. RASTREO DE CIERRES Y ACTUALIZACIÓN DE MEMORIA GLOBAL
        try:
            balance = exchange.fetch_balance()
            posiciones_actuales = balance['info']['positions']
            posiciones_activas_ahora = {p['symbol'] for p in posiciones_actuales if float(p['positionAmt']) != 0}
            
            for simbolo in list(posiciones_abiertas_rastreo):
                if simbolo not in posiciones_activas_ahora:
                    trades = exchange.fetch_my_trades(simbolo, limit=5)
                    if trades:
                        ultimo_pnl = float(trades[-1]['info'].get('realizedPnl', 0))
                        
                        # Actualizar contadores del día
                        ganancia_diaria += ultimo_pnl
                        
                        # Actualizar memoria global (JSON)
                        memoria_global['ganancia_global'] += ultimo_pnl
                        
                        if ultimo_pnl >= 0:
                            operaciones_exito += 1
                            memoria_global['exitos_globales'] += 1
                            icon = "✅"
                        else:
                            operaciones_error += 1
                            memoria_global['errores_globales'] += 1
                            icon = "❌"
                            
                        # Guardar permanentemente
                        guardar_memoria(memoria_global)
                            
                        send_telegram_alert(f"{icon} *Posición Cerrada: {simbolo}*\n💰 PNL: {ultimo_pnl:.2f} USDT", incluir_botones=True)
            
            posiciones_abiertas_rastreo = posiciones_activas_ahora
        except Exception as e:
            print(f"⚠️ Error en rastreo de cierres: {e}")

        # 2. ESCANEO NORMAL
        for moneda in WATCHLIST:
            analizar_activo(exchange, moneda)
            time.sleep(1)

        # 3. IMPRESIÓN DE SALDO EN CONSOLA
        try:
            usdt_total = balance['total'].get('USDT', 0.0)
            usdt_libre = balance['free'].get('USDT', 0.0)
            print(f"💰 Balance Total: {usdt_total:.2f} USDT")
            print(f"🔓 Disponible: {usdt_libre:.2f} USDT")
            print("-" * 30)
        except Exception as e:
            print(f"⚠️ No se pudo imprimir el saldo: {e}")

    except Exception as e:
        print(f"Error de conexión: {e}")

# --- 4. EJECUCIÓN ---
print("--- 🤖 MF1MDB V5.2: KILL SWITCH ACTIVATED ---")
send_telegram_alert("☁️ Bot Iniciado. Sistemas de emergencia activados.", incluir_botones=True)

schedule.every(1).minutes.do(ciclo_maestro)
schedule.every().day.at("22:00").do(enviar_resumen_diario)

while True:
    escuchar_botones_telegram()
    schedule.run_pending()
    time.sleep(1)