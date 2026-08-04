"""
Notification Discord via webhook — pas besoin de bot ni d'OAuth.
Variable d'environnement requise : DISCORD_WEBHOOK_URL
"""
import os

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def notifier_nouveau_ticket(ticket, user_email, premier_message):
    if not DISCORD_WEBHOOK_URL:
        print(f"[DISCORD SIMULÉ] Nouveau ticket #{ticket.id} de {user_email}", flush=True)
        return

    import requests
    icone = "🐛" if ticket.type == "bug" else "💡"
    contenu = (
        f"{icone} **Nouveau {ticket.type}** — #{ticket.id}\n"
        f"**De :** {user_email}\n"
        f"**Sujet :** {ticket.sujet}\n"
        f"**Message :** {premier_message[:500]}\n"
        f"🔗 https://hirondelleconjugaison.onrender.com/admin/tickets"
    )
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": contenu}, timeout=10)
    except Exception as e:
        print(f"[ATTENTION] Échec notification Discord : {e}", flush=True)
