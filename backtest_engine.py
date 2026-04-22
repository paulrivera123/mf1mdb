import pandas as pd
import pandas_ta as ta

def run_backtest():
    file_path = 'historial_BTCUSDT_15m.csv'
    try:
        df = pd.read_csv(file_path)
    except FileNotFoundError:
        print(f"❌ Error: No encuentro el archivo {file_path}")
        return

    print(f"--- 📊 INICIANDO BACKTEST V3 (Estrategia Sniper) ---")
    
    # --- INDICADORES ---
    df['EMA_200'] = ta.ema(df['close'], length=200)
    df['RSI'] = ta.rsi(df['close'], length=14)
    
    # Calculamos la PENDIENTE de la EMA (¿Está subiendo o bajando?)
    # Comparamos la EMA actual con la de hace 5 velas
    df['EMA_Slope'] = df['EMA_200'] - df['EMA_200'].shift(5)

    balance = 500.0
    position = None
    entry_price = 0.0
    amount = 0.0
    
    wins = 0
    losses = 0
    trades_history = []

    # --- AJUSTES DE RIESGO (Gestión Conservadora) ---
    leverage = 10     
    risk_per_trade = 0.02  # 2% Riesgo
    take_profit_ratio = 2.0 # Ratio 1:2 (Ganar el doble de lo que arriesgas)
    commission = 0.0004 

    for i in range(200, len(df)):
        current = df.iloc[i]
        
        # --- SALIDAS ---
        if position == 'LONG':
            # Stop Loss Dinámico basado en precio de entrada
            sl_price = entry_price * (1 - (risk_per_trade / leverage)) # -2% real en cuenta
            tp_price = entry_price * (1 + ((risk_per_trade * take_profit_ratio) / leverage)) # +4% real en cuenta
            
            if current['low'] <= sl_price:
                exit_price = sl_price
                pnl = (exit_price - entry_price) * amount
                balance += pnl - (exit_price * amount * commission)
                losses += 1
                position = None
                trades_history.append(f"🔴 LOSS | Bal: ${balance:.2f}")
            
            elif current['high'] >= tp_price:
                exit_price = tp_price
                pnl = (exit_price - entry_price) * amount
                balance += pnl - (exit_price * amount * commission)
                wins += 1
                position = None
                trades_history.append(f"🟢 WIN  | Bal: ${balance:.2f}")

        # --- ENTRADAS (LÓGICA MEJORADA) ---
        if position is None:
            # CONDICIONES DE COMPRA (AND estricto):
            # 1. Tendencia: Precio encima de EMA 200
            # 2. Fuerza: La EMA 200 está subiendo (Slope > 0)
            # 3. Gatillo: RSI en sobreventa extrema (< 33)
            
            trend_ok = current['close'] > current['EMA_200']
            slope_ok = current['EMA_Slope'] > 0 # ¡La tendencia debe ser fuerte!
            oversold = current['RSI'] < 33      # Punto exacto de rebote
            
            if trend_ok and slope_ok and oversold:
                position = 'LONG'
                entry_price = current['close']
                position_size_usd = balance * leverage 
                # Ajuste de seguridad: No usar más del 95% del margen
                position_size_usd = position_size_usd * 0.95 
                amount = position_size_usd / entry_price
                balance -= (position_size_usd * commission)

    # --- REPORTE ---
    print("\n" + "="*40)
    print(f"RESULTADOS V3 SNIPER")
    print("="*40)
    print(f"💰 Inicial: $500.00  ->  Final: ${balance:.2f}")
    profit = balance - 500
    print(f"📈 PnL: ${profit:.2f} ({(profit/500)*100:.2f}%)")
    print(f"🏆 Wins: {wins} | ❌ Losses: {losses}")
    if (wins+losses) > 0:
        print(f"🎯 Winrate: {(wins/(wins+losses))*100:.2f}%")
    print("="*40)

if __name__ == "__main__":
    run_backtest()