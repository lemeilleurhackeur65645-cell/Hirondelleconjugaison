"""
Vérification d'email, bienvenue, relance rétention, réinitialisation de
mot de passe. Envoi via EmailJS (API HTTPS, jamais bloquée par Render).

Variables d'environnement requises sur Render :
  EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY, EMAILJS_PRIVATE_KEY

Ton éditorial : direct, personnel, jamais criard. Un emoji maximum dans le
titre, aucun dans le corps du texte. Phrases courtes. Léger sentiment
d'urgence sur les relances, sans culpabiliser lourdement (style Duolingo,
en plus sobre).

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
BASE_URL = "https://hirondelleconjugaison.onrender.com"

EMAILJS_SERVICE_ID = os.environ.get("EMAILJS_SERVICE_ID")
EMAILJS_TEMPLATE_ID = os.environ.get("EMAILJS_TEMPLATE_ID")
EMAILJS_PUBLIC_KEY = os.environ.get("EMAILJS_PUBLIC_KEY")
EMAILJS_PRIVATE_KEY = os.environ.get("EMAILJS_PRIVATE_KEY")

RAPPEL_SPAM = "Pas dans ta boîte de réception ? Regarde du côté des spams."


# ──────────────────────────────────────────────────────────────
# ENVOI D'EMAIL VIA L'API EMAILJS
# ──────────────────────────────────────────────────────────────

def generer_code():
    return "".join(random.choices(string.digits, k=6))


def envoyer_email(destinataire, titre, message, code=None, cta_url="", cta_label=""):
    """
    Retourne (succes: bool, erreur: str|None).
    Le bouton (cta_url/cta_label) a toujours une valeur par défaut pour
    éviter un bouton vide dans le template EmailJS.
    """
    if not cta_url or not cta_label:
        cta_url = BASE_URL
        cta_label = "Ouvrir Hirondelle Conjugaison"

    if not all([EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY, EMAILJS_PRIVATE_KEY]):
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
# 1. VÉRIFICATION D'INSCRIPTION
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
            return False, f"Code déjà envoyé il y a moins d'une minute. {RAPPEL_SPAM}"

    CodeVerification.query.filter_by(email=email, type="inscription", utilise=False).update({"utilise": True})

    code = generer_code()
    entry = CodeVerification(
        email=email, code=code, type="inscription",
        nom_en_attente=nom, password_hash_en_attente=password_hash,
        expire_le=datetime.now(timezone.utc) + timedelta(minutes=DUREE_VALIDITE_MINUTES),
    )
    db.session.add(entry)
    db.session.commit()

    prenom = f" {nom}" if nom else ""
    message = (
        f"Salut{prenom}. Un dernier pas avant de commencer : entre ce code sur le site "
        f"pour activer ton compte. Il reste valable {DUREE_VALIDITE_MINUTES} minutes."
    )
    succes, erreur = envoyer_email(email, "Ton code pour activer ton compte", message, code=code)
    if not succes:
        print(f"[ATTENTION] Échec envoi email inscription à {email} : {erreur}", flush=True)
        return False, "L'envoi de l'email a échoué. Réessaie dans quelques instants."

    return True, f"Code envoyé à ton adresse email. {RAPPEL_SPAM}"


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
        return False, "Ce code a expiré. Demande-en un nouveau.", None
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
        email=email, nom=entry.nom_en_attente, password_hash=entry.password_hash_en_attente,
        methode_connexion="email", email_verifie=True,
    )
    entry.utilise = True
    db.session.add(user)
    db.session.commit()
    return True, "Compte créé et vérifié.", user


# ──────────────────────────────────────────────────────────────
# 2. EMAIL DE BIENVENUE — une seule fois, juste après création du compte
# ──────────────────────────────────────────────────────────────

def envoyer_email_bienvenue(user):
    """À appeler une fois, juste après la création réussie d'un compte
    (email vérifié OU première connexion OAuth)."""
    prenom = user.nom or ""
    salutation = f"Salut {prenom}." if prenom else "Salut."

    message = (
        f"{salutation} Ton compte est prêt. Voilà ce que tu peux faire dès maintenant : "
        "t'entraîner sur 543 verbes, dans tous les modes et tous les temps. "
        "Chaque bonne réponse te fait gagner de l'XP et monter de niveau. "
        "Joue un jour, puis reviens le lendemain : c'est ce qui construit un streak, "
        "et c'est la meilleure façon de vraiment retenir une conjugaison. "
        "Pas besoin de session longue — deux minutes suffisent pour commencer."
    )
    succes, _ = envoyer_email(
        destinataire=user.email,
        titre="Bienvenue sur Hirondelle Conjugaison",
        message=message,
        cta_url=f"{BASE_URL}/quiz?mode=entrainement",
        cta_label="Faire mon premier quiz",
    )
    return succes


# ──────────────────────────────────────────────────────────────
# 3. RÉINITIALISATION DE MOT DE PASSE
# ──────────────────────────────────────────────────────────────

def creer_code_reset_password(db, email):
    from models import CodeVerification, User

    MSG_NEUTRE = f"Si un compte existe avec cet email, un code vient d'être envoyé. {RAPPEL_SPAM}"

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

    message = "Voici ton code pour choisir un nouveau mot de passe. Si ce n'était pas toi, ignore cet email."
    envoyer_email(email, "Réinitialise ton mot de passe", message, code=code)
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
# 4. RELANCES DE RÉTENTION — 3 variantes selon la situation
# ──────────────────────────────────────────────────────────────

def envoyer_email_relance(user, base_url=BASE_URL):
    """
    Appelé pour les utilisateurs inactifs depuis exactement 3 jours.
    Trois messages différents selon le profil :
      - streak actif > 3 jours : urgence sur la perte du streak
      - streak actif court (1-3) : encouragement, pas encore assez investi pour l'urgence
      - pas de streak : relance neutre, invite simplement à reprendre
    """
    if not user.email_verifie:
        return False

    if user.streak_jours >= 4:
        titre = "Ton streak est sur le point de tomber"
        message = (
            f"Ça fait 3 jours. Ton streak de {user.streak_jours} jours tient encore, "
            "mais plus pour longtemps. Une seule question suffit pour le garder en vie."
        )
    elif user.streak_jours >= 1:
        titre = "Tu avais bien commencé"
        message = (
            f"Tu étais sur une série de {user.streak_jours} jour(s) avant de t'arrêter. "
            "Reprendre maintenant, c'est repartir sur cette lancée plutôt que de tout recommencer."
        )
    else:
        titre = "Ça fait un moment"
        message = (
            "Tu n'as pas pratiqué depuis 3 jours. Pas besoin de tout reprendre à zéro : "
            "deux minutes suffisent pour retrouver le rythme et progresser."
        )

    succes, _ = envoyer_email(
        destinataire=user.email, titre=titre, message=message,
        cta_url=f"{base_url}/quiz?mode=entrainement", cta_label="Reprendre l'entraînement",
    )
    return succes


# ──────────────────────────────────────────────────────────────
# 5. NOUVEAU NIVEAU ATTEINT
# ──────────────────────────────────────────────────────────────

def envoyer_email_niveau(user, base_url=BASE_URL):
    """
    À déclencher quand un utilisateur passe un niveau (level_up=True dans
    la logique de gamification). Optionnel : peut être limité aux paliers
    marquants (5, 10, 20...) pour ne pas sursolliciter côté quota email.
    """
    message = (
        f"Bravo! Tu viens de passer niveau {user.niveau}. Ça se joue à l'XP accumulée "
        "question après question — continue sur cette voie, pour passer au niveau supérieur."
    )
    succes, _ = envoyer_email(
        destinataire=user.email,
        titre=f"Niveau {user.niveau} atteint !",
        message=message,
        cta_url=f"{base_url}/compte",
        cta_label="Voir ma progression",
    )
    return succes


# ──────────────────────────────────────────────────────────────
# 6. NOUVEAU BADGE DÉBLOQUÉ
# ──────────────────────────────────────────────────────────────

def envoyer_email_badge(user, badge_nom, badge_description, base_url=BASE_URL):
    """
    À déclencher à chaque badge nouvellement débloqué. Le texte reste
    factuel plutôt qu'exalté — le badge parle de lui-même.
    """
    message = f"Tu viens de débloquer le badge « {badge_nom} », bravo! {badge_description}"
    succes, _ = envoyer_email(
        destinataire=user.email,
        titre=f"Badge débloqué : {badge_nom}",
        message=message,
        cta_url=f"{base_url}/badges",
        cta_label="Voir tous mes badges",
    )
    return succes
