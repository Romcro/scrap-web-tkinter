# CONTEXT.md — Outil de bureau d'extraction d'adresses e-mail

> Ce document décrit le contexte, le périmètre, l'architecture et les règles du projet.
> Il sert de référence à toute personne (ou assistant IA) qui travaille sur le code.

---

## 1. Présentation du projet

### 1.1 Objectif
Développer une **application de bureau en Python avec une interface Tkinter** qui :
1. reçoit une **liste de sites web de référence** (saisie manuelle ou import de fichier) ;
2. **parcourt automatiquement** les pages de chaque site (crawl limité au domaine) ;
3. **extrait les adresses e-mail** publiées sur ces pages ;
4. **affiche les résultats** en temps réel et permet de les **exporter** (CSV / Excel).

### 1.2 Utilisateurs cibles
Utilisateur non développeur (commercial, assistant, chargé de prospection) qui veut récupérer
les e-mails de contact publiés sur une liste de sites connus, sans ligne de commande.

### 1.3 Ce que l'outil N'EST PAS
- Pas un moteur de recherche : il ne découvre pas de sites par lui-même, il ne traite **que les URL fournies**.
- Pas un outil d'envoi d'e-mails ni de campagne.
- Pas un outil de contournement (pas de bypass de CAPTCHA, de login, de paywall ou de protections anti-bot).

---

## 2. Périmètre fonctionnel

### 2.1 Fonctionnalités du MVP (v1)

| # | Fonctionnalité | Détail |
|---|----------------|--------|
| F1 | Saisie des sites | Zone de texte multi-lignes (une URL par ligne) |
| F2 | Import de liste | Import d'un fichier `.txt` ou `.csv` (une URL par ligne / colonne `url`) |
| F3 | Normalisation des URL | Ajout de `https://` si absent, suppression des doublons et lignes vides |
| F4 | Crawl par site | Exploration des liens internes au même domaine, avec profondeur max et nombre max de pages configurables |
| F5 | Pages prioritaires | Visite en priorité des pages type `contact`, `mentions-legales`, `about`, `a-propos`, `equipe`, `team`, `impressum` |
| F6 | Extraction | Regex sur le texte + liens `mailto:` + formes obfusquées simples (`[at]`, `(at)`, ` arobase `, `[dot]`) |
| F7 | Filtrage | Exclusion des faux positifs (`image@2x.png`, `exemple@example.com`, `noreply@`, domaines de tracking type `sentry`, `wixpress`…) |
| F8 | Déduplication | Un e-mail = une ligne, avec rattachement au site et à la page source |
| F9 | Affichage temps réel | Tableau (Treeview) : e-mail, site, page source, date |
| F10 | Progression | Barre de progression + compteur (sites traités, pages visitées, e-mails trouvés) |
| F11 | Contrôle | Boutons **Démarrer**, **Arrêter** (arrêt propre) |
| F12 | Export | CSV (UTF-8 avec BOM pour Excel) et XLSX |
| F13 | Journal | Zone de log (erreurs HTTP, timeouts, pages ignorées) + fichier `logs/app.log` |
| F14 | Paramètres | Profondeur, pages max/site, délai entre requêtes, timeout, nb de threads, respect du `robots.txt` |

### 2.2 Évolutions envisagées (v2+)
- Pause / reprise d'une session.
- Sauvegarde / rechargement d'un projet (liste de sites + résultats) en JSON ou SQLite.
- Rendu JavaScript optionnel (Playwright) pour les sites dynamiques.
- Extraction complémentaire : téléphones, réseaux sociaux, nom de l'entreprise.
- Validation syntaxique avancée + vérification MX du domaine.
- Thème sombre / ttkbootstrap.
- Historique des exécutions.

---

## 3. Stack technique

| Élément | Choix | Justification |
|---------|-------|---------------|
| Langage | Python **3.11+** | Typage moderne, performances |
| Interface | **Tkinter + ttk** (stdlib) | Aucune dépendance graphique, multiplateforme |
| Requêtes HTTP | `requests` (+ `requests.Session`) | Simple, fiable, gestion des cookies/headers |
| Parsing HTML | `beautifulsoup4` + `lxml` | Robuste sur du HTML mal formé |
| Robots.txt | `urllib.robotparser` (stdlib) | Respect des règles des sites |
| URL | `urllib.parse` (stdlib) | Normalisation, `urljoin`, comparaison de domaines |
| Concurrence | `threading` + `concurrent.futures.ThreadPoolExecutor` + `queue.Queue` | Ne pas bloquer l'UI |
| Export Excel | `openpyxl` | Écriture `.xlsx` |
| Domaines | `tldextract` (optionnel) | Comparaison fiable du domaine racine |
| Logs | `logging` (stdlib) | Fichier + affichage UI |
| Tests | `pytest` | Tests unitaires de l'extraction et du crawl |
| Packaging | `PyInstaller` | Génération d'un `.exe` / binaire autonome |

