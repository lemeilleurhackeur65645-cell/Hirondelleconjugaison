"""
Notification Discord via webhook (aucun bot, aucun OAuth).
Variable d'environnement : DISCORD_WEBHOOK_URL
Minimisation des données : seuls le numéro et le type du ticket sont envoyés.
Ni l'adresse email, ni le sujet, ni le message de l'utilisateur ne quittent le site.
"""
import os

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
SITE_URL = os.environ.get("SITE_URL", "https://hirondelleconjugaison.onrender.com").rstrip("/")


def notifier_nouveau_ticket(ticket, user_email=None, premier_message=None):
    if not DISCORD_WEBHOOK_URL:
        print(f"[DISCORD SIMULÉ] Nouveau ticket #{ticket.id}", flush=True)
        return
    import requests
    icone = "☎️" if ticket.type == "bug" else "💡"
    contenu = f"{icone} Nouveau {ticket.type} — #{ticket.id}\n🔗 {SITE_URL}/admin/tickets"
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": contenu}, timeout=10)
    except Exception as e:
        print(f"[ATTENTION] Échec notification Discord : {e}", flush=True)
