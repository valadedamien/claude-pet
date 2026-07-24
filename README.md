# Claude Pet

Un petit compagnon flottant qui réagit en temps réel à l'activité de [Claude Code](https://claude.com/claude-code) : un personnage pixel-art dans une fenêtre native, toujours au-dessus, qui change d'expression et d'animation selon ce que fait Claude (édition, tests, attente, erreur, terminé...).

macOS (Apple Silicon) uniquement pour l'instant.

## Installation

```bash
git clone git@github.com:valadedamien/claude-pet.git
cd claude-pet
./install.sh
```

`install.sh` copie les fichiers dans `~/.claude/pet/`, télécharge le binaire précompilé (dernière [Release GitHub](https://github.com/valadedamien/claude-pet/releases/latest)) — **aucune dépendance Python à installer pour faire tourner l'app elle-même**, seul `python3` (déjà présent sur la plupart des Mac de dev) est requis pour les petits scripts de hooks. Les hooks nécessaires sont ajoutés à `~/.claude/settings.json` **sans toucher à tes hooks existants** (fusion idempotente, backup automatique avant modification).

Ouvre (ou relance) `claude` dans un terminal : le pet apparaît automatiquement.

## Désinstallation

```bash
./uninstall.sh
```

Retire uniquement les hooks ajoutés par Claude Pet, ferme les fenêtres actives, et supprime `~/.claude/pet/`.

## Fonctionnement

- **Un pet par conversation** : chaque session `claude` a sa propre fenêtre, sa propre couleur (parmi une palette de 6), positionnée en cascade pour ne pas se superposer. Fermeture automatique (propre via `SessionEnd`, ou via un filet de sécurité qui vérifie toutes les ~3s que le process `claude` parent est toujours vivant) si la session se termine, même brutalement.
- **7 états** : au repos, occupé, en train d'écrire, en train de tester, en attente (permission), erreur, terminé — déclenchés par les hooks `PreToolUse`/`PostToolUse`/`PostToolUseFailure`/`Notification`/`Stop`.
- **Clic pour retrouver le terminal** : cliquer sur le pet ramène au premier plan l'application (Terminal, iTerm, VS Code...) qui a lancé cette session.
- Design pixel-art conçu avec Claude Design, implémenté en SVG/CSS/JS pur (pas de dépendance de rendu).

## Structure du projet

```
install.sh          # copie les fichiers, télécharge le binaire (Release), ajoute les hooks
uninstall.sh         # retire les hooks, ferme les pets, supprime ~/.claude/pet
src/
  pet.html            # rendu (SVG + CSS + JS), état piloté par window.setPetState/setPetSkin
  pet_app.py           # fenêtre pywebview, un process par session, watchdog, clic → focus
  update_state.sh      # appelé par les hooks Claude Code, écrit l'état par session
  start_pet.sh          # lance l'app compilée pour une session donnée
  install_hooks.py      # fusion idempotente des hooks dans settings.json
build/
  setup.py              # config py2app pour compiler src/pet_app.py
  build.sh               # build + zip → build/dist/Claude-Pet-macos-arm64.zip
```

Pour ajuster le design (couleurs, formes, textes des états), tout se passe dans `src/pet.html` (objet `STATES` en JS, blocs SVG `<g data-only="...">`). `pet.html` est copié tel quel par `install.sh`, donc pas besoin de recompiler pour ce fichier — relance juste `./install.sh`.

Pour modifier `pet_app.py` (logique Python : sessions, watchdog, clic → focus...), il faut recompiler et publier une nouvelle release :

```bash
./build/build.sh                          # produit build/dist/Claude-Pet-macos-arm64.zip
gh release create v0.x.0 build/dist/Claude-Pet-macos-arm64.zip --title "..." --notes "..."
```

`install.sh` télécharge toujours la **dernière** release, donc les collègues récupèrent la mise à jour au prochain `git pull` + `./install.sh`.

### Pourquoi py2app et pas PyInstaller

PyInstaller compile bien `pet_app.py`, mais la fenêtre pywebview n'apparaît jamais une fois le binaire "frozen" (aucune erreur, la fenêtre Cocoa n'est simplement jamais créée) — testé en onefile, en `.app` exécuté directement, et via `open`. py2app, spécifique à macOS et pensé pour les apps pyobjc, fonctionne du premier coup. Le build doit se faire dans un venv qui **n'a pas** PyInstaller installé à côté : le scanner statique de py2app trébuche sur les hooks PyInstaller embarqués par pywebview (`build/build.sh` s'occupe de tout ça dans un venv isolé).
