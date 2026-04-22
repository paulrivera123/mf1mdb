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
import hashlib
from dotenv import load_dotenv
from datetime import datetime

# =============================================================================
# 1. CONFIGURACIÓN Y CLAVES
# =============================================================================
load_dotenv()
API_KEY       = os.getenv('BINANCE_API_KEY')
SECRET_KEY    = os.getenv('BINANCE_SECRET_KEY')
ADMIN_PW_HASH = os.getenv('BOT_PASSWORD_HASH')  # SHA-256 de la contraseña
TELEGRAM_TOKEN   = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- WATCHLIST DEPURADO (eliminados LTC, BCH, POL por PNL histórico negativo) ---
WATCHLIST = [
    'BTC/USDT',  'ETH/USDT',  'SOL/USDT',  'BNB/USDT',        # Majors
    'ADA/USDT',  'AVAX/USDT', 'DOT/USDT',  'LINK/USDT',        # Ecosistemas
    'XRP/USDT',  'NEAR/USDT', 'XLM/USDT',                      # Pagos y velocidad
    'DOGE/USDT', '1000SHIB/USDT', '1000PEPE/USDT',             # Volatilidad
    'FET/USDT',  'RENDER/USDT'                                  # IA
]

TIMEFRAME        = '15m'
LEVERAGE         = 10
RISK_PER_TRADE   = 0.02    # 2% del balance por operación
STOP_LOSS_PCT    = 0.025   # SL inicial: 2.5% (se activa solo si el trailing no llega a tiempo)
TRAILING_RATE    = 2.5     # Callback rate del Trailing Stop nativo de Binance (%)
                           # Binance acepta 0.1% – 5.0%

# =============================================================================
# 2. EXCHANGE — SINGLETON (una sola conexión, no una nueva cada minuto)
# =============================================================================
_exchange_instance = None

def get_exchange():
    """Devuelve la instancia del exchange, creándola solo la primera vez."""
    global _exchange_instance
    if _exchange_instance is None:
        _exchange_instance = ccxt.binance({
            'apiKey': API_KEY,
            'secret': SECRET_KEY,
            'options': {'defaultType': 'future'},
            'enableRateLimit': True,
        })
    return _exchange_instance

# =============================================================================
# 3. MEMORIA Y LOGGING
# =============================================================================
ARCHIVO_MEMORIA = "historial_bot.json"
ARCHIVO_CSV     = "historial_operaciones.csv"

def cargar_memoria() -> dict:
    if os.path.exists(ARCHIVO_MEMORIA):
        with open(ARCHIVO_MEMORIA, 'r') as f:
            return json.load(f)
    return {"ganancia_global": 0.0, "exitos_globales": 0, "errores_globales": 0}

def guardar_memoria(datos: dict):
    with open(ARCHIVO_MEMORIA, 'w') as f:
        json.dump(datos, f, indent=2)

memoria_global = cargar_memoria()

def registrar_datos_csv(activo, precio, rsi, slope, accion, saldo):
    """
    Registra operación en CSV con RSI y Slope reales.
    Bug corregido: antes siempre guardaba RSI=0 y Slope=0.
    """
    cabecera = ['Fecha', 'Activo', 'Precio', 'RSI', 'Slope', 'Accion', 'Saldo_Actual']
    datos = [
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        activo,
        precio,
        round(float(rsi), 2),    # Valor real, no hardcodeado
        round(float(slope), 4),  # Valor real, no hardcodeado
        accion,
        round(saldo, 2)
    ]
    if not os.path.exists(ARCHIVO_CSV):
        with open(ARCHIVO_CSV, 'w', newline='') as f:
            csv.writer(f).writerow(cabecera)
    with open(ARCHIVO_CSV, 'a', newline='') as f:
        csv.writer(f).writerow(datos)

# =============================================================================
# 4. TELEGRAM
# =============================================================================
ultimo_update_id = 0

# Estado del Kill Switch
estado_seguridad = {
    "esperando_password": False,
    "accion_pendiente": "",
    "chat_id_esperando": None,
    "intentos_fallidos": 0,
    "bloqueado_hasta": 0,   # timestamp unix; si > now(), rechazar sin verificar
}

def _verificar_password(texto: str) -> bool:
    """
    Compara usando SHA-256 almacenado en .env (BOT_PASSWORD_HASH).
    Nunca compara texto plano. Rate-limiting de 3 intentos antes de bloqueo.
    
    Para generar el hash inicial ejecuta en terminal:
        python3 -c "import hashlib; print(hashlib.sha256(b'TU_CLAVE').hexdigest())"
    y guarda el resultado en .env como BOT_PASSWORD_HASH=...
    """
    if not ADMIN_PW_HASH:
        return False
    ingresado = hashlib.sha256(texto.encode()).hexdigest()
    return ingresado == ADMIN_PW_HASH

