"""
Vérification d'email, relance rétention, et réinitialisation de mot de passe.
Envoi via EmailJS (API HTTPS) — EmailJS relaie l'envoi depuis SES serveurs
vers Gmail (connecté par OAuth dans le tableau de bord EmailJS), donc aucune
connexion SMTP directe n'est faite depuis Render : uniquement une requête
HTTPS classique (port 443, jamais bloqué), exactement comme charger une page web.

Variables d'environnement requises sur Render :
  EMAILJS_SERVICE_ID   : ex. service_xxxxxxx (trouvé dans Email Services)
  EMAILJS_TEMPLATE_ID  : ex. template_xxxxxxx (trouvé dans Email Templates)
  EMAILJS_PUBLIC_KEY   : trouvée dans Account > General
  EMAILJS_PRIVATE_KEY  : trouvée dans Account > General (Access Token)

Important : dans EmailJS, Account > Security, l'option "Allow API calls from
non-browser applications" DOIT être activée, sinon toutes les requêtes
serveur sont rejetées par défaut.

Le template EmailJS doit contenir ces variables (voir instructions fournies) :
  {{titre}}, {{to_email}}, {{message}}, {{code}}, {{cta_url}}, {{cta_label}}

Quota gratuit EmailJS : ~200 emails/mois (vérifier le plan actuel sur emailjs.com/pricing).

Sécurité :
  - Code à 6 chiffres, expire après 15 minutes.
  - 5 tentatives max par code — au-delà le code est invalidé.
  - Anti-spam : pas plus d'un code toutes les 60 secondes par email.
  - Mot de passe haché AVANT stockage temporaire dans CodeVerification.
"""

import os
import random
import string
from datetime import datetime, timezone, timedelta

DUREE_VALIDITE_MINUTES = 15
MAX_TENTATIVES = 5
DELAI_RENVOI_SECONDES = 60

EMAILJS_SERVICE_ID = os.environ.get("EMAILJS_SERVICE_ID")
EMAILJS_TEMPLATE_ID = os.environ.get("EMAILJS_TEMPLATE_ID")
EMAILJS_PUBLIC_KEY = os.environ.get("EMAILJS_PUBLIC_KEY")
EMAILJS_PRIVATE_KEY = os.environ.get("EMAILJS_PRIVATE_KEY")


# ──────────────────────────────────────────────────────────────
# ENVOI D'EMAIL VIA L'API EMAILJS (HTTPS — jamais bloqué par Render)
# ──────────────────────────────────────────────────────────────

def generer_code():
    return "".join(random.choices(string.digits, k=6))


