<p align="center">
  <a href="README.md">English</a> | <a href="README.zh-Hans.md">简体中文</a> | <a href="README.ja.md">日本語</a> | <a href="README.de.md">Deutsch</a> | <a href="README.ko.md">한국어</a> | <b>Français</b> | <a href="README.pt-BR.md">Português (Brasil)</a> | <a href="README.es.md">Español</a>
</p>

# Bean Network Tester 🫘 - simulateur de mauvaises conditions réseau (Windows) 
<p align="center">
  <b>Suivez-moi :</b>
  &nbsp
  <a href="https://discord.gg/bDTu8HX"><img src="https://cdn.simpleicons.org/discord/5865F2" alt="Discord" height="26" align="absmiddle"></a>
  &nbsp
  <a href="https://facebook.com/donislawdev"><img src="https://cdn.simpleicons.org/facebook/0866FF" alt="Facebook" height="26" align="absmiddle"></a>
  &nbsp
  <a href="https://x.com/donislawdev"><picture><source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/x/FFFFFF"><img src="https://cdn.simpleicons.org/x/000000" alt="X (Twitter)" height="26" align="absmiddle"></picture></a>
  &nbsp
  <a href="https://bsky.app/profile/donislawdev.bsky.social"><img src="https://cdn.simpleicons.org/bluesky/0285FF" alt="Bluesky" height="26" align="absmiddle"></a>
  &nbsp
 <a href="https://store.steampowered.com/developer/DonislawDev"><picture><source media="(prefers-color-scheme: dark)" srcset="https://cdn.simpleicons.org/steam/FFFFFF"><img src="https://cdn.simpleicons.org/steam/000000" alt="Steam" height="26" align="absmiddle"></picture></a>
</p>

