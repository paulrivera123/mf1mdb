import ccxt
import pandas as pd
import time
from datetime import datetime, timedelta

def descargar_datos_historicos(simbolo='BTC/USDT', timeframe='15m', dias=90):
    print(f"--- 📥 INICIANDO DESCARGA: {simbolo} ({timeframe}) ---")
    print(f"Objetivo: Últimos {dias} días para entrenamiento de IA.")
    
    # Usamos Binance en modo público (sin claves por ahora)
    exchange = ccxt.binance({'enableRateLimit': True})
    
    # Calculamos la fecha de inicio
    fecha_inicio = datetime.now() - timedelta(days=dias)
    since = int(fecha_inicio.timestamp() * 1000)
    
    todas_las_velas = []
    
    while True:
        try:
            # Descargamos en bloques de 1000 velas (límite de Binance)
            ohlcv = exchange.fetch_ohlcv(simbolo, timeframe, since, limit=1000)
            
            if len(ohlcv) == 0:
                break
            
            todas_las_velas.extend(ohlcv)
            
            # Actualizamos el tiempo para la siguiente tanda
            ultimo_tiempo = ohlcv[-1][0]
            since = ultimo_tiempo + 1 
            
            # Mostramos progreso
            print(f"Recibidas {len(ohlcv)} velas... (Fecha: {datetime.fromtimestamp(ultimo_tiempo/1000)})")
            
            # Si llegamos al presente, paramos
            if ultimo_tiempo >= datetime.now().timestamp() * 1000:
                break
                
            time.sleep(0.5) # Pausa de seguridad
            
        except Exception as e:
            print(f"Error en la descarga: {e}")
            break

    # Convertimos a formato Excel/Dataframe
    df = pd.DataFrame(todas_las_velas, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # Guardamos el archivo
    nombre_archivo = f"historial_{simbolo.replace('/', '')}_{timeframe}.csv"
    df.to_csv(nombre_archivo, index=False)
    
    print(f"\n✅ ÉXITO TOTAL: Se guardaron {len(df)} registros en '{nombre_archivo}'.")
    return df

if __name__ == "__main__":
    # Ejecutamos la función
    datos = descargar_datos_historicos()
    
    # Mostramos las primeras y últimas filas para verificar
    print("\n--- Muestra de los Datos ---")
    print(datos.tail())