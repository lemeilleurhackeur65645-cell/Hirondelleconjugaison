"""Jeton signé pour se désabonner des rappels par email, sans connexion."""
import os
from itsdangerous import URLSafeSerializer, BadSignature


def _serializer():
    return URLSafeSerializer(os.environ.get("SECRET_KEY", "dev"), salt="desabonnement-rappels")


def token_desabonnement(user_id):
    return _serializer().dumps(user_id)


def lire_token(token):
    try:
        return _serializer().loads(token)
    except BadSignature:
        return None
