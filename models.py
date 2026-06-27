"""
Modèles de base de données — Hirondelle Conjugaison.
Utilise PostgreSQL via SQLAlchemy. La variable d'environnement DATABASE_URL
doit être définie (Render la fournit automatiquement si la base est liée).
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    nom = db.Column(db.String(100), nullable=True)

    # Nullable car un compte créé via OAuth n'a pas de mot de passe local
    password_hash = db.Column(db.String(255), nullable=True)

    # "email", "google" ou "github" — sert à afficher la bonne icône / méthode
    methode_connexion = db.Column(db.String(20), nullable=False, default="email")

    # Sécurité : un compte créé par email doit être vérifié avant de pouvoir
    # se connecter — sans ça, n'importe qui peut s'inscrire avec un email
    # qu'il ne possède pas, ce qui casse la récupération de mot de passe.
    # Les comptes OAuth (Google/Github) sont considérés vérifiés d'office :
    # le fournisseur a déjà confirmé l'email à notre place.
    # Par défaut à True : les comptes déjà existants avant l'introduction
    # de cette vérification ne doivent pas se retrouver bloqués au prochain
    # login (ils n'ont rien fait de mal, la règle n'existait pas encore).
    # Tout nouveau compte créé via /inscription passe explicitement par
    # email_verifie=False jusqu'à validation du code — voir auth.py et
    # email_verification.py. Les comptes OAuth sont créés avec True
    # directement, le fournisseur ayant déjà vérifié l'email.
    email_verifie = db.Column(db.Boolean, nullable=False, default=True)

    date_creation = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # ── Gamification : compteurs légers, stockés directement sur l'utilisateur
    # plutôt que recalculés depuis l'historique — coût mémoire quasi nul (quelques
    # entiers par utilisateur) et lecture instantanée pour l'affichage.
    xp_total = db.Column(db.Integer, nullable=False, default=0)
    niveau = db.Column(db.Integer, nullable=False, default=1)
    streak_jours = db.Column(db.Integer, nullable=False, default=0)
    streak_record = db.Column(db.Integer, nullable=False, default=0)
    derniere_session = db.Column(db.Date, nullable=True)  # pour calculer le streak
    badges_obtenus = db.Column(db.String(500), nullable=False, default="")  # CSV léger : "premiers_pas,serie_7,..."

    # Relations
    agregats = db.relationship("AgregatVerbe", backref="user", lazy="dynamic",
                                cascade="all, delete-orphan")
    historique = db.relationship("ReponseRecente", backref="user", lazy="dynamic",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.email}>"

    def liste_badges(self):
        return [b for b in self.badges_obtenus.split(",") if b]

    def a_le_badge(self, code):
        return code in self.liste_badges()

    def ajouter_badge(self, code):
        if not self.a_le_badge(code):
            actuels = self.liste_badges()
            actuels.append(code)
            self.badges_obtenus = ",".join(actuels)
            return True  # nouveau badge débloqué
        return False


class AgregatVerbe(db.Model):
    """
    Compteurs CUMULÉS par utilisateur × verbe × mode × temps.
    Une seule ligne par combinaison déjà rencontrée, peu importe le nombre
    de fois où elle a été jouée — c'est ce qui rend cette table compacte :
    elle ne grossit jamais plus vite que (nb_utilisateurs × nb_combinaisons
    réellement explorées), pas que (nb_utilisateurs × nb_questions jouées).

    Alimente : taux de réussite par mode, verbes à réviser, score de maîtrise
    pour la répétition espacée — sans jamais relire l'historique brut.
    """
    __tablename__ = "agregats_verbe"
    __table_args__ = (
        db.UniqueConstraint("user_id", "verbe", "mode", "temps", name="uq_agregat_combo"),
        db.Index("ix_agregat_user_verbe", "user_id", "verbe"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    verbe = db.Column(db.String(50), nullable=False)
    mode = db.Column(db.String(30), nullable=False)
    temps = db.Column(db.String(40), nullable=False)

    nb_total = db.Column(db.Integer, nullable=False, default=0)
    nb_correct = db.Column(db.Integer, nullable=False, default=0)

    # Date de la dernière réponse sur cette combinaison — sert au calcul
    # de fraîcheur pour la répétition espacée, sans avoir besoin de
    # l'historique détaillé.
    derniere_date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def taux(self):
        return round(self.nb_correct / self.nb_total * 100, 1) if self.nb_total else 0

    def __repr__(self):
        return f"<Agrégat {self.verbe}/{self.mode}/{self.temps} {self.nb_correct}/{self.nb_total}>"


class ReponseRecente(db.Model):
    """
    Historique BORNÉ des dernières réponses — uniquement pour l'affichage
    "activité récente" et la pondération fine de répétition espacée.

    Contrairement à l'ancien ReponseQuiz, cette table est purgée automatiquement :
    on ne garde que les MAX_HISTORIQUE dernières lignes par utilisateur
    (voir purger_historique() dans repetition.py). Taille bornée en permanence,
    quel que soit le nombre de questions jouées dans la durée de vie du compte.
    """
    __tablename__ = "reponses_recentes"
    __table_args__ = (db.Index("ix_reponse_user_date", "user_id", "date"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    verbe = db.Column(db.String(50), nullable=False)
    mode = db.Column(db.String(30), nullable=False)
    temps = db.Column(db.String(40), nullable=False)
    correct = db.Column(db.Boolean, nullable=False)

    date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        statut = "✓" if self.correct else "✗"
        return f"<Réponse {statut} {self.verbe}/{self.mode}/{self.temps}>"


# Nombre maximum de lignes d'historique détaillé conservées par utilisateur.
# Au-delà, les plus anciennes sont supprimées (voir repetition.purger_historique).
MAX_HISTORIQUE_PAR_USER = 150


class CodeVerification(db.Model):
    """
    Code à usage unique envoyé par email — utilisé pour deux besoins distincts :
    - "inscription" : confirmer que l'utilisateur possède bien l'email donné,
      avant d'activer le compte (email_verifie = True).
    - "reset_password" : autoriser la réinitialisation du mot de passe.

    Une seule table pour les deux cas (même mécanique, juste un "type" différent)
    plutôt que deux tables quasi identiques — plus simple à maintenir et à purger.
    """
    __tablename__ = "codes_verification"
    __table_args__ = (db.Index("ix_code_email_type", "email", "type"),)

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False)
    code = db.Column(db.String(6), nullable=False)  # code à 6 chiffres, simple à taper
    type = db.Column(db.String(20), nullable=False)  # "inscription" ou "reset_password"

    # Pour le cas inscription : on stocke les infos du compte à créer, pour
    # ne créer l'utilisateur en base QUE si le code est validé — pas avant.
    # Ça évite de polluer la table users avec des comptes jamais confirmés.
    nom_en_attente = db.Column(db.String(100), nullable=True)
    password_hash_en_attente = db.Column(db.String(255), nullable=True)

    date_creation = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expire_le = db.Column(db.DateTime, nullable=False)
    utilise = db.Column(db.Boolean, nullable=False, default=False)
    tentatives = db.Column(db.Integer, nullable=False, default=0)  # anti brute-force

    def __repr__(self):
        return f"<Code {self.type} {self.email} {'utilisé' if self.utilise else 'actif'}>"
