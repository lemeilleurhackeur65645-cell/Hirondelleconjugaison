"""
Vérification d'email et réinitialisation de mot de passe — Hirondelle Conjugaison.

Service d'envoi : Resend (resend.com). Choisi à la place de Brevo car Resend
ne demande pas de numéro de téléphone pour créer un compte — seulement une
adresse email. Quota gratuit : 100 emails/jour.

Sécurité appliquée :
- Code à 6 chiffres, expirant après 15 minutes.
- Anti brute-force : 5 tentatives max par code, au-delà le code est invalidé.
- Anti-spam d'envoi : on ne génère pas un nouveau code si un code valide
  existe déjà depuis moins de 60 secondes (empêche de spammer le bouton
  "renvoyer le code" et de saturer le quota d'envoi Resend).
- Le mot de passe n'est JAMAIS stocké en clair, même temporairement : il est
  haché avant d'être mis dans CodeVerification.password_hash_en_attente.
"""

import os
import random
import string
from datetime import datetime, timezone, timedelta

DUREE_VALIDITE_MINUTES = 15
MAX_TENTATIVES = 5
DELAI_RENVOI_SECONDES = 60

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
# Par défaut : domaine de test fourni par Resend, qui fonctionne sans
# configuration DNS — pratique pour démarrer. Une fois un nom de domaine
# personnalisé vérifié dans Resend, définir EMAIL_EXPEDITEUR sur Render
# avec une adresse de ce domaine (ex: "noreply@hirondelleconjugaison.fr").
EMAIL_EXPEDITEUR = os.environ.get("EMAIL_EXPEDITEUR", "Hirondelle Conjugaison <onboarding@resend.dev>")


def generer_code():
    return "".join(random.choices(string.digits, k=6))


def envoyer_email(destinataire, sujet, contenu_html):
    """
    Envoie un email via l'API Resend. Retourne (succes: bool, erreur: str|None).

    Si RESEND_API_KEY n'est pas configurée, n'envoie rien mais affiche le
    contenu dans les logs serveur — utile pour tester le flux complet
    avant d'avoir branché un vrai service d'email.
    """
    if not RESEND_API_KEY:
        print(f"[EMAIL SIMULÉ — RESEND_API_KEY absente] À: {destinataire} | Sujet: {sujet}", flush=True)
        print(f"[EMAIL SIMULÉ] Contenu: {contenu_html}", flush=True)
        return True, None

    import requests
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": EMAIL_EXPEDITEUR,
                "to": [destinataire],
                "subject": sujet,
                "html": contenu_html,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return True, None
        return False, f"Resend a répondu {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


