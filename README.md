# 🦅 Hirondelle Conjugaison

> Quiz interactif de conjugaison française — 543 verbes, tous modes et temps, gamification complète.

**URL en production :** https://hirondelleconjugaison.onrender.com

---

## Présentation

Hirondelle Conjugaison est une application web d'entraînement à la conjugaison française, destinée principalement aux lycéens préparant le bac de français et aux apprenants de FLE (Français Langue Étrangère).

### Fonctionnalités principales

- **Quiz adaptatif** : 3 modes (entraînement infini, évaluation chronométrée 10 questions/5 min, quiz ciblé par verbe/mode/temps)
- **Répétition espacée** : algorithme de pondération basé sur l'historique personnel de chaque utilisateur connecté — les verbes ratés récemment reviennent plus souvent
- **9 121 pages de conjugaison** générées dynamiquement, toutes indexées dans le sitemap
- **Système de comptes complet** : inscription email (vérifiée par code à 6 chiffres), connexion Google OAuth, connexion Github OAuth
- **Gamification** : XP, niveaux, streak journalier, 8 badges débloquables, dashboard de progression personnel
- **Voix passive** : conjugaison à la voix passive pour 16 verbes sélectionnés

---

## Stack technique

| Composant | Technologie |
|---|---|
| Backend | Flask (Python 3.12) |
| Serveur WSGI | Gunicorn |
| Base de données | PostgreSQL (Render) |
| ORM | Flask-SQLAlchemy |
| Authentification | Flask-Login + Flask-Bcrypt + Authlib (OAuth) |
| Templates | Jinja2 |
| Hébergement | Render (plan Free) |
| Envoi d'emails | Brevo API (vérification inscription, relances rétention) |
| SEO | Sitemap XML dynamique (9 121 URLs), IndexNow, robots.txt |

---

## Architecture base de données

### Tables principales

- **`users`** : comptes utilisateurs avec champs de gamification (xp_total, niveau, streak_jours, streak_record, badges_obtenus)
- **`agregats_verbe`** : compteurs cumulés par utilisateur × verbe × mode × temps — architecture compacte (1 ligne par combinaison, pas par réponse)
- **`reponses_recentes`** : historique borné à 150 réponses par utilisateur pour l'affichage et la répétition espacée
- **`codes_verification`** : codes à usage unique pour la vérification d'email et la réinitialisation de mot de passe

### Principe d'architecture mémoire

Le stockage est délibérément compact pour rester dans le plan gratuit PostgreSQL (1 Go) : les statistiques globales sont calculées depuis les agrégats (O(n_combinaisons_vues)) et non depuis l'historique brut (O(n_questions_jouées)).


---

## Installation locale

```bash
git clone https://github.com/<ton-repo>/Hirondelleconjugaison
cd Hirondelleconjugaison
pip install -r requirements.txt

# Créer un fichier .env (pour les variables d'environnement locales)
export DATABASE_URL=sqlite:///local_dev.db  # SQLite pour le développement local
export SECRET_KEY=dev_secret_key_local

python main.py
# → http://localhost:10000
```

---

## Structure du projet

```
Hirondelleconjugaison/
├── main.py                  # Routes Flask, logique quiz, gamification
├── models.py                # Modèles SQLAlchemy (User, AgregatVerbe, ReponseRecente, CodeVerification)
├── auth.py                  # Blueprint authentification (email, Google, Github)
├── email_verification.py    # Envoi d'emails via Brevo, codes de vérification, relances rétention
├── repetition.py            # Algorithme de répétition espacée, logique XP/niveaux/badges
├── requirements.txt
├── runtime.txt              # Python 3.12.7 (pin de version pour Render)
├── data/
│   ├── actif.json           # 543 verbes à la voix active — toutes les conjugaisons
│   └── passif.json          # 16 verbes à la voix passive
└── templates/               # 19 templates Jinja2
    ├── index.html           # Page d'accueil (différente si connecté)
    ├── conjugaison.html     # Page de conjugaison individuelle (verbe/mode/temps)
    ├── quiz.html            # Interface de quiz
    ├── progression.html     # Dashboard de progression utilisateur
    ├── admin_dashboard.html # Dashboard admin (KPIs, graphiques Chart.js, table utilisateurs)
    └── ...
```

---

## Sécurité

- Mots de passe hachés avec bcrypt
- Protection CSRF sur tous les formulaires POST (Flask-WTF)
- Cookies de session sécurisés (Secure, HttpOnly, SameSite=Lax)
- Rate limiting sur les routes sensibles (Flask-Limiter)
- Honeypot anti-bot sur le formulaire d'inscription
- Vérification email obligatoire avant connexion (codes à usage unique, expiration 15 min, 5 tentatives max)
- Routes admin restreintes par email spécifique

---

## SEO

- 9 121 pages de conjugaison indexées (verbe × mode × temps)
- Sitemap XML dynamique disponible sur `/sitemap.xml`
- IndexNow configuré pour notification instantanée à Bing/Yandex
- Meta descriptions, titres, H1 optimisés sur toutes les pages
- Structure JSON-LD BreadcrumbList sur les pages de conjugaison
- robots.txt pointant vers le sitemap

---

## Données de contenu

Les données de conjugaison proviennent du projet open-source [alexey-beshenov/conjugaison](https://github.com/alexey-beshenov/conjugaison), sous licence libre.

---

## Licence

Propriétaire — tous droits réservés.
