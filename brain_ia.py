from GoogleNews import GoogleNews
from textblob import TextBlob
import time

def get_crypto_sentiment(asset_name):
    """
    Busca noticias recientes sobre el activo y calcula su sentimiento.
    Rango: -1 (Muy Negativo) a +1 (Muy Positivo).
    """
    try:
        # 1. Configurar el Buscador de Noticias
        googlenews = GoogleNews()
        googlenews.set_lang('en')        # Noticias en Inglés (son más rápidas/precisas)
        googlenews.set_period('1d')      # Últimas 24 horas
        googlenews.set_encode('utf-8')   # Evitar errores de caracteres
        
        # 2. Definir búsqueda según el activo (Contexto)
        search_term = f"{asset_name} crypto price"
        if asset_name.lower() in ['gold', 'oro', 'xau']:
            search_term = "Gold price market news"
        
        # 3. Descargar noticias
        # print(f"   🧠 Leyendo noticias sobre: {search_term}...") # (Opcional: Descomentar para ver proceso)
        googlenews.search(search_term)
        results = googlenews.result()
        
        # 4. Analizar Sentimientos
        total_score = 0
        count = 0
        
        # Analizamos los primeros 10 titulares
        for article in results[:10]: 
            title = article['title']
            # Usamos TextBlob para obtener la polaridad (-1 a 1)
            analysis = TextBlob(title)
            score = analysis.sentiment.polarity
            total_score += score
            count += 1
            
        # 5. Calcular Promedio
        if count > 0:
            final_sentiment = total_score / count
            return final_sentiment
        else:
            return 0.0 # Neutral si no hay noticias

    except Exception as e:
        print(f"⚠️ Error en cerebro IA: {e}")
        return 0.0 # Retornar neutral por seguridad