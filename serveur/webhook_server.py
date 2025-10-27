from flask import Flask, request, jsonify
import os

app = Flask(__name__)

VERIFY_TOKEN = "il_fait_beau_aujourd'hui"  # À personnaliser

@app.route("/webhook", methods=["GET", "POST"])

def webhook():
    if request.method == "GET":
        # Étape de vérification initiale
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return jsonify({"hub.challenge": request.args.get("hub.challenge")})
        else:
            return "Invalid verification token", 403

    if request.method == "POST":
        data = request.json
        if data and data.get("object_type") == "activity" and data.get("aspect_type") == "create":
            activity_id = data["object_id"]
            print(f"Nouvelle activité détectée ! ID : {activity_id}")

            # Lancer le traitement automatique ici
            os.system("python3 RecupDataStrava.py")
            os.system("python3 resume_sorties.py")
            os.system("python3 envoyerGmail.py")

            

        return "OK", 200

if __name__ == "__main__":
    app.run(port=5000)
