# Bot TikTok → YouTube

POC d'automatisation pour préparer et piloter un flux de publication vidéo depuis des assets locaux. Il sert à réduire les manipulations répétitives : préparation du média, ouverture d'une session navigateur contrôlée et exécution du parcours de publication.

## Statut

**POC en évolution** — pas un service prêt à déployer tel quel. Le lanceur YouTube privilégie une exécution vérifiable : `dry-run` activé par défaut et visibilité `private` par défaut.

## Stack

- Python 3.10+
- Playwright / Chromium
- MoviePy, Pillow, NumPy — préparation média
- aiohttp, Requests, PyYAML, python-dotenv

## Lancer

```powershell
git clone https://github.com/legadu39/bot-tiktok-youtube.git
cd bot-tiktok-youtube

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

Copier puis renseigner les fichiers d'exemple nécessaires à ton environnement : `.env.example` et `config.example.yaml`.

Ouvrir une session navigateur contrôlée :

```powershell
python youtube_cli_launcher.py --login
```

Valider un envoi sans publier :

```powershell
python youtube_cli_launcher.py --dry-run --privacy private --video "C:\chemin\video.mp4"
```

Ne retirer `--dry-run` qu'après vérification du titre, de la description, du compte et de la visibilité.

## Repères du dépôt

- `youtube_cli_launcher.py` : point d'entrée YouTube.
- `gemini_headless/` : briques d'automatisation et de collecte.
- `assets_vault/` et `temp/` : espaces de travail ; ils ne définissent pas le fonctionnement du projet.

Ne versionne jamais profils navigateur, cookies, clés, variables `.env` ni médias personnels.