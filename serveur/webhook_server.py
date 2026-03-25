import os
import subprocess
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN")

# Racine du projet (un niveau au-dessus de serveur/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == VERIFY_TOKEN:
            return jsonify({"hub.challenge": request.args.get("hub.challenge")})
        return "Invalid verification token", 403

    if request.method == "POST":
        data = request.json
        if data and data.get("object_type") == "activity" and data.get("aspect_type") == "create":
            activity_id = data["object_id"]
            print(f"Nouvelle activité détectée ! ID : {activity_id}")

            scripts = [
                os.path.join(PROJECT_ROOT, "appelAPIs", "RecupDataStrava.py"),
                os.path.join(PROJECT_ROOT, "analyse", "resume_sorties.py"),
                os.path.join(PROJECT_ROOT, "appelAPIs", "envoieGmail.py"),
            ]
            for script in scripts:
                result = subprocess.run(["python3", script], cwd=PROJECT_ROOT, capture_output=True, text=True)
                if result.returncode != 0:
                    print(f"Erreur dans {script} :\n{result.stderr}")

        return "OK", 200


if __name__ == "__main__":
    app.run(port=5000)
