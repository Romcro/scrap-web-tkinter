# Extracteur d'e-mails

Application de bureau qui récupère les adresses e-mail **publiées** sur une liste de sites que
vous fournissez. Elle parcourt les pages de chaque site (contact, mentions légales, équipe… en
priorité) et affiche les adresses trouvées avec la page où elles apparaissent.

> Les adresses e-mail nominatives sont des données personnelles (RGPD). Lisez le rappel dans
> **Aide > À propos** avant d'utiliser les résultats.

## Utilisation

1. Lancez `EmailScraper.exe` (ou `python main.py` depuis les sources).
2. Saisissez les sites, un par ligne (`site.fr`, `https://www.site2.com`…), ou cliquez sur
   **Importer…** pour charger un fichier `.txt` (une adresse par ligne) ou `.csv` (colonne
   `url` ou `site`, sinon la première colonne).
3. Réglez au besoin **Profondeur** (nombre de clics depuis l'accueil) et **Pages max/site**.
4. Cliquez sur **▶ Démarrer** (ou Ctrl+Entrée). **■ Arrêter** interrompt proprement.
5. Exportez les résultats en **CSV** (s'ouvre directement dans Excel) ou **XLSX**. Seules les
   lignes affichées (filtre appliqué) sont exportées.

Dans le tableau : clic sur un en-tête pour trier, champ **Filtre** pour chercher, double-clic
pour ouvrir la page source, Ctrl+A puis **Copier la sélection** (ou Ctrl+C) pour copier les
adresses.

Raccourcis : Ctrl+O importer · Ctrl+S exporter en CSV · Ctrl+F filtrer.

## Paramètres (Outils > Paramètres)

| Paramètre | Défaut | Rôle |
|-----------|--------|------|
| Profondeur | 2 | Clics depuis la page de départ (0 à 10) |
| Pages max par site | 50 | Limite par site (1 à 1000) |
| Délai entre requêtes | 1 s | Pause entre deux pages d'un même site (0,5 à 60 s) |
| Délai max d'une requête | 10 s | Au-delà, la page est abandonnée |
| Sites en parallèle | 4 | Sites différents traités en même temps |
| Respecter robots.txt | oui | Ne visite pas les pages que le site demande d'éviter |
| Inclure les sous-domaines | non | `blog.site.fr` est-il traité avec `site.fr` ? |
| User-Agent | … | **Mettez votre adresse de contact à la place de l'exemple** |
| Journal détaillé | non | Plus de détails dans `logs/app.log` |

Les paramètres sont enregistrés dans `config/settings.json`.

## Fichiers

- `exports/` : dossier proposé pour les exports (`emails_AAAA-MM-JJ_HHMM.csv`).
- `logs/app.log` : journal technique (3 fichiers de 1 Mo au maximum).

## Développement

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements-dev.txt

python main.py                         # interface
python -m app.cli site.fr --pages 10   # ligne de commande, sans interface
pytest                                 # tests (aucun accès réseau)
ruff check . ; mypy                    # qualité du code
.\build.ps1                            # exécutable dist\EmailScraper\EmailScraper.exe
```

Pour signer l'exécutable (évite l'avertissement Windows SmartScreen), installez un certificat
de signature de code dans le magasin de l'utilisateur, puis :

```powershell
$env:SIGN_CERT_THUMBPRINT = "<empreinte du certificat>"
.\build.ps1
```

Le fichier `CONTEXT.md` décrit l'architecture et les règles du projet.
