#!/bin/bash

# === CONFIGURATION ===
CLIENT_ID="167488"
CLIENT_SECRET="e26442f2a6ed4b75903aabd6654c31faf7fb2b0c"
VERIFY_TOKEN="il_fait_beau_aujourd'hui"
PORT=5000

echo "🚀 Lancement du serveur Flask (webhook_server.py)..."
python3 webhook_server.py &

FLASK_PID=$!
sleep 2  # Attendre un peu que Flask démarre

echo "🔁 Lancement de ngrok sur le port $PORT..."
pkill ngrok > /dev/null 2>&1
ngrok http $PORT > /dev/null &

sleep 3  # Attendre que ngrok se connecte

NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | grep -o 'https://[^"]*ngrok-free.app')
echo "🌐 URL publique détectée : $NGROK_URL"

if [ -z "$NGROK_URL" ]; then
  echo "❌ Impossible de récupérer l'URL ngrok. Assure-toi qu'il est bien lancé."
  kill $FLASK_PID
  exit 1
fi

# Supprimer les anciens webhooks
echo "🔍 Suppression des anciens webhooks..."
EXISTING=$(curl -s -X GET "https://www.strava.com/api/v3/push_subscriptions?client_id=$CLIENT_ID&client_secret=$CLIENT_SECRET")
WEBHOOK_ID=$(echo "$EXISTING" | grep -o '"id":[0-9]*' | cut -d: -f2)

if [ -n "$WEBHOOK_ID" ]; then
  curl -s -X DELETE "https://www.strava.com/api/v3/push_subscriptions/$WEBHOOK_ID?client_id=$CLIENT_ID&client_secret=$CLIENT_SECRET" > /dev/null
  echo "✅ Webhook supprimé (ID: $WEBHOOK_ID)."
else
  echo "ℹ️ Aucun webhook actif trouvé."
fi

# Créer un nouveau webhook
echo "➕ Création du nouveau webhook..."
RESPONSE=$(curl -s -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id="$CLIENT_ID" \
  -F client_secret="$CLIENT_SECRET" \
  -F callback_url="$NGROK_URL/webhook" \
  -F verify_token="$VERIFY_TOKEN")

echo "📬 Réponse de Strava :"
echo "$RESPONSE"

echo "✅ Serveur prêt ! En attente de nouvelles activités Strava..."


# Attendre indéfiniment (Ctrl+C pour quitter)
trap "echo '🛑 Interruption détectée. Fermeture propre...'; kill $FLASK_PID; pkill -f ngrok; exit" SIGINT

wait $FLASK_PID