### `requirements.txt`
```
requests>=2.31
beautifulsoup4>=4.12
lxml>=5.0
openpyxl>=3.1
tldextract>=5.1
```
`requirements-dev.txt` : `pytest`, `pyinstaller`, `ruff`, `mypy`.

---

## 4. Architecture

### 4.1 Principe
Séparation stricte **interface / logique métier** :
- le **cœur** (crawl, extraction, export) ne connaît pas Tkinter et est testable seul ;
- l'**UI** ne fait aucune requête réseau : elle lance un worker et lit ses messages.

```
┌─────────────────────────┐        commandes (start/stop)        ┌──────────────────────────┐
│        UI Tkinter       │ ───────────────────────────────────▶ │  ScraperController       │
│  (thread principal)     │                                      │  (thread de fond)        │
│                         │ ◀─────────── queue.Queue ─────────── │   ├─ Crawler (par site)  │
│  root.after(100, poll)  │   événements : progress, email,      │   ├─ EmailExtractor      │
└─────────────────────────┘   log, error, done                   │   └─ RobotsCache         │
                                                                 └──────────────────────────┘
```

### 4.2 Arborescence du projet
```
email-scraper/
├── CONTEXT.md
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── main.py                     # Point d'entrée : lance l'application
├── config/
│   └── settings.json           # Paramètres par défaut (modifiables via l'UI)
├── app/
│   ├── __init__.py
│   ├── ui/
│   │   ├── main_window.py      # Fenêtre principale, layout
│   │   ├── settings_dialog.py  # Fenêtre des paramètres
│   │   └── widgets.py          # Composants réutilisables (tableau, log)
│   ├── core/
│   │   ├── controller.py       # Orchestration, threads, file d'événements
│   │   ├── crawler.py          # Parcours des pages d'un site
│   │   ├── extractor.py        # Extraction + nettoyage des e-mails
│   │   ├── filters.py          # Listes d'exclusion, règles de faux positifs
│   │   ├── robots.py           # Cache et vérification robots.txt
│   │   └── url_utils.py        # Normalisation, même domaine, priorisation
│   ├── io/
│   │   ├── importer.py         # Lecture .txt / .csv
│   │   └── exporter.py         # Écriture .csv / .xlsx
│   └── models.py               # Dataclasses : EmailResult, CrawlStats, Settings, Event
├── logs/
├── exports/
└── tests/
    ├── test_extractor.py
    ├── test_url_utils.py
    ├── test_crawler.py         # avec réponses HTTP simulées
    └── fixtures/               # pages HTML d'exemple
```

### 4.3 Modèles de données (`models.py`)
```python
@dataclass(frozen=True)
class EmailResult:
    email: str            # en minuscules, nettoyé
    site: str             # domaine de référence fourni par l'utilisateur
    source_url: str       # page où l'e-mail a été trouvé
    found_at: datetime
    method: str           # "mailto" | "regex" | "obfuscated"

@dataclass
class CrawlStats:
    sites_total: int = 0
    sites_done: int = 0
    pages_visited: int = 0
    emails_found: int = 0
    errors: int = 0

@dataclass
class Settings:
    max_depth: int = 2
    max_pages_per_site: int = 50
    delay_seconds: float = 1.0
    timeout_seconds: int = 10
    max_workers: int = 4          # sites traités en parallèle
    respect_robots: bool = True
    user_agent: str = "EmailScraperDesktop/1.0 (+contact@votre-domaine.fr)"

@dataclass
class Event:
    type: Literal["progress", "email", "log", "error", "site_done", "done"]
    payload: Any
```

---

## 5. Règles métier détaillées

### 5.1 Crawl
- Démarrer depuis l'URL fournie ; parcours **en largeur (BFS)** avec une file de priorité :
  les URL contenant les mots-clés de F5 passent en tête.
- Ne suivre **que les liens du même domaine** (sous-domaines `www.` inclus).
- Ignorer : ancres `#`, `javascript:`, `tel:`, fichiers non HTML (`.pdf`, `.jpg`, `.png`, `.zip`, `.mp4`, `.css`, `.js`…).
- Vérifier le `Content-Type` : ne parser que `text/html`.
- Mémoriser les URL visitées (après normalisation : sans fragment, sans slash final superflu).
- Arrêter le site quand `max_depth` ou `max_pages_per_site` est atteint.
- Respecter `delay_seconds` **entre deux requêtes d'un même domaine**.
- Gérer les redirections, les erreurs 4xx/5xx, les timeouts, les erreurs SSL : log + passage à la suite, **jamais de crash**.
- Relance limitée (1 retry) sur 429 / 503, en respectant l'en-tête `Retry-After` s'il est présent.

