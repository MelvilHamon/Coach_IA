import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from appelChat import obtenir_conseils

load_dotenv()

expediteur = os.getenv("GMAIL_EXPEDITEUR")
mot_de_passe = os.getenv("GMAIL_MOT_DE_PASSE")
destinataire = os.getenv("GMAIL_DESTINATAIRE")

sujet = "🏃 Revue et conseil de ta sortie par IA"
contenu = obtenir_conseils()

message = MIMEMultipart()
message["From"] = expediteur
message["To"] = destinataire
message["Subject"] = sujet
message.attach(MIMEText(contenu, "plain"))

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(expediteur, mot_de_passe)
        server.sendmail(expediteur, destinataire, message.as_string())
    print("📤 Mail envoyé avec succès !")
except Exception as e:
    print("❌ Échec de l'envoi :", e)
