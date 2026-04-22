import brain_ia

print("--- 🧠 PROBANDO CEREBRO DE NOTICIAS ---")

monedas = ["Bitcoin", "Ethereum", "Solana", "Gold"]

for moneda in monedas:
    score = brain_ia.get_crypto_sentiment(moneda)
    estado = "NEUTRAL 😐"
    if score > 0.05: estado = "POSITIVO 😃"
    if score < -0.05: estado = "NEGATIVO 😨"
    
    print(f"Noticias de {moneda}: {round(score, 4)} -> {estado}")