def _template_email(titre, message_principal, code):
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px 24px;">
      <h2 style="color:#0f172a;margin:0 0 8px;">{titre}</h2>
      <p style="color:#475569;font-size:14px;line-height:1.6;">{message_principal}</p>
      <div style="background:#eff6ff;border-radius:12px;padding:20px;text-align:center;margin:20px 0;">
        <span style="font-size:32px;font-weight:800;letter-spacing:6px;color:#007bff;">{code}</span>
      </div>
      <p style="color:#94a3b8;font-size:12px;">Ce code expire dans {DUREE_VALIDITE_MINUTES} minutes.
      Si tu n'es pas à l'origine de cette demande, ignore simplement cet email.</p>
    </div>
    """


def creer_code_inscription(db, email, nom, password_hash):
    """
    Crée (ou réutilise si trop récent) un code de confirmation d'inscription.
    Ne crée PAS encore l'utilisateur — ça n'arrive qu'à la validation du code.

    Retourne (code_envoye: bool, message: str).
    """
    from models import CodeVerification

    # Anti-spam : si un code valide existe depuis moins de DELAI_RENVOI_SECONDES, ne pas en renvoyer un nouveau.
    recent = (
        CodeVerification.query
        .filter_by(email=email, type="inscription", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )
    if recent and (datetime.now(timezone.utc) - recent.date_creation.replace(tzinfo=timezone.utc)).total_seconds() < DELAI_RENVOI_SECONDES:
        return False, "Un code a déjà été envoyé récemment. Vérifie tes emails (et tes spams) ou réessaie dans une minute."

    # Invalider les anciens codes en attente pour cet email (un seul code actif à la fois)
    CodeVerification.query.filter_by(email=email, type="inscription", utilise=False).update({"utilise": True})

    code = generer_code()
    entry = CodeVerification(
        email=email, code=code, type="inscription",
        nom_en_attente=nom, password_hash_en_attente=password_hash,
        expire_le=datetime.now(timezone.utc) + timedelta(minutes=DUREE_VALIDITE_MINUTES),
    )
    db.session.add(entry)
    db.session.commit()

    html = _template_email(
        "Confirme ton inscription",
        "Voici ton code de vérification pour activer ton compte Hirondelle Conjugaison :",
        code,
    )
    succes, erreur = envoyer_email(email, "Confirme ton inscription — Hirondelle Conjugaison", html)
    if not succes:
        print(f"[ATTENTION] Échec envoi email inscription à {email} : {erreur}", flush=True)
        return False, "L'envoi de l'email a échoué. Réessaie dans quelques instants."

    return True, "Un code de vérification a été envoyé à ton adresse email."


def valider_code_inscription(db, email, code_saisi):
    """
    Vérifie le code et, si valide, crée réellement l'utilisateur en base.
    Retourne (succes: bool, message: str, user: User|None).
    """
    from models import CodeVerification, User

    entry = (
        CodeVerification.query
        .filter_by(email=email, type="inscription", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )

    if not entry:
        return False, "Aucun code en attente pour cet email. Recommence l'inscription.", None

    if datetime.now(timezone.utc) > entry.expire_le.replace(tzinfo=timezone.utc):
        return False, "Ce code a expiré. Demande un nouveau code.", None

    if entry.tentatives >= MAX_TENTATIVES:
        return False, "Trop de tentatives. Demande un nouveau code.", None

    if entry.code != code_saisi.strip():
        entry.tentatives += 1
        db.session.commit()
        restantes = MAX_TENTATIVES - entry.tentatives
        return False, f"Code incorrect. {restantes} tentative(s) restante(s).", None

    # Code valide : créer le compte maintenant, et marquer le code comme utilisé
    if User.query.filter_by(email=email).first():
        entry.utilise = True
        db.session.commit()
        return False, "Un compte existe déjà avec cet email.", None

    user = User(
        email=email,
        nom=entry.nom_en_attente,
        password_hash=entry.password_hash_en_attente,
        methode_connexion="email",
        email_verifie=True,
    )
    entry.utilise = True
    db.session.add(user)
    db.session.commit()

    return True, "Compte créé et vérifié avec succès !", user


def creer_code_reset_password(db, email):
    """
    Crée un code de réinitialisation de mot de passe pour un compte EXISTANT.
    Ne révèle jamais si l'email existe ou non dans le message retourné
    (sinon ça permettrait de deviner quels emails sont inscrits).
    """
    from models import CodeVerification, User

    message_neutre = "Si un compte existe avec cet email, un code de réinitialisation vient d'être envoyé."

    user = User.query.filter_by(email=email).first()
    if not user or user.methode_connexion != "email":
        # Compte inexistant, ou compte OAuth qui n'a pas de mot de passe local
        # à réinitialiser — dans les deux cas, même message neutre, pas d'envoi.
        return True, message_neutre

    recent = (
        CodeVerification.query
        .filter_by(email=email, type="reset_password", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )
    if recent and (datetime.now(timezone.utc) - recent.date_creation.replace(tzinfo=timezone.utc)).total_seconds() < DELAI_RENVOI_SECONDES:
        return True, message_neutre  # toujours neutre, même si on ne renvoie rien

    CodeVerification.query.filter_by(email=email, type="reset_password", utilise=False).update({"utilise": True})

    code = generer_code()
    entry = CodeVerification(
        email=email, code=code, type="reset_password",
        expire_le=datetime.now(timezone.utc) + timedelta(minutes=DUREE_VALIDITE_MINUTES),
    )
    db.session.add(entry)
    db.session.commit()

    html = _template_email(
        "Réinitialise ton mot de passe",
        "Voici ton code pour choisir un nouveau mot de passe sur Hirondelle Conjugaison :",
        code,
    )
    envoyer_email(email, "Réinitialisation de mot de passe — Hirondelle Conjugaison", html)
    return True, message_neutre


def valider_code_et_changer_password(db, bcrypt, email, code_saisi, nouveau_password):
    from models import CodeVerification, User

    entry = (
        CodeVerification.query
        .filter_by(email=email, type="reset_password", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )
    if not entry:
        return False, "Aucune demande de réinitialisation en attente pour cet email."

    if datetime.now(timezone.utc) > entry.expire_le.replace(tzinfo=timezone.utc):
        return False, "Ce code a expiré. Recommence la procédure."

    if entry.tentatives >= MAX_TENTATIVES:
        return False, "Trop de tentatives. Recommence la procédure."

    if entry.code != code_saisi.strip():
        entry.tentatives += 1
        db.session.commit()
        restantes = MAX_TENTATIVES - entry.tentatives
        return False, f"Code incorrect. {restantes} tentative(s) restante(s)."

    user = User.query.filter_by(email=email).first()
    if not user:
        return False, "Compte introuvable."

    user.password_hash = bcrypt.generate_password_hash(nouveau_password).decode("utf-8")
    entry.utilise = True
    db.session.commit()

    return True, "Mot de passe mis à jour. Tu peux te connecter."