### 5.2 Extraction
- Regex de base (à affiner dans les tests) :
  ```python
  EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
  ```
- Sources analysées, par ordre de fiabilité :
  1. attributs `href="mailto:..."` (décoder `%40`, retirer `?subject=...`) ;
  2. texte visible de la page ;
  3. formes obfusquées : `nom [at] domaine [dot] fr`, `nom(at)domaine.fr`, `nom arobase domaine point fr`.
- Nettoyage : minuscules, suppression ponctuation finale (`.`, `,`, `;`, `)`), décodage des entités HTML.

### 5.3 Filtrage des faux positifs
Exclure une adresse si :
- l'extension finale ressemble à un fichier : `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`, `.webp`, `.css`, `.js` ;
- le domaine est un domaine d'exemple ou technique : `example.com`, `domain.com`, `email.com`, `sentry.io`, `wixpress.com`, `sentry-next.wixpress.com`… ;
- la partie locale est générique non exploitable (paramétrable) : `noreply`, `no-reply`, `donotreply` ;
- la longueur est aberrante (> 254 caractères ou partie locale > 64).

Les listes d'exclusion sont dans `filters.py` et **modifiables** sans toucher au reste du code.

---

## 6. Interface utilisateur

### 6.1 Disposition de la fenêtre principale
```
┌──────────────────────────────────────────────────────────────────────┐
│  Menu : Fichier (Importer, Exporter CSV, Exporter XLSX, Quitter)     │
│         Outils (Paramètres)   Aide (À propos)                        │
├──────────────────────────────────────────────────────────────────────┤
│  Sites de référence (1 URL par ligne)         [Importer…] [Vider]    │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ https://site1.fr                                               │  │
│  │ site2.com                                                      │  │
│  └────────────────────────────────────────────────────────────────┘  │
│  [▶ Démarrer]  [■ Arrêter]      Profondeur [2]  Pages max/site [50]  │
├──────────────────────────────────────────────────────────────────────┤
│  Progression ███████████░░░░░░  12/30 sites · 340 pages · 87 e-mails │
├──────────────────────────────────────────────────────────────────────┤
│  Résultats                                   Filtre : [__________]   │
│  ┌──────────────────┬────────────┬──────────────────────┬────────┐   │
│  │ E-mail           │ Site       │ Page source          │ Méthode│   │
│  ├──────────────────┼────────────┼──────────────────────┼────────┤   │
│  │ contact@site1.fr │ site1.fr   │ https://site1.fr/... │ mailto │   │
│  └──────────────────┴────────────┴──────────────────────┴────────┘   │
│  [Copier la sélection]  [Exporter CSV]  [Exporter XLSX]              │
├──────────────────────────────────────────────────────────────────────┤
│  Journal (repliable)                                                 │
│  12:04:31  [INFO]  site1.fr : 14 pages visitées, 3 e-mails           │
│  12:04:35  [WARN]  site2.com : timeout sur /blog                     │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.2 Règles UI
- **Aucun appel réseau dans le thread Tkinter.** Toute mise à jour de widget se fait dans le thread principal via `root.after(100, self._poll_queue)` qui vide la `queue.Queue`.
- Pendant un scraping : **Démarrer** désactivé, **Arrêter** actif, zone d'URL en lecture seule.
- L'arrêt utilise un `threading.Event` (`stop_event`) vérifié par le crawler entre chaque page.
- Fermeture de la fenêtre pendant un scraping : demander confirmation, déclencher `stop_event`, attendre proprement.
- Tri des colonnes au clic sur l'en-tête ; double-clic sur une ligne = ouvrir la page source dans le navigateur (`webbrowser.open`).
- Messages d'erreur compréhensibles (`messagebox`) pour l'utilisateur, détails techniques dans le journal.
- Utiliser les widgets `ttk` pour un rendu natif.

---

## 7. Export
- **CSV** : séparateur `;` (compatibilité Excel FR), encodage `utf-8-sig`, colonnes :
  `email;site;page_source;methode;date_trouvee`.
- **XLSX** : même colonnes, en-tête en gras, largeur de colonnes ajustée, filtre automatique.
- Nom de fichier proposé par défaut : `exports/emails_AAAA-MM-JJ_HHMM.csv`.

---

## 8. Configuration et logs
- `config/settings.json` chargé au démarrage ; valeurs par défaut si absent ou invalide ; sauvegardé depuis la fenêtre Paramètres.
- Logs : `logs/app.log` avec rotation (`RotatingFileHandler`, 1 Mo × 3), niveau INFO par défaut, DEBUG activable.

---

## 9. Cadre légal et éthique (à respecter dans le code)

L'outil collecte des **données personnelles** (une adresse e-mail nominative en est une).
En France / UE, le **RGPD** et les recommandations de la **CNIL** s'appliquent, même si les adresses sont publiques.

Règles intégrées à l'outil :
- **Respect du `robots.txt`** activé par défaut.
- **Délai entre requêtes** (≥ 1 s par défaut) et nombre limité de pages par site : ne pas surcharger les serveurs.
- **User-Agent identifiable** avec un moyen de contact (pas d'usurpation d'un navigateur).
- Pas de contournement de protections (CAPTCHA, authentification, blocage IP).
- Traçabilité : chaque e-mail conserve sa **page source**, utile pour informer la personne de l'origine de la donnée.

Rappels pour l'utilisateur (à afficher dans « À propos » ou au premier lancement) :
- Vérifier les **conditions générales d'utilisation** des sites ciblés.
- La prospection par e-mail de **particuliers** exige en principe leur **consentement préalable** ; en **B2B**, elle est possible si le message concerne la fonction de la personne et qu'un **droit d'opposition** simple est proposé.
- Informer les personnes, limiter la durée de conservation, tenir un registre de traitement, supprimer les données sur demande.

> Ce rappel n'est pas un avis juridique : en cas de doute, se référer aux fiches de la CNIL ou à un juriste.

---

## 10. Qualité et conventions de code
- Style **PEP 8**, formatage/lint avec `ruff`, typage complet (`mypy` en mode strict sur `app/core`).
- Docstrings en français, noms de variables et fonctions en anglais.
- Fonctions courtes, une responsabilité par module.
- Aucune valeur « magique » dans le code : constantes dans `filters.py` / `settings.json`.
- Toute exception réseau est capturée au niveau de la page, jamais remontée jusqu'à l'UI.

### Tests minimum attendus
- `test_extractor.py` : mailto encodé, texte brut, formes obfusquées, faux positifs (`logo@2x.png`), ponctuation finale, doublons, majuscules.
- `test_url_utils.py` : normalisation, même domaine (`www.`, sous-domaine), exclusion d'extensions, priorisation des pages contact.
- `test_crawler.py` : respect de `max_depth` / `max_pages`, arrêt via `stop_event`, gestion des erreurs HTTP (réponses simulées, aucun accès réseau réel).

---

## 11. Lancement et packaging
```bash
# Installation
python -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\activate
pip install -r requirements.txt

