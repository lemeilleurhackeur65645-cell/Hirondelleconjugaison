# Copie corrigée pour la sécurité

Le fichier `main.py` est une copie corrigée ; le `main.py` original à la racine n'a pas été modifié.

Pour appliquer ces corrections manuellement :

1. Sauvegardez le `main.py` original, puis remplacez-le par cette copie à la racine du projet. Ne lancez pas cette copie depuis le dossier `security_fixes` : l'application y chercherait ses données.
2. Dans les variables d'environnement de l'hébergeur, définissez `SECRET_KEY` avec une valeur aléatoire longue et privée. L'application refusera désormais de démarrer si elle est absente.
3. Définissez également `INDEXNOW_ADMIN_TOKEN` avec une valeur aléatoire longue et privée. Sans ce paramètre, la route de nettoyage renverra une erreur au lieu de poursuivre.
4. Redéployez l'application. Si l'ancienne clé secrète a été utilisée en production, remplacez-la par une nouvelle valeur pour invalider les sessions existantes.

Les valeurs secrètes doivent être générées et conservées dans les paramètres secrets de l'hébergeur ; ne les inscrivez pas dans le code ni dans Git.
