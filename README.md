# Claude Pet

Un petit compagnon flottant qui réagit en temps réel à l'activité de [Claude Code](https://claude.com/claude-code) : un personnage pixel-art dans une fenêtre native, toujours au-dessus, qui change d'expression et d'animation selon ce que fait Claude (édition, tests, attente, erreur, terminé...).

macOS uniquement pour l'instant.

## Installation

```bash
git clone <url-du-repo>
cd pet
./install.sh
```

Ça installe les fichiers dans `~/.claude/pet/`, crée un environnement Python dédié (`~/.claude/pet/venv`), et ajoute les hooks nécessaires à `~/.claude/settings.json` **sans toucher à tes hooks existants** (fusion idempotente, backup automatique avant modification).

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
install.sh          # installe/copie les fichiers, crée le venv, ajoute les hooks
uninstall.sh         # retire les hooks, ferme les pets, supprime ~/.claude/pet
src/
  pet.html            # rendu (SVG + CSS + JS), état piloté par window.setPetState/setPetSkin
  pet_app.py           # fenêtre pywebview, un process par session, watchdog, clic → focus
  update_state.sh      # appelé par les hooks Claude Code, écrit l'état par session
  start_pet.sh          # lance pet_app.py pour une session donnée
  install_hooks.py      # fusion idempotente des hooks dans settings.json
```

Pour ajuster le design (couleurs, formes, textes des états), tout se passe dans `src/pet.html` (objet `STATES` en JS, blocs SVG `<g data-only="...">`). Après modification, relance `./install.sh` pour redéployer dans `~/.claude/pet/`.