def send_telegram_alert(mensaje: str, incluir_botones: bool = False):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    if incluir_botones:
        payload["reply_markup"] = json.dumps({
            "inline_keyboard": [
                [{"text": "📊 Resumen de Hoy",  "callback_data": "btn_hoy"},
                 {"text": "🌍 Resumen Global",  "callback_data": "btn_global"}],
                [{"text": "🛑 Vender todo",      "callback_data": "btn_vender"},
                 {"text": "☠️ Desactivar bot",   "callback_data": "btn_apagar"}]
            ]
        })
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

def _borrar_mensaje_telegram(chat_id, mensaje_id):
    """Elimina el mensaje con la contraseña del historial de Telegram."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage",
            json={"chat_id": chat_id, "message_id": mensaje_id},
            timeout=5
        )
    except Exception:
        pass

def escuchar_botones_telegram():
    global ultimo_update_id, estado_seguridad
    if not TELEGRAM_TOKEN:
        return

    url    = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {"offset": ultimo_update_id + 1, "timeout": 1}

    try:
        respuesta = requests.get(url, params=params, timeout=5).json()
    except Exception:
        return

    if not respuesta.get("ok"):
        return

    for resultado in respuesta["result"]:
        ultimo_update_id = resultado["update_id"]

        # --- A. Captura de contraseña ---
        if "message" in resultado and "text" in resultado["message"]:
            chat_id    = resultado["message"]["chat"]["id"]
            mensaje_id = resultado["message"]["message_id"]
            texto      = resultado["message"]["text"]

            if (estado_seguridad["esperando_password"]
                    and str(chat_id) == str(estado_seguridad["chat_id_esperando"])):

                _borrar_mensaje_telegram(chat_id, mensaje_id)

                # Comprobar bloqueo temporal
                if time.time() < estado_seguridad["bloqueado_hasta"]:
                    minutos = int((estado_seguridad["bloqueado_hasta"] - time.time()) / 60) + 1
                    send_telegram_alert(f"⏳ Demasiados intentos. Espera {minutos} min.")
                    continue

                if _verificar_password(texto):
                    # Reset estado ANTES de ejecutar para evitar doble ejecución
                    estado_seguridad["esperando_password"]  = False
                    estado_seguridad["accion_pendiente_tmp"] = estado_seguridad["accion_pendiente"]
                    estado_seguridad["accion_pendiente"]    = ""
                    estado_seguridad["chat_id_esperando"]   = None
                    estado_seguridad["intentos_fallidos"]   = 0

                    send_telegram_alert("✅ Contraseña verificada. Ejecutando protocolo...")
                    exito, msj = cerrar_todas_las_posiciones()
                    send_telegram_alert(msj)
                    if exito and estado_seguridad["accion_pendiente_tmp"] == "apagar":
                        send_telegram_alert("🔌 Bot detenido. Reinicia el proceso manualmente.")
                        _solicitar_apagado()
                else:
                    # NO reseteamos estado — seguimos esperando la contraseña correcta
                    estado_seguridad["intentos_fallidos"] += 1
                    restantes = 3 - estado_seguridad["intentos_fallidos"]
                    if restantes <= 0:
                        estado_seguridad["bloqueado_hasta"]    = time.time() + 900
                        estado_seguridad["esperando_password"] = False
                        estado_seguridad["accion_pendiente"]   = ""
                        estado_seguridad["chat_id_esperando"]  = None
                        send_telegram_alert("🔒 Demasiados intentos. Kill Switch bloqueado 15 minutos.")
                    else:
                        send_telegram_alert(f"❌ Contraseña incorrecta. Intentos restantes: {restantes}")

        # --- B. Captura de botones ---
        if "callback_query" in resultado:
            datos_boton       = resultado["callback_query"]["data"]
            chat_id           = resultado["callback_query"]["message"]["chat"]["id"]
            callback_query_id = resultado["callback_query"]["id"]

            # Responder callback para quitar el estado "cargando" del boton
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                    json={"callback_query_id": callback_query_id},
                    timeout=5
                )
            except Exception:
                pass

            if datos_boton == "btn_hoy":
                enviar_resumen_diario(resetear=False)
            elif datos_boton == "btn_global":
                enviar_resumen_global()
            elif datos_boton in ["btn_vender", "btn_apagar"]:
                estado_seguridad["esperando_password"]  = True
                estado_seguridad["accion_pendiente"]    = "apagar" if datos_boton == "btn_apagar" else "vender"
                estado_seguridad["chat_id_esperando"]   = chat_id
                estado_seguridad["intentos_fallidos"]   = 0
                accion_str = "Vender Todo" if datos_boton == "btn_vender" else "Desactivar Bot"
                send_telegram_alert(
                    f"ALERTA: Has solicitado *{accion_str}*\n\nEscribe tu contrasena de administrador:"
                )

# Bandera global de apagado (alternativa segura a sys.exit)
_apagar_bot = False

def _solicitar_apagado():
    global _apagar_bot
    _apagar_bot = True

# =============================================================================
# 5. GESTIÓN DE POSICIONES
# =============================================================================

def cerrar_todas_las_posiciones():
    try:
        exchange  = get_exchange()
        posiciones = exchange.fetch_positions()
        cerradas  = 0
        for pos in posiciones:
            amt    = float(pos['info']['positionAmt'])
            symbol = pos['symbol']
            if amt != 0:
                side = 'sell' if amt > 0 else 'buy'
                exchange.create_order(
                    symbol, 'market', side, abs(amt),
                    params={'reduceOnly': True}
                )
                cerradas += 1
        return True, f"✅ {cerradas} posición(es) cerradas a precio de mercado."
    except Exception as e:
        return False, f"❌ Error cerrando posiciones: {e}"

# =============================================================================
# 6. LÓGICA DE TRADING — TRAILING STOP NATIVO DE BINANCE
# =============================================================================

def execute_trade(exchange, symbol: str, side: str, price: float, rsi: float, slope: float):
    """
    Entra al mercado y coloca:
      1. Un Trailing Stop Market nativo de Binance (callback = TRAILING_RATE %)
         → Binance gestiona el trailing sin necesidad de bucles activos de la API.
      2. Un Stop Loss fijo de respaldo (SL inicial) por si el trailing no se activa
         a tiempo en movimientos bruscos.

    Ya NO hay Take Profit fijo. La posición corre hasta que el trailing la cierra.
    """
    try:
        balance    = float(exchange.fetch_balance()['total']['USDT'])
        amount_usd = max(balance * RISK_PER_TRADE * LEVERAGE, 12)
        amount_crypto = amount_usd / price

        try:
            exchange.set_leverage(LEVERAGE, symbol)
        except Exception:
            pass

        tipo_op = "LONG 🟢" if side == 'buy' else "SHORT 🔴"
        print(f"🚀 Ejecutando {tipo_op} en {symbol}...")

        order        = exchange.create_market_order(symbol, side, amount_crypto)
        entry_price  = float(order.get('average') or price)
        amount_filled = float(order['filled'])

        registrar_datos_csv(symbol, entry_price, rsi, slope, f"ENTRY {side.upper()}", balance)
        send_telegram_alert(
            f"🚀 *{tipo_op} EN {symbol}*\n"
            f"Entrada: `{entry_price}`\n"
            f"Inversión: `${round(amount_usd, 2)}`\n"
            f"RSI: `{round(rsi, 1)}` | Slope: `{round(slope, 4)}`"
        )

        exit_side = 'sell' if side == 'buy' else 'buy'

        # --- A. TRAILING STOP MARKET nativo de Binance ---
        # callbackRate: porcentaje de retroceso desde el máximo/mínimo alcanzado.
        # Binance lo activa automáticamente. No requiere polling.
        try:
            exchange.create_order(
                symbol,
                'TRAILING_STOP_MARKET',
                exit_side,
                amount_filled,
                params={
                    'callbackRate': TRAILING_RATE,  # e.g. 1.5 = 1.5%
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',    # más estable que LAST_PRICE
                }
            )
            send_telegram_alert(
                f"📈 *Trailing Stop activado ({symbol})*\n"
                f"Callback: `{TRAILING_RATE}%` sobre precio máximo alcanzado\n"
                f"Sin límite de ganancia."
            )
        except Exception as e_trailing:
            # Si el trailing falla (e.g. par no soportado), lo notificamos
            send_telegram_alert(f"⚠️ Trailing Stop falló en {symbol}: {e_trailing}")

        # --- B. STOP LOSS FIJO DE RESPALDO ---
        # Protege contra gaps o movimientos instantáneos donde el trailing
        # no llega a ajustarse.
        if side == 'buy':
            sl_price = entry_price * (1 - STOP_LOSS_PCT)
        else:
            sl_price = entry_price * (1 + STOP_LOSS_PCT)

        sl_price = float(exchange.price_to_precision(symbol, sl_price))

        try:
            exchange.create_order(
                symbol,
                'STOP_MARKET',
                exit_side,
                amount_filled,
                params={
                    'stopPrice': sl_price,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',
                }
            )
            send_telegram_alert(
                f"🛡️ *SL de respaldo ({symbol})*\n"
                f"Stop Loss: `{sl_price}`"
            )
        except Exception as e_sl:
            send_telegram_alert(f"⚠️ SL de respaldo falló en {symbol}: {e_sl}")

    except Exception as e:
        msg = f"❌ Error operando {symbol}: {e}"
        print(msg)
        send_telegram_alert(msg)

def analizar_activo(exchange, symbol: str):
    """
    Señal de entrada: EMA200 + RSI14 + Slope de EMA.
    brain_ia.py eliminado: latencia alta, precisión insuficiente para 15m.
    """
    try:
        # Verificar posición abierta
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            if float(pos['contracts']) > 0:
                print(f"⚠️  Posición abierta en {symbol}. Saltando.")
                return

        ohlcv = exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=250)
        df    = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        df['EMA_200']   = ta.ema(df['close'], length=200)
        df['RSI']       = ta.rsi(df['close'], length=14)
        df['EMA_Slope'] = df['EMA_200'] - df['EMA_200'].shift(5)

        current = df.iloc[-2]   # Vela cerrada, no la actual
        precio  = current['close']
        rsi     = current['RSI']
        slope   = current['EMA_Slope']
        ema200  = current['EMA_200']

        # Validar que los indicadores no son NaN
        if pd.isna(rsi) or pd.isna(slope) or pd.isna(ema200):
            return

        print(f"[{datetime.now().strftime('%H:%M')}] {symbol:20s} | "
              f"RSI: {round(rsi, 1):5.1f} | "
              f"Slope: {round(slope, 4):8.4f} | "
              f"Precio: {precio}")

        long_cond  = (precio > ema200) and (rsi < 33) and (slope > 0)
        short_cond = (precio < ema200) and (rsi > 67) and (slope < 0)

        if long_cond:
            execute_trade(exchange, symbol, 'buy',  precio, rsi, slope)
        elif short_cond:
            execute_trade(exchange, symbol, 'sell', precio, rsi, slope)

    except Exception as e:
        print(f"⚠️  Error analizando {symbol}: {e}")

# =============================================================================
# 7. RESÚMENES Y RASTREO
# =============================================================================
posiciones_abiertas_rastreo: set = set()
ganancia_diaria    = 0.0
operaciones_exito  = 0
operaciones_error  = 0

def enviar_resumen_global():
    mem = cargar_memoria()
    total_ops = mem['exitos_globales'] + mem['errores_globales']
    winrate   = (mem['exitos_globales'] / total_ops * 100) if total_ops > 0 else 0
    send_telegram_alert(
        f"🌍 *RESUMEN GLOBAL HISTÓRICO*\n\n"
        f"📈 *Ganancia Neta:* `{'+' if mem['ganancia_global'] >= 0 else ''}{mem['ganancia_global']:.2f} USDT`\n"
        f"✅ *Éxitos:* `{mem['exitos_globales']}`\n"
        f"❌ *Errores:* `{mem['errores_globales']}`\n"
        f"🎯 *Win Rate:* `{winrate:.1f}%`\n"
        f"🔄 *Total Ops:* `{total_ops}`",
        incluir_botones=True
    )

def enviar_resumen_diario(resetear: bool = True):
    global ganancia_diaria, operaciones_exito, operaciones_error
    try:
        exchange  = get_exchange()
        balance   = exchange.fetch_balance()
        usdt_total = balance['total'].get('USDT', 0.0)
        usdt_libre = balance['free'].get('USDT', 0.0)
        total_dia  = operaciones_exito + operaciones_error
        winrate_dia = (operaciones_exito / total_dia * 100) if total_dia > 0 else 0

        send_telegram_alert(
            f"📊 *RESUMEN DIARIO*\n\n"
            f"💰 *Saldo Total:* `{usdt_total:.2f} USDT`\n"
            f"🔓 *Disponible:* `{usdt_libre:.2f} USDT`\n"
            f"📈 *Ganancia Hoy:* `{'+' if ganancia_diaria >= 0 else ''}{ganancia_diaria:.2f} USDT`\n"
            f"✅ *Ganadas:* `{operaciones_exito}`\n"
            f"❌ *Perdidas:* `{operaciones_error}`\n"
            f"🎯 *Win Rate Hoy:* `{winrate_dia:.1f}%`",
            incluir_botones=not resetear
        )
        if resetear:
            ganancia_diaria   = 0.0
            operaciones_exito = 0
            operaciones_error = 0
    except Exception as e:
        print(f"⚠️  Error en resumen diario: {e}")

# =============================================================================
# 8. CICLO MAESTRO
# =============================================================================

def ciclo_maestro():
    global posiciones_abiertas_rastreo, ganancia_diaria
    global operaciones_exito, operaciones_error, memoria_global

    print(f"\n{'='*40}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Escaneando mercado...")

    try:
        exchange = get_exchange()

        # --- RASTREO DE CIERRES ---
        try:
            balance_info      = exchange.fetch_balance()
            posiciones_raw    = balance_info['info']['positions']
            posiciones_activas = {
                p['symbol'] for p in posiciones_raw
                if float(p['positionAmt']) != 0
            }

            for simbolo in list(posiciones_abiertas_rastreo):
                if simbolo not in posiciones_activas:
                    # La posición se cerró; buscar el PNL realizado
                    try:
                        trades     = exchange.fetch_my_trades(simbolo, limit=5)
                        ultimo_pnl = float(trades[-1]['info'].get('realizedPnl', 0)) if trades else 0

                        ganancia_diaria      += ultimo_pnl
                        memoria_global['ganancia_global'] += ultimo_pnl

                        if ultimo_pnl >= 0:
                            operaciones_exito += 1
                            memoria_global['exitos_globales'] += 1
                            icon = "✅"
                        else:
                            operaciones_error += 1
                            memoria_global['errores_globales'] += 1
                            icon = "❌"

                        guardar_memoria(memoria_global)
                        send_telegram_alert(
                            f"{icon} *Cerrada: {simbolo}*\n"
                            f"💰 PNL: `{'+' if ultimo_pnl >= 0 else ''}{ultimo_pnl:.2f} USDT`",
                            incluir_botones=True
                        )
                    except Exception as e_pnl:
                        print(f"⚠️  Error obteniendo PNL de {simbolo}: {e_pnl}")

            posiciones_abiertas_rastreo = posiciones_activas

        except Exception as e_rastreo:
            print(f"⚠️  Error en rastreo de cierres: {e_rastreo}")

        # --- ESCANEO DE ACTIVOS ---
        for moneda in WATCHLIST:
            analizar_activo(exchange, moneda)
            time.sleep(0.5)   # Reducido de 1s; el rate limit de ccxt ya lo gestiona

        # --- SALDO EN CONSOLA ---
        try:
            usdt_total = exchange.fetch_balance()['total'].get('USDT', 0.0)
            usdt_libre = exchange.fetch_balance()['free'].get('USDT', 0.0)
            print(f"💰 Balance: {usdt_total:.2f} USDT | Disponible: {usdt_libre:.2f} USDT")
        except Exception:
            pass

    except Exception as e:
        err = f"❌ Error de conexión en ciclo maestro: {e}"
        print(err)
        send_telegram_alert(err)

# =============================================================================
# 9. ARRANQUE
# =============================================================================
if __name__ == "__main__":
    print("=" * 50)
    print("  🤖  MF1MDB V6.0 — TRAILING STOP EDITION")
    print("=" * 50)
    print(f"  Activos monitoreados: {len(WATCHLIST)}")
    print(f"  Timeframe:            {TIMEFRAME}")
    print(f"  Apalancamiento:       {LEVERAGE}x")
    print(f"  Riesgo por op:        {RISK_PER_TRADE*100}%")
    print(f"  Trailing callback:    {TRAILING_RATE}%")
    print(f"  SL de respaldo:       {STOP_LOSS_PCT*100}%")
    print("=" * 50)

    # Validar variables de entorno críticas
    faltantes = [v for v in ['BINANCE_API_KEY', 'BINANCE_SECRET_KEY',
                              'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID',
                              'BOT_PASSWORD_HASH'] if not os.getenv(v)]
    if faltantes:
        print(f"⛔  Variables de entorno faltantes: {', '.join(faltantes)}")
        print("   Agrega estas variables a tu archivo .env y reinicia.")
        sys.exit(1)

    send_telegram_alert(
        "☁️ *Bot V6.0 iniciado.*\n"
        f"Watchlist: `{len(WATCHLIST)}` activos | "
        f"Trailing Stop: `{TRAILING_RATE}%`",
        incluir_botones=True
    )

    schedule.every(1).minutes.do(ciclo_maestro)
    schedule.every().day.at("22:00").do(enviar_resumen_diario)

    while not _apagar_bot:
        escuchar_botones_telegram()
        schedule.run_pending()
        time.sleep(1)

    # Llegamos aquí solo si Kill Switch solicitó apagado limpio
    print("🔌 Apagado limpio solicitado. Bot detenido.")