[![CI](https://github.com/donislawdev/BeanNetworkTester/actions/workflows/ci.yml/badge.svg)](https://github.com/donislawdev/BeanNetworkTester/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/donislawdev/BeanNetworkTester?sort=semver)](https://github.com/donislawdev/BeanNetworkTester/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/donislawdev/BeanNetworkTester/total)](https://github.com/donislawdev/BeanNetworkTester/releases)
[![License: GPLv3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/donislawdev/BeanNetworkTester/badge)](https://scorecard.dev/viewer/?uri=github.com/donislawdev/BeanNetworkTester)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14154/badge)](https://www.bestpractices.dev/projects/14154)
![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6)
![Platform: Linux (experimental)](https://img.shields.io/badge/platform-Linux%20%28experimental%29-FCC624)

**Bean Network Tester** est un outil pour les testeurs et les développeurs : il permet de vérifier
comment votre application se comporte sur une mauvaise connexion. Comme Clumsy ou NetLimiter, il
vous laisse dégrader le réseau volontairement - ajouter du ping, abandonner des paquets, plafonner
le débit, couper des connexions, et plus encore. Il fonctionne en interceptant le trafic grâce au
pilote **[WinDivert](https://www.reqrypt.org/windivert.html)** (via
**[PyDivert](https://github.com/ffalcinelli/pydivert)**), et propose à la fois une interface
fenêtrée claire, avec des infobulles, et un mode ligne de commande pour la CI.

⭐ **S'il vous a fait gagner du temps, laissez une étoile.** C'est ainsi que le prochain testeur qui
en a besoin apprendra qu'il existe.

**Ce qu'il sait faire**

- **Ajouter de la latence et de la gigue** - un délai fixe ou aléatoire, plus des pics occasionnels.
- **Abandonner, corrompre ou dupliquer des paquets** - la perte peut arriver par rafales, comme
  une vraie liaison sans fil qui défaille.
- **Plafonner le débit en téléchargement et en envoi** - limitez à un nombre fixe de KB/s, avec un
  tampon qui ajoute un délai de file d'attente avant de commencer à abandonner des paquets.
- **Couper des connexions** - réinitialisations TCP, liaison morte, ou nouvelles connexions qui
  ne s'établissent jamais.
- **Faire osciller la liaison** - des coupures qui vont et viennent.
- **Casser le chemin, pas seulement les paquets** - un trou noir MTU et des délais d'inactivité
  façon NAT.
- **Bloquer des ports ou des IP** - un petit pare-feu intégré, plus le mode LAN (sans Internet) et
  le mode Internet seul (sans réseau local).
- **Viser une seule application** - par nom de processus, PID, IP, port, ou une seule famille
  d'adresses.
- **Profils prêts à l'emploi et profils enregistrés** - modem 56k, Wi-Fi de café, satellite, Wi-Fi
  en avion et plus encore.
- **Exécuter des scénarios scriptés** - des étapes minutées qui modifient le réseau toutes seules.
- **Programmer la limite de débit** - une chronologie répétée de débits, sans écrire de scénario.
- **Reproductible grâce à une graine** - rejouez exactement la même perte et la même gigue
  aléatoires.
- **Transmettre un bug** - un rapport avec tous les réglages, les compteurs et la ligne de commande
  qui refait l'exécution.
- **Observer en direct** - graphique, compteurs, table des connexions avec recherche et journal
  d'événements.
- **Exporter en CSV** - les statistiques de la session et un instantané de la table des connexions.
- **Mode ligne de commande** - scriptable pour la CI, avec des codes de sortie et une sortie JSON.
- **Aucune télémétrie, n'envoie rien de lui-même** - l'outil Ping ne pingue que l'adresse que
  vous saisissez.

<p align="center">
  <img src="docs/demo.gif" alt="Bean Network Tester ajoutant du lag et de la perte de paquets à un ping en direct" width="820">
</p>

<p align="center">
  <a href="https://github.com/donislawdev/BeanNetworkTester"><img src="docs/star.gif" alt="Il vous plaît ? Mettez une étoile à Bean Network Tester sur GitHub" width="820"></a>
</p>

**Table des matières**

- [Démarrage rapide (3 étapes)](#démarrage-rapide-3-étapes)
- [Langue](#langue)
- [Prérequis](#prérequis)
- [La fenêtre](#la-fenêtre)
- [Toutes les options expliquées](#toutes-les-options-expliquées)
- [Syntaxe des filtres (processus / IP / port)](#syntaxe-des-filtres-processus--ip--port)
- [Statistiques (ce que signifient les compteurs)](#statistiques-ce-que-signifient-les-compteurs)
- [Fichier de configuration](#fichier-de-configuration)
- [Mode ligne de commande (CLI)](#mode-ligne-de-commande-cli)
- [Colonnes de la page Connections](#colonnes-de-la-page-connections)
- [Exports CSV](#exports-csv)
- [Format du fichier de scénario](#format-du-fichier-de-scénario)
- [Recettes CI/CD](#recettes-cicd)
- [Construire un .exe](#construire-un-exe)
- [Pièges à connaître (à lire avant de signaler un bug)](#pièges-à-connaître-à-lire-avant-de-signaler-un-bug)
- [Tests](#tests)
- [Organisation du projet](#organisation-du-projet)
- [Fonctionnement (en bref)](#fonctionnement-en-bref)
- [Remarques et limitations](#remarques-et-limitations)
- [Contribuer](#contribuer)
- [Soutenir le projet](#soutenir-le-projet)
- [Auteur](#auteur)
- [Licence](#licence)
- [Composants tiers](#composants-tiers)
- [Vie privée : aucune télémétrie](#vie-privée--aucune-télémétrie)
- [À propos de SmartScreen et des antivirus](#à-propos-de-smartscreen-et-des-antivirus)

## Démarrage rapide (3 étapes)

1. Téléchargez `BeanNetworkTester` : le **zip** s'exécute sans rien installer, le **`.msi`**
   l'installe pour tous les utilisateurs de l'ordinateur, dans le `PATH` et dans le menu Démarrer
   (il demande les droits d'administrateur). Ou construisez-le vous-même :
   `pyinstaller --noconfirm BeanNetworkTester.spec`.
2. Lancez `BeanNetworkTester.exe` - le programme **demande lui-même les droits d'administrateur**
   (WinDivert en a besoin). Depuis le dépôt : `python bean_network_tester.py`.
3. Choisissez un profil prêt à l'emploi dans la liste "Profiles" (par ex. "3G network") et cliquez
   sur **START**.

Le **même fichier** exécute le mode texte : `BeanNetworkTester.exe --simulate --loss 10 --duration 5`.

En haut de la fenêtre, une barre "Active: ..." résume ce que vous faites en ce moment
(par ex. *Active: +150 ms ping, 1% loss, download <= 384 KB/s*). Survolez n'importe quel champ pour
obtenir une infobulle qui explique son rôle.

> Remarque : choisir un profil ne fait que remplir les champs - la dégradation ne démarre qu'avec
> **START**. Sans les droits d'administrateur, le pilote WinDivert ne se chargera pas.

Vous cherchez une tâche précise plutôt que le manuel complet ci-dessous ? Les
[guides du site web](https://beannetworktester.donislawdev.com/fr/) expliquent pas à pas la perte de
paquets, la latence, les limites de débit, comment viser une seule application et comment tester
sans Internet, chacun avec les valeurs qui valent la peine d'être essayées et la commande qui les
applique. Deux autres guides montrent comment trouver quel programme occupe un port, et quoi
utiliser à la place de `tc netem` ou de Network Link Conditioner. Les guides sont rédigés en 22
langues, de l'anglais et du polonais à l'arabe et au vietnamien.

## Langue

Les traductions se trouvent dans des fichiers **`lang/<code>.json`** (fournis : `lang/en.json`,
`lang/pl.json` et `lang/zh.json`, qui est du chinois simplifié). Au démarrage, l'application
**analyse le dossier `lang/`** et détecte automatiquement les langues disponibles. La langue de
démarrage suit les paramètres régionaux de votre système lorsqu'une traduction correspondante
existe, et revient sinon à l'anglais. Un système réglé sur le chinois traditionnel obtient lui aussi
l'anglais : le fichier fourni est en chinois simplifié, et les deux sont des écritures différentes
et non deux orthographes d'une même langue. La liste **Language** de la fenêtre Settings (l'engrenage
en haut à droite) permet de changer de langue à tout moment - l'interface se reconstruit dans la
langue choisie en conservant vos réglages actuels.

**Tout** dans l'interface est traduit : onglets, libellés, boutons, infobulles, en-têtes de
colonnes, statistiques, panneau de session, journal d'événements, messages du journal, boîtes de
dialogue et messages d'erreur (les exceptions montrées à l'utilisateur). Le code n'utilise que des
**clés** (par ex. `app.tabs.statistics`) et le texte provient du fichier de langue. Lorsqu'une clé
manque dans la langue choisie, l'anglais est utilisé, et en dernier recours la clé elle-même. (La
ligne de commande - CLI - est **toujours en anglais**, quelle que soit la langue du système et de
l'interface.)

**Ajouter une nouvelle langue** ne demande aucune modification du code : copiez `lang/en.json` vers
par exemple `lang/de.json`, traduisez les valeurs et renseignez l'en-tête
`"_meta": {"code": "de", "name": "Deutsch"}` - la langue apparaît dans la liste après un
redémarrage. Un fichier de langue corrompu est ignoré (il ne fait pas planter l'application).

## Prérequis

- Windows 10/11 (64 bits), Python 3.10+ (avec l'option tcl/tk)
- Droits d'administrateur
- `pydivert` (capture du trafic), `psutil` (solution de repli, voir plus bas)

L'installation depuis les sources fonctionne avec Python 3.10 et les versions plus récentes. La CI
teste et construit **uniquement avec la version 3.15** - c'est la version avec laquelle le `.exe`
publié est figé, les versions plus anciennes sont donc prises en charge mais pas revalidées à
chaque commit.

Sous Windows, Python 3.10 à 3.12 mesurent le temps par pas de 15,6 ms. Chaque paquet est daté par
cette horloge : la latence, la gigue et les limites de débit plus fines qu'un pas sont donc
arrondies à des pas entiers, et `--doctor` vous en avertit. Python 3.13 et les versions plus
récentes, ainsi que le `.exe`, mesurent en microsecondes.

`psutil` est installé avec l'outil mais ce n'est pas lui qui fait fonctionner le ciblage de processus
sous Windows. Là-bas, la table des sockets et les noms de processus viennent directement du système,
et le ciblage continue de fonctionner même si `psutil` est entièrement retiré (mesuré : 310 ports
associés, 37 noms sur 37 résolus). C'est la solution de repli pour tout le reste, et c'est ainsi que
les tests du moteur s'exécutent sous Linux sans aucun pilote.

## La fenêtre

La fenêtre **s'adapte à l'écran et à la mise à l'échelle du système (DPI)**. La taille initiale est
calculée à partir de la résolution (elle tient en 1366x768 et grandit en Full HD / 2K / 4K), et
chaque dimension - largeur des colonnes, hauteur des lignes des tableaux, marges du graphique,
retour à la ligne du texte - suit la taille de la police. Le programme se déclare **compatible
Per-Monitor-V2 DPI**, si bien que déplacer la fenêtre vers un second écran avec une autre mise à
l'échelle ne rend pas l'interface floue.

La taille et la position de la fenêtre, l'onglet sélectionné, la langue, les sections repliées, la
séparation entre le journal et les onglets et l'ordre de tri des tableaux sont mémorisés dans
`bean_network_tester_ui.json` (à côté des profils). La géométrie enregistrée est validée avant
d'être utilisée - une fenêtre laissée sur un second écran s'y rouvre, et si cet écran a disparu, elle
revient au centre de l'écran actuel.

- **Control** - tous les réglages de dégradation, regroupés en **sections repliables** (l'état
  replié est mémorisé). Sur une fenêtre large, les sections se disposent **sur deux colonnes** (au
  lieu d'une seule colonne étroite et d'une moitié droite vide), ce qui réduit beaucoup le défilement.
  L'onglet entier défile - y compris avec la **molette de la souris**.
- **Statistics** - trois sous-onglets, pour que rien ne soit tronqué sur les petits écrans :
  - **Live** - des compteurs (paquets, perdus, corrompus, coupés...) et un graphique de débit. La
    grille de compteurs choisit son nombre de colonnes selon la largeur de la fenêtre. Un bouton
    "Export CSV".
  - **Session** - graine, durée, données utilisées, pics, plus les boutons "Mark bug", "Save repro
    report" et "Copy CLI command".
  - **Events** - le journal d'événements (START/STOP/CHANGE/SCENARIO/BUG/RESET).
- **Connections** - une vue des IP:port avec lesquels le système testé communique. Chaque colonne
  est documentée dans [Colonnes de la page Connections](#colonnes-de-la-page-connections) plus bas,
  et chacune a aussi une infobulle sur son en-tête. Le trafic qui n'a aucun port - le ping (ICMP) -
  est listé lui aussi, une ligne par adresse, avec les cellules de port laissées vides.
  - **"down"/"up"/"total" correspondent à ce que l'application a réellement reçu**, la même
    grandeur que le panneau de session appelle "Downloaded (MB)". **"down seen"/"up seen"
    correspondent à ce que l'outil a capturé** avant de dégrader quoi que ce soit. Sans aucun
    réglage, elles sont égales. Dès que vous ajoutez de la perte ou une limite de débit, elles se
    séparent, et **l'écart entre elles représente les dégâts sur cette connexion**. Survolez
    n'importe laquelle pour lire la phrase complète. (Avant cette séparation, il n'y avait qu'une
    seule paire, qui contenait les octets capturés sous des intitulés qui parlaient d'octets
    livrés : une ligne pouvait afficher 5 Mo reçus alors que son application en avait obtenu 0,4.)
    Il y a en plus un champ de recherche (avec temporisation, pour ne pas retravailler la table à
    chaque frappe), des en-têtes cliquables pour trier, **"Freeze"** (les lignes cessent de
    s'échapper sous le curseur) et un **menu contextuel** (clic droit) : copier la ligne / l'IP,
    **"Target this process"**, **"Limit to this IP:port"** - qui remplit les champs de filtre en un
    clic. **"Reset this connection"** coupe cette connexion immédiatement, avec ou sans session en
    cours : le programme qui l'utilise reçoit une erreur, et l'autre extrémité reçoit une
    réinitialisation TCP. Pendant une session, cette réinitialisation passe par les dégradations
    comme n'importe quel autre paquet, une forte perte peut donc l'abandonner en route. Cela ne
    fonctionne que pour TCP sur IPv4 - Windows n'a aucun moyen de réinitialiser une connexion IPv6 -
    l'entrée est donc grisée sur les autres lignes, et elle exige les droits d'administrateur.
  La table est **virtualisée** : elle ne dessine que les lignes réellement à l'écran, si bien que le
  défilement est instantané qu'elle contienne 400 lignes ou plusieurs centaines de milliers.
  L'ancienne limite stricte de 400 lignes a disparu - le nombre de lignes à afficher se règle avec
  le champ **"Row limit"** (section *Tables*, 0 = aucune limite, 50 000 par défaut).
- **Tools** - de petits utilitaires pour les questions qu'on se pose avant ou pendant un test, un
  sous-onglet chacun. Seul **Ping** envoie quelque chose sur le réseau dans cet onglet : des
  requêtes d'écho à l'adresse que vous saisissez, de Start à Stop. Aujourd'hui :
  - **Sockets** - tous les sockets TCP et UDP de cet ordinateur, comme `netstat -ano`, sans qu'aucune
    session soit nécessaire : ce qui écoute, ce qui est connecté, son état (LISTEN,
    ESTABLISHED, TIME_WAIT...) et le programme qui le possède. Servez-vous-en pour voir sur quel
    port votre application écoute avant de la dégrader, ou quel programme occupe un port. La table
    est lue à l'ouverture de l'onglet et quand vous appuyez sur **Refresh**. Recherchez-y comme dans
    la table des connexions (`lport:8080`, `state:listen`, `proc:chrome`), et faites un clic droit
    sur une ligne pour cibler son programme, le laisser tranquille, ou limiter ou bloquer son
    adresse distante. Les noms de programmes s'affichent sans droits d'administrateur.
  - **Port check** - votre programme peut-il utiliser un port ? Saisissez un port, une liste ou une
    plage, comme vous saisissez les ports sur la page Control (`8080`, `80, 443`, `9000-9100`,
    jusqu'à 1000 à la fois), puis appuyez sur **Check** (ou sur Entrée). Chaque port est vérifié
    pour TCP et UDP, en IPv4 et en IPv6, et marqué **Free**, **In use** (avec le programme qui
    l'occupe et son PID) ou **Reserved by Windows** - une plage que Windows a mise de côté, la raison
    habituelle pour laquelle un serveur ne démarre pas sur un port que rien ne semble utiliser. Les
    plages sont propres à chaque protocole, un port peut donc être libre pour UDP et pas pour TCP.
    Pour chaque port, l'outil interroge le système sur l'adresse de bouclage de cet ordinateur et
    rend aussitôt le port. Le programme qui occupe un port vient de la même table que **Sockets**.
    Faites un clic droit sur une ligne pour cibler le programme qui occupe le port ou le laisser
    tranquille.
  - **Filter tester** - choisissez un champ de la page Control (processus cible, IP ou port de
    destination, IP ou port bloqué), saisissez une expression et une valeur, et voyez aussitôt si
    elles correspondent. Il montre aussi quelle partie de l'expression a retenu la valeur, quelle
    partie `!` l'a exclue, et comment le programme interprète ce que vous avez saisi. Une valeur qui
    n'est ni une adresse, ni un port, ni un PID est signalée comme telle, et non comme "ne
    correspond pas". **"Use in the Control field"** place l'expression dans ce champ, en remplaçant
    ce qui s'y trouve. Ce que vous saisissez reste jusqu'à la fermeture du programme, même si vous
    changez de langue.
  - **Adapters** - toutes les cartes réseau de cet ordinateur et les réglages dont dépend un test,
    ceux qu'affiche `ipconfig /all` (Windows uniquement). La carte par laquelle sort votre trafic
    Internet est en tête,
    puis viennent celles qui sont actives. Choisissez-en une pour voir ses adresses avec leurs
    préfixes, la passerelle, les serveurs DNS, le DHCP, l'adresse MAC, le MTU et la vitesse de la
    liaison. Une note avertit quand un autre appareil utilise la même adresse. La liste est lue à
    l'ouverture de l'onglet et quand vous appuyez sur **Refresh**. Faites un clic droit sur une
    passerelle ou un serveur DNS pour placer son adresse dans le champ IP de destination de la page
    Control (le port qui s'y trouve reste). La première ligne, **Proxy**, indique si les programmes
    passent par un proxy : les réglages de ce compte (détection automatique, script de
    configuration, serveur proxy et ce qui le contourne), le proxy que les services Windows
    utilisent (WinHTTP) et les variables `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` et `NO_PROXY`. Un
    programme qui utilise un proxy se connecte au proxy, pas à votre cible - faites un clic droit sur
    le serveur proxy pour limiter les dégradations à son adresse. Un proxy donné sous forme de nom
    n'est pas résolu, et les mots de passe présents dans une adresse sont masqués.
    **"Copy report"** copie en anglais toutes les cartes et les réglages de proxy - le texte contient
    les adresses et les adresses MAC de cet ordinateur.
  - **Diagnostics** - pourquoi START ne fonctionne pas, sans console. Il exécute les mêmes
    vérifications que `--doctor` (droits d'administrateur, pilote WinDivert, restes dans le dossier
    temporaire...) et marque chacune OK, Warning ou Problem. **"Clean up the driver"** décharge un
    pilote WinDivert resté chargé (administrateur uniquement, jamais pendant une session).
    **"Copy environment report"** copie la ligne `--version` et la sortie de `--doctor`, prêtes à
    coller dans un rapport de bug. Le rapport contient des chemins de dossiers, et un chemin peut
    contenir votre nom d'utilisateur Windows. Cochez **"Add network adapters"** ou **"Add proxy
    settings"** pour ajouter aussi les cartes ou le proxy au rapport - les deux sont désactivés tant
    que vous ne les cochez pas, car les adresses disent à quel réseau cet ordinateur est relié.
- En bas : **START/STOP**, **Apply changes** et **Load/Save file**, avec le journal en dessous.
  Cette barre est ancrée au bord inférieur - aucun onglet ne peut la recouvrir.

### Quand les changements prennent effet

**Rien ne s'applique tout seul.** Un profil prêt à l'emploi, un profil enregistré, le mode LAN et un
fichier de configuration chargé **ne font que remplir le formulaire**. Ils n'atteignent une session
en cours que par **"Apply changes"** - le bouton **s'illumine** quand le formulaire diffère de ce que
le moteur fait réellement. La barre sous le titre vous indique ce que vous regardez :

| Préfixe | Signification |
|---|---|
| `Preview:` | l'application est arrêtée - cela décrit ce qui se passera après START |
| `Active:` | c'est exactement ce qui est appliqué au trafic en ce moment |
| `Unapplied changes:` | le formulaire a été modifié - cliquez sur "Apply changes" |

Pendant qu'une session tourne, **deux éléments sont verrouillés** (ils se déverrouillent à STOP) : le
**filtre de trafic** (appliqué uniquement au START) et le **sélecteur de langue** (changer de langue
reconstruit toute l'interface). Le bouton STOP est rouge - impossible de le confondre avec START.

Un champ qu'un autre réglage a pris en charge est **grisé avec son libellé**, accompagné d'une note
qui dit quel réglage l'a pris - "Download"/"Upload" le font lorsqu'une planification (Schedule) est
définie, car le débit provient alors des étapes de la planification. On voit d'un coup d'œil ce qui
est réellement en vigueur.

### Raccourcis clavier

| Raccourci | Action |
|---|---|
| `F5` | START / STOP |
| `Ctrl+Enter` | Apply changes |
| `Ctrl+S` / `Ctrl+O` | Enregistrer / charger un fichier de configuration |
| `Ctrl+L` | Effacer le journal |
| `Ctrl+F` | Recherche : la recherche de champs sur Control, la recherche dans la table sur Connections, la recherche de sockets sur Tools > Sockets |
| `Up` / `Down`, `Page Up` / `Page Down`, `Home` / `End` | Dans une table : déplacer la sélection. Avec `Shift`, sélectionner une plage, qui peut dépasser un écran. `Ctrl+C` copie les lignes sélectionnées et `Shift+F10` ouvre le menu contextuel |
| `Enter` / `Tab` / `Escape` | Dans une fenêtre de question ou de message : `Enter` appuie sur le bouton en surbrillance (celui par défaut à l'ouverture de la fenêtre), `Tab` passe au bouton suivant, `Escape` la ferme en répondant "No" ou "Cancel" là où elle pose la question |

**Trouver un réglage.** Le champ en haut de la page Control recherche les réglages par leur nom -
saisissez une partie du nom d'un champ ou d'une section, ou l'option de ligne de commande comme
`--loss`. Chaque correspondance est mise en évidence et celle où vous vous trouvez est renseignée, si
bien que le compteur `1 / 4` désigne toujours quelque chose que vous voyez. `Enter` passe à la
correspondance suivante, `Shift+Enter` revient en arrière, `Escape` vide le champ. Une section
repliée s'ouvre le temps de la recherche et se replie ensuite d'elle-même. Les accents sont
facultatifs. Si ce que vous cherchez est l'un des réglages qui se trouvent dans la fenêtre Settings,
la recherche vous le dit.

### Validation des champs

Les champs numériques sont vérifiés **en direct, avec leur plage** (par ex. perte 0-100 %, latence
0-600000 ms) : un champ invalide devient rouge et la raison apparaît sous la section. Il en va de
même pour les expressions de filtre. La même plage s'applique en CLI - `--loss 250` est désormais
une erreur, et non plus un écrêtage silencieux à 100 %.

## Toutes les options expliquées

**Traffic to modify** - quel trafic capturer, tout simplement. Options : les deux directions
(TCP+UDP+ICMP), sortant uniquement, entrant uniquement, TCP uniquement, UDP uniquement, ICMP
uniquement (ping), bouclage uniquement (127.0.0.1/::1 - pour tester la communication entre
processus locaux). Chaque filtre couvre **IPv4 et IPv6**. (Si le ping "ne réagit pas", c'est presque
toujours parce que le filtre choisi n'inclut pas l'ICMP.)

**Le trafic de bouclage compte comme de l'envoi.** Windows remet les deux directions d'une
conversation entre deux programmes de cet ordinateur comme sortantes, quel que soit le filtre choisi.
Pour ce trafic, **Download**, la colonne de téléchargement de la planification et **NAT timeout**
n'ont aucun effet, pas plus que les valeurs principales lorsque l'envoi a ses propres valeurs. La
limite **Upload** s'applique aux deux directions ensemble, et un processus cible n'est touché que
par ce qu'il envoie. Avec le filtre de bouclage, le programme le signale lorsque de tels réglages
sont appliqués.

> **Remarque :** les profils par port ("DNS/HTTP/HTTPS only") n'existent pas - pour restreindre par
> port, utilisez le champ **Port** de "Target destination", qui comprend les listes, les plages et
> les exclusions (`80,443,8000-8100`, `!53`). Deux endroits qui décident des ports, avec des
> sémantiques différentes, ne feraient que semer la confusion.

Le **Traffic filter** est appliqué au démarrage, il est donc **verrouillé** pendant l'exécution -
pour le changer, arrêtez (STOP), choisissez-en un autre et redémarrez (START).

**Mode LAN** - une case à cocher "LAN mode (local network only, no internet)". Elle rejette le
trafic vers et depuis les adresses publiques (Internet) et laisse passer le réseau local :
10.0.0.0/8, 172.16-31.x, 192.168.x, bouclage, lien local et CGNAT. Elle simule "le LAN fonctionne,
Internet est en panne" - un test de la façon dont l'application se comporte sans accès à Internet
(par ex. pas de passerelle ni de WAN, un portail captif).

**Internet seul** - son miroir, une case à cocher "Internet only (no local network)" dans la même
section. Elle abandonne le trafic vers et depuis ces mêmes adresses locales et laisse Internet
fonctionner, de sorte que vous pouvez tester une application qui parle à un serveur intranet, à un
NAS ou à une imprimante alors que le WAN va bien. Il y a deux choses qu'elle ne fait pas, et toutes
deux comptent :

- **Le bouclage continue de fonctionner.** 127.x et `::1` passent dans les deux cas, donc un serveur
  de développement local, une base de données sur votre propre machine et tout ce qui utilise le
  bouclage pour se parler à soi-même ne sont pas touchés. C'est voulu : votre propre machine qui se
  parle à elle-même n'est pas "le réseau local".
- **Le routeur fait partie du réseau local.** Si votre PC demande le DNS au routeur, les
  résolutions de noms s'arrêtent avec lui, et Internet paraît alors en panne alors que le trafic
  Internet est bel et bien laissé passer. Utilisez un résolveur public pendant ce test si cela vous
  gêne.

Les deux cases peuvent être cochées en même temps. C'est permis et cela coupe tout sauf le bouclage -
le programme le dit dans le journal quand vous l'appliquez, et chacun des deux compteurs rend compte
de sa propre moitié.

**Target process** - restreindre l'effet à des applications choisies : nom de processus (par ex.
`chrome.exe`), PID, liste séparée par des virgules, plage de PID, caractère générique ou expression
régulière - voir [Syntaxe des filtres](#syntaxe-des-filtres-processus--ip--port). Le reste du
trafic de la machine n'est pas touché. Champ vide = tout le trafic.

**Speed limit** - débit maximal séparément pour le téléchargement (entrant) et l'envoi (sortant),
en KB/s. 0 = pas de limite. Le ping se compose de petits paquets, une limite de débit ne le change
donc presque pas - pour tester la limite, utilisez un téléchargement de fichier. Une valeur positive
limite toujours quelque chose : une limite extrêmement petite (inférieure à 1 B/s) est ramenée à
1 B/s, elle ne se transforme pas silencieusement en "pas de limite".

**Speed unit (fenêtre Settings)** - indique si la page Statistics, le graphique et l'affichage à
côté de ces deux champs montrent le débit en `KB/s`, `Mbit/s` ou `MB/s`. Cela change ce que vous
LISEZ, jamais ce que vous saisissez : les limites elles-mêmes restent en KB/s, car c'est le nombre
que portent un fichier de configuration enregistré, la planification de débit, les scénarios fournis,
`--down`/`--up` et la sortie NDJSON. Choisissez une unité et un `(= 8.39 Mbit/s)` grisé apparaît à
côté du champ, pour que vous puissiez saisir le nombre voulu par l'outil tout en lisant celui dans
lequel votre liaison est vendue.

> **Ici, `K` vaut 1024, et un mégabit est un million décimal** - les deux conventions ne se
> compensent pas, donc 1024 KB/s font **8.39 Mbit/s**, et non 8. C'est la conversion honnête, pas une
> erreur d'arrondi : un octet fait 8 bits, `1024 x 1024 x 8 = 8 388 608` bits par seconde, et mégabit
> signifie 10^6 bits partout où une liaison est vendue. Divisez par 8,39 et non par 8 quand vous
> voulez qu'une limite corresponde à un débit annoncé.

**Buffer** - la capacité du tampon de la liaison pour une limite de débit, en millisecondes
(0 = tampon illimité). Il fixe la quantité de délai de file d'attente qui peut s'accumuler sur une
liaison à débit limité avant qu'elle commence à abandonner l'excédent (bufferbloat). Sans ce tampon,
le seau à jetons pouvait "s'emballer" et partir des dizaines de secondes dans le futur : les paquets
subissaient des délais extrêmes, et relever la limite en cours de session (par ex. une étape de
planification "la liaison se rétablit") restait sans effet, car l'arriéré avalait chaque étape plus
rapide. Avec un tampon de `N` ms, le délai est borné à ~`N` ms, l'excédent part sous
"Rate-limit drop" (un compteur à part, ni "Loss" ni "Buffer overflow"), et après avoir relevé la
limite, le débit se rétablit en ~`N` ms. 1000 ms par défaut. Actif uniquement lorsqu'une limite de
téléchargement ou d'envoi ou une planification est définie. Le temps passé dans le tampon s'ajoute à
la *Latency*, comme sur une vraie liaison : avec 200 ms de latence et un tampon plein de 150 ms, un
paquet arrive après environ 350 ms.

**Delay (ping)** - *Latency* : combien de ms ajouter à chaque paquet. *Jitter* : variation aléatoire
du délai (+/- ms), qui fait sauter le ping et réordonne les paquets. Trois points à connaître :

(0) **Le ping augmente d'environ le double de la latence réglée.** Le délai est ajouté à chaque
paquet, et avec le filtre de trafic par défaut, qui couvre les deux sens, cela concerne la requête
comme la réponse - `--latency 100` se traduit donc par environ +200 ms de ping (mesuré : `--latency 200`
a fait passer un ping de bouclage de moins de 1 ms à ~408 ms). Choisissez la moitié du ping voulu. La
gigue ne double **pas** de la même façon : chaque paquet tire sa propre valeur, donc la fluctuation
augmente d'environ 1,4x, et n'atteint 2x qu'aux extrêmes. Les profils prêts à l'emploi intégrés sont
calibrés ainsi - `Satellite (geostationary)` porte 340 ms et délivre le ping d'environ 680 ms d'une
vraie liaison géostationnaire.

(1) la gigue ajoute un délai aléatoire indépendant à chaque paquet, si bien que des paquets peuvent
se doubler dans la file - la gigue **réordonne** intrinsèquement **les paquets** (un vrai réseau
fait de même).
(2) Les écarts négatifs sont ramenés à zéro, donc quand la gigue est **supérieure à la latence**, le
délai moyen ajouté dépasse la latence elle-même (par ex. latence 0, gigue 50 ms : environ la moitié
des paquets sans délai et une moyenne de ~12 ms, et non 0). Quand la latence est supérieure à la
gigue, l'effet est négligeable.

*Latency spike* se trouve dans la même section, parce qu'un pic est lui aussi de la latence - une
latence occasionnelle et élevée. Avec la probabilité donnée, il ajoute un délai supplémentaire (ms) à
**un seul paquet**, ce qui est la façon dont le "lag" ponctuel arrive réellement. La probabilité
s'applique par paquet et **dans chaque direction**, un aller-retour y est donc exposé environ deux
fois plus souvent que le nombre ne le laisse croire.

**Tester la livraison dans le désordre** - c'est à cela que sert la paire des pics, et c'est la
raison pour laquelle la section s'appelle "Latency (ping) and packet order". Un paquet touché par un
pic arrive après des paquets envoyés plus tard que lui, de sorte que *Spike chance* et *Spike size*
réordonnent le trafic **sans** étaler le délai de tous les autres paquets comme le fait la gigue -
ce qui compte quand ce qu'on teste est un protocole UDP qui doit survivre seul au réordonnancement :
un jeu, QUIC, de la télémétrie, de la voix. Réglez une taille de pic supérieure à l'écart entre vos
paquets, faute de quoi aucun paquet n'en doublera un autre.

Savoir si cela s'est réellement produit est une question distincte de savoir si c'était configuré,
l'outil le compte donc : **Reordered** sur la page Statistics (et `packets_reordered` dans le CSV des
statistiques). 0 avec un pic réglé signifie que votre trafic était trop clairsemé pour qu'un paquet
en double un autre - pas que le réglage a été ignoré. Le compte est par direction, deux connexions
chargées peuvent donc se doubler sans que ni l'une ni l'autre extrémité ne voie quoi que ce soit en
désordre.

**Impairments** - *Loss* : pourcentage de paquets qui disparaissent sans laisser de trace (5 % est
déjà un réseau nettement défaillant). *Corruption* : pourcentage de paquets dont un bit de données
est inversé - cela n'affecte **que les paquets qui transportent des données**. Les paquets sans
données (par ex. un simple ACK, un SYN) n'ont rien à inverser, ils passent donc intacts et ne sont
**pas comptés comme corrompus**. *Duplication* : pourcentage de paquets envoyés deux fois.

**Losses in a row (burst)** - les vraies liaisons perdent rarement les paquets un par un. Un four à
micro-ondes, un ascenseur ou un changement d'émetteur prive la connexion de signal un instant, et
tout ce qui est envoyé à ce moment-là est perdu. Ce champ indique combien de paquets sont perdus à la
suite **en moyenne**, tandis que *Loss* décide toujours de la quantité perdue au total. Cela compte
plus qu'il n'y paraît : 5 % répartis, la plupart des connexions les absorbent, alors que les mêmes
5 % par séquences de vingt bloquent un transfert, cassent une connexion active et envoient une
application sur son chemin de reconnexion. Réglez 0 pour répartir la perte uniformément, ce que
l'outil faisait avant l'existence de ce réglage.

Deux limites à connaître, et le journal énonce les deux quand vous appliquez les réglages. Une perte
très élevée ne peut pas arriver en séquences très courtes, car des séquences aussi courtes laissent
trop peu de place entre elles, et la séquence indique donc ce qu'elle délivrera vraiment. Et une
longue séquence espace fortement les séquences les unes des autres, si bien qu'une session courte
peut ne pas en voir du tout. Chaque direction a ses propres séquences, donc une séquence de vingt signifie
vingt à la suite dans cette direction, et avec Asymmetry activé, le journal énonce aussi les deux
limites pour l'envoi. À 100 % de perte, tous les paquets sont perdus, la longueur des séquences ne
change donc rien.

**Link flapping** - perte totale cyclique du trafic : toutes les *Period* secondes, la liaison est
morte pendant le pourcentage de temps indiqué. Simule une connexion qui vacille. Ce n'est **pas** la
même chose que les pertes à la suite : l'oscillation est un cycle fixe que l'on peut prévoir, alors
que les séquences ci-dessus sont aléatoires et courtes, au milieu d'un trafic par ailleurs normal.

**Advanced (NAT / connections) :**
- *Target destination (IP/port)* - ne dégrader que le trafic vers et depuis des serveurs choisis. Les
  deux champs acceptent les listes, les plages, le CIDR, les caractères génériques, les comparaisons,
  les exclusions et les expressions régulières - voir
  [Syntaxe des filtres](#syntaxe-des-filtres-processus--ip--port). Par ex. IP
  `10.0.0.1-10.0.0.50,!10.0.0.7`, port `80,443,8000-8100`. Vide = n'importe lequel.
- *TCP SYN drop (%)* - pourcentage de paquets d'ouverture de connexion abandonnés. Simule une
  connexion qui ne s'établit pas (test des nouvelles tentatives) - utile pour les tests derrière un
  NAT.
- *Max size (MTU)* - abandonner les paquets plus grands que N octets. Reproduit un "trou noir MTU"
  causé par les tunnels, les VPN ou un NAT (les petits paquets passent, les grands disparaissent).
  0 = désactivé.
- *NAT timeout* - si une connexion reste silencieuse plus de N secondes, le paquet entrant suivant
  est abandonné (la correspondance "disparaît"). Un test de keep-alive. 0 = désactivé.
- *TCP tear-down (RST)* - pourcentage de connexions brutalement coupées par un paquet RST. Force les
  reconnexions. **TCP uniquement** (le RST est un concept TCP, UDP ne peut pas être "coupé" - utilisez
  la perte ou l'oscillation de liaison). Le bouton **Tear down TCP now** réinitialise toutes les
  connexions TCP actives pendant ~3 s.
- *Schedule* - un débit qui change dans le temps : `time:download:upload` en KB/s, séparés par des
  virgules. Par ex. `2:100:0, 2:500:0` = 2 s à 100 KB/s, puis 2 s à 500, en boucle. Lorsque la
  planification n'est pas vide, elle **remplace** les champs fixes "Download/Upload" - l'interface
  les grise et le dit explicitement. La durée d'une étape est supérieure à 0 et d'au plus 86400 s,
  et chaque débit va de 0 (pas de limite) à 10000000 KB/s, comme les champs fixes. Une étape hors de
  ces bornes est refusée et nommée.

**Session :**
- *Duration (s)* - après ce nombre de secondes, le programme **s'arrête de lui-même** (exactement
  comme si vous cliquiez sur STOP) : la dégradation disparaît, le pilote est libéré. `0` = tourne
  jusqu'à STOP (le comportement précédent, par défaut). L'équivalent en CLI est `--duration`. Comme
  le filtre de trafic, elle n'est prise en compte **qu'au START** ("Apply changes" n'y touche pas).
  La valeur est enregistrée dans le fichier de configuration et dans la commande de reproduction.

**Repeatability and scenario :**
- *Seed* - saisissez un nombre quelconque pour que chaque exécution tire ses aléas de la même façon
  (un bug devient reproductible). Vide = différent à chaque fois. Prise en compte **uniquement au
  START**, donc verrouillée pendant qu'une session tourne.
- *Scenario* - un fichier JSON qui modifie les réglages en temps réel (par ex. après 10 s ajouter du
  ping, après 20 s couper). "Loop" le rejoue sans fin. Exemples dans `scenarios/` (Wi-Fi de café,
  mobile LTE->3G, VPN congestionné, DNS défaillant, serveur de jeu surchargé, envoi interrompu en
  cours de route, backend/API bloqué). "Load scenario...", "Clear" et "Loop" agissent au START, ils
  sont donc verrouillés pendant qu'une session tourne. "Apply changes" pendant un scénario
  fonctionne : voir [Format du fichier de scénario](#format-du-fichier-de-scénario).

**Profiles** - des profils prêts à l'emploi **classés du meilleur (en haut) au pire (en bas)** :
Perfect network, Good Wi-Fi, 5G network, Home DSL (VDSL), LTE/4G, Satellite (low orbit), Distant
server (another continent), Weak Wi-Fi, Cafe (crowded Wi-Fi), Congested home link (bufferbloat),
Train/metro (tunnels), 3G network, Foreign roaming, Satellite (geostationary), In-flight Wi-Fi,
56k modem, Terrible network - plus les vôtres (enregistrés sous un nom). Le programme **démarre
toujours sur "Perfect network"** (rien n'est dégradé tant que vous ne réglez rien). Les profils
intégrés ne peuvent pas être supprimés - le bouton "Delete" est désactivé pour eux.

Les profils sans fil perdent aussi **par séquences** plutôt qu'un paquet à la fois, parce que c'est
ce que fait une liaison radio : l'évanouissement du signal, les interférences et les transferts entre
cellules retirent le canal pendant un moment. Les profils filaires (DSL, modem 56k) gardent leur
perte répartie uniformément, parce que là, la perte vient d'une file pleine et non d'une radio qui
s'éloigne.

Leurs valeurs proviennent de mesures publiées partout où des mesures existent (médianes
Ookla® Speedtest® pour le satellite et le mobile, études à comité de lecture pour la reconfiguration
de 15 secondes de Starlink, pour le Wi-Fi en avion et pour le nombre de paquets Wi-Fi perdus à la
suite). Chaque chiffre est attribué dans le bloc de commentaires en tête de
`beantester/presets.py`, avec les auteurs, la revue et un DOI, pour que vous puissiez le vérifier
plutôt que de vous y fier. Là où aucun chiffre de ce genre n'existe - le "Wi-Fi faible" n'est pas une
grandeur mesurable - le commentaire placé à côté de la valeur le dit au lieu d'inventer une source.
Quelques-uns méritent une phrase :

- **Satellite (low orbit)** - modélisé sur Starlink. Son régime établi est bon (environ 40 ms de
  ping, 100 Mbit/s). Ce qui le distingue, c'est la reconfiguration toutes les 15 secondes, qui
  interrompt brièvement la transmission et se manifeste par un pic de latence occasionnel plutôt que
  par de la perte.
- **Distant server (another continent)** - une liaison rapide sans rien de cassé, simplement
  lointaine (~120 ms de ping). C'est celui qui met en évidence les protocoles bavards et le code qui
  suppose que le serveur est juste à côté.
- **Congested home link (bufferbloat)** - au repos, il a l'air correct (20 ms de ping). La
  dégradation, c'est la file d'attente. ⚠️ **Elle ne mord que lorsque votre application sature
  réellement la liaison**, car le tampon fait partie du limiteur de débit : envoyez un mince filet de
  trafic de test et vous verrez une simple liaison à 8 Mbit/s en réception et 1 Mbit/s en envoi, et
  rien d'autre. Saturez les 1 Mbit/s d'envoi et regardez le ping grimper vers deux secondes - le cas
  de "l'appel vidéo qui meurt dès que quelqu'un lance une sauvegarde".
- **Train/metro (tunnels)** - le seul profil qui coupe complètement la liaison pendant plusieurs
  secondes d'affilée (3 s toutes les 30), de sorte que l'application doit **se reconnecter** et non
  simplement ralentir.
- **In-flight Wi-Fi** - le classique de type satellite : ~750 ms de ping et 7 % de perte, ce qui est
  la médiane mesurée, pas un pire cas. Les avions dotés d'un équipement en orbite basse plus récent
  se comportent plutôt comme "Satellite (low orbit)".

Un profil enregistré mémorise **ce qu'est la liaison** : la perte, la part qui arrive à la suite, la
corruption, la duplication, la latence, la gigue, les pics de latence, les coupures de liaison
(oscillation), les limites de débit et le tampon. Tout le reste - la cible, la destination, le
blocage, le RST, le MTU, l'expiration NAT, la planification, la graine - en est exclu. Enregistrer un
profil vous avertit de ceux que vous avez actuellement activés. Utilisez **"Save file..."** pour la
configuration complète. Choisir un profil ou un profil prêt à l'emploi règle **tous** ces champs à
la fois, y compris ceux qu'un profil donné ne mentionne pas - ceux-là reprennent leur valeur par
défaut, de sorte que "Perfect network" signifie vraiment parfait. Les profils enregistrés par une
version antérieure se chargent tels quels.

En CLI (`--preset`), un profil prêt à l'emploi peut être donné par son **identifiant canonique** ou
par un **nom dans n'importe quelle langue de l'interface** (sans distinction de casse ni de
diacritiques polonais - `"Perfect network"` fonctionne aussi). Identifiants :
`presets.perfect`, `presets.good_wifi`, `presets.5g`, `presets.dsl`, `presets.lte`, `presets.leo`,
`presets.distant`, `presets.weak_wifi`, `presets.cafe`, `presets.bufferbloat`, `presets.metro`,
`presets.3g`, `presets.roaming`, `presets.satellite`, `presets.inflight`, `presets.modem56k`,
`presets.terrible`.

## Syntaxe des filtres (processus / IP / port)

Trois champs - **Target process**, **IP** et **port** (dans "Target destination") - parlent le même
mini-langage. La même syntaxe sera employée dans chaque futur champ de filtrage que l'outil
accueillera. Elle fonctionne à l'identique dans l'interface et en CLI (`--target`, `--dst-ip`,
`--dst-port`).

### Éléments de base

| Notation | Signification | Exemple |
|---|---|---|
| `a,b,c` | **liste** - n'importe laquelle des valeurs correspond | `80,443` |
| `a-b` | **plage**, bornes **incluses** | `8000-8100`, `10.0.0.1-10.0.0.50` |
| `>` `<` `>=` `<=` | **comparaison** (numérique, pour une IP selon la valeur de l'adresse) | `>1024`, `<=80`, `>10.0.0.5` |
| `!` | **exclusion** - "différent de" | `!53` |
| `*` `?` | **caractère générique** (`*` = n'importe quelle suite, `?` = un caractère) | `chrome*`, `192.168.1.*` |
| `re:` | **expression régulière** (`re` de Python, insensible à la casse) | `re:^chrome\.exe$` |
| `x.x.x.x/n` | **CIDR** (champ IP uniquement) | `192.168.1.0/24`, `2001:db8::/32` |

Un champ vide = **tout** (aucun filtrage). Les espaces autour des virgules et des termes sont
ignorés.

### Comment les termes se combinent

```
matches = (no positive terms OR any positive term matches) AND no "!" term matches
```

En d'autres termes : **les termes positifs s'additionnent (OU), les exclusions se soustraient
(ET NON)**. L'ordre des termes n'a aucune importance - `80,!53` signifie exactement la même chose
que `!53,80`.

| Saisie | Signification |
|---|---|
| *(vide)* | tout |
| `443` | port 443 uniquement |
| `80,443` | 80 **ou** 443 uniquement |
| `!53` | **tout sauf** 53 (il n'y a aucun terme positif) |
| `!53,!443` | tout sauf 53 et 443 |
| `1000-2000,!1500` | 1000-2000 mais sans 1500 |
| `>1024,!3389` | tout ce qui dépasse 1024 mais pas 3389 |
| `80,443,8000-8100,>9000,!8080` | 80, 443, 8000-8100 et tout ce qui dépasse 9000 - sauf 8080 |

### Le champ "Target process"

Un terme peut être un **nom** ou un **PID** - vous pouvez les mélanger dans un même champ.

* Un **nom** (sans `*` et sans `re:`) fonctionne comme une **sous-chaîne insensible à la casse** :
  `chrome` attrape `chrome.exe` **et** `chromedriver.exe`. (Cela a toujours fonctionné ainsi - conservé
  volontairement pour que les anciennes configurations et les anciens profils fonctionnent encore.)
* Un **PID** - un nombre seul (`12345`), une plage (`1000-2000`) ou une comparaison (`>1000`).
* Un **caractère générique** et **`re:`** s'appliquent au **nom** du processus.
* Les comparaisons `>` `<` `>=` `<=` n'ont de sens que pour un **PID** (des nombres). `>chrome` est
  une **erreur** - l'outil le dit explicitement au lieu de ne rien trouver en silence.

```
chrome.exe                     all processes with "chrome.exe" in the name
chrome, !chromedriver          chrome but NOT chromedriver
chrome.exe, firefox.exe        two apps at once
12345                          a specific PID
12345, 6789                    two PIDs
1000-2000                      all processes with a PID in that range
>1000                          all processes with a PID > 1000
firefox*                       a name starting with "firefox"
re:^(chrome|firefox)\.exe$      exactly chrome.exe or firefox.exe
firefox, 12345                 a name and a PID in one field
```

Tous les processus correspondants apportent leurs ports locaux - le ciblage couvre l'**union** de
leurs ports. L'ensemble des ports est tenu à jour pendant la session à partir des événements de
sockets du système, de sorte que les connexions nouvellement ouvertes par le processus sont
interceptées dès leur ouverture (sans le vrai WinDivert, il se rabat sur une nouvelle analyse de la
table des sockets quelques fois par seconde).

**Ce que signifie "ses ports locaux" en pratique.** Un paquet porte des adresses et des ports, jamais
un nom de programme, l'outil ne peut donc pas filtrer directement sur "Chrome". Il cherche quels
ports **locaux** le processus possède et retient chaque paquet qui passe par son port local.

C'est pourquoi `443` n'apparaît jamais ici. Quand Chrome charge une page, `443` est le port du
**serveur** - l'extrémité de Chrome dans cette connexion est un port temporaire comme `15597`, et ce
numéro appartient à un seul processus à la fois, son trafic est donc intercepté avec précision.

Quelques ports fonctionnent différemment. mDNS (5353), SSDP (1900) et DHCP (67/68) sont détenus par
plusieurs programmes à la fois, parce que c'est ainsi que les programmes trouvent les appareils de
votre réseau. Là, le numéro de port ne dit plus à qui appartient le trafic, c'est donc tout ou rien :
soit tout ce qui passe par ce port est dégradé, soit rien ne l'est. Le journal l'indique quand cela
arrive et nomme celle des deux situations qui s'applique. Le trafic ordinaire n'est pas affecté.

### Le champ "IP"

**IPv4 et IPv6** sont pris en charge. Une règle ne correspond jamais à une adresse de l'autre
famille - une règle IPv4 n'attrapera pas une adresse IPv6, et inversement (vous pouvez les mélanger
sans risque dans un même champ).

```
1.2.3.4                        one address
1.2.3.4, 8.8.8.8               two addresses
10.0.0.1-10.0.0.50             a range (both ends inclusive)
10.0.0.1-10.0.0.50, !10.0.0.7  a range with a hole
192.168.1.0/24                 a whole subnet (CIDR)
192.168.1.*                    the same via wildcard
!8.8.8.8                       everything except 8.8.8.8
>10.0.0.5                      addresses "greater" than 10.0.0.5
2001:db8::/32                  an IPv6 subnet
2001:db8::1-2001:db8::ff       an IPv6 range
10.0.0.0/8, 2001:db8::/32      IPv4 and IPv6 in one field
re:^10\.                        anything starting with 10.
```

La notation de l'adresse n'a pas d'importance : `2001:0db8:0000:0000:0000:0000:0000:0001` et
`2001:db8::1` sont la même adresse pour l'outil.

### Le champ "port"

```
443                            one port
80,443                         a list
8000-8100                      a range (both ends inclusive)
>1024                          high ports
<=1024                         privileged ports
!53                            everything except DNS
80,443,8000-8100,!8080         a mix
```

La plage autorisée est **0-65535**. `99999` est une erreur, pas une omission silencieuse.

### Expressions régulières (`re:`)

Le préfixe `re:` est **obligatoire** - sans lui, un terme est une simple valeur. Ainsi, `chrome.exe`
est un nom de fichier (un point est un point), et non un motif d'expression régulière.

| Motif | Attrape |
|---|---|
| `re:^chrome` | les noms qui commencent par `chrome` |
| `re:^chrome\.exe$` | **exactement** `chrome.exe` (pas `chromedriver.exe`) |
| `re:^(chrome\|firefox)\.exe$` | exactement `chrome.exe` ou `firefox.exe` |
| `re:(node\|python)` | les noms qui contiennent `node` ou `python` |
| `re:^\d+$` | (dans un champ de port ou de PID) un nombre seul |
| `re:^10\.` | (dans un champ IP) les adresses qui commencent par `10.` |
| `!re:^chrome` | **tout sauf** les noms qui commencent par `chrome` |

Les motifs sont **insensibles à la casse** et cherchent une correspondance n'importe où
(`re.search`) - si vous voulez une correspondance du début à la fin, utilisez `^` et `$`.

**Une virgule à l'intérieur d'une expression régulière doit être échappée par une barre oblique
inverse** (`\,`), car la virgule sépare les termes :

```
re:^ch.{1\,8}e\.exe$          correct - {1,8} with a backslash before the comma
re:^ch.{1,8}e\.exe$           WRONG - it is split into "re:^ch.{1" and "8}e\.exe$"
```

### Cas qui piègent

* **`chrome` attrape aussi `chromedriver`, mais `chrome.exe` non.** Un nom seul est une
  *sous-chaîne* : le texte "chrome" apparaît dans `chromedriver.exe`, mais le texte "chrome.exe"
  n'y apparaît pas (on y trouve `chrome` + `driver.exe`). Donc `chrome.exe` -> uniquement
  `chrome.exe`. `chrome` -> `chrome.exe` **et** `chromedriver.exe`.
* **`chrome*` est plus large qu'il n'y paraît.** L'étoile signifie "n'importe quelle suite", donc
  `chrome*` attrape `chromedriver.exe` exactement comme `chrome`. Vous voulez exactement une seule
  application ? Utilisez `re:^chrome\.exe$` ou ajoutez une exclusion : `chrome, !chromedriver`.
* **`8*` dans un champ de port est un caractère générique appliqué au texte du nombre**, il attrape
  donc `8`, `80`, `8080` et `8443` - mais **pas** `443`. Vous vouliez presque toujours une plage :
  `8000-8999`. N'utilisez les caractères génériques de port qu'en connaissance de cause.
* **`80,443,!8080` équivaut simplement à `80,443`.** Une exclusion qui ne retranche rien n'est pas une
  erreur - elle est simplement inutile.
* **`!53` couvre aussi le trafic sans port** (par ex. ICMP/ping). "Tout sauf 53" signifie
  littéralement "tout ce qui n'est pas le port 53", et un paquet ICMP n'est pas le port 53. Si vous ne
  voulez que TCP/UDP, restreignez le **Traffic filter**.
* **Un terme vide est une erreur**, pas "tout" : `80,,443` et `80,!` sont rejetés. Un **champ
  entièrement** vide signifie "tout".
* **L'IP et le port se combinent avec ET.** `IP=10.0.0.0/8` + `port=443` signifie "le trafic vers le
  réseau 10.x **et en même temps** sur le port 443". Vous voulez "l'un ou l'autre" ? Laissez l'autre
  champ vide et faites deux exécutions.
* **`>chrome` est une erreur.** Les comparaisons portent sur des nombres (PID), pas sur des noms.
* **`2000-1000` est une erreur** (plage inversée), pas un ensemble vide.
* **Un caractère générique n'est pas une expression régulière.** Dans `chrome*`, l'étoile signifie
  "n'importe quelle suite". Dans `re:chrome*`, elle signifie "la lettre `e` répétée 0 fois ou plus".
  Si vous écrivez `re:`, vous écrivez une expression régulière.
* **Une répétition dans une répétition est refusée car trop lente**, par exemple `re:^(\w+)+$` ou
  `re:^([0-9:]+)+$`. Un tel motif peut prendre des secondes sur un seul nom ou une seule adresse qui
  correspond presque, et une adresse est vérifiée à chaque paquet. N'écrivez la répétition qu'une
  fois : `re:^\w+$`.

Chaque erreur de syntaxe est signalée **immédiatement** : dans l'interface, le champ devient rouge
avec la raison en dessous (dans la langue de l'interface), et la CLI se termine par un `error: ...`
lisible - jamais un silencieux "rien ne marche".

## Statistiques (ce que signifient les compteurs)

Le graphique de débit a un axe Y avec des valeurs (KB/s), une grille, une échelle aux valeurs rondes
et, dans le coin, les débits courants de réception et d'envoi. Download/Upload (KB/s en direct),
Packets (combien sont passés), Queued (en attente - augmente avec le délai ou la limite), Lost, Loss
runs (en combien de SÉQUENCES cette perte est arrivée - voir "Losses in a row"), Corrupted,
Duplicated, Buffer overflow (abandonnés quand l'outil est surchargé), Dropped at stop (encore en
file d'attente quand STOP a été pressé), Send failed (l'outil les avait capturés mais n'a pas pu les
remettre sur le fil - la connexion est tombée, ou le pilote a refusé), Rate-limit drop (abandonnés
par un tampon de limite de débit plein - comptés séparément de la perte et de "Buffer overflow"),
SYN dropped, MTU dropped, NAT expired, RST torn, LAN: internet cut off, Local network cut, RST sent.

**Copier les chiffres.** Faites un clic droit sur n'importe quelle valeur de "Live" ou "Session" pour
copier cette valeur, ou l'onglet entier. Chaque panneau a aussi un bouton - "Copy counters" sous la
grille, "Copy session details" à côté des boutons de reproduction - qui copie chaque ligne telle
qu'elle se lit à l'écran, avec les légendes et les unités. Pratique pour un rapport de bug : le
panneau de session porte le nom de l'ordinateur, ses adresses, la graine et ce que la capture
couvrait.

Les trois derniers de cette liste - "Buffer overflow", "Dropped at stop" et "Send failed" - sont des
paquets que l'outil vous fait perdre, et non la liaison que vous lui avez demandé de simuler. Ils
sont comptés, ils maintiennent honnête l'arithmétique vu/livré/abandonné, et ils ne font
volontairement **pas** partie de la "Effective loss". Si l'un d'eux est différent de zéro, une partie
de la perte que vous mesurez est de notre fait.

### Reproduire un bug (le panneau "Session and reproduction")

Conçu pour que, après un bug, vous puissiez recréer exactement les mêmes conditions :

- **Seed (effective)** - même si vous laissez le champ Seed vide, le programme tire et mémorise une
  graine concrète. Saisissez-la plus tard dans le champ Seed et relancez pour obtenir les mêmes
  tirages.
- **Oscillation répétable** - le motif de coupure de liaison est mesuré depuis le début de la
  session, donc avec les mêmes réglages il se répète à l'identique d'une exécution à l'autre (il ne
  dépend pas de l'horloge système).
- **Ce que la graine reproduit** - la graine reproduit les **décisions** du moteur (quels paquets
  sont abandonnés, corrompus, dupliqués, et de combien ils sont retardés), pas le **nombre de
  paquets**. Le trafic qui traverse la liaison dépend de ce que font vos applications et le système à
  ce moment-là, deux exécutions avec la même graine donnent donc les mêmes *proportions* (par ex.
  15,8 % de perte dans les deux) mais pas des compteurs identiques au paquet près. Pour les
  comparaisons en CI, utilisez des taux (%), pas des nombres de paquets bruts.
- **Start / Duration / Effective loss / Queue peak / Down-up peak** - un aperçu rapide de
  l'exécution.
- **Ce que compte "Effective loss"** - la part du trafic que vous avez visé que **cet outil** a
  cassée, pour **chaque** dégradation : la Loss configurée plus les abandons dus à la limite de débit,
  le blocage, la coupure LAN, la coupure du réseau local, les coupures de liaison, les
  réinitialisations de connexion, les abandons de SYN, les abandons MTU et l'expiration NAT. Quand une
  cible est définie, seul le trafic de la cible compte, de sorte que les autres applications ne
  peuvent pas le diluer. Les paquets que **l'outil** a jetés sont volontairement exclus - "Buffer
  overflow", "Dropped at stop" et "Send failed" sont ses propres défaillances, pas celles de la
  liaison, et ils ont leurs propres compteurs. Le `effective_loss_pct` du rapport est le même
  nombre, à côté de `packets_in_scope`.
- **Driver queue wait (peak)** - le plus long temps qu'un paquet avait **déjà** attendu dans WinDivert
  quand cet outil l'a reçu. Il est mesuré, pas estimé : le pilote appose sur chaque paquet une
  heure de capture, et l'outil l'échantillonne 20 fois par seconde. Sur une machine au repos, c'est une
  fraction de milliseconde (mesuré ici : 0,05-0,16 ms). S'il augmente, l'outil ajoute un délai qui
  n'apparaît dans aucun autre compteur, car il se produit dans la file du pilote, en amont de la
  sienne - et dès qu'il atteint 50 ms, l'outil le dit dans le journal et dans la liste d'événements.
  Vide avec `--simulate`, qui n'a pas de pilote.
- **Il mesure cette machine, pas Internet.** L'outil voit les paquets qui traversent la pile réseau
  de cet ordinateur, donc un paquet perdu sur le réseau - la réponse qui n'est jamais revenue - n'arrive
  jamais ici et rien ici ne peut le compter. Un ping propre de 30 paquets qui perd une réponse montre
  **59** paquets sur la ligne de connexion et **zéro** abandon, et les deux chiffres sont justes :
  30 requêtes sont parties, 29 réponses sont revenues, et l'outil n'en a cassé aucune. La perte de
  bout en bout, ce sont les chiffres de votre propre application (ou le "Lost" de `ping`) qui la
  donnent.
- **Data used** - Downloaded / Uploaded / Total (MB) cumulés depuis le début, plus le débit moyen de
  la session. Vous savez aussitôt combien de données l'application a utilisées. (Le rapport contient
  aussi les "attempted MB" - ce que l'application voulait envoyer avant que la perte et les limites
  soient soustraites.)
- **Journal d'événements** horodaté : démarrage, changements de réglages, étapes de scénario, coupures
  de connexions et vos marqueurs de bug - avec un **tri** au clic sur l'en-tête d'une colonne.
- **Marquer l'instant d'un bug** - cliquez exactement au moment où vous voyez le bug. Cela insère un
  marqueur horodaté dans le journal.
- **Save reproduction report** - un seul fichier JSON qui contient tout : graine, tous les réglages,
  compteurs, métriques, journal d'événements, connexions et une **commande CLI prête à l'emploi** qui
  recrée les conditions. Il consigne aussi **la file WinDivert derrière laquelle la session a
  tourné** (`session.driver_queue` : longueur, temps et taille). C'est le tampon propre au pilote, en
  amont de celui de cet outil, et les trois valeurs sont des plafonds, pas un délai fixe : tant que
  l'outil suit, les paquets y attendent à peine (voir **Driver queue wait (peak)** plus haut). Elle ne
  se remplit que lorsque l'outil prend du retard. Alors les paquets attendent plus longtemps, et une
  fois qu'elle est pleine, le pilote les abandonne avant que cet outil les voie. Une file plus petite
  ne supprimerait pas cette attente, elle la transformerait en paquets perdus qu'aucun compteur ne
  peut montrer, c'est pourquoi l'outil laisse les réglages propres au pilote tranquilles. Un rapport
  venant d'une machine que vous n'avez pas sous les yeux dit quelle file a produit ses chiffres. Les
  trois mêmes valeurs vont dans le journal au START.
- **Copy CLI command** - directement dans le presse-papiers : `BeanNetworkTester.exe --seed ... --loss ...
  --duration ...` (la commande s'adapte à la version : depuis le dépôt, vous obtenez
  `python bean_network_tester.py ...`).
- **Ce que décrivent le rapport et la commande** - la dernière session, pas le formulaire : les
  réglages que START lui a donnés, mis à jour par chaque "Apply changes", avec sa graine et son
  scénario (`--scenario`, plus `--loop` s'il tournait en boucle). Un changement que vous avez saisi
  sans l'appliquer est laissé de côté, de même qu'un profil chargé après STOP. Pendant un scénario,
  "Apply changes" devient la base sur laquelle ses étapes suivantes se construisent, la commande
  reprend donc aussi ces réglages. Un scénario fourni avec le programme est nommé à partir du dossier
  du programme (`scenarios\...` depuis les sources, `_internal\scenarios\...` à côté du `.exe`), et
  la commande le retrouve depuis n'importe quel dossier où vous l'exécutez. Tout autre fichier est
  nommé par le chemin que vous avez choisi. Avant la première session, **Copy CLI command** copie les
  réglages du formulaire.

## Fichier de configuration

Les boutons "Save/Load file" écrivent tous les réglages en JSON. Le même fichier fonctionne en CLI
via `--config`. Ordre de priorité : valeurs par défaut < fichier < profil < options.

Chaque valeur est vérifiée selon son type à la lecture du fichier, et une étape de scénario l'est de
la même façon. Un interrupteur (`lan_mode`, `internet_only`, `narrow_filter`...) vaut `true` ou
`false`, ou `1` ou `0`. Le texte `"false"` est refusé, il n'est pas lu comme "activé". `filter` est
l'un des choix de `--filter`, et `seed` est un nombre entier (`-1` pour une graine aléatoire). Une
valeur du mauvais type arrête la CLI avec le code `3` et nomme le réglage. La fenêtre affiche le même
message et laisse le formulaire tel qu'il était.

## Mode ligne de commande (CLI)

La CLI s'exécute **depuis le même `BeanNetworkTester.exe`** que l'interface : le lancer avec n'importe
quel argument démarre le mode texte (pas de fenêtre, pas de tkinter), et sans argument - l'interface.
Les messages et `--help` sont toujours en anglais.

```bat
:: GUI
BeanNetworkTester.exe

:: CLI (from the same exe)
BeanNetworkTester.exe --loss 5 --latency 100 --down 1024 --target chrome.exe
BeanNetworkTester.exe --preset "3G network" --duration 60
```

> Vous travaillez depuis le dépôt (sans compilation) ? Partout, remplacez `BeanNetworkTester.exe` par
> `python bean_network_tester.py` - toutes les options et tous les codes de sortie sont identiques.

### Codes de sortie (le contrat CI/CD)

Chaque façon de se terminer a son propre code - un pipeline n'a pas besoin d'analyser du texte :

| Code | Nom | Quand |
|---|---|---|
| `0` | ok | la session s'est exécutée et toutes les vérifications ont réussi |
| `1` | runtime | impossible de démarrer (pas de `pydivert`, pilote, défaillance du moteur) |
| `2` | usage | ligne de commande incorrecte (option inconnue, mauvais type) - le code d'argparse |
| `3` | config | réglages invalides : expression, planification, plage, profil, fichier de configuration |
| `4` | scenario | le fichier de scénario est absent ou mal formé |
| `5` | io | un artefact n'a pas pu être écrit (rapport de reproduction, configuration enregistrée) |
| `6` | assertion | l'exécution a abouti mais `--min-packets` / `--fail-on-no-traffic` n'est pas passé |
| `7` | permission | les droits d'administrateur (Windows), ou root ou CAP_BPF, CAP_NET_ADMIN et CAP_NET_RAW (Linux), sont requis et absents |
| `130` | interrupted | Ctrl+C (SIGINT) |
| `143` | terminated | SIGTERM (annulation d'une tâche, `docker stop`), Ctrl+Break, ou fermeture de la fenêtre de la console |

`BeanNetworkTester.exe --help` affiche les mêmes codes.

### Sortie : les journaux sur stderr, les données sur stdout

- **stderr** - le journal lisible par l'humain, préfixé `[bean]` (démarrage, graine, erreurs, raison
  de l'arrêt),
- **stdout** - les données : lignes de rapport, et avec `--format json` du **NDJSON** (un objet JSON
  par ligne : des objets `sample` successifs, puis un `summary` final avec le code de sortie, la graine
  et la commande de reproduction).

```bat
BeanNetworkTester.exe --simulate --duration 30 --format json > run.ndjson
```

### Tous les paramètres de la CLI

**Dégradation de la liaison**

| Option | Unité | Description |
|---|---|---|
| `--loss` | % | pourcentage de paquets abandonnés |
| `--loss-burst` | paquets | nombre moyen de paquets perdus à la suite (0 = perte répartie uniformément). Façonne `--loss`, ne s'y ajoute pas |
| `--corrupt` | % | pourcentage de paquets dont un bit est inversé |
| `--dup` | % | pourcentage de paquets envoyés deux fois |
| `--latency` | ms | délai fixe ajouté à chaque paquet |
| `--jitter` | ms | variation aléatoire du délai (+/-) |
| `--down` `--up` | KB/s | limite de débit (0 = pas de limite) |
| `--buffer` | ms | tampon de la liaison pour la limite de débit (0 = pas de limite). Borne le délai de file d'attente, l'excédent part sous "Rate-limit drop" |
| `--spike-prob` `--spike-ms` | % / ms | avec la probabilité donnée, ajoute un délai supplémentaire |
| `--syn-drop` | % | pourcentage de paquets TCP SYN abandonnés |
| `--max-size` | B | "trou noir MTU" - abandonne les paquets plus grands que N octets (0 = désactivé) |
| `--nat-timeout` | s | après N s de silence, la correspondance NAT "disparaît" (0 = désactivé) |
| `--rst-prob` `--rst-cooldown` | % / s | pourcentage de connexions coupées par RST et durée pendant laquelle la coupure est maintenue |
| `--flap-period` `--flap-down` | s / % | coupure cyclique de la liaison : à quelle fréquence et sur quelle fraction de la période |
| `--rate-schedule` | - | débit variable : `"time:download:upload,..."` en KB/s, en boucle. Durée supérieure à 0 et d'au plus 86400 s, débits de 0 (pas de limite) à 10000000 |
| `--asym` | - | donne à l'envoi ses propres valeurs. Sans cette option, un seul jeu de nombres s'applique dans les deux sens, ce qui est le comportement par défaut |
| `--loss-up` `--corrupt-up` `--dup-up` | % | les trois mêmes dégradations, pour les paquets que cette machine ENVOIE. Utilisés uniquement avec `--asym` |
| `--latency-up` `--jitter-up` | ms | le délai et sa variation, pour les paquets que cette machine ENVOIE. Utilisés uniquement avec `--asym` |
| `--spike-prob-up` `--spike-ms-up` | % / ms | le délai plus long occasionnel, pour les paquets que cette machine ENVOIE. Utilisés uniquement avec `--asym` |
| `--ipv4-only` `--ipv6-only` | - | ne dégrade qu'une seule famille d'adresses. L'autre continue de circuler sans être touchée - cela vise l'outil, cela ne bloque pas un protocole. Fonctionne aussi avec `--dst-ip` vide, c'est-à-dire toutes les adresses. Les deux options à la fois s'excluent mutuellement, rien n'est dégradé, et le journal le dit |
| `--lan-mode` | - | mode LAN : coupe Internet (adresses publiques), conserve le réseau local |
| `--internet-only` | - | son miroir : coupe le réseau local (10.x, 172.16-31.x, 192.168.x, lien local, CGNAT), conserve Internet. Le bouclage continue de fonctionner. Attention : le DNS demandé à votre routeur est du trafic local, Internet peut donc cesser de fonctionner avec lui |
| `--narrow-filter` | - | pousse `--dst-ip`/`--dst-port` dans le filtre WinDivert pour que le pilote ne remette jamais du trafic qui ne pourrait pas être dégradé (bien plus rapide à débit de paquets élevé). Uniquement au START. Tant qu'il est actif, les statistiques et les connexions ne couvrent que le trafic restreint |

**Ciblage** (les trois acceptent la [syntaxe de filtre](#syntaxe-des-filtres-processus--ip--port)
complète : listes, plages, `!`, `>`, `<`, `>=`, `<=`, caractères génériques, `re:`, et `--dst-ip`
accepte en plus le CIDR)

| Option | Description | Exemples |
|---|---|---|
| `--target` | processus : nom, PID, plage de PID, caractère générique, expression régulière | `--target chrome.exe`<br>`--target "chrome,!chromedriver"`<br>`--target ">1000"` |
| `--dst-ip` | adresses IP distantes (IPv4 et IPv6) | `--dst-ip 1.2.3.4`<br>`--dst-ip "10.0.0.1-10.0.0.50,!10.0.0.7"`<br>`--dst-ip "192.168.1.0/24"`<br>`--dst-ip "2001:db8::/32"` |
| `--dst-port` | ports distants (0-65535) | `--dst-port 443`<br>`--dst-port "80,443,8000-8100"`<br>`--dst-port "!53"`<br>`--dst-port ">1024"` |
| `--filter` | quel trafic capturer, tout simplement (IPv4 + IPv6) : `both,out,in,tcp,udp,ping,loopback` | `--filter tcp` |

**Blocage (pare-feu)** - abandonne tout le trafic vers les destinations choisies. Le blocage se déclenche sur **IP OU port** (un champ vide est ignoré, donc `--block-port 443` seul bloque le 443 vers n'importe quelle adresse). Même [syntaxe de filtre](#syntaxe-des-filtres-processus--ip--port) que ci-dessus. Il respecte le ciblage par processus (ne bloque que le trafic de la cible).

| Option | Description | Exemples |
|---|---|---|
| `--block-ip` | bloque des adresses IP distantes (IPv4 et IPv6) | `--block-ip 1.2.3.4`<br>`--block-ip "10.0.0.0/8,!10.0.0.1"` |
| `--block-port` | bloque des ports distants (0-65535) | `--block-port 443`<br>`--block-port "80,443,8000-8100"` |
| `--block-reject` | refuse les connexions TCP bloquées au lieu de les abandonner en silence | `--block-port 443 --block-reject` |

**Refusé ou ignoré** - par défaut, une connexion bloquée ne reçoit aucune réponse, et le
programme que vous testez attend jusqu'à abandonner de lui-même. Avec `--block-reject`, elle est
refusée à la place, et le programme signale "connection refused" en deux secondes environ, comme
il le ferait pour un port réellement fermé. Ce sont deux chemins de code différents dans la plupart
des applications, et une suite de tests qui n'en a jamais vu qu'un seul n'a testé que celui-là.
Le refus couvre les **connexions que cet ordinateur initie, en TCP** : le trafic UDP, et les
connexions qui arrivent de l'extérieur, restent bloqués en silence.

> Dans `cmd.exe`/PowerShell, **mettez l'expression entre guillemets** si elle contient une virgule,
> `!`, `>`, `<`, `*` ou `^` - sinon l'interpréteur de commandes la comprend à sa façon (`cmd.exe`
> supprime un `^` isolé, si bien que `re:^edge` arriverait sous la forme `re:edge`). La commande qui
> recrée la session (`Copy CLI command` et la ligne `Reproduce:`) les met entre guillemets pour vous.

**Exécution et rapports**

| Option | Description |
|---|---|
| `--preset NAME` | profil prêt à l'emploi par identifiant canonique ou par un nom dans n'importe quelle langue de l'interface |
| `--config FILE` / `--save-config FILE` | charge / enregistre les réglages (JSON, partagé avec l'interface) |
| `--scenario FILE` `--loop` | un scénario chronologique (JSON) et sa lecture en boucle |
| `--seed N` | graine d'aléa - la même exécution peut être répétée |
| `--duration N` | **durée d'exécution en secondes** (0 = jusqu'à Ctrl+C, ou jusqu'à ce qu'une chronologie `--scenario` soit épuisée). Le même champ existe dans l'interface ("Session") |
| `--row-limit N` | un réglage **propre à l'interface** : nombre maximal de lignes dans les tables (0 = pas de limite, 50 000 par défaut). En CLI sans fenêtre, il ne fait rien - il est seulement enregistré dans le fichier de configuration et prend effet quand cette configuration est ouverte dans l'interface. L'équivalent du champ "Row limit" |
| `--interval N` | fréquence des rapports, en secondes (supérieure à 0, au plus 86 400 - le même plafond que `--duration`, de sorte qu'un intervalle qui ne pourrait jamais se déclencher est refusé au lieu d'être accepté) |
| `--log-conns` | affiche les connexions observées à la fin |
| `--repro-out FILE` | enregistre un rapport de reproduction (JSON) |
| `--simulate` | trafic synthétique à la place de WinDivert (tester sans Windows, sans pilote, sans administrateur) |
| `--gui` | ouvre l'interface. Valide **seule uniquement** - l'interface a ses propres commandes, la combiner avec des options de réglages est donc une erreur d'usage (sortie 2) plutôt qu'une exécution silencieuse sans fenêtre |
| `--version` | affiche la version et quitte |

**Sortie et diagnostics**

| Option | Description |
|---|---|
| `-v`, `--verbose` | journalise ce que fait le programme : réglages effectifs, filtres compilés, ports de processus résolus, étapes de scénario, ouverture et fermeture du pilote |
| `-q`, `--quiet` | erreurs uniquement : ni journal ni rapports périodiques |
| `--log-level {error,warn,info,debug}` | niveau de journalisation explicite (remplace `-v`/`-q`) |
| `--log-file FILE` | ajoute aussi le journal (et les rapports) à un fichier - un artefact de CI prêt à l'emploi |
| `--format {text,json}` | format de stdout : texte lisible ou NDJSON pour un pipeline |

**Pour la CI/CD**

| Option | Description |
|---|---|
| `--dry-run` | vérifie la configuration et quitte (ne touche pas au pilote, ne fait passer aucun trafic) - idéal pour valider des fichiers de configuration dans un pipeline. Un `--scenario` est lui aussi lu et validé, de sorte que l'essai à blanc et l'exécution réelle concordent |
| `--print-config` | affiche les réglages effectifs (après `defaults < file < preset < flags`) en JSON et quitte |
| `--min-packets N` | quitte avec le code `6` si moins de N paquets ont été interceptés |
| `--fail-on-no-traffic` | raccourci pour `--min-packets 1` - **détecte un filtre qui n'a rien intercepté** |
| `--doctor` | vérifie l'environnement (administrateur, `pydivert`, état du pilote WinDivert, restes dans `%TEMP%`, possibilité d'écrire dans le dossier du programme sans droits d'administrateur, finesse de mesure du temps par l'horloge) et quitte |
| `--cleanup-driver` | décharge un pilote WinDivert bloqué (libère le fichier `.sys` verrouillé **sans redémarrer le système**) et quitte. Chaque ligne dit ce qu'il est advenu d'un service. Le code de sortie est `0` même si un service n'a pas pu être arrêté |

Ordre de priorité : **defaults < `--config` < `--preset` < flags**. Liste complète :
`BeanNetworkTester.exe --help`.

### Exemples de ciblage

```bat
:: only the browser, but not its test driver
BeanNetworkTester.exe --loss 10 --target "chrome,!chromedriver"

:: only HTTPS traffic to a test server and its backup address
BeanNetworkTester.exe --latency 300 --dst-ip "10.0.0.5,10.0.0.9" --dst-port 443

:: the whole test subnet except one host, on application ports
BeanNetworkTester.exe --down 128 --dst-ip "10.0.0.0/24,!10.0.0.1" --dst-port "8000-8100"

:: everything EXCEPT DNS (so name resolution works while the rest breaks)
BeanNetworkTester.exe --loss 20 --dst-port "!53"

:: high-PID processes, traffic to IPv6
BeanNetworkTester.exe --jitter 80 --target ">1000" --dst-ip "2001:db8::/32"
```

### Exemples de blocage (pare-feu)

```bat
:: cut the app off from an external API (the server is "down")
BeanNetworkTester.exe --block-ip 203.0.113.10

:: block all HTTPS - see how the app copes with no connection
BeanNetworkTester.exe --block-port 443

:: block several ports OR the whole backend subnet (blocking is IP OR port)
BeanNetworkTester.exe --block-port "8080,9090" --block-ip 203.0.113.0/24

:: impair only your app's traffic, and cut its link to the payment server entirely
BeanNetworkTester.exe --latency 200 --target myapp.exe --block-ip 198.51.100.7
```

### Le mode `--simulate` (test sans Windows et sans administrateur)

Un aperçu sur du trafic synthétique - n'exige ni WinDivert ni privilèges :

```bat
BeanNetworkTester.exe --simulate --down 500 --loss 10 --duration 4 --interval 1
```

### Répétabilité et scénarios depuis la CLI

```bat
BeanNetworkTester.exe --simulate --seed 42 --loss 20 --duration 10
BeanNetworkTester.exe --simulate --scenario scenarios/cafe-wifi.json
```

`scenarios/<name>.json` (ou `_internal\scenarios\<name>.json`) ouvre depuis n'importe quel dossier un
scénario fourni avec le programme. Si le dossier courant contient un fichier sous ce chemin, c'est ce
fichier qui est utilisé.

La graine garantit des **décisions identiques paquet par paquet** pour la même séquence de paquets.
Les étapes d'un scénario sont cumulatives (chacune modifie l'état), et `action: reset_tcp` coupe les
connexions TCP à ce moment-là. Le fichier de scénario est **validé à son ouverture** - un JSON
quelconque se termine par une erreur lisible, et non par un "scenario with 0 steps", et les réglages
d'une étape sont vérifiés selon les mêmes règles que le formulaire, si bien qu'une valeur que le
programme ne peut pas utiliser est nommée avec son numéro d'étape au lieu d'arrêter l'exécution en
cours de route.

Chaque exécution de la CLI se termine en affichant la **graine effective** et une commande prête à
l'emploi pour la reproduire - avec le fichier `--scenario` tel que vous l'avez saisi, `--loop` et
`--simulate` lorsque l'exécution les avait - et `--repro-out file.json` enregistre le rapport de
reproduction complet avec la même commande.

## Colonnes de la page Connections

Dix-sept colonnes, toutes triables en cliquant sur l'en-tête, et chacune avec la même explication en
infobulle sur cet en-tête.

| colonne | ce qu'elle contient |
|---|---|
| `process` | Le processus qui possède le port local. `?` signifie que le nom n'a pas pu être résolu - exécutez en tant qu'administrateur. |
| `PID` | Identifiant du processus qui possède le port local, résolu au moment où le paquet a été capturé. |
| `proto` | Protocole de transport : TCP / UDP / ICMP / IP. |
| `remote IP` | L'adresse avec laquelle cette machine communique. Faites un clic droit sur une ligne pour limiter les dégradations à cette adresse. |
| `r.port` | Port côté distant (443 = HTTPS, 53 = DNS, 80 = HTTP). Vide pour le trafic sans port, comme le ping. |
| `l.port` | Port sur cette machine - ce qui relie la connexion à un processus. Vide pour le ping/ICMP, ce qui explique aussi pourquoi ces lignes n'ont généralement pas de nom de processus. |
| `packets` | Paquets vus sur cette connexion depuis son apparition. |
| `impaired?` | Indique si la connexion était **dans le périmètre de dégradation** pendant cette session - dégradée, et pas simplement observée. Elle reste à `yes` après la fermeture de la connexion, à titre d'historique. Sans ciblage défini, tout est dans le périmètre. |
| `dropped` | Paquets abandonnés sur cette connexion par les dégradations actives (perte, coupure de liaison, mode LAN, "Internet only", réinitialisations, ...). |
| `down` | Données qui ont réellement **atteint** l'application - ce qu'elle a téléchargé. La même grandeur que le panneau de session appelle "Downloaded (MB)". |
| `up` | Données qui ont réellement **quitté** cette machine - ce que l'application a envoyé. |
| `total` | Téléchargement livré + envoi livré. |
| `down seen` | Données que l'outil a **capturées** en entrée, avant toute dégradation - ce que la connexion offrait. |
| `up seen` | Données que l'outil a **capturées** en sortie - ce que l'application a essayé d'envoyer. |
| `avg[B]` | Taille moyenne d'un paquet sur cette connexion (total d'octets / paquets). |
| `time[s]` | Secondes entre le premier et le dernier paquet de cette connexion dans cette session. |
| `idle[s]` | Secondes depuis le dernier paquet. Cesse de compter quand la session s'arrête. |

**Les cinq colonnes de trafic portent leur propre unité.** Chaque cellule est affichée dans celle de
B, KB, MB ou GB qui lui convient, si bien qu'un flux de 5 GB se lit `5.00 GB` au lieu de `5242880.0`
et qu'une réponse DNS de quatre-vingt-dix octets se lit `90 B` au lieu de `0.0`. Le pied sous la table
fait de même pour ses totaux. `avg` est une taille de paquet et reste en octets. Le tri et l'export
CSV ne sont pas affectés - tous deux travaillent sur le nombre brut d'octets, jamais sur le texte de
la cellule.

**La paire livré/vu est tout l'intérêt de la table.** Sans aucune dégradation, elles sont égales.
Ajoutez de la perte ou une limite de débit et elles se séparent, et **l'écart entre elles représente
les dégâts causés à cette connexion**. (Avant leur séparation, il n'y avait qu'une seule paire, qui
contenait les octets capturés sous des intitulés qui parlaient d'octets livrés : une ligne pouvait
afficher 5 MB reçus alors que son application en avait obtenu 0,4.)

## Exports CSV

Deux boutons écrivent deux fichiers, et ils se comportent **différemment, volontairement**. Les deux
atterrissent dans votre propre dossier, `%LOCALAPPDATA%\BeanNetworkTester`, avec vos profils et l'état
de la fenêtre (ou à la racine du projet quand on exécute depuis les sources). Le programme écrit le
chemin complet dans le journal à chaque enregistrement. Ils sont tenus hors du dossier du programme
pour que la mise à jour du programme - à la main ou par un gestionnaire de paquets, qui remplace ce
dossier - ne puisse pas emporter vos fichiers avec lui. Définissez `BEAN_DATA_DIR` sur un dossier de
votre choix pour tout garder ailleurs, par exemple sur la même clé qu'une copie portable.

Le dossier appartient au compte Windows sous lequel le programme s'exécute. Sur un compte sans
droits d'administrateur, accepter l'invite d'élévation exécute le programme sous le compte
administrateur dont le mot de passe a été saisi, et il utilise alors le dossier de CE compte - les
profils que vous avez enregistrés sans élévation ne sont donc pas ceux que vous voyez avec elle.
"About" et `--doctor` affichent tous deux le dossier utilisé, pour que vous puissiez toujours savoir
lequel vous regardez. Pour donner à tous les comptes de la machine un dossier commun, un
administrateur peut définir `BEAN_DATA_DIR` comme variable d'environnement système.

| | **Statistics** ("Export CSV", Statistics -> Live) | **Connections** ("Export connections CSV") |
|---|---|---|
| fichier | `bean_network_tester_stats.csv` | `bean_network_tester_connections.csv` |
| mode | **Ajoute** une ligne à chaque clic - un journal à partir duquel construire un graphique sur plusieurs exécutions | **Écrase** - un instantané de la table telle qu'elle est maintenant |
| écriture | atomique (fichier temporaire + renommage), donc un plantage en cours d'écriture ne peut pas le tronquer | idem |
| votre recherche / tri | sans objet | **respectés** - le fichier correspond à ce que vous regardiez |
| "Show only the targeted traffic" | **ignoré volontairement** - voir ci-dessous | **respecté** |
| le champ "Row limit" | sans objet | **ignoré** - toutes les lignes filtrées sont exportées, pas seulement celles qui sont dessinées |
| les colonnes changent d'une version à l'autre | l'ancien fichier est renommé avec un horodatage et un nouveau est commencé, pour que les lignes ne se décalent jamais sous un en-tête périmé | sans objet |
| encodage | UTF-8 sans marque d'ordre des octets. Ouvert par double-clic, Excel lit un tel fichier dans la page de codes Windows et abîme les lettres qui en sortent (noms de processus en polonais ou en chinois). Ouvrez-le via **Données > Obtenir des données > À partir d'un fichier > À partir du texte/CSV** (**Data > Get Data > From File > From Text/CSV** dans Excel en anglais) et réglez **Origine du fichier** (**File Origin**) sur **65001: Unicode (UTF-8)** | idem |

Le CSV des statistiques ne suit pas l'interrupteur "show only the targeted traffic" parce que c'est un
journal à ajout : un fichier dont les colonnes signifient une chose dans certaines lignes et une autre
dans les autres est pire qu'inutile pour le tableur auquel il est destiné. Il porte à la place **les
deux** totaux (`bytes_in`/`bytes_out` et `delivered_in_scope_bytes_*`), si bien que vous pouvez le
restreindre vous-même tout en voyant lequel est lequel. **"Capture only the targeted traffic" ne peut
pas être annulé de cette façon** - cela change ce que `packets_seen` a compté dès l'origine - c'est
pourquoi chaque ligne l'enregistre dans `capture_narrowed`.

### Colonnes du CSV des statistiques

`time`, le périmètre de capture de la session, puis chaque compteur, dans cet ordre :

| colonne | signification |
|---|---|
| `time` | heure réelle du clic |
| `capture_narrowed` | `yes` quand "Capture only the targeted traffic" était actif pour cette session, de sorte que chaque nombre de la ligne couvre **uniquement** le trafic de votre destination. `no` signifie que la ligne couvre tout ce que le filtre de trafic a laissé passer. Sans cette colonne, deux lignes avec le même `packets_seen` pourraient décrire un trafic complètement différent |
| `packets_seen` | paquets capturés |
| `packets_in_scope` | parmi eux, ceux visés par le ciblage choisi pour la dégradation |
| `dropped_loss` | abandonnés par le réglage Loss |
| `loss_runs` | en combien de SÉQUENCES cette perte est arrivée (voir "Losses in a row"). 0 avec une longueur de séquence définie signifie que la session était trop courte pour en voir une, ou que la perte est de 100 % et qu'il n'y a donc pas de séquences distinctes |
| `dropped_overflow` | abandonnés parce que la propre file de l'outil était pleine (voir la remarque plus bas) |
| `corrupted` | paquets dont la charge utile a été inversée |
| `duplicated` | copies supplémentaires mises en file |
| `packets_reordered` | paquets qui sont sortis de l'outil dans un ordre différent de celui d'entrée. 0 avec une gigue ou un pic configuré signifie que les paquets étaient trop espacés pour que l'un d'eux en double un autre. Compté par direction, donc deux connexions chargées peuvent se doubler sans que ni l'une ni l'autre extrémité ne voie quoi que ce soit en désordre |
| `dropped_syn` | SYN TCP abandonnés ("connexions qui ne s'ouvrent jamais") |
| `dropped_mtu` | abandonnés pour dépassement de la taille maximale (trou noir MTU) |
| `dropped_nat` | abandonnés parce que la correspondance NAT avait expiré |
| `dropped_rst` | trafic englouti pendant qu'une connexion était maintenue coupée après une réinitialisation |
| `dropped_lan` | abandonnés par le mode LAN (Internet coupé, réseau local actif) |
| `dropped_local_network` | abandonnés par "Internet only" (réseau local coupé, Internet et bouclage actifs) |
| `dropped_block` | abandonnés par les champs de blocage (pare-feu) |
| `dropped_link_outage` | abandonnés pendant une coupure d'oscillation |
| `dropped_rate_limit` | abandonnés par un tampon de limite de débit plein |
| `dropped_at_stop` | paquets en file d'attente jetés à l'arrêt de la session |
| `dropped_send_failed` | le pilote a refusé de les réinjecter |
| `connections_reset` | connexions réellement coupées |
| `connections_refused` | connexions bloquées qui ont été refusées au lieu d'être ignorées (`--block-reject`) |
| `rst_sent` | paquets RST qui ont atteint la pile |
| `bytes_in` / `bytes_out` | octets livrés, tout le trafic capturé |
| `bytes_in_total` / `bytes_out_total` | octets capturés, avant dégradation |
| `delivered_in_scope_bytes_down` / `delivered_in_scope_bytes_up` | octets livrés, trafic ciblé uniquement |
| `queue_len` / `queue_peak` | paquets en attente dans la file de délai, maintenant et au pic |
| `driver_wait_peak_ms` | le plus long temps que le pilote a fait attendre un paquet avant que l'outil le voie, compté une fois que l'outil lit (les paquets interceptés pendant que START se préparait encore sont exclus) |

Les trois derniers compteurs d'abandon - `dropped_overflow`, `dropped_at_stop`, `dropped_send_failed` -
sont les pertes **propres à l'outil** et non une dégradation que vous avez demandée, ce qui explique
pourquoi ils sont comptés à part.

### Colonnes du CSV des connexions

Les mêmes lignes que la table, mais **les en-têtes ne sont pas les libellés de la table** - ils
écrivent en toutes lettres ce que la table abrège :

| colonne du CSV | colonne de la table |
|---|---|
| `process`, `pid`, `proto`, `remote_ip`, `remote_port`, `local_port`, `packets` | identiques, sans abréviation |
| `impaired` | `impaired?` (`yes` / `no`) |
| `dropped` | `dropped` |
| `delivered_down_bytes`, `delivered_up_bytes`, `delivered_total_bytes` | `down`, `up`, `total` - **toujours des octets bruts ici**, jamais l'unité choisie par l'écran |
| `captured_down_bytes`, `captured_up_bytes`, `captured_total_bytes` | `down seen`, `up seen` (plus leur total) |
| `avg_bytes` | `avg[B]` |
| `duration_s`, `idle_s` | `time[s]`, `idle[s]` |

## Format du fichier de scénario

Un scénario est une chronologie : une liste d'étapes, chacune avec un temps en secondes et ce qu'il
faut faire à ce moment-là. Le fichier est du JSON, soit un objet, soit une simple liste d'étapes :

```json
{
  "loop": true,
  "steps": [
    { "at": 0,  "settings": { "latency": 20, "jitter": 15, "loss": 1, "down": 1024, "up": 256 } },
    { "at": 20, "settings": { "loss": 3, "down": 512 } },
    { "at": 45, "action": "reset_tcp", "duration": 5 },
    { "at": 60, "settings": { "loss": 0, "flap_period": 0 } }
  ]
}
```

**Niveau du fichier**

| clé | signification |
|---|---|
| `steps` | obligatoire - la liste des étapes. Un simple `[ ... ]` au niveau supérieur fonctionne aussi, et signifie `loop: false`. |
| `loop` | facultatif, `false` par défaut. Rejoue la chronologie sans fin, en recommençant après le `at` de la DERNIÈRE étape. Les réglages et l'action de la dernière étape sont appliqués juste avant chaque redémarrage, ils ne durent donc qu'un instant dans une boucle - pour tenir une phase finale, ajoutez une étape plus tardive. |

**"Apply changes" pendant qu'un scénario tourne** - il est appliqué immédiatement, et chaque étape
suivante s'appuie sur lui plutôt que sur les réglages que START a donnés à la session. Un réglage
qu'aucune étape ne touche (le processus cible, le ciblage de destination) garde sa nouvelle valeur
jusqu'à la fin. Un réglage que les étapes définissent ne garde la nouvelle valeur que jusqu'à l'étape
suivante, qui remet la valeur du scénario.

**Niveau de l'étape** - une étape a besoin de `settings`, de `action`, ou des deux. Une étape qui n'a
ni l'un ni l'autre est une erreur, pas une pause.

| clé | signification |
|---|---|
| `at` | obligatoire - secondes depuis le début de la session (`>= 0`). Les étapes sont triées selon cette valeur, leur ordre dans le fichier n'a donc pas d'importance. |
| `settings` | un objet de réglages **partiel**. **Cumulatif** : chaque étape modifie l'état laissé par les précédentes, une valeur reste donc en place jusqu'à ce qu'une étape ultérieure la change à nouveau. |
| `action` | `reset_tcp` - coupe les connexions TCP dans le périmètre à ce moment-là. **C'est la seule action.** L'ancienne orthographe `reset_now`, d'avant la 1.3, a été supprimée, un fichier qui l'utilise encore échoue donc au chargement avec un message qui nomme l'étape. |
| `duration` | secondes pendant lesquelles la réinitialisation maintient les connexions coupées (`3` par défaut), plus de 0 et au plus 3600. Valide uniquement avec une `action`. |

**Quels noms dans `settings`** - n'importe quel réglage de l'outil, sous le **même nom que dans le
fichier de configuration** (c'est-à-dire son option de ligne de commande, les tirets devenant des
tirets bas) : `loss`, `latency`, `jitter`,
`down`, `up`, `buffer`, `spike_prob`, `flap_period`, `dst_ip`, `block_port`, `target`,
`rate_schedule`, `max_size`, `nat_timeout`, `rst_prob`, `lan_mode`, `internet_only` et les
autres. Lancez
`--print-config` pour obtenir l'ensemble complet des noms avec leurs valeurs actuelles. Une étape ne
peut pas modifier `filter`, `duration`, `narrow_filter`, `row_limit` ni `seed` : une session prend les
trois premiers et `seed` uniquement au START, et seules les tables de la fenêtre lisent `row_limit`,
jamais le moteur. Une étape qui en définit un ne change rien - le fichier se charge quand même, et
le dit.

**Tout est validé au chargement du fichier, et une erreur se désigne d'elle-même.** Un réglage
inconnu, une action inconnue, une clé inconnue, une `duration` qui n'est pas un nombre, une étape qui
ne fait rien, une liste d'étapes vide ou de plus de **1000** étapes - chacun échoue avec un message
qui pointe le numéro de l'étape. Cela compte plus qu'il n'y paraît : une clé mal orthographiée était
autrefois **silencieuse**, si bien que `"duraton"` laissait tranquillement la réinitialisation à sa
valeur par défaut de 3 secondes et que `"lop"` désactivait tranquillement la boucle, et dans les deux
cas l'outil avait l'air d'ignorer le fichier.

Les étapes sont appliquées par un minuteur qui bat **toutes les 0,1 s**, les temps inférieurs à la
seconde sont donc respectés à cette précision près. `--dry-run` valide un `--scenario` sans toucher
au pilote, ce qui en fait une vérification peu coûteuse dans un pipeline.

### Les scénarios fournis dans `scenarios/`

Tous bouclent, sauf `upload-drop-midway.json`, vous pouvez donc en lancer un et le laisser tourner.

| fichier | ce qu'il reproduit |
|---|---|
| `cafe-wifi.json` | Un café qui se remplit en 85 s : une liaison correcte se dégrade jusqu'à ~240 ms de ping, 6 % de perte et 2 Mbit/s, avec la connexion qui coupe complètement toutes les 12 s au pire moment, puis se rétablit. |
| `mobile-lte-to-3g.json` | Un téléphone qui sort de la couverture LTE : de 33 Mbit/s à 0,8 en 3G, puis une **coupure totale avec une réinitialisation TCP** à 60 s, puis une reprise partielle et le retour en LTE. Celui à utiliser pour tester ce que fait votre application quand le réseau meurt en pleine requête. |
| `congested-vpn.json` | Un VPN dont l'**envoi** s'effondre alors que la réception reste correcte (de 512 à 160 KB/s), avec des pics de latence, un MTU de 1400 et des réinitialisations occasionnelles. |
| `failing-dns.json` | Vise **uniquement le port 53** (DNS - pour laisser le DNS sur TCP tranquille, réglez le Filter sur "UDP only" avant START) : la résolution de noms se dégrade jusqu'à 60 % de perte et 1,5 s de ping, devient **100 % morte pendant 13 s**, puis revient. Tout le reste de la machine continue de fonctionner, ce qui en fait un test DNS plutôt qu'un test de panne. |
| `overloaded-game-server.json` | Un serveur qui plie sous la charge : le ping, la gigue, la perte et la duplication montent ensemble, avec des pics de latence jusqu'à 800 ms sur 45 % des paquets. |
| `same-loss-in-runs.json` | La même perte de 5 % pendant toute l'exécution, arrivant de quatre façons différentes : répartie uniformément, puis par séquences de 5, 15 et 40 paquets. Rien d'autre ne change, donc ce qui casse, c'est la FORME de la perte et non son importance. Celui à utiliser pour savoir si votre chemin de reconnexion fonctionne. |
| `upload-drop-midway.json` | **Ne boucle pas** - un tir unique : un envoi qui démarre bien, se dégrade, est **ramené à zéro en plein transfert** avec une réinitialisation TCP, puis se rétablit partiellement. Pour tester les envois reprenables et les barres de progression qui mentent. |
| `blocked-endpoint.json` | Un backend (`203.0.113.0/24`) est **bloqué** à 20 s alors que tout le reste continue de fonctionner, puis débloqué. Pour tester les délais d'attente, les nouvelles tentatives et les solutions de repli face à une seule dépendance. |

## Recettes CI/CD

### 1. Dégrader la liaison en arrière-plan de tests E2E (GitHub Actions, Windows)

Les tests s'exécutent avec 300 ms de délai et 5 % de perte. Le shaper s'arrête de lui-même après
120 s, donc aucune étape "bloquée" ne laisse un réseau cassé sur l'agent.

```yaml
- name: Start the network shaper (background, self-stopping)
  shell: pwsh
  run: |
    $p = Start-Process -FilePath dist\BeanNetworkTester\BeanNetworkTester.exe `
      -ArgumentList '--latency','300','--loss','5','--duration','120',
                    '--dst-port','443','--fail-on-no-traffic',
                    '--format','json','--log-file','shaper.log' `
      -RedirectStandardOutput shaper.ndjson -PassThru
    "SHAPER_PID=$($p.Id)" >> $env:GITHUB_ENV

- name: Run the E2E suite under bad network
  run: npm run test:e2e

- name: Stop the shaper and check it actually impaired something
  if: always()
  shell: pwsh
  run: |
    Stop-Process -Id $env:SHAPER_PID -ErrorAction SilentlyContinue
    Get-Content shaper.ndjson | Select-Object -Last 1
```

> **Remarque :** lancez le processus d'arrière-plan avec `--duration` - c'est le filet de sécurité.
> Même si l'étape "Stop" ne s'exécute jamais (annulation de la tâche, délai dépassé), la session se
> ferme d'elle-même, le pilote est libéré et l'agent retrouve son réseau normal.

### 2. Validation de la configuration en pre-commit / PR (sans pilote, sans administrateur)

```bat
BeanNetworkTester.exe --dry-run --config profiles/bad-3g.json
```
Le code `0` = le fichier est valide. `3` = il y a une erreur (avec un message lisible sur stderr).
Un réglage mal orthographié compte comme une erreur et dit de quelle clé il s'agit - il était
autrefois ignoré en silence, de sorte que la vérification passait puis que l'exécution partait sans ce
réglage.

`--dry-run` vérifie les **réglages**, pas la machine : il ne s'enquiert jamais des droits
d'administrateur ni du pilote, il répond donc `0` sur un agent de build qui ne pourrait pas réellement
lancer une capture. C'est voulu - valider une configuration à un endroit et l'exécuter à un autre est
normal. Quand vous voulez que les deux moitiés aient leur réponse, lancez la paire :

```bat
BeanNetworkTester.exe --doctor && BeanNetworkTester.exe --dry-run --config profiles/bad-3g.json
```

### 3. Une exécution courte et répétable avec un artefact

```bat
BeanNetworkTester.exe --preset presets.3g --seed 42 --duration 60 ^
  --repro-out repro.json --format json --fail-on-no-traffic > run.ndjson
```
Les artefacts (`run.ndjson`, `repro.json`) suffisent à recréer les conditions à l'identique -
`repro.json` contient un `cli_command` prêt à l'emploi.

### 4. Nettoyer l'environnement de l'agent

```bat
BeanNetworkTester.exe --doctor
BeanNetworkTester.exe --cleanup-driver
```

## Construire un .exe

Sous Windows :

```bat
pip install pyinstaller pydivert psutil
pyinstaller --noconfirm BeanNetworkTester.spec
```

Résultat : **`dist\BeanNetworkTester\BeanNetworkTester.exe`** (un dossier avec l'exe, le pilote
WinDivert, les traductions et l'icône). Ce fichier unique exécute **à la fois l'interface et la CLI**.

Trois choix de build délibérés (ne les changez pas sans nécessité - chacun corrige un vrai bug) :

- **sous-système console** (pas `--noconsole`) : sinon l'exe n'a ni `stdout` ni `stderr`, et
  `cmd.exe` et PowerShell **n'attendent pas** un processus graphique - la CI ne verrait ni la sortie
  ni le code de sortie. Au démarrage de l'interface, le programme se détache lui-même de la console,
  si bien qu'un double-clic ne laisse aucune fenêtre noire.
- **onedir** (pas `--onefile`) : `pydivert` embarque `WinDivert64.sys`, et onefile le dépaquetait dans
  `%TEMP%\_MEIxxxx`. Le noyau garde un handle ouvert sur le `.sys` chargé, si bien que le dossier
  **ne pouvait pas être supprimé** avant un redémarrage. Dans la version en dossier, le pilote se
  trouve à côté de l'exe, sur un chemin stable.
- **`asInvoker`** (pas `--uac-admin`) : `requireAdministrator` crée toujours un **nouveau** processus
  lors de l'élévation - ce qui perd les tubes et le code de sortie de l'appelant. Désormais,
  l'interface demande elle-même l'élévation, et la CLI se termine avec le code `7` et un message clair
  lorsque les droits manquent (`--simulate` n'en a pas besoin).

L'icône peut être régénérée avec un script Pillow (`pip install pillow`), mais Pillow n'est pas
nécessaire pour un fonctionnement normal.

## Pièges à connaître (à lire avant de signaler un bug)

- **`--duration` est un filet de sécurité, pas seulement un confort.** Sans elle, une session dure
  jusqu'à `Ctrl+C` / STOP. En CI, passez **toujours** `--duration`. La seule exception est un scénario
  avec chronologie : `--scenario` avec un fichier qui ne boucle pas et comporte plus d'une étape
  termine désormais l'exécution à la fin du scénario, et le dit au démarrage. Un scénario en boucle
  ou à étape unique n'a pas de fin où s'arrêter, il avertit donc et continue jusqu'à ce que vous
  l'arrêtiez.
- **Fermer la fenêtre de la console arrête proprement une exécution, se déconnecter non.** Fermer la
  fenêtre de la console termine l'exécution comme le fait Ctrl+Break : la capture s'arrête, le
  résumé est affiché, le rapport `--repro-out` et le `--log-file` sont écrits si vous les avez
  demandés, le pilote WinDivert est déchargé, le journal indique `Terminated (console window closed).`
  et le code de sortie est `143`. Windows n'attend qu'environ 5 secondes pour ce nettoyage. Se
  déconnecter ou éteindre met fin au programme sur-le-champ. Windows ferme quand même sa capture,
  donc aucun trafic ne reste dégradé, mais après une déconnexion le pilote peut rester chargé jusqu'à
  `--cleanup-driver` ou un redémarrage.
- **Pas de trafic = une exécution verte.** Si le filtre n'intercepte pas un seul paquet, le programme
  fonctionne correctement et se termine avec le code `0`. Vous voulez que ce soit une erreur ->
  `--fail-on-no-traffic`.
- **Le filtre de trafic et la durée ne prennent effet qu'au START** (comme dans l'interface) :
  "Apply changes" n'y touche pas.
- **Après STOP, les paquets en attente dans la file de délai sont abandonnés.** Avec
  `--latency 5000`, cela peut représenter pas mal de paquets d'un coup - ce n'est pas une fuite,
  c'est la fin de la session.
- **La limite de débit a un tampon (`--buffer`, 1000 ms par défaut).** Avec une charge offerte
  supérieure à la limite, une fois le tampon plein, l'excédent part sous "Rate-limit drop" (un
  compteur à part) - c'est le comportement d'une liaison engorgée, pas un bug. Relever la limite en
  cours de session ne prend effet qu'une fois le tampon vidé (jusqu'à ~`--buffer` ms). Vous voulez
  l'ancien tampon illimité (des paquets au lieu d'abandons, au prix d'un délai croissant) ? Réglez
  `--buffer 0`.
- **`--dst-port "!53"` attrape aussi le trafic sans port** (par ex. ICMP) : un paquet sans port "n'est
  pas le port 53".
- **Un nom de processus seul est une sous-chaîne** : `--target chrome` attrape aussi
  `chromedriver.exe`. Pour être précis : `--target "re:^chrome\.exe$"`.
- **Les plages sont inclusives aux deux bouts** (`80-80` = un seul port), comme dans nmap/iptables.
- **La CLI est toujours en anglais**, quelle que soit la langue de l'interface et du système.
- **`-q` est vraiment silencieux** : en cas de succès, il n'affiche rien. Lisez le résultat dans le
  code de sortie (ou ajoutez `--format json`).
- **Lancer sans droits d'administrateur** (et sans `--simulate`) se termine par le code `7` - pas par
  du "silence".
- **Le pilote a verrouillé un fichier dans `%TEMP%` ?** C'est un vestige des anciennes versions
  onefile : `BeanNetworkTester.exe --cleanup-driver` le libère sans redémarrer le système.

## Tests

Le moteur est séparé de WinDivert, les tests s'exécutent donc sur n'importe quel système (ils n'ont
besoin ni de Windows, ni de droits d'administrateur, ni de tkinter). La suite repose sur **pytest** :

```bat
pip install --require-hashes -r requirements.txt
pip install -r requirements-dev.txt
python -m pytest tests
```

Ils couvrent chaque mécanisme : perte, latence, gigue, limitation de débit par direction, corruption,
duplication, expressions de filtre (listes, plages, `!`, `>`, `<`, caractères génériques, `re:`, CIDR,
IPv6), ciblage par processus et par destination, abandon des SYN, MTU, oscillation, expiration NAT,
injection de RST, pics de latence, la planification, le journal des connexions, la répétabilité
(graine), les scénarios, le fichier de configuration, le résumé (PL/EN), les traductions de
l'interface et la reproduction (graine effective, journal d'événements, rapport et commande CLI). Un
test distinct exécute aussi le test de fumée de l'interface (`smoke_gui.py`, sur un faux tkinter), et
les conventions du dépôt (nommage, pas de tkinter dans le paquet central, découpage en couches
autorisé) sont gardées par des tests.

Le **contrat CLI pour la CI/CD** est gardé séparément :
- `tests/test_cli_runtime.py` - codes de sortie (0/1/3/4/5/6/130/143), précision de `--duration` (pas
  "au rapport le plus proche"), séparation stdout/stderr, NDJSON, `-q`/`-v`, `--dry-run`,
  `--print-config`, `--min-packets`, priorité de `--duration` sur le fichier de configuration. La
  boucle de rapport reçoit une horloge injectée, les tests de durée s'exécutent donc en microsecondes.
- `tests/test_failsafe.py` - la session s'arrête d'elle-même après `duration`, un thread de capture
  mort provoque un *fail-open* (libérer le pilote = le réseau revient), le `_tick` de l'interface
  survit à une exception, le thread de ciblage ne touche jamais tkinter, fermer la fenêtre libère
  toujours le moteur.

**GitHub Actions** exécute les mêmes tests à chaque push (`.github/workflows/ci.yml`), sur une matrice
Linux + **Windows** : la suite derrière un **seuil de couverture**, le test de fumée de l'interface sur
le faux tkinter, des assertions sur les codes de sortie, une vérification du NDJSON, `--doctor` et
`--license`, puis **un build de l'`.exe` avec un test de fumée du fichier construit** (`--version`,
`--simulate`, une mauvaise configuration -> code 3) ainsi qu'une vérification que le pilote WinDivert
est bien livré à côté de l'exe, avec un artefact téléchargeable.

<!-- ci-jobs:start -->
Chaque job de ce workflow, et ce que signifie un job rouge :

| job | ce qu'il fait |
|---|---|
| `public-text` | les messages de commit et la description de la pull request : en anglais, avec des tirets simples, rien de propre à une machine |
| `lint` | **ruff**. Le code mort, les formes de bug, le plafond de complexité et le plafond d'arguments font échouer l'exécution. La famille sécurité est rapportée et ne bloque jamais |
| `types` | **mypy** sur le paquet |
| `semgrep` | le jeu de règles par défaut du registre. ERROR, HIGH et CRITICAL font échouer l'exécution, le reste est affiché |
| `mutations` | casse chaque comportement gardé et prouve que son test passe au rouge. Une pull request exécute les entrées qu'elle a touchées, l'exécution hebdomadaire les exécute toutes |
| `audit` | **pip-audit** sur l'ensemble figé. Chaque semaine, pour demander si le monde a bougé sous des versions qui n'ont pas bougé, et sur une pull request qui modifie un fichier de dépendances, pour demander si l'ensemble a bougé. L'exécution hebdomadaire ouvre une issue, et une pull request qui fige quelque chose de vulnérable échoue tout simplement |
| `tests` | la suite, le test de fumée de l'interface, la vérification de rendu avec le vrai Tk et les assertions de la CLI, sous Linux et Windows |
| `linux-capture` | la capture expérimentale sous Linux sur un vrai noyau : la ligne de commande en root, dans son propre espace de noms réseau. La latence et la perte doivent atteindre la cible et rien d'autre. Non requis pour fusionner |
| `build` | l'exécutable Windows, testé en fumée, avec la vérification du pilote et l'analyse du registre des licences |
| `cron-issue` | ouvre une issue quand l'exécution hebdomadaire passe au rouge, dédoublonnée selon les jobs en échec. Une tâche cron est facile à manquer et rien d'autre n'en annonce une. Il répond aussi à une exécution lancée à la main, ce qui est le seul moyen de l'exercer sans attendre un lundi rouge. Ne s'exécute jamais sur une pull request, et ne ferme jamais une issue de lui-même |
<!-- ci-jobs:end -->

**Trois vérifications statiques tournent à côté des tests**, uniquement sous Linux, parce qu'elles lisent
le code source au lieu de l'exécuter. **ruff** fait échouer une pull request sur un constat de code
mort ou de forme de bug (`F` et `B`) et rapporte la famille sécurité (`S`, `ASYNC`) sous forme
d'annotations qui ne bloquent jamais. Deux de ses règles sont des plafonds plutôt que des opinions :
`C90` pour le nombre de chemins à travers une fonction et `PLR0913` pour le nombre d'arguments
qu'elle prend, tous deux réglés sur le plus large qui existe aujourd'hui, ils sont donc silencieux
jusqu'à ce que quelque chose les dépasse. **mypy** vérifie les types du paquet. **semgrep** analyse
avec son jeu de règles par défaut du registre, et un constat de niveau ERROR, HIGH ou CRITICAL fait
échouer l'exécution, tandis que tout ce qui est en dessous est affiché en entier. Les versions des
trois outils sont figées, si bien qu'une nouvelle version d'un linter ne peut pas faire passer au
rouge une pull request qui n'a rien changé : ruff et mypy dans `requirements-lint.txt`, que la CI
installe par empreintes exactes de fichiers, et semgrep dans `requirements-scan.txt`, figé sur une
version seulement. Semgrep est le seul endroit où une version figée ne peut de toute façon pas
promettre une réponse stable, car il télécharge ses règles à l'exécution.

**Les dépendances sont vérifiées sous trois angles.** Le job `audit` exécute pip-audit sur l'ensemble
d'exécution et de build tel qu'installé. `review new dependencies`
(`.github/workflows/dependency-review.yml`) fait échouer une pull request qui ajoute une dépendance
avec un avis de sécurité connu ou une licence que le projet ne peut pas distribuer.
**OSV-Scanner** (`.github/workflows/osv-scanner.yml`) lit chaque fichier de dépendances figées
contre la base OSV : sur `master` et chaque semaine, il rapporte dans l'onglet Security, et sur une
pull request, il n'échoue que lorsque cette pull request apporte un nouvel avis.

Une étape mérite d'être connue parce qu'aucun test unitaire ne peut faire son travail : une
**vérification du rendu de l'interface sur le vrai Tk** sous un écran virtuel, au minimum pris en
charge de 1366x768, **dans chaque langue**. Elle construit la vraie fenêtre, parcourt chaque page,
ouvre la fenêtre About et fait échouer le build lorsqu'un bouton est plus étroit que ce qu'il demande,
c'est-à-dire lorsque son texte est rogné. Les libellés polonais sont plus longs que les anglais, c'est
donc là que les mises en page cassent, et elle a détecté des défauts invisibles en anglais.

Les versions sont publiées par un second workflow (`.github/workflows/release.yml`) sur un tag `v*`.
Il compare le tag à `VERSION.txt`, refuse de publier tant que les journaux des modifications sont
encore ouverts, construit l'exe et le teste en fumée, puis ouvre un **brouillon** accompagné du SBOM
SPDX. Il ne publie volontairement aucune archive : la clé de signature vit sur une carte matérielle
qu'aucun runner ne peut atteindre, l'archive est donc signée sur la machine du mainteneur
(`tools/sign_release.py`) et envoyée depuis là, puis un troisième workflow atteste les octets qui sont
réellement livrés.

Une version publiée comporte donc le zip, le `SHA256SUMS.txt` que ce README vous dit de vérifier, le
SBOM et le bundle d'attestation. Une version complète comporte un cinquième fichier, l'installeur
`.msi`. Une version candidate n'en a pas, car Windows Installer ignore le `-rc.1` et traiterait une
candidate et sa version finale comme la même version.

## Organisation du projet

Le code est découpé dans le paquet `beantester/`. Un lanceur léger `bean_network_tester.py` reste à
la racine, si bien que toutes les commandes existantes (README, rapports de reproduction,
PyInstaller) fonctionnent sans changement.

```
bean_network_tester.py   lanceur + façade de compatibilité (réexporte l'API publique)
beantester/              le paquet d'implémentation
  core.py                noyau de décision pur, paquet par paquet (BeanCore)
  damage.py              ampleur des dégâts d'une session : raisons d'abandon, parts de perte/corruption
  engine.py              threads de capture/réinjection, statistiques (BeanEngine)
  connlog.py             le journal des connexions de la session : une ligne par flux, et son plafond
  driverwait.py          combien de temps les paquets ont attendu dans la file du pilote avant l'outil
  matchers.py            expressions de filtre (liste/plage/!/>/</générique/re:) - partagées
                         par les champs processus, IP et port : une seule source de vérité
  settings.py            modèle des réglages, fichier de configuration, apply_settings
  scenario.py  presets.py  filters.py  summary.py  repro.py  views.py
  cli.py                 analyseur d'arguments, mode CLI et répartiteur interface/CLI
  exitcodes.py           CODES DE SORTIE - le contrat CLI/CI-CD (source unique de vérité)
  clilog.py              sortie de la CLI : journal sur stderr ([bean]), données sur stdout (texte/NDJSON)
  winenv.py              Windows : administrateur, élévation (UAC), détachement de la console, DPI
  driver.py              cycle de vie du pilote WinDivert + --doctor / --cleanup-driver
  fields.py              REGISTRE DES CHAMPS - source unique de vérité : type, libellé, unité,
                         plage, section du formulaire, portée du profil, option CLI
  validators.py          validation des nombres et des plages (partagée par l'interface, la CLI et le fichier de configuration)
  portmap.py             table des sockets : port local -> PID (iphlpapi/ctypes, repli psutil),
                         et chaque socket avec son état pour l'onglet Tools
  adapters.py            cartes réseau et route de sortie (iphlpapi/ctypes), pour l'onglet Tools
  proxy.py               le proxy que ce compte et cette machine utilisent (winhttp/ctypes et le
                         registre), en lecture seule, pour l'onglet Tools
  tcpreset.py            réinitialise une connexion TCP (iphlpapi/ctypes), pour le menu de ligne
                         de la page Connections
  targeting.py           ensemble des ports cibles en direct : arbre de processus, demande une reconstruction en cas de manque
  target_resolver.py     reconstruit cet ensemble de ports sur son propre thread, hors du chemin des paquets
  socketwatch.py         port local -> PID en direct à partir des événements SOCKET de WinDivert (source pilotée par les événements)
  jsonfile.py            écriture atomique + mise en quarantaine des fichiers utilisateur corrompus
  crashlog.py            journal de plantage : quiet/note/once, quarantaine, rapport en arrière-plan
  appinfo.py             identité de l'application et lecteur de version (une seule source : VERSION.txt)
  i18n.py  paths.py  utils.py  processes.py  synthetic.py  legal.py  scenario_runner.py
  nettools/              la logique derrière l'onglet Tools, un module par outil - pas de tkinter,
                         donc testée sans fenêtre
  gui/                   l'interface tkinter
    app.py               composition de la fenêtre, état, start/stop, état modifié
    logview.py           la zone de journal : sa file, son tampon de lignes et son widget
    form.py              formulaire généré à partir de fields.FIELD_DEFS
    form_search.py       rapprochement d'une requête saisie avec le registre des champs (pur)
    scaling.py           DPI, pixels mis à l'échelle, géométrie fenêtre/graphique/infobulle
    wheel.py             normalisation de la molette de la souris (une fonction pure)
    scrollable.py        ScrollableFrame + UN répartiteur global de la molette
    accordion.py         sections repliables
    ui_state.py          persistance de l'état de la fenêtre (bean_network_tester_ui.json)
    prefs.py             préférences de l'interface (langue, graphique, journal) stockées dans ui.json
    pages/               registre des pages : control, stats (3 sous-onglets), conns, toolbox (Tools)
    toolbox/             l'onglet Tools : son registre d'outils et un panneau par outil
    field_actions.py     remplir un champ de la page Control depuis ailleurs (menus de ligne des tables, onglet Tools)
    clipboard.py         copier un texte entier, confirmé en relisant le presse-papiers
    links.py             les boutons Donate et GitHub - le seul code qui ouvre une page web
    configure.py         configurer un widget avec seulement les options qui changent réellement
    panels/              fenêtres secondaires : "About", "Settings" et le journal d'événements détaché
    widgets/             SortableTree (tri, différentiel de lignes, Ctrl+C, plafond de largeur de colonne, menu de ligne)
    model_worker.py      reconstruit le modèle d'une table sur un thread de travail (l'interface ne bloque jamais)
    windows.py           classe de base et registre des fenêtres secondaires
    dialogs.py           remplacements sombres, intégrés à l'application, de messagebox/simpledialog
    rates.py             moyenne du débit et pic de chaque vue (pur, testable)
    scope.py             ce que couvrent les nombres à l'écran (un seul verdict pur)
    crash.py             ce que l'interface dit au journal de plantage : contexte du rapport, fil d'Ariane
    csv_export.py        les deux exports CSV et les noms de colonnes qu'ils écrivent
    session_repro.py     avec quoi la session a tourné : le rapport de reproduction et "Copy CLI command"
    applied.py           ce à quoi "Apply changes" compare le formulaire (une fonction pure)
    theme.py  chart.py  tooltip.py  profiles.py  icon.py  labels.py
lang/                    traductions (en, pl, zh)
tests/                   tests pytest
smoke_gui.py             test de fumée de l'interface sur un faux tkinter
BeanNetworkTester.spec   la recette de build (onedir, console, asInvoker)
```

## Fonctionnement (en bref)

Le noyau `BeanCore.decide()` est une fonction pure qui décide du sort d'un paquet, dans cet ordre :
ciblage -> mode LAN -> blocage (pare-feu) -> NAT -> RST -> oscillation -> MTU -> SYN -> perte -> corruption ->
délai/gigue/pic -> limite de débit (un seau à jetons avec un tampon borné, éventuellement issu de la
planification) -> duplication. Le thread de capture lit les paquets et exécute la décision. Le thread de
réinjection les renvoie au moment choisi. Tout l'aléa passe par un seul générateur (éventuellement
initialisé par une graine).

## Remarques et limitations

- L'outil modifie le trafic qui correspond au filtre. Pour des tests plus ciblés, utilisez "Target
  process" ou "Target destination".
- Ping = ICMP : pour l'affecter, choisissez un filtre qui inclut l'ICMP.
- Une limite de débit se voit mal sur un ping (petits paquets) - testez avec un téléchargement de
  fichier.
- La capture et l'injection réelles de RST ne fonctionnent que sous Windows avec WinDivert. La
  logique est confirmée par des tests qui s'exécutent partout.
- Un outil pour tester vos propres applications et vos propres réseaux.

### Comportements à connaître

- **La planification boucle** - après la dernière étape, elle revient à la première (`2:100:0, 2:500:0`
  alterne 2 s à 100 KB/s et 2 s à 500 KB/s, sans fin). Appliquer une planification modifiée en cours de
  session fait repartir le cycle de la première étape. Appliquer la même une seconde fois, ou changer
  n'importe quel autre réglage, laisse le cycle là où il en est.
- **La planification prime sur une limite fixe** - lorsque le champ "Schedule" n'est pas vide, les
  valeurs "Download/Upload" (KB/s) sont ignorées, car le débit provient des étapes de la
  planification.
- **La planification est facultative mais doit être valide** - un champ vide = pas de planification,
  tandis qu'une saisie incorrecte (par ex. `1:100`, `2:abc:0`) est signalée comme une erreur :
  l'interface ne démarre pas la session et la CLI se termine avec un message. Rien n'est ignoré en
  silence.
- **Les expressions de filtre sont validées** - une saisie invalide dans le champ processus/IP/port
  (par ex. `999.1.1.1`, `2000-1000`, `>chrome`, `re:[`) est signalée comme une erreur au lieu de ne
  rien faire en silence : dans l'interface, le champ devient rouge avec la raison en dessous, et la CLI
  se termine par un message `error: ...`. La comparaison d'adresses ne dépend pas de la notation (une
  forme IPv6 courte et une forme complète sont la même adresse).
- **Les termes positifs s'additionnent, les exclusions se soustraient** - `80,443,!8080` signifie "80
  ou 443 mais pas 8080", et `!53` seul signifie "tout sauf 53". L'ordre des termes n'a pas
  d'importance. Détails et cas limites : [Syntaxe des filtres](#syntaxe-des-filtres-processus--ip--port).
- **Les plages sont inclusives aux deux bouts** - `8000-8100` couvre 8000 et 8100 (comme dans
  nmap/iptables), et `80-80` est exactement un seul port.
- **L'IP et le port de "Target destination" se combinent avec ET** - renseigner les deux champs
  restreint au trafic qui satisfait **les deux** conditions à la fois.
- **Une limite de débit très basse = une vraie perte** - avec le tampon par défaut (1000 ms),
  l'excédent au-dessus de la limite est abandonné dès que le tampon est plein et compté dans la
  statistique **"Rate-limit drop"** (un compteur à part, pas "Loss") - c'est ainsi que se comporte une
  liaison engorgée, la perte effective peut donc alors être supérieure au pourcentage "Loss"
  configuré. Ce n'est qu'avec `--buffer 0` (un tampon illimité) que la file de l'outil grossit jusqu'à
  son plafond strict de **20 000** paquets, et l'excédent est alors compté comme
  **"Buffer overflow"**.
- **Un champ Seed vide = une graine aléatoire** - le programme tire quand même une valeur concrète et
  l'affiche dans le panneau de session. Dans les fichiers de configuration, la valeur `-1` signifie
  "aléatoire", `-1` ne peut donc pas servir de graine ordinaire (tout autre nombre, y compris négatif,
  fonctionne normalement).
- **Le ciblage de processus inclut les processus enfants** - un socket appartient à la cible si le
  processus **qui l'a ouvert, ou l'un de ses ancêtres**, correspond. C'est pourquoi `chrome.exe` (ou le
  PID de la fenêtre du navigateur) attrape aussi son processus réseau - celui qui détient toutes les
  connexions. Une exclusion explicite l'emporte : `chrome, !chromedriver` n'attirera pas `chromedriver`
  par l'intermédiaire d'un parent.
- **Le ciblage de processus est piloté par des événements de sockets, pas par une lente
  interrogation.** WinDivert nous remet un paquet, pas un PID, nous associons donc un paquet à son
  processus par le **port local**. Sous Windows, l'outil surveille les événements de sockets du
  système (connect / bind / accept / close) au moment où ils se produisent, si bien qu'une nouvelle
  connexion **ou un nouveau flux UDP** d'un programme **déjà** dans le périmètre est dégradé dès son
  tout premier paquet - cela couvre les requêtes DNS et QUIC, qui prennent chacun un nouveau port.
  L'exception est la *première* connexion du programme : tant qu'il ne possède pas au moins un socket,
  il n'y a rien pour le reconnaître, et cette connexion passe donc intacte. Sans le vrai WinDivert (le
  chemin de test / simulation), l'outil se rabat sur une analyse de la table des sockets quelques fois
  par seconde, où le premier paquet de toute connexion toute neuve peut passer à travers. Dans les deux
  cas, la surveillance tourne sur son propre thread, jamais sur celui qui traite vos paquets, elle ne
  peut donc jamais se transformer en trafic perdu.
- **Si le programme testé redémarre, visez par son NOM, pas par son identifiant de processus.**
  Mesuré : une cible qui se termine et revient sous un nouvel identifiant de processus est reprise
  toute seule, et le redémarrage coûte exactement une connexion - celle qu'elle ouvre avant de
  posséder le moindre socket. Viser un **identifiant de processus** ne se rétablit jamais, parce que
  cet identifiant désignait le processus qui s'est terminé : tout ce qui suit le redémarrage est
  laissé intact. Un programme à qui Windows attribue plus tard le même numéro est lui aussi laissé
  intact - un identifiant de processus ne désigne jamais que le processus qui le portait quand vous
  avez défini la cible. En ligne de commande, l'exécution le signale quand cela arrive, et se termine
  en indiquant quelle part du trafic capturé était réellement dans le périmètre. Dans la fenêtre, c'est
  la note rouge sous le champ du processus.
- **Une exclusion seule couvre aussi tout ce que l'outil ne peut pas identifier.** `!chrome` dans le
  champ processus signifie "dégrade tout sauf chrome" - et "tout" inclut toute connexion dont le
  processus propriétaire n'a pas pu être déterminé : les processus système protégés que l'outil ne
  peut pas ouvrir et - sur le repli par interrogation - les premiers paquets d'un socket tout neuf.
  **N'utilisez donc pas une exclusion pour protéger une application.** Si vous voulez qu'une
  application soit laissée tranquille, nommez celle que vous voulez VOIR casser (`--target thatapp`) -
  alors tout ce qui n'est pas identifié passe intact, ce qui est le sens sûr. C'est le pendant de
  `!53` sur les ports, plus bas.
- **Un ciblage qui n'attrape rien ne casse rien** - si aucun processus correspondant n'a de connexion
  ouverte, le trafic passe intact. Cela couvre un programme qui ne tourne pas et un programme qui
  tourne mais reste inactif. Quand un tel programme ouvre une connexion, l'outil l'ajoute en quelques
  millisecondes, si bien que les premiers paquets de cette connexion peuvent passer intacts et que le
  reste est dégradé. Le programme le dit explicitement (une note rouge sous le champ et une entrée de
  journal), parce qu'"une exécution où rien n'a cassé" ressemble à s'y méprendre à "l'application a
  tenu".
- **Un nom de processus seul est une sous-chaîne** - `chrome` attrape aussi `chromedriver.exe`. C'est
  conservé volontairement (compatibilité avec les anciennes configurations). Pour de la précision,
  utilisez `re:^chrome\.exe$` ou l'exclusion `chrome, !chromedriver`.
- **Une cible qui désigne tous les programmes ne restreint rien** - `*.exe`, `exe` ou `*` correspondent
  à presque tous les processus qui ont une connexion, si bien qu'une telle exécution reçoit le même
  avertissement au démarrage qu'une exécution sans aucune cible.
- **Statistics et Connections montrent TOUT le trafic capturé par défaut** - quel que soit ce que le
  filtre "Traffic to modify" laisse passer. Le ciblage (processus / IP / port) décide uniquement
  **de ce qui est cassé**, pas de ce qui est visible dans les tables et les compteurs. Deux
  interrupteurs de Settings, dans la carte **"Scope"**, changent cela, et ce n'est pas la même chose :
  - **"Show only the targeted traffic"** restreint les compteurs, le graphique de débit, la table
    Connections et le CSV des connexions à ce que votre ciblage a sélectionné. Cela change ce que vous
    VOYEZ - jamais ce qui est capturé, jamais ce qui est dégradé, et vous pouvez le basculer à tout
    moment.
  - **"Capture only the targeted traffic"** restreint *la capture elle-même* : le pilote cesse de
    remettre autre chose que le trafic de votre destination, de sorte que les onglets couvrent ce
    trafic parce qu'il n'y a rien d'autre à couvrir. Il est fixé au démarrage de la session, et ne
    fonctionne que pour une destination que le langage de filtre du pilote sait exprimer - une adresse
    simple, une liste, une plage ou un CIDR. Un caractère générique, un motif `re:` ou un ciblage de
    processus seul ne peuvent pas être poussés dans le pilote, et l'option ne fait alors rien. La
    carte Scope dit lequel des deux vous obtenez **avant** que vous appuyiez sur START, le journal le
    redit au démarrage, et la ligne **"Capture"** du panneau Session l'enregistre pour l'exécution.

  Quel que soit celui qui est actif, **la note au-dessus des compteurs et au-dessus de la table
  Connections dit ce que ces chiffres couvrent réellement**, y compris le cas où la capture est
  restreinte *et* où une cible de processus est définie - l'outil capture alors le trafic de votre
  destination venant de tous les processus et dégrade la part d'un seul processus, si bien que les
  compteurs couvrent plus que la dégradation.
  **Trois compteurs restent sur le trafic complet même avec "Show only" activé** : "Queue overflow",
  "Dropped at stop" et "Send failed" comptent des paquets que *cet outil* a perdus, y compris du
  trafic que vous n'avez jamais ciblé, et les masquer cacherait les propres dégâts de l'outil. Le CSV
  des statistiques ne suit pas non plus l'interrupteur "Show only" - c'est un journal à ajout, il
  porte donc les deux totaux dans des colonnes séparées - mais il enregistre bien "Capture only" par
  ligne dans `capture_narrowed`, parce que celui-là change ce qui a été compté tout court. Le rapport
  de reproduction et `--format json` portent toujours les deux nombres.
- **La limite de débit façonne la MOYENNE** - le seau à jetons laisse passer de brèves rafales, le
  "Download/Upload peak" (moyenné sur une fenêtre de 1 s) peut donc être un peu supérieur à la limite
  fixée. Les doublons comptent dans la limite (la seconde copie parcourt elle aussi la liaison).
- **La fenêtre a une taille maximale et ne peut pas être agrandie** - la mise en page (deux colonnes +
  la barre du journal) n'a plus de sens étirée en 4K, la taille est donc plafonnée et le bouton
  d'agrandissement retiré.
- **La durée se compte à partir de START** - modifier le champ en cours de session ne fait rien
  (comme le filtre de trafic). Une fois la limite atteinte, le programme fait simplement STOP et
  laisse les résultats à l'écran.
- **STOP abandonne les paquets qui attendent dans la file de délai** - la fin d'une session est
  immédiate. Avec une `latency` élevée, cela se voit comme un "trou" ponctuel. Ce n'est pas un bug.
- **Une défaillance en cours de session se termine toujours par un réseau rétabli** - si le thread de
  capture ou de réinjection meurt, ou cesse de progresser pendant 10 secondes, le moteur fait STOP de
  lui-même et libère le pilote (*fail-open*), au lieu de garder un handle ouvert que personne
  n'atteint (c'était un vrai chemin vers "l'utilisateur n'a soudain plus Internet"). La raison va dans
  le journal et dans le journal d'événements. Un thread encore bloqué après STOP est laissé de côté
  plutôt qu'attendu, et le START suivant le dit dans le journal.
- **Fermer le programme libère le pilote WinDivert** - pas après chaque session (un redémarrage de
  session doit être instantané), mais **une seule fois, à la sortie**. Tant que le pilote est chargé,
  le noyau garde ouvert le `WinDivert64.sys` situé à côté de l'exe - et alors **le dossier du programme
  ne peut pas être supprimé, même s'il paraît vide** (Windows vous laisse supprimer un fichier dont un
  handle est ouvert : il disparaît de la liste mais reste en *suppression en attente* et bloque le
  dossier). S'il reste quelque chose, le sauvetage sans redémarrage est
  `BeanNetworkTester.exe --cleanup-driver` (ou `sc stop
  WinDivert` + `sc delete WinDivert`). À la sortie, le programme ne touche qu'au service `WinDivert`
  qu'il charge, et le laisse chargé tant qu'une autre copie de ce programme l'utilise.
  `--cleanup-driver` arrête aussi `WinDivert1.4` et `WinDivert1.1`, que d'autres programmes installent.
- **"Duration" et "Traffic to modify" ne sont pris en compte qu'au START** - c'est pourquoi pendant une
  session les deux sont **verrouillés** (un champ modifiable qui ne fait rien est pire qu'un champ
  grisé).

## Contribuer

Les contributions sont les bienvenues. [CONTRIBUTING.md](CONTRIBUTING.md) explique comment configurer
les tests et quelles conventions le projet suit. Veuillez aussi lire le
[Code de conduite](CODE_OF_CONDUCT.md). Les rapports de bug et les demandes de fonctionnalités passent
par les modèles d'issue, et les problèmes de sécurité sont traités en privé via la
[politique de sécurité](SECURITY.md).

## Soutenir le projet

Le projet est développé par **DonislawDev** et il est gratuit. Si l'outil vous fait gagner du temps et
que vous souhaitez voir apparaître plus de fonctionnalités, vous pouvez **volontairement** soutenir son
développement :

**https://donislawdev.com/support/**

Le soutien est entièrement facultatif - toutes les fonctionnalités marchent sans lui. Dans le
programme, le bouton **Donate** y mène (l'en-tête de la fenêtre et la fenêtre About). Le bouton
**GitHub** à côté ouvre la page de ce projet.

## Auteur

**DonislawDev** - https://donislawdev.com/

Bean Network Tester est développé avec une méthode de travail assistée par IA.

## Licence

Bean Network Tester est un **logiciel libre et open source**, sous licence **GNU General Public
License, version 3 (GPLv3)** - voir le fichier [LICENSE](LICENSE).

En bref : vous êtes libre de l'utiliser à n'importe quelle fin (privée ou commerciale), d'étudier son
fonctionnement et de le modifier, et d'en redistribuer des copies - y compris modifiées - à condition
de transmettre le programme sous les mêmes termes GPLv3 et de rendre le code source correspondant
disponible. Le programme est fourni "EN L'ÉTAT", sans garantie ni responsabilité de la part de
l'auteur. L'auteur est **DonislawDev**.

### Marques et chiffres des profils prêts à l'emploi

Ookla, Speedtest, Starlink, HughesNet et Viasat sont des marques de leurs propriétaires respectifs.
Elles ne sont nommées dans ce projet que pour une seule raison : dire de **quelles mesures publiées**
proviennent les chiffres d'un profil. Bean Network Tester n'est ni affilié à aucune d'elles, ni
approuvé, ni sponsorisé par elles, et aucune de leurs données n'est redistribuée ici - seulement des
chiffres isolés, cités avec leur source, comme n'importe quel document technique en cite un.

### Ce que vous produisez avec est à vous

**La GPL couvre le programme, pas ce qu'il produit.** Les fichiers de scénario que vous écrivez, les
profils enregistrés et les fichiers de configuration, les rapports de reproduction, les CSV exportés,
les fichiers journaux et les captures d'écran sont votre propre travail. Utiliser Bean Network Tester
ne les place pas sous la GPL et ne vous oblige à rien publier. Gardez-les privés, livrez-les avec un
produit propriétaire, vendez-les - c'est votre choix.

Une seule chose à garder à part : les scénarios d'exemple qui sont fournis **avec** le programme, dans
le dossier `scenarios/`, font partie du projet et sont sous GPLv3 comme le reste. Un scénario que vous
écrivez vous-même ne l'est pas, même si vous êtes parti de l'un d'eux en changeant les chiffres.

## Composants tiers

Le programme utilise des bibliothèques d'autres auteurs, sous leurs propres licences - parmi elles
**[WinDivert](https://www.reqrypt.org/windivert.html)** et
**[PyDivert](https://github.com/ffalcinelli/pydivert)** sous **LGPLv3**,
**[psutil](https://github.com/giampaolo/psutil)** (BSD), **[CPython](https://www.python.org/)** (PSF),
**[Tcl/Tk](https://www.tcl-lang.org/)** et le chargeur d'amorçage de
**[PyInstaller](https://pyinstaller.org/)**. La liste complète, les versions et les adresses des
sources se trouvent dans
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md), et les textes complets des licences dans le dossier
`licenses/`. Depuis le programme : `--license` (CLI) ou le bouton **About** de l'interface.

Les bibliothèques LGPL peuvent être remplacées par vos propres versions compatibles avec l'interface,
et les deux se remplacent différemment. **WinDivert** est une DLL et un pilote chargés depuis le
disque à l'exécution, vous remplacez donc les fichiers dans `_internal\pydivert\windivert_dll\` - c'est
pourquoi le programme est construit en **onedir** plutôt qu'en fichier unique. **PyDivert** est du
Python pur et est compilé dans le .exe, il se remplace donc en reconstruisant le programme avec votre
version, ou en l'exécutant depuis les sources. Déposer une copie modifiée à côté du .exe ne
fonctionne pas, et
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) le dit plutôt que de vous laisser le découvrir. La
GPLv3 est compatible avec les licences de ces composants, et rien dans la licence du projet ne
restreint les droits qui en découlent.

## Vie privée : aucune télémétrie

Bean Network Tester **n'envoie rien de lui-même**. Il n'a ni télémétrie, ni vérification de mise à
jour, ni service externe. L'outil capture le trafic réseau sur votre ordinateur - et ces données
**ne le quittent jamais**. Deux choses sortent, et seulement quand vous les demandez : une page
ouverte dans votre navigateur - la page de soutien ou la page du projet sur GitHub - quand vous
cliquez vous-même sur le bouton correspondant, et les requêtes d'écho de l'outil **Ping** de
l'onglet Tools, qui ne vont qu'à l'adresse que vous saisissez, de Start à Stop. Si vous saisissez un
nom au lieu d'une adresse, Windows le résout d'abord, comme pour n'importe quel programme.

## À propos de SmartScreen et des antivirus

**Depuis la 0.5.0, le .exe est signé**, avec un certificat dont la clé privée vit sur une carte
matérielle qui ne quitte jamais le bureau du mainteneur - Windows nomme donc l'éditeur au lieu
d'afficher "Éditeur inconnu". Sachez ce que cela apporte et ce que cela n'apporte pas : un nouveau
certificat n'a pas encore de réputation SmartScreen, un avertissement peut donc encore apparaître
pendant un temps, et certains antivirus peuvent encore lever une fausse alerte sur un programme qui
demande les droits d'administrateur et charge un pilote réseau. Ce qui change, c'est que
l'avertissement dit maintenant qui l'a signé. Le **pilote WinDivert lui-même est signé numériquement
par son auteur**. Vous pouvez toujours comparer la somme de contrôle SHA-256 de la version
(`SHA256SUMS.txt`) pour confirmer que le fichier est arrivé intact.

**Vous pouvez aussi vérifier ce que contient le téléchargement, pas seulement qu'il est intact.**
Chaque archive de version porte une déclaration signée qui liste tout ce qu'elle contient, établie par
le propre workflow de ce dépôt sur les octets exacts que vous avez téléchargés :

```bash
gh attestation verify BeanNetworkTester-v0.5.0-windows-x64.zip -R donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

Une somme de contrôle prouve que le fichier correspond à ce que dit la page de la version. Ceci prouve
que la nomenclature (bill of materials) qui l'accompagne décrit ces mêmes octets, et que la déclaration
a été établie par un workflow de ce dépôt plutôt que par la personne qui vous a remis le fichier.

`--predicate-type` n'est pas facultatif. Sans lui, `gh` cherche une déclaration de provenance du build
et répond `HTTP 404`, parce que l'archive que vous téléchargez a été **signée sur la machine du
mainteneur**, et non construite sur un runner - la clé de signature est sur une carte qu'aucun runner
ne peut atteindre. La provenance est attestée pour le build non signé dans le workflow. Ce qui voyage
avec la version, c'est la nomenclature portant sur le fichier signé.

Cette commande demande à GitHub quelles attestations existent. La preuve est aussi livrée **sous forme
de fichier**, `BeanNetworkTester-vX.Y.Z.sigstore.json`, pour que vous puissiez vérifier l'archive
contre une preuve qui a voyagé avec elle :

```bash
gh attestation verify BeanNetworkTester-v0.5.0-windows-x64.zip --bundle BeanNetworkTester-v0.5.0.sigstore.json --repo donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

Les deux options supplémentaires sont nécessaires et aucune n'est décorative. `--repo` nomme le dépôt
auquel l'identité de signature doit correspondre. `--predicate-type` est là parce que ce bundle est
l'attestation du **SBOM**, et `gh` cherche une attestation de provenance de build sauf indication
contraire - sans elle, vous obtenez "no attestations found with predicate type", ce qui est l'outil
qui se montre précis et non défaillant. Quand le fichier est bon, il n'affiche rien et se termine avec
0. Changez un seul octet et il se termine avec 1.

Trois déclarations, et il vaut la peine de savoir qu'elles répondent à des questions différentes. La
**signature** dit qui se porte garant du fichier. Le **bundle ci-dessus** lie cette archive exacte à sa
nomenclature, et il est établi après la signature, sur les octets que vous avez téléchargés. La
**provenance du build** dit quel commit et quel workflow ont produit le build qui a ensuite été signé
- elle décrit forcément le build non signé, parce que la signature change les octets, et elle vit
dans le magasin d'attestations de ce dépôt plutôt que dans le téléchargement.

### Ce que contient le téléchargement, et comment le vérifier

Chaque version porte un **SBOM** - une liste, au format standard SPDX, de chaque composant tiers du
build avec sa version, sa licence et l'endroit où se trouve son code source. C'est la même liste que
celle qu'affiche `BeanNetworkTester.exe --license`, sous une forme qu'un outil peut lire.

Le SBOM est **signé contre l'archive qu'il décrit**, les deux ne peuvent donc pas être séparés :

```bash
gh attestation verify BeanNetworkTester-vX.Y.Z-windows-x64.zip --repo donislawdev/BeanNetworkTester --predicate-type https://spdx.dev/Document/v2.3
```

Une somme de contrôle vous dit que le fichier est arrivé intact. L'attestation vous dit que *cette*
nomenclature appartient à *cette* archive, et que la déclaration a été établie par le workflow de
version de ce dépôt. Omettez `--predicate-type` et `gh` cherche à la place une déclaration de
provenance du build et répond `HTTP 404`.
