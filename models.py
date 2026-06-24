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

    date_creation = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relation vers l'historique de progression
    reponses = db.relationship("ReponseQuiz", backref="user", lazy="dynamic")

    def __repr__(self):
        return f"<User {self.email}>"


class ReponseQuiz(db.Model):
    """
    Une ligne = une question répondue par un utilisateur connecté.
    C'est la donnée brute qui alimente toute la page de progression
    (taux de réussite par mode/temps, verbes les plus ratés, etc.)
    """
    __tablename__ = "reponses_quiz"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    verbe = db.Column(db.String(50), nullable=False)
    mode = db.Column(db.String(30), nullable=False)
    temps = db.Column(db.String(40), nullable=False)
    personne = db.Column(db.String(20), nullable=True)
    voix = db.Column(db.String(10), nullable=False, default="active")  # active / passive

    correct = db.Column(db.Boolean, nullable=False)
    reponse_donnee = db.Column(db.String(255), nullable=True)
    reponse_attendue = db.Column(db.String(255), nullable=True)

    date = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def __repr__(self):
        statut = "✓" if self.correct else "✗"
        return f"<Réponse {statut} {self.verbe}/{self.mode}/{self.temps}>"