def envoyer_email(destinataire, titre, message, code=None, cta_url="", cta_label=""):
    """
    Envoie un email via l'API REST d'EmailJS. EmailJS relaie l'envoi via le
    compte Gmail connecté (OAuth) sur ses propres serveurs — aucune connexion
    SMTP n'est faite depuis Render, uniquement cette requête HTTPS.

    Sans les 4 variables d'environnement, affiche le contenu dans les logs
    (mode dev) plutôt que d'échouer silencieusement.

    Retourne (succes: bool, erreur: str|None).
    """
    config_manquante = not all([EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY, EMAILJS_PRIVATE_KEY])
    if config_manquante:
        print(f"[EMAIL SIMULÉ] À: {destinataire} | Sujet: {titre}", flush=True)
        return True, None

    import requests
    try:
        resp = requests.post(
            "https://api.emailjs.com/api/v1.0/email/send",
            headers={"Content-Type": "application/json"},
            json={
                "service_id": EMAILJS_SERVICE_ID,
                "template_id": EMAILJS_TEMPLATE_ID,
                "user_id": EMAILJS_PUBLIC_KEY,
                "accessToken": EMAILJS_PRIVATE_KEY,
                "template_params": {
                    "to_email": destinataire,
                    "titre": titre,
                    "message": message,
                    "code": code or "",
                    "cta_url": cta_url,
                    "cta_label": cta_label,
                },
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return True, None
        return False, f"EmailJS {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)


# ──────────────────────────────────────────────────────────────
# VÉRIFICATION D'INSCRIPTION
# ──────────────────────────────────────────────────────────────

def creer_code_inscription(db, email, nom, password_hash):
    from models import CodeVerification

    recent = (
        CodeVerification.query
        .filter_by(email=email, type="inscription", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )
    if recent:
        age = (datetime.now(timezone.utc) - recent.date_creation.replace(tzinfo=timezone.utc)).total_seconds()
        if age < DELAI_RENVOI_SECONDES:
            return False, "Un code a déjà été envoyé il y a moins d'une minute. Vérifie ta boîte mail (et les spams)."

    CodeVerification.query.filter_by(email=email, type="inscription", utilise=False).update({"utilise": True})

    code = generer_code()
    entry = CodeVerification(
        email=email, code=code, type="inscription",
        nom_en_attente=nom, password_hash_en_attente=password_hash,
        expire_le=datetime.now(timezone.utc) + timedelta(minutes=DUREE_VALIDITE_MINUTES),
    )
    db.session.add(entry)
    db.session.commit()

    succes, erreur = envoyer_email(
        destinataire=email,
        titre="Confirme ton inscription — Hirondelle Conjugaison",
        message=f"Bonjour {nom or ''} ! Voici ton code de vérification pour activer ton compte. Il est valable {DUREE_VALIDITE_MINUTES} minutes.",
        code=code,
    )
    if not succes:
        print(f"[ATTENTION] Échec envoi email inscription à {email} : {erreur}", flush=True)
        return False, "L'envoi de l'email a échoué. Réessaie dans quelques instants."

    return True, "Un code de vérification a été envoyé à ton adresse email."


def valider_code_inscription(db, email, code_saisi):
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
        return False, "Trop de tentatives incorrectes. Demande un nouveau code.", None

    if entry.code != code_saisi.strip():
        entry.tentatives += 1
        db.session.commit()
        restantes = MAX_TENTATIVES - entry.tentatives
        return False, f"Code incorrect. {restantes} tentative(s) restante(s).", None

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


# ──────────────────────────────────────────────────────────────
# RÉINITIALISATION DE MOT DE PASSE
# ──────────────────────────────────────────────────────────────

def creer_code_reset_password(db, email):
    from models import CodeVerification, User

    MSG_NEUTRE = "Si un compte existe avec cet email, un code de réinitialisation vient d'être envoyé."

    user = User.query.filter_by(email=email).first()
    if not user or user.methode_connexion != "email":
        return True, MSG_NEUTRE

    recent = (
        CodeVerification.query
        .filter_by(email=email, type="reset_password", utilise=False)
        .order_by(CodeVerification.date_creation.desc())
        .first()
    )
    if recent:
        age = (datetime.now(timezone.utc) - recent.date_creation.replace(tzinfo=timezone.utc)).total_seconds()
        if age < DELAI_RENVOI_SECONDES:
            return True, MSG_NEUTRE

    CodeVerification.query.filter_by(email=email, type="reset_password", utilise=False).update({"utilise": True})

    code = generer_code()
    entry = CodeVerification(
        email=email, code=code, type="reset_password",
        expire_le=datetime.now(timezone.utc) + timedelta(minutes=DUREE_VALIDITE_MINUTES),
    )
    db.session.add(entry)
    db.session.commit()

    envoyer_email(
        destinataire=email,
        titre="Réinitialisation de mot de passe — Hirondelle Conjugaison",
        message="Tu as demandé à réinitialiser ton mot de passe. Voici ton code :",
        code=code,
    )
    return True, MSG_NEUTRE


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


# ──────────────────────────────────────────────────────────────
# EMAIL DE RELANCE RÉTENTION (streak en danger)
# ──────────────────────────────────────────────────────────────

def envoyer_email_relance(user, base_url="https://hirondelleconjugaison.onrender.com"):
    if not user.email_verifie:
        return False

    if user.streak_jours > 0:
        message = f"Ton streak de {user.streak_jours} jour(s) est en danger ! Si tu ne joues pas aujourd'hui, ton streak repart à zéro."
        titre = f"🔥 Ton streak de {user.streak_jours} jour(s) risque de tomber !"
    else:
        message = "Tu n'as pas conjugué depuis 3 jours. Reprends là où tu t'es arrêté(e) — 2 minutes suffisent."
        titre = "🦅 Reviens t'entraîner — 2 minutes, c'est tout !"

    succes, _ = envoyer_email(
        destinataire=user.email,
        titre=titre,
        message=message,
        cta_url=f"{base_url}/quiz?mode=entrainement",
        cta_label="Reprendre l'entraînement →",
    )
    return succes
