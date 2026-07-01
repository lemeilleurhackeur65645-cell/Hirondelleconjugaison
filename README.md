# Hirondelle Conjugaison

**Le quiz de conjugaison française le plus complet, gratuit, et sans pub.**

> 543 verbes · 9 121 pages · Répétition espacée · Gamification complète · Comptes utilisateurs sécurisés

🌐 **Site en ligne :** https://hirondelleconjugaison.onrender.com

---

## Table des matières

1. [Ce qu'est le site](#-ce-quest-le-site)
2. [Ce qui le différencie de la concurrence](#-ce-qui-le-différencie-de-la-concurrence)
3. [Fonctionnalités détaillées](#-fonctionnalités-détaillées)
4. [Architecture technique](#-architecture-technique)
5. [Sécurité](#-sécurité)
6. [SEO et visibilité](#-seo-et-visibilité)
7. [Gamification et rétention](#-gamification-et-rétention)
8. [Contact](#-contact)

---

## Ce qu'est le site

Hirondelle Conjugaison est une application web d'entraînement à la conjugaison française. Elle s'adresse principalement à trois publics :

- **Les lycéens** qui préparent le bac de français, ou n'importe quel examen ou évaluation et qui doivent maîtriser le subjonctif, le passé simple et le conditionnel.
- **Les apprenants de FLE** (Français Langue Étrangère) qui veulent pratiquer la conjugaison de façon interactive
- **Les enseignants** qui cherchent un outil gratuit et sans inscription obligatoire à recommander à leurs élèves

Le site génère dynamiquement **9 121 pages de conjugaison** (une page par combinaison verbe × mode × temps), toutes optimisées pour le référencement naturel et toutes équipées d'un quiz intégré.

---

## Ce qui le différencie de la concurrence

### Comparé à Bescherelle en ligne, Conjugaison.com, Le Conjugueur

Ces sites existent depuis des années mais ont un défaut commun : ils sont des **dictionnaires passifs**. Ils ne permettent pas de s'exercer de manière approfondie, et ne propose souvent qu'un tableau. Il n'y a aucune interaction, aucune rétention, aucune progression mesurable.

**Hirondelle ajoute :**
- Un quiz interactif sur chaque page de conjugaison — tu consultes ET tu t'entraînes en même temps
- Un historique de progression personnel si tu es connecté
- Un algorithme de répétition espacée qui ramène automatiquement les verbes que tu rates


**Tout le contenu est gratuit et accessible sans compte.** Le compte ne sert qu'à sauvegarder la progression — pas à déverrouiller du contenu caché derrière un paywall.

---

## Fonctionnalités détaillées

### Quiz — 3 modes d'entraînement

**Mode entraînement (infini)**
Le mode principal. Questions infinies, aucun timer, tu vas à ton rythme. Pour les utilisateurs connectés, l'algorithme de répétition espacée pondère les questions en faveur des verbes ratés récemment — les verbes maîtrisés depuis longtemps reviennent moins souvent, les points faibles reviennent plus souvent. Pour les visiteurs non connectés, le tirage est uniformément aléatoire.

**Mode évaluation (chronométré)**
10 questions, 5 minutes. Simule les conditions d'un contrôle scolaire. Score sur 10 à la fin. Pas de répétition espacée dans ce mode — le tirage est délibérément équitable pour évaluer objectivement le niveau global.

**Mode quiz ciblé (débloqué au niveau 3)**
Le mode avancé. L'utilisateur choisit précisément le(s) verbe(s), le(s) mode(s) et le(s) temps, le(s) personnes ou même la voix à travailler. Permet de cibler un point faible spécifique (ex : "je veux travailler uniquement le subjonctif des verbes irréguliers du 1er groupe"). Accessible seulement à partir du niveau 3 pour encourager une progression progressive.

### Bilan et révision des erreurs

Après chaque session, un bilan détaillé affiche :
- Le score global et le taux de réussite
- La liste exhaustive des erreurs (verbe, mode, temps, réponse donnée vs attendue)
- Une analyse statistique : verbes les plus ratés, modes les moins maîtrisés, suggestion de révision prioritaire
- Un badge numéroté unique (avec numéro de série et watermark anti-copie) si le taux de réussite dépasse 80% sur 10+ questions
- Un bouton "Partager mon score" avec texte pré-rempli adaptatif selon le niveau de performance (différent si 10/10, >80%, <50%), avec lien direct vers WhatsApp

Immédiatement après le bilan, l'utilisateur peut lancer une session de révision ciblée sur ses erreurs uniquement, afin de pouvoir certifier qu'il ne refasse pas les mêmes erreurs.

### 9 121 pages de conjugaison

Chaque combinaison verbe × mode × temps a sa propre page dédiée, accessible via `/conjugaison/{verbe}/{mode}/{temps}`. Ces pages contiennent :
- Le tableau de conjugaison complet (6 personnes, ou 3 pour l'impératif)
- Un quiz intégré directement sur la page
- Un exemple de phrase en contexte pour les combinaisons les plus consultées (50 exemples couvrant les verbes et modes les plus cherchés)
- Des liens vers les verbes de la même famille morphologique (maillage interne SEO)
- La navigation vers les autres modes et temps du même verbe
- Des conseils pédagogiques spécifiques selon le mode (subjonctif, conditionnel, etc.)

Les pages de la voix passive (`/conjugaison/{verbe}/indicatif-passif/{temps}`) sont disponibles pour 16 verbes courants.

### Système de comptes utilisateurs

**Inscription par email**
Flux en deux étapes avec vérification obligatoire : l'utilisateur entre son email et son mot de passe, reçoit un code à 6 chiffres par email (valable 15 minutes), et ne crée réellement son compte qu'après validation. Le mot de passe n'est jamais stocké en clair (haché avec bcrypt avant même l'envoi du code).

**Connexion Google OAuth**
Il est possible de se connecter via Google, avec un simple clic. L'email est vérifié automatiquement par Google.

**Connexion Github OAuth**
Même principe pour Github.

**Page "Mon compte"**
Affiche : email, prénom, méthode de connexion (avec badge visuel), date d'inscription, niveau, streak, nombre de badges, taux de réussite global, et le verbe statistiquement le plus raté du compte.

**Récupération de mot de passe**
Envoi d'un code à 6 chiffres par email, même mécanique que la vérification d'inscription. Le message de confirmation est volontairement neutre (ne révèle pas si l'email est inscrit ou non) pour éviter l'énumération de comptes.

---

## Architecture technique

### Vue d'ensemble

Le site est une application web Python/Flask hébergée sur Render (plan gratuit, avec réveil automatique configuré via UptimeRobot). La base de données est PostgreSQL (plan gratuit Render, 1 Go). L'envoi d'emails passe par Brevo (300 emails/jour gratuits).

### Pourquoi cette architecture est compacte et maintenable

**Le stockage est délibérément conçu pour ne pas exploser.** Plutôt que de stocker une ligne en base à chaque question répondue (ce qui ferait des millions de lignes au bout d'un an), le site utilise deux tables complémentaires :

1. **Les agrégats** (une ligne par utilisateur × verbe × mode × temps) : compteurs cumulés qui s'incrémentent à chaque réponse. Une table qui grandit au rythme du nombre de combinaisons *explorées*, pas du nombre de questions jouées. Un utilisateur qui joue 10 000 questions sur les mêmes 50 verbes n'aura que 50 lignes dans cette table.

2. **L'historique récent** (restreint à 150 lignes par utilisateur) : les 150 dernières réponses en détail, utilisées pour l'affichage "activité récente" et le calcul fin de la répétition espacée. Au-delà de 150, les plus anciennes sont supprimées automatiquement.

Cette architecture permet de rester confortablement dans le quota de 1 Go du plan gratuit PostgreSQL même avec des centaines d'utilisateurs actifs.

### Fichiers principaux

**`main.py`** — Le cœur du site. Contient toutes les routes Flask, la logique du quiz (génération de questions, vérification des réponses, calcul des scores), la gamification, le dashboard admin, et les routes de maintenance (IndexNow, relances email). Environ 1 600 lignes.

**`models.py`** — La définition des tables de base de données. Contient aussi la logique des badges (méthodes `ajouter_badge`, `a_le_badge`, `liste_badges` directement sur le modèle `User`) et les constantes de configuration mémoire.

**`auth.py`** — Un Blueprint Flask séparé qui gère tout ce qui touche à l'authentification : inscription en deux étapes, connexion email/Google/Github, déconnexion, vérification de code, mot de passe oublié, réinitialisation de mot de passe. Inclut le rate limiting spécifique aux routes sensibles.

**`email_verification.py`** — Module autonome responsable de la génération et de la vérification des codes, de l'envoi des emails via Brevo, et de l'envoi des emails de relance rétention.

**`repetition.py`** — L'algorithme de répétition espacée (calcul des poids depuis les agrégats, tirage pondéré), la logique de gamification (gain XP, mise à jour du streak, vérification des badges), et la fonction d'enregistrement compact des réponses.

### Données de conjugaison

Les 543 verbes et leurs conjugaisons complètes sont stockés dans deux fichiers JSON (`data/actif.json` et `data/passif.json`) chargés en mémoire au démarrage. Cela évite des requêtes base de données pour chaque page de conjugaison consultée — les pages sont générées depuis ces données en mémoire, ce qui les rend très rapides.

Source des données : projet open-source [alexey-beshenov/conjugaison](https://github.com/alexey-beshenov/conjugaison).

---

## Sécurité

La sécurité a été traitée en profondeur, avec 7 mécanismes complémentaires :

**1. Mots de passe hachés avec bcrypt**
Les mots de passe ne sont jamais stockés en clair, même temporairement. Ils sont hachés dès la saisie du formulaire d'inscription, avant même d'être écrits dans la table des codes de vérification en attente.

**2. Clé secrète via variable d'environnement**
La clé qui signe les sessions utilisateurs est définie uniquement via variable d'environnement sur Render — jamais dans le code source, afin d'écarter toute tentative de se la procurer. Si la variable venait à manquer, une alerte explicite apparaîtrait alors dans les logs au démarrage.

**3. Cookies de session sécurisés**
Trois attributs activés sur tous les cookies : `Secure` (transmis uniquement en HTTPS), `HttpOnly` (inaccessible au JavaScript, protège contre le vol de session par XSS), `SameSite=Lax` (protection complémentaire contre le CSRF sur les navigations cross-site).

**4. Protection CSRF**
Tous les formulaires POST du site (connexion, inscription, quiz, révision ciblée, vérification de code, mot de passe oublié) contiennent un token secret unique par session. Une requête forgée depuis un autre site ne peut pas reproduire ce token et sera rejetée automatiquement.

**5. Rate limiting par adresse IP**
Les routes sensibles ont des limites strictes : connexion (10 tentatives/min), inscription (5/min), envoi de code (3/min), soumission de quiz (sécurité globale 200/heure). Les routes publiques de conjugaison et le sitemap sont explicitement exemptés pour ne pas gêner Googlebot.

**6. Vérification email obligatoire**
Un compte créé par email ne peut pas se connecter tant que l'adresse n'est pas confirmée par code. Anti-brute-force : 5 tentatives max par code, après quoi le code est invalidé définitivement. Anti-spam : un nouveau code ne peut être demandé que 60 secondes après le précédent.

**7. Honeypot anti-bot**
Le formulaire d'inscription contient un champ caché par CSS avec un nom générique. Un bot qui remplit automatiquement tous les champs visibles le complètera, trahissant sa nature de bot. Un humain ne le voit jamais et ne le remplit jamais. Evidemment, ce n'est pas exactement ce qui se produit, afin de protéger totalement le site.

---

## SEO et visibilité

### Pages générées

**9 121 pages de conjugaison** au format `/conjugaison/{verbe}/{mode}/{temps}`, toutes incluses dans le sitemap XML dynamique disponible sur `/sitemap.xml`. Les impératifs vides (verbes défectifs comme *falloir*, *pleuvoir*) sont automatiquement exclus du sitemap pour éviter les pages sans contenu.

**543 pages "verbe central"** au format `/conjugaison/{verbe}`, qui présentent un résumé de tous les modes disponibles pour ce verbe avec des liens vers chaque tableau détaillé.

**1 page index des conjugaisons** (`/conjugaisons`) avec barre de recherche en autocomplétion sur les 543 verbes, filtres par groupe grammatical, et index alphabétique.

### Optimisations techniques

- Meta descriptions sous 160 caractères sur toutes les pages (optimisées pour l'affichage dans les résultats Google/Bing)
- Titres sous 60 caractères sur toutes les pages
- H1 présent sur chaque page (y compris le quiz, avec un H1 invisible pour le SEO)
- Structure JSON-LD BreadcrumbList sur les pages de conjugaison individuelles
- `robots.txt` pointant vers le sitemap
- IndexNow configuré pour notification instantanée à Bing, Yandex, et les moteurs partenaires à chaque mise à jour de contenu

### Résultats mesurés (juin 2026)

**Bing :** Premières impressons. Requêtes génériques réelles (pas de marque) : *"surseoir conjugaison"*, *"recourir conjugaison"*, *"conjugaison vaincre"*, *"verbe employer à tous les temps"*.

**Google :** Indexation en cours.

---

## Gamification et rétention

### Système d'XP et de niveaux

Chaque bonne réponse rapporte 10 XP. Un bonus de 5 XP est accordé si le verbe/temps était statistiquement difficile pour cet utilisateur (taux de réussite historique < 60%) — ce qui encourage à s'attaquer à ses points faibles plutôt qu'à répéter ce qu'on maîtrise déjà.

La courbe de niveaux suit une progression en puissance 1,5 (niveau 2 = 50 XP, niveau 3 = 141 XP, niveau 4 = 259 XP, etc.) — assez rapide pour donner le sentiment de progression en début d'utilisation, assez lente pour rester motivante sur la durée.

### Streak journalier

Le streak compte le nombre de jours consécutifs où l'utilisateur a répondu à au moins une question. Il s'incrémente une seule fois par jour (même si l'utilisateur joue 5 fois dans la journée), se réinitialise à 1 si un jour est manqué, et un record est conservé séparément.

Sur la page d'accueil, une alerte orange s'affiche si l'utilisateur n'a pas encore joué aujourd'hui : *"⚠️ Joue aujourd'hui pour garder ton streak de X jours !"* — ce signal d'urgence disparaît dès qu'il répond à sa première question de la journée.

### 8 badges débloquables

| Badge | Condition |
|---|---|
| 🌱 Premiers pas | Premier quiz terminé |
| 🔥 Sur la lancée | 3 jours de suite |
| ⚡ Semaine parfaite | 7 jours de suite |
| 🏆 Habitude ancrée | 30 jours de suite |
| 💯 Centurion | 100 questions répondues |
| 🎖️ Marathonien | 1 000 questions répondues |
| ✨ Sans faute | 10 bonnes réponses d'affilée |
| 📚 Polyglotte verbal | 20 verbes différents travaillés |

### Email de relance automatique

Un email de relance est envoyé automatiquement aux utilisateurs inactifs depuis exactement 3 jours. Le message est personnalisé : si l'utilisateur avait un streak actif, le mail mentionne spécifiquement le risque de perdre ce streak. Sinon, il invite à reprendre l'entraînement avec un CTA direct vers le quiz. Ce mécanisme est déclenché par un cron job externe (cron-job.org) qui appelle une route admin protégée une fois par jour.

---

## 📬 Contact

**Discord :** lemeilleur0101

Pour toute question sur le site, une reprise du projet, ou une proposition de collaboration.

---

*Projet développé en autonomie avec Flask (Python), PostgreSQL, Jinja2, Chart.js. Hébergé sur Render. Données de conjugaison : [alexey-beshenov/conjugaison](https://github.com/alexey-beshenov/conjugaison) (open-source).*