# Lancement
python main.py

# Tests
pytest -q

# Exécutable autonome
pyinstaller --noconsole --onefile --name EmailScraper main.py
```

---

## 12. Plan de réalisation

| Étape | Contenu | Livrable |
|-------|---------|----------|
| 1 | Squelette du projet, `models.py`, `url_utils.py`, `extractor.py` + tests | Extraction fiable testée hors UI |
| 2 | `crawler.py` + `robots.py` + tests avec réponses simulées | Crawl d'un site en ligne de commande |
| 3 | `controller.py` : threads, `queue`, `stop_event`, statistiques | Orchestration multi-sites |
| 4 | Fenêtre principale Tkinter (saisie, boutons, tableau, progression, log) | Application utilisable |
| 5 | Import / export CSV-XLSX, fenêtre Paramètres, `settings.json` | MVP complet |
| 6 | Finitions : tri, filtre, copier, confirmations, packaging PyInstaller | v1.0 distribuable |

---

## 13. Critères d'acceptation du MVP
- [ ] Je colle 10 URL, je clique sur **Démarrer** : l'interface reste fluide pendant tout le traitement.
- [ ] Les e-mails apparaissent au fur et à mesure, sans doublon, avec leur page source.
- [ ] **Arrêter** interrompt le traitement en moins de quelques secondes, sans crash.
- [ ] Un site injoignable ou en erreur n'interrompt pas les autres.
- [ ] Les faux positifs courants (images, domaines d'exemple) ne sont pas listés.
- [ ] L'export CSV s'ouvre correctement dans Excel (accents, colonnes séparées).
- [ ] Le `robots.txt` et le délai entre requêtes sont respectés par défaut.
- [ ] Les tests `pytest` passent.
