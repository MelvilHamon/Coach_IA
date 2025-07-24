import smtplib
from appelChat import obtenir_conseils  
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Paramètres de l’expéditeur (ton adresse Gmail)
expediteur = "melvil.coach@gmail.com"
mot_de_passe = "prwf jvaq bxdy xgaq"

# Destinataire
destinataire = "melvil.hamon@gmail.com"  # ton adresse perso

# Sujet et contenu
sujet = "🏃 Revue et conseil de ta sorrie par IA"

contenu = obtenir_conseils()  # Appel à la fonction pour obtenir les conseils

# Création de l’e-mail
message = MIMEMultipart()
message["From"] = expediteur
message["To"] = destinataire
message["Subject"] = sujet
message.attach(MIMEText(contenu, "plain"))

# Envoi
try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(expediteur, mot_de_passe)
        server.sendmail(expediteur, destinataire, message.as_string())
    print("📤 Mail envoyé avec succès !")
except Exception as e:
    print("❌ Échec de l'envoi :", e)
