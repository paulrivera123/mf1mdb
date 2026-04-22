import ccxt
import pandas as pd
import pandas_ta as ta
from dotenv import load_dotenv
import os

load_dotenv()

# Configuración
ex = ccxt.binance({
    'apiKey': os.getenv('BINANCE_API_KEY'),
    'secret': os.getenv('BINANCE_SECRET_KEY'),
    'options': {'defaultType': 'future'}
})

coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XAU/USDT']

print("--- 🕵️‍♂️ DIAGNÓSTICO DE SEÑALES V2 ---")
print("Reglas SHORT: RSI > 67  AND  Slope < 0")
print("Reglas LONG:  RSI < 33  AND  Slope > 0")
print("-" * 50)

for symbol in coins:
    try:
        # 1. Bajar SUFICIENTES datos (1000 velas)
        ohlcv = ex.fetch_ohlcv(symbol, '15m', limit=1000)
        df = pd.DataFrame(ohlcv, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        
        # 2. Calcular Indicadores
        # EMA 200
        ema_series = ta.ema(df['close'], length=200)
        ema = ema_series.iloc[-1]
        
        # Slope (Pendiente)
        slope = ema - ema_series.iloc[-6]
        
        # RSI 14
        rsi = ta.rsi(df['close'], length=14).iloc[-1]
        
        precio = df['close'].iloc[-1]
        
        # 3. Evaluar Lógica
        cond_short_rsi = rsi > 67
        cond_short_slope = slope < 0
        
        cond_long_rsi = rsi < 33
        cond_long_slope = slope > 0
        
        estado = "😴 DORMIDO (No cumple requisitos)"
        detalle = ""
        
        if cond_short_rsi and cond_short_slope:
            estado = "🔴 SHORT ACTIVO (Debería entrar)"
        elif cond_long_rsi and cond_long_slope:
            estado = "🟢 LONG ACTIVO (Debería entrar)"
        else:
            # Explicar por qué NO entra
            if cond_short_slope and not cond_short_rsi:
                detalle = f"[Falla RSI: {round(rsi, 2)} < 67]"
            elif cond_short_rsi and not cond_short_slope:
                detalle = f"[Falla Slope: {round(slope, 2)} > 0]"
            else:
                detalle = f"[RSI {round(rsi, 2)} neutro]"

        print(f"\n💎 {symbol}:")
        print(f"   Precio: {precio} | EMA200: {round(ema, 2)}")
        print(f"   RSI: {round(rsi, 2)} | Slope: {round(slope, 4)}")
        print(f"   >> {estado} {detalle}")
        
    except Exception as e:
        print(f"❌ Error leyendo {symbol}: {e}")