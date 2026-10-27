# SPDX-License-Identifier: GPL-2.0-or-later
"""The Gravity Rush launcher window (Tkinter).

A fixed layout that never overlaps: a dark glass sidebar on the left (brand, menu, status, the
play button), the background picture on the right, pages in an opaque card beside the sidebar,
dialogs and notices in that area too. Shapes, icons and labels are drawn with Pillow (Tk has no
anti-aliasing, clip paths or blur), the controls are Tk widgets on the card. Only what the port
really does is shown.

The logic (settings, run.py environment, saves, game process) is the one of
gravityrush_launcher.py, passed in as `logic`.
"""
import ctypes
import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageTk

# Frozen (Gravity Rush Launcher.exe), the code runs from PyInstaller's temporary folder: the files live in
# the launcher folder beside the executable.
HERE = Path(sys.executable).resolve().parent / 'launcher' if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
FONT_FILE = HERE / 'fonts' / 'Cabin.ttf'
BACKGROUND = HERE / 'assets' / 'background.png'   # a player's own picture (optional, never in the repository)
DEFAULT_BACKGROUND = HERE / 'background.jpg'      # the launcher's own picture (no game characters)

# Design size; everything is scaled from it.
W, H = 1120, 700
SIDEBAR_W = 272

# Dark theme: glass over the background picture, opaque cards for the pages (Tk widgets need a
# solid background), one gold accent.
CARD, FIELD, FIELD_HI = '#12171d', '#1b222b', '#232c37'   # card and dialogs; inputs (normal, hover)
LINE, LINE2, LINE3 = '#252e38', '#34404d', '#465361'       # rules, input borders, hovered borders
TEXT, TEXT2, TEXT3 = '#eef1f5', '#a9b2be', '#76818f'       # text, secondary text, captions
ACCENT, ACCENT_HI, ACCENT_LO, ON_ACCENT = '#f0b23e', '#f6c45f', '#d89a27', '#1b1306'
OK_C, WARN_C = '#43c584', '#f0a63e'
CONSOLE_BG = '#0b0f14'
GLASS = (11, 15, 20, 222)  # the sidebar over the picture
# The names the pages use.
PAPER, PAPER2, INK, MU, SD, TX = CARD, FIELD_HI, CONSOLE_BG, TEXT2, TEXT, TEXT
UI_FONT, UI_FONT_SEMI = 'Segoe UI', 'Segoe UI Semibold'  # Windows' own font

# ---------------------------------------------------------------------------------------------
# Texts in the European set (EFIGS: English, French, Italian, German, Spanish). Each row: English,
# Italian, French, German, Spanish. The launcher follows Windows unless a language is chosen.

LANGUAGES = [('it', 'Italiano'), ('en', 'English'), ('fr', 'Français'), ('de', 'Deutsch'), ('es', 'Español')]
_ROWS = [
    ('Play', 'Avvia', 'Jouer', 'Spielen', 'Jugar'),
    ('Game', 'Gioco', 'Jeu', 'Spiel', 'Juego'),
    ('Video', 'Video', 'Vidéo', 'Video', 'Vídeo'),
    ('Controls', 'Controlli', 'Commandes', 'Steuerung', 'Controles'),
    ('Advanced', 'Avanzate', 'Avancé', 'Erweitert', 'Avanzado'),
    ('Log & diagnostics', 'Log e diagnostica', 'Journal et diagnostic', 'Protokoll & Diagnose', 'Registro y diagnóstico'),
    ('Quit', 'Esci', 'Quitter', 'Beenden', 'Salir'),
    ('VERSION {}', 'VERSIONE {}', 'VERSION {}', 'VERSION {}', 'VERSIÓN {}'),
    ('Version {}', 'Versione {}', 'Version {}', 'Version {}', 'Versión {}'),
    ('FOLDERS', 'CARTELLE', 'DOSSIERS', 'ORDNER', 'CARPETAS'),
    ('Game folder', 'Cartella del gioco', 'Dossier du jeu', 'Spielordner', 'Carpeta del juego'),
    ('Your game dump (eboot.bin, sce_module, sce_sys).', 'Il tuo dump del gioco (eboot.bin, sce_module, sce_sys).',
     'Votre copie du jeu (eboot.bin, sce_module, sce_sys).', 'Dein Spiel-Dump (eboot.bin, sce_module, sce_sys).',
     'Tu copia del juego (eboot.bin, sce_module, sce_sys).'),
    ('Saves folder', 'Cartella dei salvataggi', 'Dossier des sauvegardes', 'Speicherordner', 'Carpeta de partidas'),
    ('Empty: the launcher data folder (it also holds the shader cache).',
     'Se vuota usa la cartella dei dati del launcher (contiene anche la cache degli shader).',
     'Vide : le dossier de données du lanceur (il contient aussi le cache des shaders).',
     'Leer: der Datenordner des Launchers (er enthält auch den Shader-Cache).',
     'Vacía: la carpeta de datos del lanzador (también guarda la caché de shaders).'),
    ('Browse…', 'Sfoglia…', 'Parcourir…', 'Durchsuchen…', 'Examinar…'),
    ('Open', 'Apri', 'Ouvrir', 'Öffnen', 'Abrir'),
    ('SHORTCUTS', 'COLLEGAMENTI', 'RACCOURCIS', 'VERKNÜPFUNGEN', 'ACCESOS DIRECTOS'),
    ('Create desktop shortcuts', 'Crea collegamenti sul desktop', 'Créer les raccourcis sur le bureau',
     'Desktop-Verknüpfungen erstellen', 'Crear accesos directos en el escritorio'),
    ('Gravity Rush starts the game with the saved settings, Gravity Rush Launcher opens this window.',
     'Gravity Rush avvia il gioco con le impostazioni salvate, Gravity Rush Launcher apre questa finestra.',
     'Gravity Rush lance le jeu avec les réglages enregistrés, Gravity Rush Launcher ouvre cette fenêtre.',
     'Gravity Rush startet das Spiel mit den gespeicherten Einstellungen, Gravity Rush Launcher öffnet dieses Fenster.',
     'Gravity Rush inicia el juego con los ajustes guardados, Gravity Rush Launcher abre esta ventana.'),
    ('SAVES', 'SALVATAGGI', 'SAUVEGARDES', 'SPIELSTÄNDE', 'PARTIDAS GUARDADAS'),
    ('Save backups', 'Backup dei salvataggi', 'Copies des sauvegardes', 'Spielstand-Backups', 'Copias de seguridad'),
    ('Restore', 'Ripristina', 'Restaurer', 'Wiederherstellen', 'Restaurar'),
    ('Refresh', 'Aggiorna', 'Actualiser', 'Aktualisieren', 'Actualizar'),
    ('Made before every start, newest first: the last {} are kept. Restoring backs up the current saves first.',
     'Creati prima di ogni avvio, dal più recente: ne restano {}. Il ripristino salva prima i dati attuali.',
     'Créées avant chaque lancement, les plus récentes d\'abord : les {} dernières sont gardées. La restauration '
     'sauvegarde d\'abord les données actuelles.',
     'Vor jedem Start erstellt, neueste zuerst: die letzten {} bleiben. Beim Wiederherstellen werden die aktuellen '
     'Spielstände zuerst gesichert.',
     'Se crean antes de cada inicio, de la más reciente a la más antigua: se guardan las últimas {}. Al restaurar se '
     'guardan antes los datos actuales.'),
    ('LANGUAGE', 'LINGUA', 'LANGUE', 'SPRACHE', 'IDIOMA'),
    ('Game language', 'Lingua del gioco', 'Langue du jeu', 'Spielsprache', 'Idioma del juego'),
    ('English', 'Inglese', 'Anglais', 'Englisch', 'Inglés'),
    ('Italian', 'Italiano', 'Italien', 'Italienisch', 'Italiano'),
    ('French', 'Francese', 'Français', 'Französisch', 'Francés'),
    ('German', 'Tedesco', 'Allemand', 'Deutsch', 'Alemán'),
    ('Spanish', 'Spagnolo', 'Espagnol', 'Spanisch', 'Español'),
    ('Japanese', 'Giapponese', 'Japonais', 'Japanisch', 'Japonés'),
    ('SCREEN', 'SCHERMO', 'ÉCRAN', 'BILDSCHIRM', 'PANTALLA'),
    ('Window mode', 'Modalità finestra', 'Mode d\'affichage', 'Fenstermodus', 'Modo de ventana'),
    ('Windowed', 'Finestra', 'Fenêtré', 'Fenster', 'Ventana'),
    ('Fullscreen', 'Schermo intero', 'Plein écran', 'Vollbild', 'Pantalla completa'),
    ('Borderless', 'Senza bordi', 'Sans bordure', 'Rahmenlos', 'Sin bordes'),
    ('Vertical sync', 'Sincronia verticale', 'Synchro verticale', 'Vertikale Synchronisation', 'Sincronización vertical'),
    ('FPS limit', 'Limite FPS', 'Limite d\'IPS', 'FPS-Limit', 'Límite de FPS'),
    ('Refresh rate', 'Frequenza schermo', 'Fréquence d\'affichage', 'Bildwiederholrate', 'Frecuencia de pantalla'),
    ('Desktop', 'Come Windows', 'Comme Windows', 'Wie Windows', 'Como Windows'),
    ('Used in Fullscreen and Borderless, while the game runs. Windowed keeps the Windows setting.',
     'Vale in Schermo intero e Senza bordi, mentre giochi. In Finestra resta quella di Windows.',
     'S\'applique en Plein écran et Sans bordure, pendant le jeu. En Fenêtré, le réglage de Windows reste.',
     'Gilt im Vollbild und rahmenlos, während das Spiel läuft. Im Fenster bleibt die Windows-Einstellung.',
     'Se aplica en Pantalla completa y Sin bordes, mientras juegas. En Ventana se mantiene el ajuste de Windows.'),
    ('Unlimited', 'Libero', 'Illimité', 'Unbegrenzt', 'Sin límite'),
    ('IMAGE', 'IMMAGINE', 'IMAGE', 'BILD', 'IMAGEN'),
    ('F12 closes the game', 'F12 chiude il gioco', 'F12 ferme le jeu', 'F12 beendet das Spiel', 'F12 cierra el juego'),
    ('F12 always saves screenshots and the log for bug reports; this also closes the game right after.',
     'F12 salva sempre screenshot e log per le segnalazioni; così chiude anche il gioco subito dopo.',
     'F12 enregistre toujours captures et journal pour les rapports ; ceci ferme aussi le jeu juste après.',
     'F12 speichert immer Screenshots und Log für Fehlerberichte; damit wird das Spiel danach auch beendet.',
     'F12 siempre guarda capturas y registro para los informes; así también cierra el juego justo después.'),
    ('Shadow quality', 'Qualità ombre', 'Qualité des ombres', 'Schattenqualität', 'Calidad de sombras'),
    ('Standard (2048)', 'Standard (2048)', 'Standard (2048)', 'Standard (2048)', 'Estándar (2048)'),
    ('High (4096)', 'Alta (4096)', 'Élevée (4096)', 'Hoch (4096)', 'Alta (4096)'),
    ('Sharper shadow edges and fewer jagged lines. Uses 256 MB of video memory.',
     'Bordi delle ombre più definiti e meno scalettati. Usa 256 MB di memoria video.',
     'Bords des ombres plus nets et moins crénelés. Utilise 256 Mo de mémoire vidéo.',
     'Schärfere Schattenkanten mit weniger Treppenstufen. Belegt 256 MB Grafikspeicher.',
     'Bordes de sombra más definidos y menos dentados. Usa 256 MB de memoria de vídeo.'),
    ('Anisotropic filtering', 'Filtro anisotropico', 'Filtrage anisotrope', 'Anisotrope Filterung',
     'Filtrado anisotrópico'),
    ("Game's own", 'Del gioco', 'Celui du jeu', 'Wie im Spiel', 'El del juego'),
    ('Sharper textures seen at an angle. The game already uses 16x on its world textures; this raises the '
     'ones that use less.',
     'Texture più nitide viste di sbieco. Il gioco usa già 16x sulle texture del mondo; questo alza quelle '
     'che ne usano meno.',
     'Textures plus nettes vues de biais. Le jeu utilise déjà 16x sur ses textures du monde ; ceci relève '
     'celles qui en utilisent moins.',
     'Schärfere Texturen bei schrägem Blick. Das Spiel nutzt für seine Welttexturen bereits 16x; dies hebt '
     'die an, die weniger nutzen.',
     'Texturas más nítidas vistas en ángulo. El juego ya usa 16x en sus texturas del mundo; esto sube las '
     'que usan menos.'),
    ('Render resolution', 'Risoluzione di rendering', 'Résolution de rendu', 'Render-Auflösung',
     'Resolución de renderizado'),
    ('Native (1080p)', 'Nativa (1080p)', 'Native (1080p)', 'Nativ (1080p)', 'Nativa (1080p)'),
    ('720p (faster)', '720p (più veloce)', '720p (plus rapide)', '720p (schneller)', '720p (más rápido)'),
    ('4K (sharpest)', '4K (massima nitidezza)', '4K (le plus net)', '4K (am schärfsten)', '4K (máxima nitidez)'),
    ('The size the game draws at. Above your screen it works as anti-aliasing: 4K on a 1440p screen is '
     'the cleanest image.',
     'La dimensione a cui il gioco disegna. Sopra quella dello schermo fa da antialiasing: il 4K su uno '
     'schermo 1440p dà l’immagine più pulita.',
     'La taille à laquelle le jeu dessine. Au-delà de votre écran, elle sert d’anticrénelage : la 4K sur un '
     'écran 1440p donne l’image la plus propre.',
     'Die Größe, in der das Spiel zeichnet. Über der Bildschirmauflösung wirkt sie als Kantenglättung: 4K auf '
     'einem 1440p-Bildschirm ergibt das sauberste Bild.',
     'El tamaño al que dibuja el juego. Por encima de tu pantalla actúa como antialiasing: 4K en una '
     'pantalla 1440p da la imagen más limpia.'),
    ('The game is made for 60 FPS; other values can change physics and animations.',
     'Il gioco è pensato per 60 FPS: valori diversi possono alterare fisica e animazioni.',
     'Le jeu est prévu pour 60 IPS : d\'autres valeurs peuvent modifier la physique et les animations.',
     'Das Spiel ist für 60 FPS gemacht; andere Werte können Physik und Animationen verändern.',
     'El juego está pensado para 60 FPS; otros valores pueden alterar la física y las animaciones.'),
    ('Reset', 'Ripristina', 'Réinitialiser', 'Zurücksetzen', 'Restablecer'),
    ('Apply', 'Applica', 'Appliquer', 'Übernehmen', 'Aplicar'),
    ('Reset all', 'Ripristina tutto', 'Tout réinitialiser', 'Alles zurücksetzen', 'Restablecer todo'),
    ('COMMAND', 'COMANDO', 'COMMANDE', 'BEFEHL', 'COMANDO'),
    ('CONTROLLER', 'CONTROLLER', 'MANETTE', 'CONTROLLER', 'MANDO'),
    ('KEYBOARD', 'TASTIERA', 'CLAVIER', 'TASTATUR', 'TECLADO'),
    ('BUTTONS', 'TASTI', 'TOUCHES', 'TASTEN', 'BOTONES'),
    ('D-PAD', 'CROCE DIREZIONALE', 'CROIX DIRECTIONNELLE', 'STEUERKREUZ', 'CRUCETA'),
    ('GYROSCOPE', 'GIROSCOPIO', 'GYROSCOPE', 'GYROSKOP', 'GIROSCOPIO'),
    ('Sensitivity', 'Sensibilità', 'Sensibilité', 'Empfindlichkeit', 'Sensibilidad'),
    ('Aiming by moving a DualSense or DualShock 4.', 'Per mirare muovendo un DualSense o un DualShock 4.',
     'Pour viser en bougeant une DualSense ou une DualShock 4.', 'Zum Zielen durch Bewegen eines DualSense oder DualShock 4.',
     'Para apuntar moviendo un DualSense o un DualShock 4.'),
    ('Click a key, then press the new one (Esc cancels).', 'Clicca un tasto, poi premi quello nuovo (Esc annulla).',
     'Cliquez sur une touche, puis appuyez sur la nouvelle (Échap annule).',
     'Klicke auf eine Taste und drücke dann die neue (Esc bricht ab).',
     'Haz clic en una tecla y pulsa la nueva (Esc cancela).'),
    ('Press a key…', 'Premi un tasto…', 'Appuyez sur une touche…', 'Taste drücken…', 'Pulsa una tecla…'),
    ('LAUNCHER', 'LAUNCHER', 'LANCEUR', 'LAUNCHER', 'LANZADOR'),
    ('Launcher language', 'Lingua del launcher', 'Langue du lanceur', 'Sprache des Launchers', 'Idioma del lanzador'),
    ('System', 'Sistema', 'Système', 'System', 'Sistema'),
    ('IN GAME', 'IN GIOCO', 'EN JEU', 'IM SPIEL', 'EN EL JUEGO'),
    ('Performance overlay', 'Overlay prestazioni', 'Affichage des performances', 'Leistungsanzeige', 'Indicador de rendimiento'),
    ('Shows the FPS while you play.', 'Mostra gli FPS mentre giochi.', 'Affiche les IPS pendant la partie.',
     'Zeigt die FPS beim Spielen.', 'Muestra los FPS mientras juegas.'),
    ('In-game menu', 'Menu in gioco', 'Menu en jeu', 'Menü im Spiel', 'Menú en el juego'),
    ('Opens the settings while you play: Ins on the keyboard, or R3 + L2 on the controller.',
     'Apre le impostazioni durante la partita: Ins sulla tastiera, oppure R3 + L2 sul controller.',
     'Ouvre les réglages pendant la partie : Inser au clavier, ou R3 + L2 sur la manette.',
     'Öffnet die Einstellungen im Spiel: Einfg auf der Tastatur oder R3 + L2 am Controller.',
     'Abre los ajustes durante la partida: Insert en el teclado o R3 + L2 en el mando.'),
    ('PERFORMANCE', 'PRESTAZIONI', 'PERFORMANCES', 'LEISTUNG', 'RENDIMIENTO'),
    ('Shader cache', 'Cache degli shader', 'Cache des shaders', 'Shader-Cache', 'Caché de shaders'),
    ('Clear', 'Svuota', 'Vider', 'Leeren', 'Vaciar'),
    ('DEVELOPMENT', 'SVILUPPO', 'DÉVELOPPEMENT', 'ENTWICKLUNG', 'DESARROLLO'),
    ('Validation layer', 'Strato di validazione', 'Couche de validation', 'Validierungsebene', 'Capa de validación'),
    ('Vulkan checks for bug reports; slower.', 'Controlli di Vulkan per le segnalazioni di errori; più lento.',
     'Vérifications Vulkan pour signaler les bugs ; plus lent.', 'Vulkan-Prüfungen für Fehlerberichte; langsamer.',
     'Comprobaciones de Vulkan para informar de errores; más lento.'),
    ('DATA', 'DATI', 'DONNÉES', 'DATEN', 'DATOS'),
    ('Launcher data folder', 'Cartella dei dati del launcher', 'Dossier de données du lanceur', 'Datenordner des Launchers',
     'Carpeta de datos del lanzador'),
    ('Export settings', 'Esporta configurazione', 'Exporter les réglages', 'Einstellungen exportieren', 'Exportar ajustes'),
    ('Import settings', 'Importa configurazione', 'Importer les réglages', 'Einstellungen importieren', 'Importar ajustes'),
    ('Copy log', 'Copia log', 'Copier le journal', 'Protokoll kopieren', 'Copiar registro'),
    ('Open log folder', 'Apri cartella log', 'Ouvrir le dossier', 'Ordner öffnen', 'Abrir carpeta'),
    ('Game messages', 'Messaggi del gioco', 'Messages du jeu', 'Meldungen des Spiels', 'Mensajes del juego'),
    ('No game started yet.', 'Nessuna partita avviata finora.', 'Aucune partie lancée pour l\'instant.',
     'Noch kein Spiel gestartet.', 'Aún no se ha iniciado ninguna partida.'),
    ('Game found · all ready', 'Gioco rilevato · tutto pronto', 'Jeu détecté · tout est prêt', 'Spiel gefunden · alles bereit',
     'Juego detectado · todo listo'),
    ('Choose the game folder', 'Scegli la cartella del gioco', 'Choisissez le dossier du jeu', 'Spielordner wählen',
     'Elige la carpeta del juego'),
    ('Last save · {}', 'Ultimo salvataggio · {}', 'Dernière sauvegarde · {}', 'Letzter Spielstand · {}', 'Última partida · {}'),
    ('No saves yet', 'Nessun salvataggio', 'Aucune sauvegarde', 'Noch keine Spielstände', 'Sin partidas guardadas'),
    ('VSync', 'VSync', 'VSync', 'VSync', 'VSync'),
    ('Limit {} FPS', 'Limite {} FPS', 'Limite {} IPS', 'Limit {} FPS', 'Límite {} FPS'),
    ('Unlimited FPS', 'FPS libero', 'IPS illimitées', 'FPS unbegrenzt', 'FPS sin límite'),
    ('Settings applied', 'Impostazioni applicate', 'Réglages appliqués', 'Einstellungen übernommen', 'Ajustes aplicados'),
    ('Defaults restored', 'Valori predefiniti ripristinati', 'Valeurs par défaut rétablies', 'Standardwerte wiederhergestellt',
     'Valores predeterminados restablecidos'),
    ('Quit?', 'Uscire?', 'Quitter ?', 'Beenden?', '¿Salir?'),
    ('Close the launcher?', 'Vuoi chiudere il launcher?', 'Fermer le lanceur ?', 'Launcher schließen?',
     '¿Cerrar el lanzador?'),
    ('Cancel', 'Annulla', 'Annuler', 'Abbrechen', 'Cancelar'),
    ('The game keeps running.', 'Il gioco resta aperto.', 'Le jeu reste ouvert.', 'Das Spiel läuft weiter.',
     'El juego sigue abierto.'),
    ('Starting…', 'Avvio in corso…', 'Lancement…', 'Wird gestartet…', 'Iniciando…'),
    ('Preparing the game', 'Preparazione del gioco', 'Préparation du jeu', 'Spiel wird vorbereitet', 'Preparando el juego'),
    ('The game is starting', 'Il gioco si sta aprendo', 'Le jeu s\'ouvre', 'Das Spiel öffnet sich', 'El juego se está abriendo'),
    ('In game', 'In gioco', 'En jeu', 'Im Spiel', 'Jugando'),
    ('The game is running in its own window.', 'Il gioco è aperto nella sua finestra.',
     'Le jeu tourne dans sa propre fenêtre.', 'Das Spiel läuft in seinem eigenen Fenster.',
     'El juego está abierto en su propia ventana.'),
    ('Stop the game', 'Chiudi il gioco', 'Fermer le jeu', 'Spiel beenden', 'Cerrar el juego'),
    ('Close the launcher', 'Chiudi il launcher', 'Fermer le lanceur', 'Launcher schließen', 'Cerrar el lanzador'),
    ('The game exited.', 'Il gioco si è chiuso.', 'Le jeu s\'est fermé.', 'Das Spiel wurde beendet.', 'El juego se ha cerrado.'),
    ('Choose the game folder first.', 'Prima scegli la cartella del gioco.', 'Choisissez d\'abord le dossier du jeu.',
     'Wähle zuerst den Spielordner.', 'Primero elige la carpeta del juego.'),
    ('Restore saves?', 'Ripristinare?', 'Restaurer ?', 'Wiederherstellen?', '¿Restaurar?'),
    ('The current saves are backed up first.', 'Prima verranno salvati i dati attuali.',
     'Les données actuelles seront sauvegardées d\'abord.', 'Die aktuellen Spielstände werden zuerst gesichert.',
     'Antes se guardarán los datos actuales.'),
    ('Saves restored', 'Salvataggi ripristinati', 'Sauvegardes restaurées', 'Spielstände wiederhergestellt',
     'Partidas restauradas'),
    ('Close the game first.', 'Prima chiudi il gioco.', 'Fermez d\'abord le jeu.', 'Beende zuerst das Spiel.',
     'Primero cierra el juego.'),
    ('Shortcut created on the desktop', 'Collegamento creato sul desktop', 'Raccourci créé sur le bureau',
     'Verknüpfung auf dem Desktop erstellt', 'Acceso directo creado en el escritorio'),
    ('Shader cache cleared', 'Cache degli shader svuotata', 'Cache des shaders vidé', 'Shader-Cache geleert',
     'Caché de shaders vaciada'),
    ('Log copied', 'Log copiato', 'Journal copié', 'Protokoll kopiert', 'Registro copiado'),
    ('Settings exported', 'Configurazione esportata', 'Réglages exportés', 'Einstellungen exportiert', 'Ajustes exportados'),
    ('Settings imported', 'Configurazione importata', 'Réglages importés', 'Einstellungen importiert', 'Ajustes importados'),
    ('Could not: {}', 'Non riuscito: {}', 'Échec : {}', 'Fehlgeschlagen: {}', 'No se pudo: {}'),
    ('empty', 'vuota', 'vide', 'leer', 'vacía'),
    # PlayStation buttons (names as each country's manuals call them).
    ('Cross', 'Croce', 'Croix', 'Kreuz', 'Equis'),
    ('Circle', 'Cerchio', 'Rond', 'Kreis', 'Círculo'),
    ('Square', 'Quadrato', 'Carré', 'Quadrat', 'Cuadrado'),
    ('Triangle', 'Triangolo', 'Triangle', 'Dreieck', 'Triángulo'),
    ('Up', 'Su', 'Haut', 'Oben', 'Arriba'),
    ('Down', 'Giù', 'Bas', 'Unten', 'Abajo'),
    ('Left', 'Sinistra', 'Gauche', 'Links', 'Izquierda'),
    ('Right', 'Destra', 'Droite', 'Rechts', 'Derecha'),
    ('Trigger', 'Grilletto', 'Gâchette', 'Trigger', 'Gatillo'),
    ('D-pad up', 'Croce su', 'Croix haut', 'Steuerkreuz oben', 'Cruceta arriba'),
    ('D-pad down', 'Croce giù', 'Croix bas', 'Steuerkreuz unten', 'Cruceta abajo'),
    ('D-pad left', 'Croce sinistra', 'Croix gauche', 'Steuerkreuz links', 'Cruceta izquierda'),
    ('D-pad right', 'Croce destra', 'Croix droite', 'Steuerkreuz rechts', 'Cruceta derecha'),
    ('Touchpad click', 'Clic touchpad', 'Clic du pavé tactile', 'Touchpad-Klick', 'Clic del panel táctil'),
    # Anti-aliasing, upscaler, sharpening.
    ('Anti-aliasing', 'Anti-aliasing', 'Anticrénelage', 'Kantenglättung', 'Antialiasing'),
    ('FXAA (as on PS4)', 'FXAA (come su PS4)', 'FXAA (comme sur PS4)', 'FXAA (wie auf PS4)', 'FXAA (como en PS4)'),
    ("FXAA is the game's own. TAA and FSR 3.1 smooth edges over several frames: steadier edges and thin details. With a render resolution below your screen, FSR 3.1 also enlarges the image to the screen and keeps the detail.",
     'FXAA è quello del gioco. TAA e FSR 3.1 smussano i bordi su più fotogrammi: bordi e dettagli sottili più stabili. Con una risoluzione di rendering più bassa dello schermo, FSR 3.1 ingrandisce anche l’immagine fino allo schermo mantenendo i dettagli.',
     'FXAA est celui du jeu. TAA et FSR 3.1 lissent les contours sur plusieurs images : contours et détails fins plus stables. Avec une résolution de rendu inférieure à l’écran, FSR 3.1 agrandit aussi l’image jusqu’à l’écran en gardant les détails.',
     'FXAA ist die spieleigene Glättung. TAA und FSR 3.1 glätten Kanten über mehrere Bilder: ruhigere Kanten und feine Details. Ist die Render-Auflösung niedriger als der Bildschirm, vergrößert FSR 3.1 das Bild außerdem detailreich auf den Bildschirm.',
     'FXAA es el del propio juego. TAA y FSR 3.1 suavizan los bordes a lo largo de varios fotogramas: bordes y detalles finos más estables. Con una resolución de renderizado menor que la pantalla, FSR 3.1 también amplía la imagen hasta la pantalla conservando el detalle.'),
    ('Upscaler', 'Upscaler', 'Upscaler', 'Upscaler', 'Escalador'),
    ('FSR 1.0', 'FSR 1.0', 'FSR 1.0', 'FSR 1.0', 'FSR 1.0'),
    ('Off', 'Disattivato', 'Désactivé', 'Aus', 'Desactivado'),
    ('A simple enlargement to your screen when the render resolution is lower, with FXAA or TAA. FSR 3.1 does it with more detail.',
     'Un ingrandimento semplice fino allo schermo quando la risoluzione di rendering è più bassa, con FXAA o TAA. FSR 3.1 lo fa con più dettaglio.',
     'Un agrandissement simple jusqu’à l’écran quand la résolution de rendu est plus basse, avec FXAA ou TAA. FSR 3.1 le fait avec plus de détails.',
     'Eine einfache Vergrößerung auf den Bildschirm, wenn die Render-Auflösung niedriger ist, mit FXAA oder TAA. FSR 3.1 macht das detailreicher.',
     'Una ampliación sencilla hasta la pantalla cuando la resolución de renderizado es menor, con FXAA o TAA. FSR 3.1 lo hace con más detalle.'),
    ('Sharpening', 'Nitidezza', 'Netteté', 'Schärfe', 'Nitidez'),
    ('Sharpens the final image with FSR 1.0, when the game image is smaller than the screen. 0: off.',
     'Rende più nitida l’immagine finale con FSR 1.0, se l’immagine del gioco è più piccola dello schermo. 0: disattivata.',
     'Rend l’image finale plus nette avec FSR 1.0, si l’image du jeu est plus petite que l’écran. 0 : désactivée.',
     'Schärft das fertige Bild mit FSR 1.0, wenn das Spielbild kleiner als der Bildschirm ist. 0: aus.',
     'Hace más nítida la imagen final con FSR 1.0, si la imagen del juego es menor que la pantalla. 0: desactivada.'),
    ('Simple upscaler',
     'Upscaler semplice',
     'Upscaler simple',
     'Einfaches Upscaling',
     'Escalador simple'),
    ('The size the game draws at. Lower than your screen runs faster: FSR 3.1 or FSR 1.0 enlarge it to the screen.',
     'La dimensione a cui il gioco disegna. Più bassa dello schermo va più veloce: FSR 3.1 o FSR 1.0 la ingrandiscono fino allo schermo.',
     'La taille à laquelle le jeu dessine. Plus basse que l’écran, c’est plus rapide : FSR 3.1 ou FSR 1.0 l’agrandissent jusqu’à l’écran.',
     'Die Größe, in der das Spiel zeichnet. Niedriger als der Bildschirm läuft schneller: FSR 3.1 oder FSR 1.0 vergrößern sie auf den Bildschirm.',
     'El tamaño al que dibuja el juego. Menor que la pantalla va más rápido: FSR 3.1 o FSR 1.0 la amplían hasta la pantalla.'),
    # Updates.
    ('UPDATES', 'AGGIORNAMENTI', 'MISES À JOUR', 'UPDATES', 'ACTUALIZACIONES'),
    ('Check for updates at start', "Cerca aggiornamenti all'avvio", 'Rechercher les mises à jour au démarrage', 'Beim Start nach Updates suchen', 'Buscar actualizaciones al iniciar'),
    ('Looks for a new version on GitHub when the launcher opens and asks before installing it.', 'Cerca una nuova versione su GitHub quando apri il launcher e chiede prima di installarla.', "Recherche une nouvelle version sur GitHub à l'ouverture du lanceur et demande avant de l'installer.", 'Sucht beim Öffnen des Launchers auf GitHub nach einer neuen Version und fragt vor der Installation.', 'Busca una nueva versión en GitHub al abrir el lanzador y pregunta antes de instalarla.'),
    ('Installed version', 'Versione installata', 'Version installée', 'Installierte Version', 'Versión instalada'),
    ('Check now', 'Controlla ora', 'Vérifier', 'Jetzt prüfen', 'Comprobar ahora'),
    ('Development copy: it updates with git.', 'Copia di sviluppo: si aggiorna con git.', 'Copie de développement : elle se met à jour avec git.', 'Entwicklungskopie: Sie wird mit git aktualisiert.', 'Copia de desarrollo: se actualiza con git.'),
    ('Checking for updates…', 'Ricerca aggiornamenti…', 'Recherche des mises à jour…', 'Suche nach Updates…', 'Buscando actualizaciones…'),
    ('Could not check for updates.', 'Impossibile cercare aggiornamenti.', 'Impossible de rechercher les mises à jour.', 'Die Suche nach Updates ist fehlgeschlagen.', 'No se pudieron buscar actualizaciones.'),
    ('You have the latest version.', "Hai già l'ultima versione.", 'Vous avez la dernière version.', 'Du hast die neueste Version.', 'Tienes la última versión.'),
    ('Update available', 'Aggiornamento disponibile', 'Mise à jour disponible', 'Update verfügbar', 'Actualización disponible'),
    ('Version {} is available (you have {}). Install it now? Saves and settings are kept.', 'È disponibile la versione {} (hai la {}). Vuoi installarla ora? Salvataggi e impostazioni restano.', "La version {} est disponible (vous avez la {}). L'installer maintenant ? Sauvegardes et réglages sont conservés.", 'Version {} ist verfügbar (du hast {}). Jetzt installieren? Spielstände und Einstellungen bleiben erhalten.', 'La versión {} está disponible (tienes la {}). ¿Instalarla ahora? Las partidas y los ajustes se conservan.'),
    ('Not now', 'Non ora', 'Plus tard', 'Später', 'Ahora no'),
    ("What's new", 'Novità', 'Nouveautés', 'Neuigkeiten', 'Novedades'),
    ('Install', 'Installa', 'Installer', 'Installieren', 'Instalar'),
    ('Updating', 'Aggiornamento', 'Mise à jour', 'Aktualisierung', 'Actualizando'),
    ('Downloading version {}… {}%', 'Download della versione {}… {}%', 'Téléchargement de la version {}… {} %', 'Version {} wird heruntergeladen… {} %', 'Descargando la versión {}… {} %'),
    ('The launcher closes, installs the update and opens again.', "Il launcher si chiude, installa l'aggiornamento e si riapre.", 'Le lanceur se ferme, installe la mise à jour et se rouvre.', 'Der Launcher schließt sich, installiert das Update und öffnet sich wieder.', 'El lanzador se cierra, instala la actualización y se vuelve a abrir.'),
    ('Update failed', 'Aggiornamento non riuscito', 'Échec de la mise à jour', 'Update fehlgeschlagen', 'Error al actualizar'),
    ('The update could not be installed: {}', "Impossibile installare l'aggiornamento: {}", "Impossible d'installer la mise à jour : {}", 'Das Update konnte nicht installiert werden: {}', 'No se pudo instalar la actualización: {}'),
    ('This folder is read-only, so the launcher cannot update itself here. Download the new version from the releases page.', 'Questa cartella è in sola lettura: il launcher non può aggiornarsi qui. Scarica la nuova versione dalla pagina delle release.', 'Ce dossier est en lecture seule : le lanceur ne peut pas se mettre à jour ici. Téléchargez la nouvelle version depuis la page des versions.', 'Dieser Ordner ist schreibgeschützt, daher kann sich der Launcher hier nicht aktualisieren. Lade die neue Version von der Release-Seite herunter.', 'Esta carpeta es de solo lectura, así que el lanzador no puede actualizarse aquí. Descarga la nueva versión desde la página de versiones.'),
    ('Open the page', 'Apri la pagina', 'Ouvrir la page', 'Seite öffnen', 'Abrir la página'),
    ('Close', 'Chiudi', 'Fermer', 'Schließen', 'Cerrar'),
    # Advanced: GPU readbacks and threads.
    ('GPU AND THREADS', 'GPU E THREAD', 'GPU ET THREADS', 'GPU UND THREADS', 'GPU E HILOS'),
    ('Graphics card', 'Scheda video', 'Carte graphique', 'Grafikkarte', 'Tarjeta gráfica'),
    ('The card the game uses when the PC has more than one, such as a laptop with integrated and dedicated graphics. Auto picks the most capable one. Applied at start.',
     'La scheda usata dal gioco quando il PC ne ha più di una, come i portatili con grafica integrata e dedicata. Automatico sceglie la più potente. Applicata all’avvio.',
     'La carte utilisée par le jeu quand le PC en a plusieurs, comme les portables avec graphismes intégrés et dédiés. Auto choisit la plus puissante. Appliqué au démarrage.',
     'Die Karte, die das Spiel nutzt, wenn der PC mehrere hat, etwa Laptops mit integrierter und dedizierter Grafik. Auto wählt die leistungsstärkste. Wird beim Start übernommen.',
     'La tarjeta que usa el juego cuando el PC tiene más de una, como los portátiles con gráficos integrados y dedicados. Auto elige la más potente. Se aplica al iniciar.'),
    ('Auto', 'Automatico', 'Auto', 'Automatisch', 'Automático'),
    ('On', 'Attivo', 'Activé', 'An', 'Activado'),
    ('Relaxed', 'Rilassate', 'Souples', 'Locker', 'Relajadas'),
    ('Precise', 'Precise', 'Précises', 'Genau', 'Precisas'),
    ('GPU readbacks', 'Letture dalla GPU', 'Relectures GPU', 'GPU-Rücklesungen', 'Lecturas de la GPU'),
    ('How the game reads data the graphics card produced. Auto is recommended. Precise is the most faithful and the slowest; Off is the fastest but lighting or objects may look wrong.', 'Come il gioco legge i dati prodotti dalla scheda video. Automatico è consigliato. Precise è la più fedele e la più lenta; Disattivato è la più veloce, ma luci o oggetti possono apparire sbagliati.', 'Comment le jeu lit les données produites par la carte graphique. Auto est recommandé. Précises est le plus fidèle et le plus lent ; Désactivé est le plus rapide, mais l’éclairage ou des objets peuvent sembler faux.', 'Wie das Spiel Daten liest, die die Grafikkarte erzeugt hat. Automatisch wird empfohlen. Genau ist am originalgetreuesten und am langsamsten; Aus ist am schnellsten, aber Licht oder Objekte können falsch aussehen.', 'Cómo lee el juego los datos que produce la tarjeta gráfica. Se recomienda Automático. Precisas es lo más fiel y lo más lento; Desactivado es lo más rápido, pero la iluminación o los objetos pueden verse mal.'),
    ('Deferred readbacks', 'Letture differite', 'Relectures différées', 'Verzögerte Rücklesungen', 'Lecturas diferidas'),
    ('Fewer waits for the graphics card. Switch it off if textures or shadows look wrong. Applied at start.', 'Meno attese della scheda video. Disattivale se texture o ombre appaiono sbagliate. Applicato all’avvio.', 'Moins d’attentes de la carte graphique. Désactivez-les si des textures ou des ombres semblent fausses. Appliqué au démarrage.', 'Weniger Warten auf die Grafikkarte. Schalte sie aus, wenn Texturen oder Schatten falsch aussehen. Gilt beim Start.', 'Menos esperas a la tarjeta gráfica. Desactívalas si las texturas o las sombras se ven mal. Se aplica al iniciar.'),
    ('Read without waiting', 'Lettura senza attesa', 'Lecture sans attente', 'Lesen ohne Warten', 'Lectura sin espera'),
    ('More FPS: the game may read GPU data one frame old. Switch it off if lighting or objects look wrong. Applied at start.', 'Più FPS: il gioco può leggere dati della GPU vecchi di un fotogramma. Disattivala se luci o oggetti appaiono sbagliati. Applicato all’avvio.', 'Plus d’IPS : le jeu peut lire des données GPU vieilles d’une image. Désactivez-la si l’éclairage ou des objets semblent faux. Appliqué au démarrage.', 'Mehr FPS: Das Spiel kann GPU-Daten lesen, die ein Bild alt sind. Schalte es aus, wenn Licht oder Objekte falsch aussehen. Gilt beim Start.', 'Más FPS: el juego puede leer datos de la GPU de un fotograma antes. Desactívala si la iluminación o los objetos se ven mal. Se aplica al iniciar.'),
    ('Draw pipeline thread', 'Thread della pipeline di disegno', 'Thread du pipeline de dessin', 'Thread der Zeichen-Pipeline', 'Hilo de la canalización de dibujo'),
    ('Records the draws on a second thread: about 4% more FPS, but it can show one-frame glitches (stretched triangles). Auto leaves it off. Applied at start.', 'Registra i disegni su un secondo thread: circa il 4% di FPS in più, ma può causare glitch di un fotogramma (triangoli stirati). Automatico lo lascia spento. Applicato all’avvio.', 'Enregistre les dessins sur un second thread : environ 4 % d’IPS en plus, mais cela peut causer des glitchs d’une image (triangles étirés). Auto le laisse désactivé. Appliqué au démarrage.', 'Zeichnet die Zeichenbefehle in einem zweiten Thread auf: etwa 4 % mehr FPS, kann aber Ein-Bild-Fehler (gestreckte Dreiecke) verursachen. Automatisch lässt ihn aus. Gilt beim Start.', 'Graba los dibujos en un segundo hilo: alrededor de un 4 % más de FPS, pero puede causar fallos de un fotograma (triángulos estirados). Automático lo deja desactivado. Se aplica al iniciar.'),
    ('Draw preparation threads', 'Thread di preparazione', 'Threads de préparation', 'Vorbereitungs-Threads', 'Hilos de preparación'),
    ('Helper threads that pre-process the game’s draw lists. Auto uses half of your CPU threads, at most 8. Applied at start.', 'Thread di aiuto che preparano in anticipo le liste di disegno del gioco. Automatico usa metà dei thread della CPU, al massimo 8. Applicato all’avvio.', 'Threads d’aide qui pré-traitent les listes de dessin du jeu. Auto utilise la moitié des threads processeur, 8 au plus. Appliqué au démarrage.', 'Hilfs-Threads, die die Zeichenlisten des Spiels vorverarbeiten. Automatisch nutzt die Hälfte der CPU-Threads, höchstens 8. Gilt beim Start.', 'Hilos de ayuda que preprocesan las listas de dibujo del juego. Automático usa la mitad de los hilos de CPU, como máximo 8. Se aplica al iniciar.'),
    ('Copy threads', 'Thread di copia', 'Threads de copie', 'Kopier-Threads', 'Hilos de copia'),
    ('Threads for the memory copies the game waits for. Auto uses a quarter of your CPU threads, at most 4. Applied at start.', 'Thread per le copie di memoria che il gioco aspetta. Automatico usa un quarto dei thread della CPU, al massimo 4. Applicato all’avvio.', 'Threads pour les copies mémoire que le jeu attend. Auto utilise un quart des threads processeur, 4 au plus. Appliqué au démarrage.', 'Threads für Speicherkopien, auf die das Spiel wartet. Automatisch nutzt ein Viertel der CPU-Threads, höchstens 4. Gilt beim Start.', 'Hilos para las copias de memoria que espera el juego. Automático usa una cuarta parte de los hilos de CPU, como máximo 4. Se aplica al iniciar.'),
    ('Vulkan recording thread', 'Thread di registrazione Vulkan', 'Thread d’enregistrement Vulkan', 'Vulkan-Aufzeichnungs-Thread', 'Hilo de grabación de Vulkan'),
    ('Records the graphics commands on their own thread. Turn it off only to diagnose problems. Applied at start.', 'Registra i comandi grafici su un thread dedicato. Disattivalo solo per diagnosticare problemi. Applicato all’avvio.', 'Enregistre les commandes graphiques sur un thread dédié. Ne le désactivez que pour diagnostiquer des problèmes. Appliqué au démarrage.', 'Zeichnet die Grafikbefehle in einem eigenen Thread auf. Schalte ihn nur zur Fehlersuche aus. Gilt beim Start.', 'Graba los comandos gráficos en su propio hilo. Desactívalo solo para diagnosticar problemas. Se aplica al iniciar.'),
    ('Restore GPU and thread defaults', 'Ripristina GPU e thread', 'Rétablir GPU et threads', 'GPU und Threads zurücksetzen', 'Restablecer GPU e hilos'),
    # Upscaling modes.
    ('Mode', 'Modalità', 'Mode', 'Modus', 'Modo'),
    ('Native', 'Nativa', 'Native', 'Nativ', 'Nativa'),
    ('DLAA', 'DLAA', 'DLAA', 'DLAA', 'DLAA'),
    ('Quality', 'Qualità', 'Qualité', 'Qualität', 'Calidad'),
    ('Balanced', 'Bilanciato', 'Équilibré', 'Ausgewogen', 'Equilibrado'),
    ('Performance', 'Prestazioni', 'Performances', 'Leistung', 'Rendimiento'),
    ('Draws at your screen’s size ({}): anti-aliasing only, the sharpest image.', 'Disegna alla misura del tuo schermo ({}): solo anti-aliasing, l’immagine più nitida.', 'Dessine à la taille de votre écran ({}) : anticrénelage seul, l’image la plus nette.', 'Zeichnet in der Größe deines Bildschirms ({}): nur Kantenglättung, das schärfste Bild.', 'Dibuja al tamaño de tu pantalla ({}): solo antialiasing, la imagen más nítida.'),
    ('Draws at {} and enlarges to your {} screen. Quality is the sharpest, Performance the fastest.', 'Disegna a {} e ingrandisce fino al tuo schermo {}. Qualità è la più nitida, Prestazioni la più veloce.', 'Dessine en {} et agrandit jusqu’à votre écran {}. Qualité est le plus net, Performances le plus rapide.', 'Zeichnet in {} und vergrößert auf deinen {}-Bildschirm. Qualität ist am schärfsten, Leistung am schnellsten.', 'Dibuja a {} y amplía hasta tu pantalla de {}. Calidad es la más nítida, Rendimiento la más rápida.'),
    # Video page: per-mode anti-aliasing hints, sections, footer note.
    ("FXAA: the game's own edge smoothing, as on the PS4. The lightest.", 'FXAA: lo smussamento dei bordi del gioco, come su PS4. Il più leggero.', 'FXAA : le lissage des contours du jeu, comme sur PS4. Le plus léger.', 'FXAA: die spieleigene Kantenglättung, wie auf der PS4. Am leichtesten.', 'FXAA: el suavizado de bordes del propio juego, como en PS4. El más ligero.'),
    ('TAA: smooths edges over several frames, steadier than FXAA, a little softer.', 'TAA: smussa i bordi su più fotogrammi, più stabile di FXAA, un po’ più morbido.', 'TAA : lisse les contours sur plusieurs images, plus stable que FXAA, un peu plus doux.', 'TAA: glättet Kanten über mehrere Bilder, ruhiger als FXAA, etwas weicher.', 'TAA: suaviza los bordes a lo largo de varios fotogramas, más estable que FXAA, algo más suave.'),
    ('FSR 3.1: sharp, steady anti-aliasing. With a render resolution below your screen it also enlarges the image to the screen.', 'FSR 3.1: anti-aliasing nitido e stabile. Con una risoluzione di rendering più bassa dello schermo ingrandisce anche l’immagine fino allo schermo.', 'FSR 3.1 : anticrénelage net et stable. Avec une résolution de rendu inférieure à l’écran, il agrandit aussi l’image jusqu’à l’écran.', 'FSR 3.1: scharfe, ruhige Kantenglättung. Ist die Render-Auflösung niedriger als der Bildschirm, vergrößert es das Bild zusätzlich auf den Bildschirm.', 'FSR 3.1: antialiasing nítido y estable. Con una resolución de renderizado menor que la pantalla, también amplía la imagen hasta la pantalla.'),
    ('DLSS: NVIDIA’s anti-aliasing for RTX cards. Like FSR 3.1, it enlarges a lower render resolution to the screen.', 'DLSS: l’anti-aliasing di NVIDIA per le schede RTX. Come FSR 3.1, ingrandisce una risoluzione di rendering più bassa fino allo schermo.', 'DLSS : l’anticrénelage de NVIDIA pour les cartes RTX. Comme FSR 3.1, il agrandit une résolution de rendu plus basse jusqu’à l’écran.', 'DLSS: NVIDIAs Kantenglättung für RTX-Karten. Wie FSR 3.1 vergrößert es eine niedrigere Render-Auflösung auf den Bildschirm.', 'DLSS: el antialiasing de NVIDIA para tarjetas RTX. Como FSR 3.1, amplía una resolución de renderizado menor hasta la pantalla.'),
    ('Off: no smoothing. The sharpest image, with jagged edges.', 'Disattivato: nessuno smussamento. L’immagine più nitida, con bordi seghettati.', 'Désactivé : aucun lissage. L’image la plus nette, avec des bords crénelés.', 'Aus: keine Glättung. Das schärfste Bild, mit gezackten Kanten.', 'Desactivado: sin suavizado. La imagen más nítida, con bordes dentados.'),
    ('IMAGE QUALITY', 'QUALITÀ DELL’IMMAGINE', 'QUALITÉ D’IMAGE', 'BILDQUALITÄT', 'CALIDAD DE IMAGEN'),
    ('DETAILS', 'DETTAGLI', 'DÉTAILS', 'DETAILS', 'DETALLES'),
    ('Saved automatically', 'Salvato automaticamente', 'Enregistré automatiquement', 'Automatisch gespeichert', 'Guardado automáticamente'),
    ('The size the game draws at. Lower than your screen runs faster.', 'La dimensione a cui il gioco disegna. Più bassa dello schermo va più veloce.', 'La taille à laquelle le jeu dessine. Plus basse que l’écran, c’est plus rapide.', 'Die Größe, in der das Spiel zeichnet. Niedriger als der Bildschirm läuft schneller.', 'El tamaño al que dibuja el juego. Menor que la pantalla va más rápido.'),
    # Inkfall functions: detected game, backups, play time, exit diagnosis.
    ('DETECTED GAME', 'GIOCO RILEVATO', 'JEU DÉTECTÉ', 'ERKANNTES SPIEL', 'JUEGO DETECTADO'),
    ('Title', 'Titolo', 'Titre', 'Titel', 'Título'),
    ('Code', 'Codice', 'Code', 'Code', 'Código'),
    ('Version', 'Versione', 'Version', 'Version', 'Versión'),
    ('Status', 'Stato', 'État', 'Status', 'Estado'),
    ('Found, ready to play', 'Trovato, pronto per giocare', 'Trouvé, prêt à jouer', 'Gefunden, spielbereit', 'Encontrado, listo para jugar'),
    ('Not found: choose the folder that contains eboot.bin', 'Non trovato: scegli la cartella che contiene eboot.bin', 'Introuvable : choisissez le dossier qui contient eboot.bin', 'Nicht gefunden: wähle den Ordner, der eboot.bin enthält', 'No encontrado: elige la carpeta que contiene eboot.bin'),
    ('Back up before every start', 'Backup prima di ogni avvio', 'Sauvegarde avant chaque lancement', 'Sicherung vor jedem Start', 'Copia antes de cada inicio'),
    ('Copies your saves before the game starts, so you can always go back.', 'Copia i salvataggi prima che il gioco parta, così puoi sempre tornare indietro.', 'Copie vos sauvegardes avant le lancement du jeu : vous pouvez toujours revenir en arrière.', 'Kopiert deine Spielstände vor dem Spielstart, damit du immer zurück kannst.', 'Copia tus partidas antes de que empiece el juego, para poder volver atrás siempre.'),
    ('Backups to keep', 'Backup da tenere', 'Sauvegardes à garder', 'Zu behaltende Sicherungen', 'Copias a conservar'),
    ('The oldest ones are deleted.', 'I più vecchi vengono eliminati.', 'Les plus anciennes sont supprimées.', 'Die ältesten werden gelöscht.', 'Las más antiguas se borran.'),
    ('Back up now', 'Crea backup ora', 'Sauvegarder maintenant', 'Jetzt sichern', 'Copiar ahora'),
    ('Backup created', 'Backup creato', 'Sauvegarde créée', 'Sicherung erstellt', 'Copia creada'),
    ('No saves to back up yet', 'Ancora nessun salvataggio da copiare', 'Pas encore de sauvegarde à copier', 'Noch keine Spielstände zum Sichern', 'Aún no hay partidas que copiar'),
    ('Newest first. Restoring backs up the current saves first.', 'I più recenti in alto. Il ripristino copia prima i salvataggi attuali.', 'Les plus récentes en haut. La restauration copie d’abord les sauvegardes actuelles.', 'Die neuesten oben. Beim Wiederherstellen werden die aktuellen Spielstände zuerst gesichert.', 'Las más recientes arriba. Al restaurar, primero se copian las partidas actuales.'),
    ('The game closed right away', 'Il gioco si è chiuso subito', 'Le jeu s’est fermé tout de suite', 'Das Spiel wurde sofort beendet', 'El juego se cerró enseguida'),
    ('The game closed unexpectedly', 'Il gioco si è chiuso in modo inatteso', 'Le jeu s’est fermé de façon inattendue', 'Das Spiel wurde unerwartet beendet', 'El juego se cerró de forma inesperada'),
    ('Exit code {}. Its last messages:', 'Codice di uscita {}. Gli ultimi messaggi:', 'Code de sortie {}. Ses derniers messages :', 'Exit-Code {}. Die letzten Meldungen:', 'Código de salida {}. Sus últimos mensajes:'),
    ('Open the log', 'Apri il log', 'Ouvrir le journal', 'Protokoll öffnen', 'Abrir el registro'),
    ('Close the game before updating.', 'Chiudi il gioco prima di aggiornare.', 'Fermez le jeu avant la mise à jour.', 'Schließe das Spiel vor dem Update.', 'Cierra el juego antes de actualizar.'),
    ('Updated to version {}', 'Aggiornato alla versione {}', 'Mis à jour vers la version {}', 'Auf Version {} aktualisiert', 'Actualizado a la versión {}'),
]
TRANSLATIONS = {code: {row[0]: row[i] for row in _ROWS} for i, code in enumerate(('it', 'fr', 'de', 'es'), 1)}
LANG = 'en'


def refresh_rates():
    """Refresh rates (Hz) the main display offers at the desktop resolution, from Windows."""
    from ctypes import wintypes

    class DEVMODEW(ctypes.Structure):
        _fields_ = [('dmDeviceName', wintypes.WCHAR * 32), ('dmSpecVersion', wintypes.WORD),
                    ('dmDriverVersion', wintypes.WORD), ('dmSize', wintypes.WORD),
                    ('dmDriverExtra', wintypes.WORD), ('dmFields', wintypes.DWORD),
                    ('dmPositionX', wintypes.LONG), ('dmPositionY', wintypes.LONG),
                    ('dmDisplayOrientation', wintypes.DWORD), ('dmDisplayFixedOutput', wintypes.DWORD),
                    ('dmColor', ctypes.c_short), ('dmDuplex', ctypes.c_short), ('dmYResolution', ctypes.c_short),
                    ('dmTTOption', ctypes.c_short), ('dmCollate', ctypes.c_short),
                    ('dmFormName', wintypes.WCHAR * 32), ('dmLogPixels', wintypes.WORD),
                    ('dmBitsPerPel', wintypes.DWORD), ('dmPelsWidth', wintypes.DWORD),
                    ('dmPelsHeight', wintypes.DWORD), ('dmDisplayFlags', wintypes.DWORD),
                    ('dmDisplayFrequency', wintypes.DWORD)]
    try:
        enum = ctypes.windll.user32.EnumDisplaySettingsW
        current = DEVMODEW(dmSize=ctypes.sizeof(DEVMODEW))
        if not enum(None, -1, ctypes.byref(current)):  # ENUM_CURRENT_SETTINGS
            return []
        rates, mode, index = set(), DEVMODEW(dmSize=ctypes.sizeof(DEVMODEW)), 0
        while enum(None, index, ctypes.byref(mode)):
            if (mode.dmPelsWidth, mode.dmPelsHeight) == (current.dmPelsWidth, current.dmPelsHeight) and \
                    mode.dmDisplayFrequency > 1:
                rates.add(int(mode.dmDisplayFrequency))
            index += 1
        return sorted(rates)
    except (AttributeError, OSError):
        return []


def t(text):
    return TRANSLATIONS.get(LANG, {}).get(text, text)


def pick_language(choice, windows):
    """The launcher language: the chosen one, else Windows', else English."""
    codes = {code for code, _name in LANGUAGES}
    return choice if choice in codes else windows if windows in codes else 'en'


# PS4 button names, per row of the logic's CONTROLS (translated with t()).
BUTTON_NAMES = {'cross': 'Cross', 'circle': 'Circle', 'square': 'Square', 'triangle': 'Triangle', 'l1': 'L1', 'r1': 'R1',
                'l2': 'L2', 'r2': 'R2', 'l3': 'L3', 'r3': 'R3', 'options': 'Options', 'touchpad': 'Touchpad',
                'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right'}
# Tk key names -> the SDL key names the runtime's key map uses (src/runtime_pad.c).
TK_KEYS = {'space': 'Space', 'Shift_L': 'Left Shift', 'Shift_R': 'Right Shift', 'Control_L': 'Left Ctrl',
           'Control_R': 'Right Ctrl', 'Alt_L': 'Left Alt', 'Alt_R': 'Right Alt', 'Return': 'Return', 'Tab': 'Tab',
           'BackSpace': 'Backspace', 'Up': 'Up', 'Down': 'Down', 'Left': 'Left', 'Right': 'Right',
           'Caps_Lock': 'CapsLock', 'Insert': 'Insert', 'Delete': 'Delete', 'Home': 'Home', 'End': 'End',
           'Prior': 'PageUp', 'Next': 'PageDown'}
GAME_LANGUAGES = [('5', 'Italian'), ('1', 'English'), ('2', 'French'), ('4', 'German'), ('3', 'Spanish'),
                  ('0', 'Japanese')]
WINDOW_MODES = [('windowed', 'Windowed'), ('fullscreen', 'Fullscreen'), ('borderless', 'Borderless')]
FPS_CHOICES = [('30', '30'), ('60', '60'), ('120', '120'), ('0', 'Unlimited')]
# Render resolution patches (patches/CUSA01113.xml, scripts/gr_resolution_patch.py).
RESOLUTION_CHOICES = [('540p', '540p'), ('648p', '648p'), ('720p', '720p'), ('864p', '864p'), ('972p', '972p'),
                      ('native', 'Native (1080p)'), ('1296p', '1296p'), ('1440p', '1440p'), ('1800p', '1800p'),
                      ('4K', '4K')]
RESOLUTION_SIZES = {'540p': (960, 540), '648p': (1152, 648), '720p': (1280, 720), '864p': (1536, 864),
                    '972p': (1728, 972), 'native': (1920, 1080), '1296p': (2304, 1296), '1440p': (2560, 1440),
                    '1800p': (3200, 1800), '4K': (3840, 2160)}
# FSR 3.1 / DLSS modes: the render resolution for a 1080p, 1440p or 2160p screen (patches/CUSA01113.xml
# has these sizes): native 1x, quality ~1.5x, balanced ~1.7x, performance 2x.
UPSCALE_MODES = ('native', 'quality', 'balanced', 'performance')
MODE_RESOLUTIONS = {1080: ('native', '720p', '648p', '540p'),
                    1440: ('1440p', '972p', '864p', '720p'),
                    2160: ('4K', '1440p', '1296p', 'native')}


def screen_size():
    """The main display's resolution (Windows), or 1920x1080."""
    try:
        user32 = ctypes.windll.user32
        dc = user32.GetDC(0)
        width, height = ctypes.windll.gdi32.GetDeviceCaps(dc, 118), ctypes.windll.gdi32.GetDeviceCaps(dc, 117)
        user32.ReleaseDC(0, dc)  # DESKTOPHORZRES / DESKTOPVERTRES: physical pixels, whatever the scaling
        return (width, height) if width and height else (1920, 1080)
    except (AttributeError, OSError):
        return (1920, 1080)


def mode_table():
    height = screen_size()[1]
    return MODE_RESOLUTIONS[min(MODE_RESOLUTIONS, key=lambda h: abs(h - height))]
# Anti-aliasing: the game's FXAA, a temporal pass on the scene (gravityrush.ini upscaler; it replaces
# the FXAA while it runs), or none. DLAA only when the DLSS libraries are installed.
AA_CHOICES = [('fxaa', 'FXAA (as on PS4)'), ('taa', 'TAA'), ('fsr3', 'FSR 3.1'), ('off', 'Off')]
TEMPORAL_AA = ('taa', 'fsr3', 'dlss')
AA_HINTS = {'fxaa': "FXAA: the game's own edge smoothing, as on the PS4. The lightest.", 'taa': 'TAA: smooths edges over several frames, steadier than FXAA, a little softer.', 'fsr3': 'FSR 3.1: sharp, steady anti-aliasing. With a render resolution below your screen it also enlarges the image to the screen.', 'dlss': 'DLSS: NVIDIA’s anti-aliasing for RTX cards. Like FSR 3.1, it enlarges a lower render resolution to the screen.', 'off': 'Off: no smoothing. The sharpest image, with jagged edges.'}


def dlss_installed():
    folders = [Path(sys.executable).parent / 'bin', Path(sys.executable).parent / 'out',
               Path(__file__).resolve().parent.parent / 'out']
    return any((f / 'gow3_dlss.dll').is_file() and (f / 'nvngx_dlss.dll').is_file() for f in folders)


def aa_mode(ini):
    upscaler = ini.get('upscaler', 'off')
    if upscaler in TEMPORAL_AA:
        return upscaler
    return 'off' if ini.get('fxaa', '1') == '0' else 'fxaa'
UPSCALER_CHOICES = [('0', 'Off'), ('1', 'FSR 1.0')]
SHADOW_CHOICES = [('standard', 'Standard (2048)'), ('high', 'High (4096)')]
ANISOTROPY_CHOICES = [('0', "Game's own"), ('2', '2x'), ('4', '4x'), ('8', '8x'), ('16', '16x')]


# ---------------------------------------------------------------------------------------------
# Drawing (Pillow). Shapes are drawn at twice the size and scaled down for smooth edges.

def rgba(color, alpha=255):
    if isinstance(color, tuple):
        return color
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)) + (alpha,)


_fonts = {}
FONT_FILES = {400: 'segoeui.ttf', 600: 'seguisb.ttf', 700: 'segoeuib.ttf'}
WINDOWS_FONTS = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Fonts'


def pil_font(size, weight=600):
    """Segoe UI at 400, 600 or 700 (Cabin, shipped with the launcher, where it is missing)."""
    weight = 400 if weight < 500 else 600 if weight < 650 else 700
    key = (round(size), weight)
    if key not in _fonts:
        try:
            font = ImageFont.truetype(str(WINDOWS_FONTS / FONT_FILES[weight]), max(1, round(size)))
        except OSError:
            try:
                font = ImageFont.truetype(str(FONT_FILE), max(1, round(size)))
                font.set_variation_by_axes([weight, 100])
            except (OSError, ValueError):
                font = ImageFont.load_default(size)
        _fonts[key] = font
    return _fonts[key]


def text_width(text, font, spacing=0.0):
    if not spacing:
        return font.getlength(text)
    return sum(font.getlength(c) for c in text) + spacing * max(0, len(text) - 1)


def draw_text(draw, x, y, text, font, fill, spacing=0.0, stroke=0, stroke_fill=None):
    """Text with letter spacing (Pillow has none), from the top-left of its ink box."""
    if not spacing:
        draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        return
    for c in text:
        draw.text((x, y), c, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
        x += font.getlength(c) + spacing


def text_top(font, height):
    """The y that centres capital letters in `height`."""
    box = font.getbbox('H')
    return (height - (box[3] - box[1])) / 2 - box[1]


def text_in(draw, x, y0, height, text, font, fill, spacing=0.0):
    """Text whose capitals sit centred in the band y0 .. y0 + height."""
    draw_text(draw, x, y0 + text_top(font, height), text, font, fill, spacing)


def fit(text, font, limit):
    """The text, cut with an ellipsis to fit `limit`."""
    while text and text_width(text, font) > limit:
        text = text[:-2] + '…'
    return text


def paint_icon(img, kind, x0, y0, size, color, stroke=2.0):
    """Line icons on a 24-unit grid (after Lucide), drawn into img at (x0, y0), size wide."""
    u = size / 24
    d = ImageDraw.Draw(img)
    c = rgba(color)
    w = max(1, round(stroke * u))

    def p(x, y):
        return (x0 + x * u, y0 + y * u)

    def line(*points, closed=False):
        pts = [p(x, y) for x, y in points] + ([p(*points[0])] if closed else [])
        d.line(pts, fill=c, width=w, joint='curve')
        if not closed:
            for x, y in (pts[0], pts[-1]):  # round caps
                d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=c)

    def box(x1, y1, x2, y2, r):
        d.rounded_rectangle((*p(x1, y1), *p(x2, y2)), r * u, outline=c, width=w)

    def dot(cx, cy, r):
        d.ellipse((*p(cx - r, cy - r), *p(cx + r, cy + r)), fill=c)

    if kind == 'folder':
        box(2, 6.5, 22, 20, 2)
        line((2, 9), (2, 5.5), (3.5, 4), (9, 4), (11, 6.5))
    elif kind == 'monitor':
        box(2, 3, 22, 16.5, 2)
        line((8, 21), (16, 21))
        line((12, 16.5), (12, 21))
    elif kind == 'gamepad':
        box(2, 6, 22, 18, 6)
        line((6, 12), (10, 12))
        line((8, 10), (8, 14))
        dot(15, 13.2, 1.3)
        dot(18, 10.8, 1.3)
    elif kind == 'sliders':
        line((21, 5), (14, 5))
        line((10, 5), (3, 5))
        line((21, 12), (12, 12))
        line((8, 12), (3, 12))
        line((21, 19), (16, 19))
        line((12, 19), (3, 19))
        line((14, 3), (14, 7))
        line((8, 10), (8, 14))
        line((16, 17), (16, 21))
    elif kind == 'terminal':
        box(2, 3.5, 22, 20.5, 2.5)
        line((6.5, 9), (10, 12), (6.5, 15))
        line((12.5, 15), (17.5, 15))
    elif kind == 'play':
        pts = [p(7, 4.5), p(19.5, 12), p(7, 19.5)]
        d.polygon(pts, fill=c)
        d.line(pts + [pts[0]], fill=c, width=w, joint='curve')
    elif kind == 'check':
        d.ellipse((*p(2, 2), *p(22, 22)), outline=c, width=w)
        line((7.5, 12.5), (10.5, 15.5), (16.5, 9))
    elif kind == 'alert':
        line((12, 3), (22, 20), (2, 20), closed=True)
        line((12, 9.5), (12, 13.5))
        dot(12, 16.8, 1.2)
    elif kind == 'clock':
        d.ellipse((*p(2, 2), *p(22, 22)), outline=c, width=w)
        line((12, 7), (12, 12), (15.5, 14))
    elif kind == 'x':
        line((6, 6), (18, 18))
        line((18, 6), (6, 18))
    elif kind == 'chevron':
        line((6, 9), (12, 15), (18, 9))


class Painter:
    """Every picture of the window, at the window's scale: drawn at twice the size, then reduced."""

    def __init__(self, scale):
        self.s = scale

    def px(self, v):
        return max(1, round(v * self.s))

    def canvas(self, w, h):
        return Image.new('RGBA', (self.px(w) * 2, self.px(h) * 2), (0, 0, 0, 0))

    def done(self, image):
        return image.resize((image.width // 2, image.height // 2), Image.LANCZOS)

    def soft_shadow(self, img, box, radius, blur, alpha, offset=(0, 8)):
        """A blurred shadow under `box` (canvas units), `blur` and `offset` in design units."""
        k = self.s * 2
        shade = Image.new('RGBA', img.size, (0, 0, 0, 0))
        x0, y0, x1, y1 = box
        dx, dy = offset[0] * k, offset[1] * k
        ImageDraw.Draw(shade).rounded_rectangle((x0 + dx, y0 + dy, x1 + dx, y1 + dy), radius, fill=(0, 0, 0, alpha))
        img.alpha_composite(shade.filter(ImageFilter.GaussianBlur(blur * k)))

    def sidebar(self, height):
        """Dark glass over the picture, a hairline on its right edge."""
        k = self.s * 2
        img = self.canvas(SIDEBAR_W, height)
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, img.width, img.height), fill=GLASS)
        d.rectangle((img.width - max(1, round(k)), 0, img.width, img.height), fill=(255, 255, 255, 22))
        return self.done(img)

    def scrim(self, width, height):
        """A shade at the top of the picture, so the window buttons read on a bright sky."""
        img = Image.new('RGBA', (self.px(width), self.px(height)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for y in range(img.height):
            d.line([(0, y), (img.width, y)], fill=(8, 11, 15, int(120 * (1 - y / img.height) ** 1.7)))
        return img

    def brand(self, icon):
        """The port's icon (a rounded tile), the wordmark and REMASTERED."""
        k = self.s * 2
        img = self.canvas(236, 48)
        d = ImageDraw.Draw(img)
        if icon is not None:
            size = round(46 * k)
            img.alpha_composite(icon.resize((size, size), Image.LANCZOS), (0, round(1 * k)))
        text_in(d, 58 * k, 4 * k, 24 * k, 'GRAVITY RUSH', pil_font(19 * k, 700), rgba(TEXT), .05 * 19 * k)
        text_in(d, 59 * k, 29 * k, 14 * k, 'REMASTERED', pil_font(10.5 * k, 600), rgba(ACCENT), .3 * 10.5 * k)
        return self.done(img)

    def nav_item(self, label, icon, look):
        """A menu entry: icon and label; a tint on hover; the open page gold, with a bar."""
        k = self.s * 2
        w, h = NAV_W, NAV_H
        img = self.canvas(w, h)
        d = ImageDraw.Draw(img)
        if look == 'hover':
            d.rounded_rectangle((0, 0, w * k, h * k), 8 * k, fill=(255, 255, 255, 18))
        elif look == 'on':
            d.rounded_rectangle((0, 0, w * k, h * k), 8 * k, fill=rgba(ACCENT, 36))
            d.rounded_rectangle((0, 12 * k, 3 * k, (h - 12) * k), 1.5 * k, fill=rgba(ACCENT))
        dim = '#c2cad4'
        paint_icon(img, icon, 16 * k, (h - 20) / 2 * k, 20 * k, ACCENT if look == 'on' else TEXT if look == 'hover' else dim)
        font = pil_font(14 * k, 600)
        text_in(d, 50 * k, 0, h * k, fit(label, font, (w - 62) * k), font, rgba(dim if look == 'normal' else TEXT))
        return self.done(img)

    def play_button(self, label, look):
        """The big gold play button (with its soft shadow below)."""
        k = self.s * 2
        w, h = PLAY_W, PLAY_H
        img = self.canvas(w + 16, h + 20)
        box = (8 * k, 4 * k, (8 + w) * k, (4 + h) * k)
        self.soft_shadow(img, box, 10 * k, 7, 30 if look == 'press' else 90, offset=(0, 4))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, 10 * k, fill=rgba({'normal': ACCENT, 'hover': ACCENT_HI, 'press': ACCENT_LO}[look]))
        font = pil_font(16 * k, 700)
        spacing = .14 * 16 * k
        icon, gap = 15 * k, 11 * k
        x = box[0] + (w * k - (icon + gap + text_width(label, font, spacing))) / 2
        paint_icon(img, 'play', x, box[1] + (h * k - icon) / 2, icon, ON_ACCENT)
        text_in(d, x + icon + gap, box[1], h * k, label, font, rgba(ON_ACCENT), spacing)
        return self.done(img)

    def status_line(self, text, icon, color, width):
        """A status line of the sidebar: a small icon and the text."""
        k = self.s * 2
        h = 24
        img = self.canvas(width, h)
        d = ImageDraw.Draw(img)
        paint_icon(img, icon, 0, (h - 16) / 2 * k, 16 * k, color)
        font = pil_font(12.5 * k, 400)
        text_in(d, 26 * k, 0, h * k, fit(text, font, (width - 26) * k), font, rgba(TEXT2))
        return self.done(img)

    def panel(self, w, h, title=None):
        """A card (pages, dialogs): opaque, 14 px corners, a hairline edge and a soft shadow; with
        a title, the title and a rule under it. The picture starts 28 px before the card."""
        k = self.s * 2
        pad = 28
        img = self.canvas(w + 2 * pad, h + 2 * pad)
        box = (pad * k, pad * k, (pad + w) * k, (pad + h) * k)
        self.soft_shadow(img, box, 14 * k, 18, 150)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, 14 * k, fill=rgba(CARD), outline=(255, 255, 255, 24), width=max(1, round(k)))
        if title:
            text_in(d, (pad + 28) * k, (pad + 14) * k, 36 * k, title, pil_font(21 * k, 600), rgba(TEXT))
            y = (pad + 62) * k
            d.rectangle(((pad + 1) * k, y, (pad + w - 1) * k, y + max(1, round(k))), fill=rgba(LINE))
        return self.done(img)

    def icon_button(self, icon, hover):
        """A round 32 px button with an icon (the card's close button)."""
        k = self.s * 2
        img = self.canvas(32, 32)
        if hover:
            ImageDraw.Draw(img).ellipse((0, 0, 32 * k, 32 * k), fill=rgba(FIELD_HI))
        paint_icon(img, icon, 8 * k, 8 * k, 16 * k, TEXT if hover else TEXT2)
        return self.done(img)

    def toggle(self, on):
        k = self.s * 2
        img = self.canvas(40, 22)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, 40 * k, 22 * k), 11 * k, fill=rgba(ACCENT if on else '#3a4451'))
        cx = 29 * k if on else 11 * k
        d.ellipse((cx - 8 * k, 3 * k, cx + 8 * k, 19 * k), fill=rgba('#ffffff' if on else '#d3d9e0'))
        return self.done(img)

    def pill(self, text, on, size=13, height=32, padding=12):
        """An option of a choice row: gold when chosen, else a field."""
        k = self.s * 2
        font = pil_font(size * k, 600)
        w = text_width(text, font) / k + padding * 2
        img = self.canvas(w, height)
        d = ImageDraw.Draw(img)
        if on:
            d.rounded_rectangle((0, 0, w * k, height * k), 8 * k, fill=rgba(ACCENT))
        else:
            d.rounded_rectangle((0, 0, w * k, height * k), 8 * k, fill=rgba(FIELD), outline=rgba(LINE2), width=max(1, round(k)))
        text_in(d, padding * k, 0, height * k, text, font, rgba(ON_ACCENT if on else TEXT2))
        return self.done(img)

    def button(self, text, kind, look):
        """pri (gold), gh (outlined), sm (a small field button) and chip (a key cap)."""
        k = self.s * 2
        size = {'pri': 13.5, 'gh': 13.5, 'sm': 13, 'chip': 12}[kind]
        height = {'pri': 38, 'gh': 38, 'sm': 34, 'chip': 28}[kind]
        font = pil_font(size * k, 600)
        pad = {'pri': 18, 'gh': 18, 'sm': 14, 'chip': 10}[kind]
        w = max(text_width(text, font) / k + pad * 2, {'pri': 96, 'gh': 96, 'sm': 0, 'chip': 46}[kind])
        img = self.canvas(w, height + 1)
        d = ImageDraw.Draw(img)
        r = (6 if kind == 'chip' else 8) * k
        y = k if look == 'press' else 0
        edge = max(1, round(k))
        if kind == 'pri':
            d.rounded_rectangle((0, y, w * k, y + height * k), r,
                                fill=rgba({'normal': ACCENT, 'hover': ACCENT_HI, 'press': ACCENT_LO}[look]))
            color = ON_ACCENT
        elif kind == 'gh':
            d.rounded_rectangle((0, y, w * k, y + height * k), r, fill=rgba({'normal': CARD, 'hover': FIELD, 'press': FIELD_HI}[look]),
                                outline=rgba(LINE2 if look == 'normal' else LINE3), width=edge)
            color = TEXT
        elif kind == 'sm':
            d.rounded_rectangle((0, y, w * k, y + height * k), r, fill=rgba({'normal': FIELD, 'hover': FIELD_HI, 'press': '#2a3440'}[look]),
                                outline=rgba(LINE2 if look == 'normal' else LINE3), width=edge)
            color = TEXT
        else:  # a key cap: a darker lower edge
            d.rounded_rectangle((0, y + 2 * k, w * k, y + height * k), r, fill=rgba('#0d1116'))
            d.rounded_rectangle((0, y, w * k, y + (height - 2) * k), r, fill=rgba(FIELD_HI if look != 'normal' else FIELD),
                                outline=rgba(LINE2 if look == 'normal' else LINE3), width=edge)
            color = TEXT
        band = (height - (2 if kind == 'chip' else 0)) * k
        text_in(d, (w * k - text_width(text, font)) / 2, y, band, text, font, rgba(color))
        return self.done(img)

    def field(self, text, width, hover=False):
        """A select's face: a field with the text and a chevron."""
        k = self.s * 2
        h = 34
        img = self.canvas(width, h)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, width * k, h * k), 8 * k, fill=rgba(FIELD_HI if hover else FIELD),
                            outline=rgba(LINE3 if hover else LINE2), width=max(1, round(k)))
        font = pil_font(13.5 * k, 400)
        text_in(d, 12 * k, 0, h * k, fit(text, font, (width - 42) * k), font, rgba(TEXT))
        paint_icon(img, 'chevron', (width - 28) * k, (h - 16) / 2 * k, 16 * k, TEXT2)
        return self.done(img)

    def entry_frame(self, width, height=34):
        k = self.s * 2
        img = self.canvas(width, height)
        ImageDraw.Draw(img).rounded_rectangle((0, 0, width * k, height * k), 8 * k, fill=rgba(FIELD), outline=rgba(LINE2),
                                              width=max(1, round(k)))
        return self.done(img)

    def section(self, text):
        """A section title: small spaced capitals."""
        k = self.s * 2
        font = pil_font(11.5 * k, 600)
        spacing = .14 * 11.5 * k
        h = 18
        img = self.canvas(text_width(text, font, spacing) / k + 4, h)
        text_in(ImageDraw.Draw(img), 0, 0, h * k, text, font, rgba(TEXT3), spacing)
        return self.done(img)

    def gauge(self, w, fraction, phase):
        """A thin progress bar: gold, with a lighter band running along the filled part."""
        k = self.s * 2
        h = 8
        img = self.canvas(w, h)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, w * k, h * k), h / 2 * k, fill=rgba(FIELD_HI))
        fill_w = max(h, max(0.0, min(1.0, fraction)) * w) * k
        mask = Image.new('L', img.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, fill_w, h * k), h / 2 * k, fill=255)
        layer = Image.new('RGBA', img.size, rgba(ACCENT))
        x = (phase * 1.4 - .2) * fill_w
        ImageDraw.Draw(layer).rectangle((x, 0, x + 48 * k, h * k), fill=rgba(ACCENT_HI))
        img.paste(layer, (0, 0), mask)
        return self.done(img)

    def window_buttons(self, hover):
        """Minimize and close, Windows-style: 46 x 32 cells, the close cell red on hover."""
        k = self.s * 2
        img = self.canvas(92, 32)
        d = ImageDraw.Draw(img)
        if hover == 0:
            d.rectangle((0, 0, 46 * k, 32 * k), fill=(255, 255, 255, 36))
        elif hover == 1:
            d.rectangle((46 * k, 0, 92 * k, 32 * k), fill=rgba('#e81123'))
        width = max(1, round(1.2 * k))
        cx, cy = 23 * k, 16 * k
        d.line([(cx - 5 * k, cy), (cx + 5 * k, cy)], fill=rgba(TEXT), width=width)
        cx = 69 * k
        d.line([(cx - 5 * k, cy - 5 * k), (cx + 5 * k, cy + 5 * k)], fill=rgba(TEXT), width=width)
        d.line([(cx - 5 * k, cy + 5 * k), (cx + 5 * k, cy - 5 * k)], fill=rgba(TEXT), width=width)
        return self.done(img)

    def toast(self, text):
        """A notice: a dark pill with a gold dot (the picture has room for its shadow)."""
        k = self.s * 2
        font = pil_font(13 * k, 600)
        h = 32
        w = text_width(text, font) / k + 48
        img = self.canvas(w + 24, h + 20)
        box = (12 * k, 6 * k, (12 + w) * k, (6 + h) * k)
        self.soft_shadow(img, box, h / 2 * k, 6, 120, offset=(0, 3))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle(box, h / 2 * k, fill=rgba('#1d242d'), outline=rgba(LINE2), width=max(1, round(k)))
        cy = (6 + h / 2) * k
        d.ellipse(((12 + 16) * k, cy - 4 * k, (12 + 24) * k, cy + 4 * k), fill=rgba(ACCENT))
        text_in(d, (12 + 34) * k, 6 * k, h * k, text, font, rgba(TEXT))
        return self.done(img)

    def background(self, width, height):
        """The background covering width x height: a player's own picture, else the launcher's,
        else a dusk gradient."""
        w, h = self.px(width), self.px(height)
        try:
            source_path = BACKGROUND if BACKGROUND.is_file() else DEFAULT_BACKGROUND
            with Image.open(source_path) as source:
                pic = source.convert('RGB')
            scale = max(w / pic.width, h / pic.height)
            return pic.resize((math.ceil(pic.width * scale), math.ceil(pic.height * scale)), Image.LANCZOS)
        except OSError:
            img = Image.new('RGB', (w, h), '#2a3a44')
            d = ImageDraw.Draw(img)
            for y in range(h):
                f = y / h
                d.line([(0, y), (w, y)], fill=(int(42 + 30 * f), int(58 - 20 * f), int(68 - 30 * f)))
            return img

    def overlay(self):
        return Image.new('RGBA', (self.px(W), self.px(H)), (4, 7, 10, 150))


# ---------------------------------------------------------------------------------------------
# Animation: tweens advanced by one timer.

def ease_out_back(x, s=1.2):
    x -= 1
    return x * x * ((s + 1) * x + s) + 1


def ease_in(x):
    return x * x * x


def ease_out(x):
    return 1 - (1 - x) ** 3


class Animator:
    def __init__(self, root, enabled):
        self.root, self.enabled, self.items = root, enabled, []
        self.running = False

    def add(self, duration_ms, update, ease=ease_out, delay_ms=0, done=None):
        if not self.enabled:
            update(1.0)
            if done:
                done()
            return
        self.items.append([time.perf_counter() + delay_ms / 1000, duration_ms / 1000, update, ease, done])
        if not self.running:
            self.running = True
            self.root.after(10, self.tick)

    def tick(self):
        now = time.perf_counter()
        for item in self.items[:]:
            start, length, update, ease, done = item
            if now < start:
                continue
            x = min(1.0, (now - start) / length) if length else 1.0
            update(ease(x))
            if x >= 1.0:
                self.items.remove(item)
                if done:
                    done()
        if self.items:
            self.root.after(10, self.tick)
        else:
            self.running = False


def reduced_motion():
    """Windows "show animations" switched off (Settings > Accessibility > Visual effects)."""
    try:
        value = ctypes.c_bool(True)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0)  # SPI_GETCLIENTAREAANIMATION
        return not value.value
    except (AttributeError, OSError):
        return False


# ---------------------------------------------------------------------------------------------
# Widgets on the paper.

class ImageButton:
    """A Label showing normal / hover / press pictures."""

    def __init__(self, app, parent, text, command, kind='sm', bg=PAPER):
        self.app, self.command, self.kind, self.text = app, command, kind, text
        tk = app.tk
        self.widget = tk.Label(parent, bd=0, bg=bg, cursor='hand2', highlightthickness=0)
        self.render()
        self.widget.bind('<Enter>', lambda e: self.show('hover'))
        self.widget.bind('<Leave>', lambda e: self.show('normal'))
        self.widget.bind('<ButtonPress-1>', lambda e: self.show('press'))
        self.widget.bind('<ButtonRelease-1>', self.release)

    def render(self):
        self.images = {look: ImageTk.PhotoImage(self.app.paint.button(self.text, self.kind, look))
                       for look in ('normal', 'hover', 'press')}
        self.show('normal')

    def set_text(self, text):
        self.text = text
        self.render()

    def show(self, look):
        self.widget.configure(image=self.images[look])

    def release(self, event):
        inside = 0 <= event.x < self.widget.winfo_width() and 0 <= event.y < self.widget.winfo_height()
        self.show('hover' if inside else 'normal')
        if inside and self.command:
            self.command()


class Toggle:
    def __init__(self, app, parent, value, on_change):
        self.app, self.value, self.on_change = app, bool(value), on_change
        self.images = [ImageTk.PhotoImage(app.paint.toggle(False)), ImageTk.PhotoImage(app.paint.toggle(True))]
        self.widget = app.tk.Label(parent, bd=0, bg=CARD, cursor='hand2', image=self.images[self.value])
        self.widget.bind('<Button-1>', self.flip)

    def flip(self, _event=None):
        self.value = not self.value
        self.widget.configure(image=self.images[self.value])
        self.on_change(self.value)


class Segments:
    """A row of options, one chosen."""

    def __init__(self, app, parent, options, value, on_change):
        self.app, self.options, self.value, self.on_change = app, options, value, on_change
        self.widget = app.tk.Frame(parent, bg=CARD)
        self.labels = []
        for key, text in options:
            images = (ImageTk.PhotoImage(app.paint.pill(t(text), False)), ImageTk.PhotoImage(app.paint.pill(t(text), True)))
            label = app.tk.Label(self.widget, bd=0, bg=CARD, cursor='hand2')
            label.images = images
            label.bind('<Button-1>', lambda e, k=key: self.choose(k))
            label.pack(side='left', padx=(0, app.px(6)))
            self.labels.append((key, label))
        self.refresh()

    def refresh(self):
        for key, label in self.labels:
            label.configure(image=label.images[key == self.value])

    def choose(self, key):
        self.value = key
        self.refresh()
        self.on_change(key)


class Select:
    """A select: our own field (Tk's OptionMenu draws Windows' indicator), the options in a menu."""

    def __init__(self, app, parent, options, names, value, on_change, width):
        self.app, self.options, self.names, self.on_change, self.width = app, options, names, on_change, width
        self.index = next((i for i, (key, _t) in enumerate(options) if key == value), 0)
        self.widget = app.tk.Label(parent, bd=0, bg=CARD, cursor='hand2')
        self.menu = app.tk.Menu(self.widget, tearoff=False, font=app.font(13.5), bg=FIELD, fg=TEXT,
                                activebackground=ACCENT, activeforeground=ON_ACCENT, bd=0, relief='flat')
        for i, name in enumerate(names):
            self.menu.add_command(label=name, command=lambda i=i: self.choose(i))
        self.widget.bind('<Enter>', lambda e: self.render(True))
        self.widget.bind('<Leave>', lambda e: self.render(False))
        self.widget.bind('<Button-1>', self.open)
        self.render(False)

    def render(self, hover):
        self.photo = ImageTk.PhotoImage(self.app.paint.field(self.names[self.index], self.width, hover))
        self.widget.configure(image=self.photo)

    def open(self, _event=None):
        w = self.widget
        self.menu.tk_popup(w.winfo_rootx(), w.winfo_rooty() + w.winfo_height() + self.app.px(2))

    def choose(self, index):
        self.index = index
        self.render(False)
        self.on_change(self.options[index][0])


class RoundEntry:
    """A text field with rounded corners: an Entry inside a drawn frame that follows its width."""

    def __init__(self, app, parent, var):
        self.app = app
        self.widget = app.tk.Canvas(parent, width=app.px(60), height=app.px(34), bg=CARD, highlightthickness=0, bd=0)
        self.entry = app.tk.Entry(self.widget, textvariable=var, font=app.font(13.5), bg=FIELD, fg=TEXT,
                                  relief='flat', bd=0, highlightthickness=0, insertbackground=TEXT,
                                  selectbackground=ACCENT, selectforeground=ON_ACCENT)
        self.window = self.widget.create_window(app.px(12), app.px(17), anchor='w', window=self.entry)
        self.frame = self.widget.create_image(0, 0, anchor='nw')
        self.widget.tag_lower(self.frame)
        self.widget.bind('<Configure>', self.layout)

    def layout(self, event):
        width = event.width / self.app.s
        self.photo = ImageTk.PhotoImage(self.app.paint.entry_frame(max(40, width)))
        self.widget.itemconfigure(self.frame, image=self.photo)
        self.widget.itemconfigure(self.window, width=max(10, event.width - self.app.px(24)))


class Slider:
    """A thin track with a gold fill and a white knob (Tk's Scale draws native blocks on Windows)."""

    def __init__(self, app, parent, low, high, step, value, on_change, width=220):
        self.app, self.low, self.high, self.step, self.on_change = app, low, high, step, on_change
        self.value = value
        self.w, self.h = app.px(width), app.px(26)
        self.widget = app.tk.Canvas(parent, width=self.w, height=self.h, bg=CARD, highlightthickness=0, bd=0,
                                    cursor='hand2')
        for sequence in ('<Button-1>', '<B1-Motion>'):
            self.widget.bind(sequence, self.pick)
        self.draw()

    def draw(self):
        c, px = self.widget, self.app.px
        c.delete('all')
        r, y, pad = px(2), self.h / 2, px(10)
        frac = (self.value - self.low) / (self.high - self.low)
        x = pad + frac * (self.w - 2 * pad)
        c.create_rectangle(pad, y - r, self.w - pad, y + r, fill='#3a4451', outline='')
        c.create_rectangle(pad, y - r, x, y + r, fill=ACCENT, outline='')
        c.create_oval(x - px(8), y - px(8), x + px(8), y + px(8), fill='#ffffff', outline=ACCENT, width=px(2))

    def pick(self, event):
        pad = self.app.px(10)
        frac = min(1.0, max(0.0, (event.x - pad) / max(1, self.w - 2 * pad)))
        value = round((self.low + frac * (self.high - self.low)) / self.step) * self.step
        value = round(min(self.high, max(self.low, value)), 3)
        if value != self.value:
            self.value = value
            self.draw()
            self.on_change(value)


class InkScrollbar:
    """A thin rounded thumb, no track."""

    def __init__(self, app, parent, command):
        self.app, self.command = app, command
        self.first, self.last = 0.0, 1.0
        self.widget = app.tk.Canvas(parent, width=app.px(6), bg=CARD, highlightthickness=0, bd=0)
        self.widget.bind('<Configure>', lambda e: self.draw())
        self.widget.bind('<Button-1>', self.drag)
        self.widget.bind('<B1-Motion>', self.drag)

    def set(self, first, last):
        self.first, self.last = float(first), float(last)
        self.draw()

    def draw(self):
        c = self.widget
        c.delete('all')
        w, h = int(c['width']), c.winfo_height()
        if h < 4 or self.last - self.first >= 1.0:
            return
        r = w / 2
        y0, y1 = self.first * h, max(self.first * h + w * 3, self.last * h)
        color = '#3c4652'
        c.create_rectangle(0, y0 + r, w, y1 - r, fill=color, outline=color)
        c.create_oval(0, y0, w, y0 + w, fill=color, outline=color)
        c.create_oval(0, y1 - w, w, y1, fill=color, outline=color)

    def drag(self, event):
        h = max(1, self.widget.winfo_height())
        size = self.last - self.first
        self.command('moveto', min(1 - size, max(0.0, event.y / h - size / 2)))


class DashLine:
    """A hairline rule between rows."""

    def __init__(self, app, parent):
        self.widget = app.tk.Frame(parent, height=1, bg=LINE)


# ---------------------------------------------------------------------------------------------
# The window.

NAV = [('game', 'Game'), ('video', 'Video'), ('controls', 'Controls'), ('advanced', 'Advanced'), ('log', 'Log & diagnostics')]
NAV_ICONS = {'game': 'folder', 'video': 'monitor', 'controls': 'gamepad', 'advanced': 'sliders', 'log': 'terminal'}
# The layout (design units). Sidebar: brand, menu, status, play button, version. The pages' card,
# dialogs and notices stay right of the sidebar, so nothing ever covers the menu.
BRAND_X, BRAND_Y = 22, 26
NAV_X, NAV_Y, NAV_W, NAV_H, NAV_GAP = 12, 104, 248, 44, 4
STATUS_X, STATUS_Y, STATUS_W = 28, 446, 220
PLAY_X, PLAY_Y, PLAY_W, PLAY_H = 24, 574, 224, 54
PANEL_X, PANEL_Y, PANEL_W, PANEL_H = 296, 52, 800, 624
CONTENT_CX = (SIDEBAR_W + W) / 2


class LauncherWindow:
    def __init__(self, root, tk, filedialog, logic):
        global LANG
        self.root, self.tk, self.filedialog, self.logic = root, tk, filedialog, logic
        self.app = {**logic.APP_DEFAULTS, 'gyro_sens': 1.4,
                    **logic.load_json(logic.CONFIG_FILE, {})}
        self.ini, self.ini_lines = logic.load_ini()
        LANG = pick_language(self.app.get('ui_language'), logic.windows_language())
        self.process = self.job = None
        self.output, self.log_lines = queue.Queue(), []
        self.ui_calls = queue.Queue()  # work for the Tk thread from helper threads (updates)
        self.update_checking = False
        self.page = None
        self.capture = None   # (button, chip) while waiting for a key
        self.register_font()
        # Windows' timer ticks every 15.6 ms by default: Tk's after() then lands unevenly and the
        # animations stutter. 1 ms while the launcher is open (released when it closes).
        try:
            ctypes.windll.winmm.timeBeginPeriod(1)
            root.bind('<Destroy>', lambda e: e.widget is root and ctypes.windll.winmm.timeEndPeriod(1))
        except (AttributeError, OSError):
            pass
        # Scale: the screen's DPI, kept inside 92 % of the work area.
        dpi = root.winfo_fpixels('1i') / 96
        fit = min(root.winfo_screenwidth() * .92 / W, root.winfo_screenheight() * .92 / H)
        self.s = max(.6, min(dpi, fit))
        self.paint = Painter(self.s)
        self.anim = Animator(root, not reduced_motion())
        self.build_window()
        self.build_scene()
        self.root.after(100, self.drain)
        # A release package looks for a newer version once the window is up (not a development copy).
        if logic.IS_RELEASE and self.app.get('update_check', True):
            self.root.after(1500, self.check_update)
        if '--updated' in sys.argv:
            self.root.after(900, lambda: self.toast(t('Updated to version {}').format(logic.VERSION)))

    # ---- basics ----------------------------------------------------------------------------
    def px(self, v):
        return max(1, round(v * self.s))

    def font(self, size, weight='normal', family=UI_FONT):
        return (family, -self.px(size), weight)

    def register_font(self):
        try:
            ctypes.windll.gdi32.AddFontResourceExW(str(FONT_FILE), 0x10, 0)  # FR_PRIVATE
        except (AttributeError, OSError):
            pass

    def save(self):
        logic = self.logic
        logic.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        logic.CONFIG_FILE.write_text(json.dumps(self.app, indent=2, ensure_ascii=False), encoding='utf-8')
        logic.save_ini({key: self.ini.get(key, value) for key, value in logic.INI_DEFAULTS.items()}, self.ini_lines)
        self.ini, self.ini_lines = logic.load_ini()

    def user_dir(self):
        return Path(self.app.get('user_dir') or self.logic.DATA_DIR / 'user')

    # ---- window ----------------------------------------------------------------------------
    def build_window(self):
        root, tk = self.root, self.tk
        root.title('Gravity Rush Launcher')
        root.configure(bg='#2b3a36')
        width, height = self.px(W), self.px(H)
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 2
        root.geometry(f'{width}x{height}+{x}+{y}')
        root.resizable(False, False)
        try:
            root.iconbitmap(default=str(HERE / 'gravityrush.ico'))
        except tk.TclError:
            pass
        root.overrideredirect(True)
        root.after(10, self.taskbar_entry)
        root.bind('<Map>', self.restore_frameless)
        self.cv = tk.Canvas(root, width=width, height=height, highlightthickness=0, bd=0, bg='#2b3a36')
        self.cv.pack()
        self.cv.bind('<Button-1>', self.click_background)
        root.bind('<Escape>', self.escape)
        root.bind_all('<MouseWheel>', self.wheel)
        root.bind('<KeyPress>', self.key_press)

    def taskbar_entry(self):
        """A frameless window still gets its taskbar button and Windows 11 rounded corners."""
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
            user32.SetWindowLongW(hwnd, -20, (style & ~0x80) | 0x40000)  # no TOOLWINDOW, APPWINDOW
            corner = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
            self.root.withdraw()
            self.root.after(10, self.root.deiconify)
        except (AttributeError, OSError):
            pass

    def minimize(self):
        self.root.overrideredirect(False)
        self.root.iconify()

    def restore_frameless(self, _event=None):
        if self.root.state() == 'normal' and not self.root.overrideredirect():
            self.root.overrideredirect(True)
            self.root.after(10, self.taskbar_entry)

    # ---- scene -----------------------------------------------------------------------------
    def build_scene(self):
        cv, paint = self.cv, self.paint
        self.photos = {}
        # Background, 18 px larger on every side (it shifts a little when a page opens).
        self.bg_image = ImageTk.PhotoImage(paint.background(W + 36, H + 36))
        self.bg_excess = self.bg_image.width() / self.s - (W + 36)
        self.bg_pos = .5          # background-position: 50 % (home), 35 % (a page is open)
        self.par = [0.0, 0.0, 0.0, 0.0]
        self.bg = cv.create_image(0, 0, anchor='nw', image=self.bg_image)
        self.place_background()
        # A shade at the top of the picture, the sidebar's glass, the window buttons.
        self.photos['scrim'] = ImageTk.PhotoImage(paint.scrim(W - SIDEBAR_W, 96))
        cv.create_image(self.px(SIDEBAR_W), 0, anchor='nw', image=self.photos['scrim'])
        self.photos['sidebar'] = ImageTk.PhotoImage(paint.sidebar(H))
        self.sidebar = cv.create_image(0, 0, anchor='nw', image=self.photos['sidebar'])
        self.drag_area = cv.create_rectangle(0, 0, self.px(W - 92), self.px(40), fill='', outline='')
        cv.tag_bind(self.drag_area, '<ButtonPress-1>', self.drag_start)
        cv.tag_bind(self.drag_area, '<B1-Motion>', self.drag_move)
        self.win_images = [ImageTk.PhotoImage(paint.window_buttons(i)) for i in (None, 0, 1)]
        self.win = cv.create_image(self.px(W), 0, anchor='ne', image=self.win_images[0])
        cv.tag_bind(self.win, '<Motion>', self.window_hover)
        cv.tag_bind(self.win, '<Leave>', lambda e: cv.itemconfigure(self.win, image=self.win_images[0]))
        cv.tag_bind(self.win, '<Button-1>', self.window_click)
        # Brand: the port's icon and the wordmark.
        try:
            icon = Image.open(HERE / 'gravityrush.png').convert('RGBA')
        except OSError:
            icon = None
        self.photos['brand'] = ImageTk.PhotoImage(paint.brand(icon))
        self.brand = cv.create_image(self.px(BRAND_X), self.px(BRAND_Y), anchor='nw', image=self.photos['brand'])
        cv.tag_bind(self.brand, '<Button-1>', lambda e: self.modal_items or self.open_page(None))
        # Menu, status, play button, version.
        self.nav_items = {}
        self.nav_hover = None
        self.render_nav()
        self.status_items = []
        self.refresh_status()
        self.play = None
        self.render_play()
        self.ver = cv.create_text(self.px(SIDEBAR_W / 2), self.px(H - 24), text=t('Version {}').format(self.logic.VERSION),
                                  fill=TEXT3, font=self.font(11.5))
        # Card (hidden until a page opens), dialog and notice.
        self.panel_items = []
        self.modal_items = []
        self.toast_items = []
        self.drop_in()

    def place_background(self):
        x = -18 + -self.bg_excess * self.bg_pos + self.par[0]
        y = -18 + self.par[1]
        self.cv.coords(self.bg, self.px(x) if x >= 0 else -self.px(-x), self.px(y) if y >= 0 else -self.px(-y))

    def window_hover(self, event):
        part = 0 if event.x < self.px(W - 46) else 1
        self.cv.itemconfigure(self.win, image=self.win_images[1 + part])

    def window_click(self, event):
        if event.x < self.px(W - 46):
            self.minimize()
        else:
            self.ask_quit()

    def drag_start(self, event):
        self.drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def drag_move(self, event):
        self.root.geometry(f'+{event.x_root - self.drag[0]}+{event.y_root - self.drag[1]}')

    # ---- menu ------------------------------------------------------------------------------
    def render_nav(self):
        """The menu entries (in the current language)."""
        y = NAV_Y
        for index, (key, label) in enumerate(NAV):
            images = {look: ImageTk.PhotoImage(self.paint.nav_item(t(label), NAV_ICONS[key], look))
                      for look in ('normal', 'hover', 'on')}
            item = self.nav_items.get(key)
            if item:
                item['images'] = images
                self.cv.itemconfigure(item['id'], image=self.nav_image(key))
            else:
                item_id = self.cv.create_image(self.px(NAV_X), self.px(y), anchor='nw', image=images['normal'])
                self.nav_items[key] = {'id': item_id, 'images': images, 'y': y, 'x': NAV_X, 'index': index}
                self.cv.tag_bind(item_id, '<Enter>', lambda e, k=key: self.nav_enter(k))
                self.cv.tag_bind(item_id, '<Leave>', lambda e, k=key: self.nav_leave(k))
                self.cv.tag_bind(item_id, '<Button-1>', lambda e, k=key: self.nav_click(k))
            y += NAV_H + NAV_GAP

    def nav_image(self, key):
        item = self.nav_items[key]
        if key == self.page:
            return item['images']['on']
        return item['images']['hover' if self.nav_hover == key else 'normal']

    def nav_enter(self, key):
        self.nav_hover = key
        self.cv.itemconfigure(self.nav_items[key]['id'], image=self.nav_image(key))
        self.cv.configure(cursor='hand2')

    def nav_leave(self, key):
        if self.nav_hover == key:
            self.nav_hover = None
        self.cv.itemconfigure(self.nav_items[key]['id'], image=self.nav_image(key))
        self.cv.configure(cursor='')

    def nav_click(self, key):
        if self.modal_items:
            return 'break'
        self.open_page(None if key == self.page else key)
        return 'break'

    def render_play(self):
        """The play button (in the current language)."""
        cv = self.cv
        self.play_looks = {look: ImageTk.PhotoImage(self.paint.play_button(t('Play').upper(), look))
                           for look in ('normal', 'hover', 'press')}
        if self.play:
            cv.itemconfigure(self.play, image=self.play_looks['normal'])
            return
        self.play = cv.create_image(self.px(PLAY_X - 8), self.px(PLAY_Y - 4), anchor='nw', image=self.play_looks['normal'])

        def look(name, cursor):
            cv.itemconfigure(self.play, image=self.play_looks[name])
            cv.configure(cursor=cursor)
        cv.tag_bind(self.play, '<Enter>', lambda e: look('hover', 'hand2'))
        cv.tag_bind(self.play, '<Leave>', lambda e: look('normal', ''))
        cv.tag_bind(self.play, '<ButtonPress-1>', lambda e: look('press', 'hand2'))
        cv.tag_bind(self.play, '<ButtonRelease-1>', self.play_release)

    def play_release(self, event):
        inside = self.px(PLAY_X) <= event.x <= self.px(PLAY_X + PLAY_W) and \
            self.px(PLAY_Y) <= event.y <= self.px(PLAY_Y + PLAY_H)
        self.cv.itemconfigure(self.play, image=self.play_looks['hover' if inside else 'normal'])
        if inside and not self.modal_items:
            self.launch()

    def drop_in(self):
        """Entrance: the menu slides in from the left, 30 ms apart; the play button rises."""
        for key, item in self.nav_items.items():
            def update(v, item=item):
                self.cv.coords(item['id'], self.px(item['x'] - 14 * (1 - v)), self.px(item['y']))
            update(0.0)
            self.anim.add(320, update, ease_out, delay_ms=60 + item['index'] * 30)

        def rise(v):
            self.cv.coords(self.play, self.px(PLAY_X - 8), self.px(PLAY_Y - 4 + 12 * (1 - v)))
        rise(0.0)
        self.anim.add(360, rise, ease_out, delay_ms=220)

    # ---- status ----------------------------------------------------------------------------
    def refresh_status(self):
        """The sidebar's status lines: the game folder, the newest save, the display settings."""
        for item in self.status_items:
            self.cv.delete(item)
        self.status_items = []
        found = self.logic.game_info(self.app['game_dir'])
        saves = self.user_dir() / 'savedata'
        newest = 0.0
        if saves.is_dir():
            for path in saves.rglob('*'):
                if path.is_file() and path.suffix not in ('.png',):
                    newest = max(newest, path.stat().st_mtime)
        mode = dict(WINDOW_MODES).get(self.ini.get('display_mode', 'borderless'), 'Borderless')
        fps = self.ini.get('fps_limit', '0')
        display = t(mode) + (' · ' + t('VSync') if self.ini.get('vsync', '1') == '1' else '') + ' · ' + \
            (f'{fps} FPS' if fps not in ('', '0') else t('Unlimited FPS'))
        rows = [(t('Game found · all ready'), 'check', OK_C) if found else (t('Choose the game folder'), 'alert', WARN_C),
                (t('Last save · {}').format(time.strftime('%d/%m %H:%M', time.localtime(newest))) if newest
                 else t('No saves yet'), 'clock', TEXT3),
                (display, 'monitor', TEXT3)]
        self.status_photos = []
        y = STATUS_Y
        for index, (text, icon, color) in enumerate(rows):
            photo = ImageTk.PhotoImage(self.paint.status_line(text, icon, color, STATUS_W))
            self.status_photos.append(photo)
            item = self.cv.create_image(self.px(STATUS_X), self.px(y), anchor='nw', image=photo)
            if index == 0 and not found:  # opens the page where the folder is chosen
                self.cv.tag_bind(item, '<Button-1>', lambda e: self.modal_items or self.open_page('game'))
            self.status_items.append(item)
            y += 28

    # ---- pages -----------------------------------------------------------------------------
    def click_background(self, event):
        hit = self.cv.find_overlapping(event.x, event.y, event.x, event.y)
        ours = {i['id'] for i in self.nav_items.values()} | set(self.panel_items) | set(self.modal_items) | \
            set(self.status_items) | {self.win, self.drag_area, self.sidebar, self.play, self.brand}
        if self.page and not (set(hit) & ours):
            self.open_page(None)

    def escape(self, _event=None):
        if self.capture:
            return
        if self.modal_items:
            if not self.process:
                self.close_modal()
        elif self.page:
            self.open_page(None)

    def open_page(self, key):
        """Opens (or closes, None) a page in the card right of the sidebar."""
        self.page = key
        self.capture = None
        for item in self.panel_items:
            self.cv.delete(item)
        self.panel_items = []
        if hasattr(self, 'panel_frame'):
            self.panel_frame.destroy()
            del self.panel_frame
        for k, item in self.nav_items.items():
            self.cv.itemconfigure(item['id'], image=self.nav_image(k))
        start, end = self.bg_pos, .35 if key else .5
        if start != end:
            self.anim.add(700, lambda v: (setattr(self, 'bg_pos', start + (end - start) * v), self.place_background()),
                          ease_out)
        if key:
            self.build_panel(key)

    def build_panel(self, key):
        tk, cv = self.tk, self.cv
        titles = dict(NAV)
        self.photos['panel'] = ImageTk.PhotoImage(self.paint.panel(PANEL_W, PANEL_H, t(titles[key])))
        shell = cv.create_image(self.px(PANEL_X - 28), self.px(PANEL_Y - 28), anchor='nw', image=self.photos['panel'])
        self.photos['close'] = [ImageTk.PhotoImage(self.paint.icon_button('x', hover)) for hover in (False, True)]
        close = cv.create_image(self.px(PANEL_X + PANEL_W - 30), self.px(PANEL_Y + 32), anchor='center',
                                image=self.photos['close'][0])
        cv.tag_bind(close, '<Enter>', lambda e: cv.itemconfigure(close, image=self.photos['close'][1]))
        cv.tag_bind(close, '<Leave>', lambda e: cv.itemconfigure(close, image=self.photos['close'][0]))
        cv.tag_bind(close, '<Button-1>', lambda e: self.modal_items or self.open_page(None))
        inner_w, inner_h = PANEL_W - 56, PANEL_H - 76 - 20
        frame = self.panel_frame = tk.Frame(cv, bg=CARD, width=self.px(inner_w), height=self.px(inner_h))
        frame.pack_propagate(False)
        window = cv.create_window(self.px(PANEL_X + 28), self.px(PANEL_Y + 76), anchor='nw', window=frame,
                                  state='hidden')
        self.panel_items = [shell, close, window]
        # Scrolling body and the footer.
        foot = tk.Frame(frame, bg=CARD)
        foot.pack(side='bottom', fill='x')
        holder = tk.Frame(frame, bg=CARD)
        holder.pack(side='top', fill='both', expand=True)
        body_cv = tk.Canvas(holder, bg=CARD, highlightthickness=0, bd=0)
        bar = InkScrollbar(self, holder, body_cv.yview)
        body = tk.Frame(body_cv, bg=CARD)
        body_window = body_cv.create_window(0, 0, anchor='nw', window=body)
        body.bind('<Configure>', lambda e: body_cv.configure(scrollregion=body_cv.bbox('all')))
        body_cv.bind('<Configure>', lambda e: body_cv.itemconfigure(body_window, width=e.width))
        body_cv.configure(yscrollcommand=bar.set)
        body_cv.pack(side='left', fill='both', expand=True, padx=(0, self.px(12)))
        bar.widget.pack(side='right', fill='y')
        self.body_canvas = body_cv
        getattr(self, f'page_{key}')(body, foot)
        # Entrance: the card (one picture) rises a little; the controls, slow to move in Tk,
        # appear when it is in place.
        def update(v):
            dy = 14 * (1 - v)
            cv.coords(shell, self.px(PANEL_X - 28), self.px(PANEL_Y - 28 + dy))
            cv.coords(close, self.px(PANEL_X + PANEL_W - 30), self.px(PANEL_Y + 32 + dy))

        def landed():
            if window in self.panel_items:
                cv.itemconfigure(window, state='normal')
        update(0.0)
        self.anim.add(220, update, ease_out, done=landed)

    def wheel(self, event):
        if self.page and hasattr(self, 'body_canvas'):
            try:
                self.body_canvas.yview_scroll(int(-event.delta / 120) * 3, 'units')
            except self.tk.TclError:
                pass

    # ---- page building blocks ----------------------------------------------------------------
    def sec(self, parent, title, first=False):
        holder = self.tk.Frame(parent, bg=CARD)
        holder.pack(fill='x', pady=(self.px(2 if first else 24), self.px(2)))
        photo = ImageTk.PhotoImage(self.paint.section(t(title)))
        label = self.tk.Label(holder, image=photo, bg=CARD, bd=0)
        label.image = photo
        label.pack(anchor='w', pady=(0, self.px(2)))

    def row(self, parent, title, make, hint=None, wide=False):
        tk = self.tk
        line = tk.Frame(parent, bg=CARD)
        line.pack(fill='x')
        inner = tk.Frame(line, bg=CARD, height=self.px(48))
        inner.pack(fill='x')
        label = tk.Label(inner, text=t(title), bg=CARD, fg=TEXT, font=self.font(14), anchor='w', width=0,
                         justify='left', wraplength=self.px(320))
        label.pack(side='left', fill='y', pady=self.px(8))
        control = tk.Frame(inner, bg=CARD)
        control.pack(side='right', fill='x' if wide else None, expand=bool(wide), pady=self.px(7))
        make(control)
        if hint:
            tk.Label(line, text=t(hint), bg=CARD, fg=TEXT2, font=self.font(12.5), anchor='w', justify='left',
                     wraplength=self.px(PANEL_W - 120)).pack(fill='x', pady=(0, self.px(10)))
        DashLine(self, line).widget.pack(fill='x')

    def folder_row(self, parent, title, key, hint):
        tk = self.tk
        line = tk.Frame(parent, bg=CARD)
        line.pack(fill='x', pady=(self.px(10), 0))
        tk.Label(line, text=t(title), bg=CARD, fg=TEXT, font=self.font(14), anchor='w').pack(fill='x', pady=(0, self.px(6)))
        fields = tk.Frame(line, bg=CARD)
        fields.pack(fill='x')
        var = tk.StringVar(value=self.app.get(key, ''))
        RoundEntry(self, fields, var).widget.pack(side='left', fill='x', expand=True)

        def changed(*_):
            self.app[key] = var.get().strip()
            self.save()
            self.refresh_status()
        var.trace_add('write', changed)

        def browse():
            chosen = self.filedialog.askdirectory(initialdir=var.get() or str(self.logic.PORT_DIR))
            if chosen:
                var.set(str(Path(chosen)))
        ImageButton(self, fields, t('Browse…'), browse).widget.pack(side='left', padx=(self.px(8), 0))
        ImageButton(self, fields, t('Open'), lambda: self.open_path(var.get(), key)).widget.pack(side='left', padx=(self.px(8), 0))
        if hint:
            tk.Label(line, text=t(hint), bg=CARD, fg=TEXT2, font=self.font(12.5), anchor='w', justify='left',
                     wraplength=self.px(PANEL_W - 120)).pack(fill='x', pady=(self.px(6), self.px(10)))
        DashLine(self, line).widget.pack(fill='x')

    def toggle_row(self, parent, title, value, on_change, hint=None):
        self.row(parent, title, lambda c: Toggle(self, c, value, on_change).widget.pack(side='right'), hint)

    def choice(self, parent, options, value, on_change, width=22, translate=True):
        """A select (width in characters, about 11 px each)."""
        names = [t(text) if translate else text for _key, text in options]
        return Select(self, parent, options, names, value, on_change, 24 + width * 11).widget

    def buttons(self, parent, entries):
        holder = self.tk.Frame(parent, bg=CARD)
        holder.pack(fill='x', pady=self.px(10))
        for text, command in entries:
            ImageButton(self, holder, t(text), command).widget.pack(side='left', padx=(0, self.px(8)))

    def footer(self, foot, entries):
        """The card's footer: a rule, then the buttons on the right."""
        self.tk.Frame(foot, bg=LINE, height=1).pack(fill='x', pady=(self.px(10), self.px(14)))
        row = self.tk.Frame(foot, bg=CARD)
        row.pack(fill='x')
        self.tk.Label(row, text='✓  ' + t('Saved automatically'), bg=CARD, fg=TEXT3,
                      font=self.font(12.5)).pack(side='left')
        for text, command, primary in reversed(entries):
            ImageButton(self, row, t(text), command, 'pri' if primary else 'gh').widget.pack(side='right', padx=(self.px(10), 0))

    def hint(self, parent, text):
        self.tk.Label(parent, text=t(text), bg=CARD, fg=TEXT2, font=self.font(12.5), anchor='w', justify='left',
                      wraplength=self.px(PANEL_W - 120)).pack(fill='x', pady=(self.px(4), self.px(8)))

    # ---- the pages ---------------------------------------------------------------------------
    def page_game(self, body, foot):
        logic = self.logic
        self.sec(body, 'FOLDERS', first=True)
        self.folder_row(body, 'Game folder', 'game_dir', 'Your game dump (eboot.bin, sce_module, sce_sys).')
        self.folder_row(body, 'Saves folder', 'user_dir', 'Empty: the launcher data folder (it also holds the shader cache).')
        self.sec(body, 'DETECTED GAME')
        found = logic.game_info(self.app['game_dir'])
        if found:
            try:
                title_id = logic.game_profile_of(self.app['game_dir'])[0] or '—'
            except Exception:
                title_id = '—'
            details = [('Title', found[0]), ('Code', title_id), ('Version', found[1])]
        else:
            details = []
        for title, value in details:
            self.row(body, title, lambda c, v=value: self.tk.Label(c, text=v, bg=CARD, fg=TEXT2,
                                                                  font=self.font(14)).pack(side='right'))
        self.row(body, 'Status', lambda c: self.tk.Label(
            c, text=t('Found, ready to play') if found else t('Not found: choose the folder that contains eboot.bin'),
            bg=CARD, fg=OK_C if found else WARN_C, font=self.font(14, 'bold')).pack(side='right'))
        self.sec(body, 'SHORTCUTS')
        self.hint(body, 'Gravity Rush starts the game with the saved settings, Gravity Rush Launcher opens this window.')
        self.buttons(body, [('Create desktop shortcuts', self.shortcut)])
        self.sec(body, 'SAVES')
        names = logic.save_backup.list_backups(self.user_dir())
        self.backup_choice = names[0] if names else ''

        def make(control):
            if names:
                def when(name):  # 20261018-204037 -> 18/10/2026 20:40
                    return f'{name[6:8]}/{name[4:6]}/{name[:4]} {name[9:11]}:{name[11:13]}' if len(name) >= 13 else name
                self.choice(control, [(n, when(n)) for n in names], self.backup_choice,
                            lambda n: setattr(self, 'backup_choice', n), 16).pack(side='left')
            else:
                self.tk.Label(control, text='—', bg=PAPER, fg=MU, font=self.font(14)).pack(side='left')
            ImageButton(self, control, t('Restore'), self.ask_restore).widget.pack(side='left', padx=(self.px(8), 0))
        self.toggle_row(body, 'Back up before every start', self.app.get('save_backup', True),
                        lambda v: self.set_app('save_backup', v),
                        'Copies your saves before the game starts, so you can always go back.')
        self.row(body, 'Backups to keep',
                 lambda c: Segments(self, c, [('5', '5'), ('10', '10'), ('20', '20')],
                                    str(self.app.get('save_backup_keep', 10)),
                                    lambda v: self.set_app('save_backup_keep', int(v))).widget.pack(side='right'),
                 'The oldest ones are deleted.')
        self.row(body, 'Save backups', make, 'Newest first. Restoring backs up the current saves first.')
        self.buttons(body, [('Back up now', self.backup_now)])
        self.sec(body, 'LANGUAGE')
        self.row(body, 'Game language', lambda c: self.choice(c, GAME_LANGUAGES, str(self.app.get('language', '1')),
                                                             lambda v: self.set_app('language', v), 14).pack(side='right'))

    def page_video(self, body, foot):
        self.sec(body, 'SCREEN', first=True)
        gpus = self.logic.vulkan_gpus()
        if gpus or self.app.get('gpu'):
            names = [name for name, _ in gpus]
            options = [('', 'Auto')] + [(name, name) for name in names]
            if self.app.get('gpu') and self.app['gpu'] not in names:
                options.append((self.app['gpu'], self.app['gpu']))
            self.row(body, 'Graphics card',
                     lambda c: self.choice(c, options, self.app.get('gpu', ''), lambda v: self.set_app('gpu', v),
                                           26).pack(side='right'),
                     'The card the game uses when the PC has more than one, such as a laptop with integrated and '
                     'dedicated graphics. Auto picks the most capable one. Applied at start.')
        self.row(body, 'Window mode', lambda c: Segments(self, c, WINDOW_MODES, self.ini.get('display_mode', 'borderless'),
                                                        lambda v: self.set_ini('display_mode', v)).widget.pack(side='right'))
        self.toggle_row(body, 'Vertical sync', self.ini.get('vsync', '1') == '1', lambda v: self.set_ini('vsync', '1' if v else '0'))
        self.row(body, 'FPS limit', lambda c: Segments(self, c, FPS_CHOICES, self.ini.get('fps_limit', '0'),
                                                      lambda v: self.set_ini('fps_limit', v)).widget.pack(side='right'),
                 'The game is made for 60 FPS; other values can change physics and animations.')
        rates = [('0', 'Desktop')] + [(str(r), f'{r} Hz') for r in refresh_rates()]
        rate = self.ini.get('refresh_rate', '0')
        if rate not in dict(rates):
            rates.append((rate, f'{rate} Hz'))
        self.row(body, 'Refresh rate',
                 lambda c: self.choice(c, rates, rate, lambda v: self.set_ini('refresh_rate', v), 16).pack(side='right'),
                 'Used in Fullscreen and Borderless, while the game runs. Windowed keeps the Windows setting.')

        self.sec(body, 'IMAGE QUALITY')
        aa_choices = AA_CHOICES[:3] + [('dlss', 'DLSS')] + AA_CHOICES[3:] if dlss_installed() else AA_CHOICES
        mode = aa_mode(self.ini)

        def set_aa(chosen):
            self.ini['upscaler'] = chosen if chosen in TEMPORAL_AA else 'off'
            self.ini['fxaa'] = '0' if chosen == 'off' else '1'
            self.save()
            self.refresh_status()
            self.reopen_page()  # the hint and the FSR 1.0 rows follow the mode
        self.row(body, 'Anti-aliasing',
                 lambda c: Segments(self, c, aa_choices, mode, set_aa).widget.pack(side='right'), AA_HINTS[mode])
        current = self.ini.get('render_resolution', 'native')
        if current not in dict(RESOLUTION_CHOICES):
            current = 'native'
        if mode in ('fsr3', 'dlss'):
            table = mode_table()
            chosen = UPSCALE_MODES[table.index(current)] if current in table else ''
            labels = [('native', 'DLAA' if mode == 'dlss' else 'Native'), ('quality', 'Quality'),
                      ('balanced', 'Balanced'), ('performance', 'Performance')]

            def set_mode(name):
                self.ini['render_resolution'] = table[UPSCALE_MODES.index(name)]
                self.save()
                self.reopen_page()
            w, h = RESOLUTION_SIZES[current]
            sw, sh = screen_size()
            hint = t('Draws at your screen’s size ({}): anti-aliasing only, the sharpest image.').format(f'{w}x{h}') \
                if chosen == 'native' else \
                t('Draws at {} and enlarges to your {} screen. Quality is the sharpest, Performance the fastest.') \
                .format(f'{w}x{h}', f'{sw}x{sh}')
            self.row(body, 'Mode', lambda c: Segments(self, c, labels, chosen, set_mode).widget.pack(side='right'), hint)
        else:
            self.row(body, 'Render resolution',
                     lambda c: self.choice(c, RESOLUTION_CHOICES, current,
                                           lambda v: self.set_ini('render_resolution', v), 16).pack(side='right'),
                     'The size the game draws at. Lower than your screen runs faster.')
        if mode not in TEMPORAL_AA or mode == 'taa':
            # FSR 1.0 and its sharpening act only without FSR 3.1 / DLSS (they enlarge on their own).
            self.row(body, 'Simple upscaler',
                     lambda c: Segments(self, c, UPSCALER_CHOICES, '1' if self.ini.get('fsr1', '0') == '1' else '0',
                                        lambda v: self.set_ini('fsr1', v)).widget.pack(side='right'),
                     'A simple enlargement to your screen when the render resolution is lower, with FXAA or TAA. '
                     'FSR 3.1 does it with more detail.')

            def make_sharpening(control):
                try:
                    value = int(self.ini.get('rcas_strength', '75')) if self.ini.get('rcas', '1') == '1' else 0
                except ValueError:
                    value = 75
                shown = self.tk.Label(control, text=f'{value}%', bg=CARD, fg=TEXT2, font=self.font(13.5, 'bold'),
                                      width=5, anchor='e')

                def changed(v):
                    v = int(round(v))
                    shown.configure(text=f'{v}%')
                    self.ini['rcas'] = '1' if v > 0 else '0'
                    if v > 0:
                        self.ini['rcas_strength'] = str(v)
                    self.save()
                Slider(self, control, 0, 100, 5, value, changed).widget.pack(side='left')
                shown.pack(side='left')
            self.row(body, 'Sharpening', make_sharpening,
                     'Sharpens the final image with FSR 1.0, when the game image is smaller than the screen. 0: off.')

        self.sec(body, 'DETAILS')
        shadows = self.ini.get('shadow_quality', 'standard')
        self.row(body, 'Shadow quality',
                 lambda c: self.choice(c, SHADOW_CHOICES, shadows if shadows in dict(SHADOW_CHOICES) else 'standard',
                                       lambda v: self.set_ini('shadow_quality', v), 16).pack(side='right'),
                 'Sharper shadow edges and fewer jagged lines. Uses 256 MB of video memory.')
        aniso = self.ini.get('anisotropy', '16')
        self.row(body, 'Anisotropic filtering',
                 lambda c: self.choice(c, ANISOTROPY_CHOICES, aniso if aniso in dict(ANISOTROPY_CHOICES) else '16',
                                       lambda v: self.set_ini('anisotropy', v), 16).pack(side='right'),
                 'Sharper textures seen at an angle. The game already uses 16x on its world textures; this raises the '
                 'ones that use less.')
        self.footer(foot, [('Reset', lambda: self.reset({'display_mode': 'borderless', 'vsync': '1', 'fps_limit': '0',
                                                         'refresh_rate': '0',
                                                         'render_resolution': 'native', 'anisotropy': '16',
                                                         'shadow_quality': 'standard', 'fxaa': '1', 'upscaler': 'off',
                                                         'fsr1': '0',
                                                         'rcas': '1', 'rcas_strength': '75', 'sharpen': '0'}),
                           False),
                           ('Close', lambda: self.open_page(None), True)])

    def reopen_page(self):
        """Draws the open page again at the same scroll position."""
        try:
            top = self.body_canvas.yview()[0]
        except (AttributeError, self.tk.TclError):
            top = 0.0
        self.open_page(self.page)
        try:
            self.root.update_idletasks()
            self.body_canvas.yview_moveto(top)
        except (AttributeError, self.tk.TclError):
            pass

    def page_controls(self, body, foot):
        tk, logic = self.tk, self.logic
        self.sec(body, 'MENUS', first=True)
        self.row(body, 'Menu confirm button',
                 lambda c: self.choice(c, [('cross', ('Cross (X / A)',)), ('circle', ('Circle (O / B)',))],
                                       self.ini.get('menu_confirm', 'cross'),
                                       lambda v: self.set_ini('menu_confirm', v), 18).pack(side='right'),
                 'Applies on next launch. Changes menu confirm/back only, not gameplay buttons.')
        self.sec(body, 'GYROSCOPE')

        def make_slider(control):
            value = float(self.app.get('gyro_sens', 1.4))
            shown = tk.Label(control, text=f'{value:.1f}×', bg=PAPER, fg=MU, font=self.font(14, 'bold'), width=5, anchor='e')

            def changed(v):
                shown.configure(text=f'{v:.1f}×')
                self.set_app('gyro_sens', round(v, 1))
            Slider(self, control, 0.5, 3.0, 0.1, value, changed).widget.pack(side='left')
            shown.pack(side='left')
        self.row(body, 'Sensitivity', make_slider, 'Aiming by moving a DualSense or DualShock 4.')
        keys = self.app.get('controls', {}).get('key', {}) if isinstance(self.app.get('controls'), dict) else {}
        pads = logic.PAD_STYLES.get(self.app.get('pad_style', 'playstation'), logic.PAD_STYLES['playstation'])
        for group, members in (('BUTTONS', logic.CONTROLS[:12]), ('D-PAD', logic.CONTROLS[12:])):
            self.sec(body, group)
            if group == 'BUTTONS':
                self.hint(body, 'Click a key, then press the new one (Esc cancels).')
                head = tk.Frame(body, bg=PAPER, height=self.px(26))
                head.pack(fill='x', pady=(self.px(4), 0))
                head.pack_propagate(False)
                for text, x in (('COMMAND', 0), ('CONTROLLER', 250), ('KEYBOARD', 480)):  # the rows' columns
                    tk.Label(head, text=t(text), bg=PAPER, fg=TEXT3, font=self.font(11.5, 'bold')).place(
                        x=self.px(x), rely=.5, anchor='w')
            for button, default_key, pad in members:
                line = tk.Frame(body, bg=PAPER, height=self.px(36))
                line.pack(fill='x')
                line.pack_propagate(False)
                tk.Label(line, text=t(BUTTON_NAMES[button]), bg=PAPER, fg=SD,
                         font=self.font(13.5), width=0, anchor='w').place(x=0, rely=.5, anchor='w')
                pad_label = t(pads.get(pad, pad) if pad else 'Trigger')
                tk.Label(line, text=pad_label, bg=PAPER, fg=SD,
                         font=self.font(13.5)).place(x=self.px(250), rely=.5, anchor='w')
                chip = ImageButton(self, line, keys.get(button) or default_key, None, 'chip')
                chip.command = lambda b=button, c=chip: self.start_capture(b, c)
                chip.widget.place(x=self.px(480), rely=.5, anchor='w')
        self.footer(foot, [('Reset', self.reset_controls, False), ('Close', lambda: self.open_page(None), True)])

    def page_advanced(self, body, foot):
        self.sec(body, 'LAUNCHER', first=True)
        self.row(body, 'Launcher language', lambda c: self.choice(c, [('', t('System'))] + LANGUAGES,
                                                                 self.app.get('ui_language', ''), self.set_language,
                                                                 14, translate=False).pack(side='right'))
        self.sec(body, 'UPDATES')
        self.toggle_row(body, 'Check for updates at start', self.app.get('update_check', True),
                        lambda v: self.set_app('update_check', v),
                        'Looks for a new version on GitHub when the launcher opens and asks before installing it.')

        def make_version(control):
            self.tk.Label(control, text=self.logic.VERSION, bg=PAPER, fg=MU,
                          font=self.font(14, 'bold')).pack(side='left', padx=(0, self.px(10)))
            ImageButton(self, control, t('Check now'), lambda: self.check_update(manual=True)).widget.pack(side='left')
        self.row(body, 'Installed version', make_version,
                 None if self.logic.IS_RELEASE else 'Development copy: it updates with git.')
        self.sec(body, 'IN GAME')
        self.toggle_row(body, 'Performance overlay', self.ini.get('show_fps', '1') == '1',
                        lambda v: self.set_ini('show_fps', '1' if v else '0'), 'Shows the FPS while you play.')
        self.row(body, 'In-game menu', lambda c: ImageButton(self, c, 'Ins', None, 'chip').widget.pack(side='right'),
                 'Opens the settings while you play: Ins on the keyboard, or R3 + L2 on the controller.')
        self.sec(body, 'PERFORMANCE')
        cache = self.user_dir() / 'cache'
        size = sum(p.stat().st_size for p in cache.rglob('*') if p.is_file()) if cache.is_dir() else 0

        def make_cache(control):
            self.tk.Label(control, text=f'{size / 1048576:.0f} MB' if size else t('empty'), bg=PAPER, fg=MU,
                          font=self.font(14, 'bold')).pack(side='left', padx=(0, self.px(10)))
            ImageButton(self, control, t('Clear'), self.clear_cache).widget.pack(side='left')
        self.row(body, 'Shader cache', make_cache)
        self.gpu_threads(body)
        self.sec(body, 'DEVELOPMENT')
        self.toggle_row(body, 'Validation layer', self.app.get('vk_validation', False),
                        lambda v: self.set_app('vk_validation', v), 'Vulkan checks for bug reports; slower.')
        self.toggle_row(body, 'F12 closes the game', self.app.get('f12_quits', False),
                        lambda v: self.set_app('f12_quits', v),
                        'F12 always saves screenshots and the log for bug reports; this also closes the game right after.')
        self.sec(body, 'DATA')
        self.row(body, 'Launcher data folder', lambda c: ImageButton(self, c, t('Open'), lambda: self.open_path(
            str(self.logic.CONFIG_DIR))).widget.pack(side='right'))
        self.buttons(body, [('Export settings', self.export_settings), ('Import settings', self.import_settings)])
        self.footer(foot, [('Reset all', self.reset_all, False), ('Close', lambda: self.open_page(None), True)])

    def gpu_threads(self, body):
        """GPU readbacks and the port's threads (environment variables at the next start)."""
        self.sec(body, 'GPU AND THREADS')
        self.row(body, 'GPU readbacks',
                 lambda c: self.choice(c, [('', 'Auto'), ('0', 'Off'), ('1', 'Relaxed'), ('2', 'Precise')],
                                       self.app.get('readbacks', ''), lambda v: self.set_app('readbacks', v),
                                       14).pack(side='right'),
                 'How the game reads data the graphics card produced. Auto is recommended. Precise is the most faithful and the slowest; Off is the fastest but lighting or objects may look wrong.')
        self.toggle_row(body, 'Deferred readbacks', self.ini.get('deferred_readback', '1') == '1',
                        lambda v: self.set_ini('deferred_readback', '1' if v else '0'),
                        'Fewer waits for the graphics card. Switch it off if textures or shadows look wrong. Applied at start.')
        self.toggle_row(body, 'Read without waiting', self.ini.get('stale_readback', '0') == '1',
                        lambda v: self.set_ini('stale_readback', '1' if v else '0'),
                        'More FPS: the game may read GPU data one frame old. Switch it off if lighting or objects look wrong. Applied at start.')
        self.row(body, 'Draw pipeline thread',
                 lambda c: self.choice(c, [('', 'Auto'), ('1', 'On'), ('0', 'Off')], self.app.get('draw_pipe', ''),
                                       lambda v: self.set_app('draw_pipe', v), 14).pack(side='right'),
                 'Records the draws on a second thread: about 4% more FPS, but it can show one-frame glitches (stretched triangles). Auto leaves it off. Applied at start.')
        self.row(body, 'Draw preparation threads',
                 lambda c: self.choice(c, [('', 'Auto'), ('0', '0'), ('1', '1'), ('2', '2'), ('4', '4'), ('8', '8')],
                                       str(self.app.get('prep_workers', '')),
                                       lambda v: self.set_app('prep_workers', v), 14).pack(side='right'),
                 'Helper threads that pre-process the game’s draw lists. Auto uses half of your CPU threads, at most 8. Applied at start.')
        self.row(body, 'Copy threads',
                 lambda c: self.choice(c, [('', 'Auto'), ('1', '1'), ('2', '2'), ('4', '4')],
                                       str(self.app.get('copy_threads', '')),
                                       lambda v: self.set_app('copy_threads', v), 14).pack(side='right'),
                 'Threads for the memory copies the game waits for. Auto uses a quarter of your CPU threads, at most 4. Applied at start.')
        self.toggle_row(body, 'Vulkan recording thread', self.app.get('record_thread', True),
                        lambda v: self.set_app('record_thread', v),
                        'Records the graphics commands on their own thread. Turn it off only to diagnose problems. Applied at start.')

        def restore():
            for key, value in (('readbacks', ''), ('draw_pipe', ''), ('prep_workers', ''), ('copy_threads', ''),
                               ('record_thread', True), ('gpu', '')):
                self.app[key] = value
            self.ini['deferred_readback'], self.ini['stale_readback'] = '1', '0'
            self.save()
            self.open_page(self.page)
            self.toast(t('Defaults restored'))
        self.buttons(body, [('Restore GPU and thread defaults', restore)])

    def page_log(self, body, foot):
        tk = self.tk
        self.body_canvas.configure(yscrollincrement=1)
        tk.Label(body, text=t('Game messages'), bg=PAPER, fg=TEXT2, font=self.font(13)).pack(anchor='w')
        text = self.console = tk.Text(body, height=18, bg=CONSOLE_BG, fg='#b8c2cd', insertbackground=TEXT, relief='flat',
                                      font=('Consolas', -self.px(12)), highlightthickness=1, highlightbackground=LINE,
                                      highlightcolor=LINE, wrap='none', padx=self.px(12), pady=self.px(10),
                                      selectbackground=ACCENT, selectforeground=ON_ACCENT)
        text.tag_configure('ok', foreground=OK_C)
        text.tag_configure('warn', foreground=ACCENT)
        text.pack(fill='both', expand=True, pady=(self.px(8), 0))
        if not self.log_lines:
            try:
                self.log_lines = (self.user_dir() / 'last_run.log').read_text(encoding='utf-8', errors='replace').splitlines(True)[-3000:]
            except OSError:
                self.log_lines = [t('No game started yet.')]
        for line in self.log_lines:
            self.console_line(line)
        text.configure(state='disabled')
        self.footer(foot, [('Copy log', self.copy_log, False), ('Open log folder', lambda: self.open_path(str(self.user_dir())), True)])

    def console_line(self, line):
        tag = 'warn' if ('Fault' in line or 'STOP' in line or 'error' in line.lower() or '<Warning>' in line) else \
              'ok' if ('trophy' in line or 'mounted' in line or 'Entering original' in line) else ''
        self.console.insert('end', line if line.endswith('\n') else line + '\n', tag)

    # ---- settings actions ------------------------------------------------------------------
    def set_app(self, key, value):
        self.app[key] = value
        self.save()

    def set_ini(self, key, value):
        self.ini[key] = value
        self.save()
        self.refresh_status()

    def set_language(self, code):
        """Switches the launcher's language at once ("" follows Windows)."""
        global LANG
        self.app['ui_language'] = code
        self.save()
        LANG = pick_language(code, self.logic.windows_language())
        self.render_nav()
        self.render_play()
        self.cv.itemconfigure(self.ver, text=t('Version {}').format(self.logic.VERSION))
        self.refresh_status()
        self.open_page(self.page)

    def apply(self):
        self.save()
        self.refresh_status()
        self.toast(t('Settings applied'))

    def reset(self, values):
        self.ini.update(values)
        self.save()
        self.refresh_status()
        self.open_page(self.page)
        self.toast(t('Defaults restored'))

    def reset_controls(self):
        self.app['controls'] = {}
        self.app['gyro_sens'] = 1.4
        self.save()
        self.open_page('controls')
        self.toast(t('Defaults restored'))

    def reset_all(self):
        self.ini.update({'show_fps': '1'})
        self.app['vk_validation'] = False
        self.app['ui_language'] = ''
        self.save()
        self.open_page('advanced')
        self.toast(t('Defaults restored'))

    def start_capture(self, button, chip):
        if self.capture:
            self.capture[1].set_text(self.capture[2])
        self.capture = (button, chip, chip.text)
        chip.set_text(t('Press a key…'))

    def key_press(self, event):
        if not self.capture:
            return
        button, chip, old = self.capture
        self.capture = None
        if event.keysym == 'Escape':
            chip.set_text(old)
            return 'break'
        name = TK_KEYS.get(event.keysym) or (event.keysym.upper() if len(event.keysym) == 1 else event.keysym)
        chip.set_text(name)
        controls = self.app.get('controls') if isinstance(self.app.get('controls'), dict) else {}
        keys = dict(controls.get('key', {}))
        default = next(row[1] for row in self.logic.CONTROLS if row[0] == button)
        if name.casefold() == default.casefold():
            keys.pop(button, None)
        else:
            keys[button] = name
        controls['key'] = keys
        self.app['controls'] = controls
        self.save()
        return 'break'

    def shortcut(self):
        """Gravity Rush.lnk (plays with the saved settings) and Gravity Rush Launcher.lnk on the desktop."""
        logic = self.logic
        if logic.FROZEN:
            game = logic.PORT_DIR / logic.GAME_EXE
            links = [('Gravity Rush', game if game.is_file() else Path(sys.executable), '--play' if not game.is_file() else ''),
                     ('Gravity Rush Launcher', Path(sys.executable), '')]
            icon = HERE / 'gravityrush.ico'
        else:  # a source tree: the launcher script with the windowless Python
            pythonw = Path(sys.executable).with_name('pythonw.exe')
            python = pythonw if pythonw.exists() else Path(sys.executable)
            script = HERE / 'gravityrush_launcher.py'
            links = [('Gravity Rush', python, f'"{script}" --play'), ('Gravity Rush Launcher', python, f'"{script}"')]
            icon = HERE / 'gravityrush.ico'
        command = ''
        for name, target, arguments in links:
            command += ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath("Desktop")'
                        f'+"\\{name}.lnk");$s.TargetPath="{target}";$s.WorkingDirectory="{logic.PORT_DIR}";'
                        f'$s.IconLocation="{icon}";' + (f"$s.Arguments='{arguments}';" if arguments else '') + '$s.Save();')
        result = subprocess.run(['powershell', '-NoProfile', '-Command', command], capture_output=True,
                                creationflags=logic.NO_WINDOW)
        self.toast(t('Shortcut created on the desktop') if result.returncode == 0 else
                   t('Could not: {}').format(result.stderr.decode(errors='replace')[:80]))

    def ask_restore(self):
        if not getattr(self, 'backup_choice', ''):
            return
        if self.process:
            self.toast(t('Close the game first.'))
            return
        self.modal(t('Restore saves?'), t('The current saves are backed up first.'),
                   [('Cancel', self.close_modal, False), ('Restore', self.restore_backup, True)])

    def backup_now(self):
        if self.process:
            self.toast(t('Close the game first.'))
            return
        try:
            made = self.logic.save_backup.backup(self.user_dir(), keep=int(self.app.get('save_backup_keep', 10)))
        except OSError as error:
            self.toast(t('Could not: {}').format(error))
            return
        self.toast(t('Backup created') if made else t('No saves to back up yet'))
        self.open_page('game')

    def restore_backup(self):
        self.close_modal()
        try:
            self.logic.save_backup.restore(self.user_dir(), self.backup_choice,
                                           keep=int(self.app.get('save_backup_keep', 10)))
            self.toast(t('Saves restored'))
        except (OSError, ValueError) as error:
            self.toast(t('Could not: {}').format(error))
        self.refresh_status()
        self.open_page('game')

    def clear_cache(self):
        if self.process:
            self.toast(t('Close the game first.'))
            return
        shutil.rmtree(self.user_dir() / 'cache', ignore_errors=True)
        self.toast(t('Shader cache cleared'))
        self.open_page('advanced')

    def export_settings(self):
        path = self.filedialog.asksaveasfilename(defaultextension='.json', initialfile='gravityrush-launcher-settings.json',
                                                 filetypes=[('JSON', '*.json')])
        if path:
            Path(path).write_text(json.dumps({'app': self.app, 'ini': self.ini}, indent=2, ensure_ascii=False), encoding='utf-8')
            self.toast(t('Settings exported'))

    def import_settings(self):
        path = self.filedialog.askopenfilename(filetypes=[('JSON', '*.json')])
        if not path:
            return
        data = self.logic.load_json(path, {})
        self.app.update(data.get('app', {}))
        self.ini.update(data.get('ini', {}))
        self.save()
        self.refresh_status()
        self.open_page(self.page)
        self.toast(t('Settings imported'))

    def open_path(self, path, key=None):
        if key == 'user_dir' and not path:
            path = self.logic.DATA_DIR / 'user'
        path = Path(path or self.logic.DATA_DIR)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(''.join(self.log_lines))
        self.toast(t('Log copied'))

    # ---- modal and toast -------------------------------------------------------------------
    def modal(self, title, text, buttons, gauge=False, size=None):
        """A dialog: the window dims, the card sits right of the sidebar, as tall as its content,
        and rises a little. size: (width, ignored height)."""
        self.close_modal()
        tk, cv = self.tk, self.cv
        self.photos['overlay'] = ImageTk.PhotoImage(self.paint.overlay())
        dim = cv.create_image(0, 0, anchor='nw', image=self.photos['overlay'])
        bw = (size or (440, 0))[0]
        frame = tk.Frame(cv, bg=CARD)
        tk.Frame(frame, bg=CARD, width=self.px(bw - 56), height=0).pack()  # the dialog's width
        tk.Label(frame, text=title, bg=CARD, fg=TEXT, font=self.font(19, 'normal', UI_FONT_SEMI), anchor='w').pack(fill='x')
        self.modal_gauge = None
        if gauge:
            self.gauge_width = bw - 56
            self.modal_gauge = tk.Label(frame, bg=CARD, bd=0)
            self.modal_gauge.pack(fill='x', pady=(self.px(14), 0))
            self.gauge_fraction, self.gauge_phase = .08, 0.0
            self.tick_gauge()
        self.modal_text = tk.Label(frame, text=text, bg=CARD, fg=TEXT2, font=self.font(14), anchor='w', justify='left',
                                   wraplength=self.px(bw - 60))
        self.modal_text.pack(fill='x', pady=(self.px(10), self.px(4)))
        if buttons:
            foot = tk.Frame(frame, bg=CARD)
            foot.pack(fill='x', pady=(self.px(18), 0))
            for label, command, primary in reversed(buttons):
                ImageButton(self, foot, t(label), command, 'pri' if primary else 'gh').widget.pack(side='right', padx=(self.px(10), 0))
        frame.update_idletasks()
        bh = frame.winfo_reqheight() / self.s + 48
        self.photos['box'] = ImageTk.PhotoImage(self.paint.panel(bw, bh))
        bx, by = CONTENT_CX - bw / 2, (H - bh) / 2
        box = cv.create_image(self.px(bx - 28), self.px(by - 28), anchor='nw', image=self.photos['box'])
        win = cv.create_window(self.px(bx + 28), self.px(by + 24), anchor='nw', window=frame)
        self.modal_frame = frame
        self.modal_items = [dim, box, win]

        def pop(v):
            dy = 10 * (1 - v)
            cv.coords(box, self.px(bx - 28), self.px(by - 28 + dy))
            cv.coords(win, self.px(bx + 28), self.px(by + 24 + dy))
        pop(0.0)
        self.anim.add(200, pop, ease_out)

    def tick_gauge(self):
        if not self.modal_gauge or not self.modal_gauge.winfo_exists():
            return
        self.gauge_phase = (self.gauge_phase + 0.025) % 1.0
        photo = ImageTk.PhotoImage(self.paint.gauge(self.gauge_width, self.gauge_fraction, self.gauge_phase))
        self.modal_gauge.configure(image=photo)
        self.modal_gauge.image = photo
        self.root.after(33, self.tick_gauge)

    def close_modal(self):
        for item in self.modal_items:
            self.cv.delete(item)
        self.modal_items = []
        if hasattr(self, 'modal_frame'):
            self.modal_frame.destroy()
            del self.modal_frame
        self.modal_gauge = None

    def toast(self, text):
        """A notice at the top of the picture, right of the sidebar and above the card."""
        for item in self.toast_items:
            self.cv.delete(item)
        self.photos['toast'] = ImageTk.PhotoImage(self.paint.toast(text))
        item = self.cv.create_image(self.px(CONTENT_CX), self.px(8), anchor='n', image=self.photos['toast'])
        self.toast_items = [item]
        self.anim.add(240, lambda v: self.cv.coords(item, self.px(CONTENT_CX), self.px(8 - 8 * (1 - v)) if v < 1 else self.px(8)),
                      ease_out)
        self.root.after(2200, lambda: item in self.toast_items and (self.cv.delete(item), self.toast_items.remove(item)))

    # ---- updates -----------------------------------------------------------------------------
    def check_update(self, manual=False):
        """Asks GitHub for the newest release on a helper thread (the window stays responsive)."""
        if self.update_checking:
            return
        self.update_checking = True
        if manual:
            self.toast(t('Checking for updates…'))

        def work():
            try:
                release, failure = self.logic.latest_release(), None
            except Exception as error:  # offline, GitHub down, rate limit: only a manual check says so
                release, failure = None, error
            self.ui_calls.put(lambda: self.update_checked(release, failure, manual))
        threading.Thread(target=work, daemon=True).start()

    def update_checked(self, release, failure, manual):
        self.update_checking = False
        logic = self.logic
        if failure or not release:
            if manual:
                self.toast(t('Could not check for updates.'))
            return
        if logic.version_tuple(release['version']) <= logic.version_tuple(logic.INSTALLED_VERSION):
            if manual:
                self.toast(t('You have the latest version.'))
            return
        if not manual and (self.process or self.modal_items):  # busy: asked again at the next start
            return
        self.modal(t('Update available'),
                   t('Version {} is available (you have {}). Install it now? Saves and settings are kept.').format(
                       release['version'], logic.INSTALLED_VERSION),
                   [('Not now', self.close_modal, False), ("What's new", lambda: webbrowser.open(release['page']), False),
                    ('Install', lambda: self.install_update(release), True)], size=(480, 250))

    def install_update(self, release):
        """Downloads the release on a helper thread; the new launcher then replaces this one."""
        logic = self.logic
        if self.process:
            self.close_modal()
            self.toast(t('Close the game before updating.'))
            return
        if not logic.IS_RELEASE:  # a development copy updates with git
            self.close_modal()
            webbrowser.open(release['page'])
            return
        if not logic.folder_writable(logic.PORT_DIR):
            self.modal(t('Update failed'), t('This folder is read-only, so the launcher cannot update itself here. '
                                             'Download the new version from the releases page.'),
                       [('Close', self.close_modal, False),
                        ('Open the page', lambda: (webbrowser.open(release['page']), self.close_modal()), True)],
                       size=(480, 250))
            return
        self.modal(t('Updating'), t('Downloading version {}… {}%').format(release['version'], 0) + '\n' +
                   t('The launcher closes, installs the update and opens again.'), [], gauge=True, size=(480, 220))
        self.gauge_fraction = .02

        def progress(done, total):
            fraction = done / total if total else 0.0
            self.ui_calls.put(lambda: self.update_progress(release, fraction))

        def work():
            try:
                new = logic.download_update(release, progress)
                logic.start_update(new)
            except Exception as error:  # shown to the player; the launcher stays as it is
                self.ui_calls.put(lambda error=error: self.update_failed(release, error))
                return
            self.ui_calls.put(self.quit)
        threading.Thread(target=work, daemon=True).start()

    def update_progress(self, release, fraction):
        if self.modal_gauge is None:
            return
        self.gauge_fraction = max(.02, min(fraction, 1.0))
        self.modal_text.configure(text=t('Downloading version {}… {}%').format(release['version'], int(fraction * 100)) +
                                  '\n' + t('The launcher closes, installs the update and opens again.'))

    def update_failed(self, release, error):
        self.modal(t('Update failed'), t('The update could not be installed: {}').format(error),
                   [('Close', self.close_modal, False),
                    ('Open the page', lambda: (webbrowser.open(release['page']), self.close_modal()), True)],
                   size=(480, 250))

    # ---- quit --------------------------------------------------------------------------------
    def ask_quit(self):
        if self.modal_items:
            return
        self.modal(t('Quit?'), t('Close the launcher?') + ('\n' + t('The game keeps running.') if self.process else ''),
                   [('Cancel', self.close_modal, False), ('Quit', self.quit, True)])

    def quit(self):
        try:
            self.save()
        except Exception:  # never keep the window open over a settings problem
            pass
        self.root.destroy()

    # ---- launch ----------------------------------------------------------------------------
    def launch(self):
        if self.process:
            return
        self.save()
        if not self.logic.game_info(self.app['game_dir']):
            self.toast(t('Choose the game folder first.'))
            self.open_page('game')
            return
        if self.capture:
            self.capture[1].set_text(self.capture[2])
            self.capture = None
        if self.page:
            self.open_page(None)
        self.start_game()

    def start_game(self):
        logic = self.logic
        env = logic.game_environment(self.app)
        self.log_lines = []
        try:  # the game, started through run.py, may bring its own window to the front
            ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
        except (AttributeError, OSError):
            pass
        try:
            self.process = subprocess.Popen(logic.run_command(), cwd=logic.PORT_DIR, env=env, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=logic.NO_WINDOW)
        except OSError as error:
            self.toast(t('Could not: {}').format(error))
            return
        self.job = logic.GameJob(self.process)
        self.reached_game = False
        threading.Thread(target=self.read_output, args=(self.process,), daemon=True).start()
        self.modal(t('Starting…'), t('Preparing the game'), [], gauge=True)

    def read_output(self, process):
        log = None
        try:
            self.user_dir().mkdir(parents=True, exist_ok=True)
            log = open(self.user_dir() / 'last_run.log', 'w', encoding='utf-8', buffering=1)
        except OSError:
            pass
        for raw in iter(process.stdout.readline, b''):
            text = raw.decode('utf-8', errors='replace')
            if log:
                log.write(text)
            self.output.put(text)
        code = process.wait()
        if log:
            log.write(f'\nThe game exited (code {code}).\n')
            log.close()
        self.logic.convert_frame_dumps(self.user_dir())  # F12's frames as PNG files
        self.output.put((code,))

    def drain(self):
        while True:
            try:
                call = self.ui_calls.get_nowait()
            except queue.Empty:
                break
            call()
        try:
            for _i in range(500):
                item = self.output.get_nowait()
                if isinstance(item, tuple):
                    self.game_exited(item[0])
                    continue
                self.log_lines.append(item)
                if len(self.log_lines) > 6000:
                    del self.log_lines[:1000]
                if self.page == 'log' and hasattr(self, 'console') and self.console.winfo_exists():
                    self.console.configure(state='normal')
                    self.console_line(item)
                    self.console.see('end')
                    self.console.configure(state='disabled')
                if self.modal_gauge is not None:
                    if 'Mapped' in item or 'Linked modules' in item:
                        self.gauge_fraction = max(self.gauge_fraction, .4)
                        self.modal_text.configure(text=t('The game is starting'))
                    elif 'Window:' in item or 'Vulkan' in item:
                        self.gauge_fraction = max(self.gauge_fraction, .7)
                    elif 'Entering original x86-64 code' in item:
                        self.gauge_fraction = 1.0
                        self.root.after(600, self.in_game)
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def in_game(self):
        if not self.process:
            return
        self.reached_game = True
        self.modal(t('In game'), t('The game is running in its own window.'),
                   [('Stop the game', self.stop_game, False), ('Close the launcher', self.quit, True)])
        # The game plays in its own window: the launcher steps aside to the taskbar (where it shows
        # this dialog) and comes back when the game exits.
        self.stepped_aside = True
        self.minimize()

    def come_back(self):
        """The launcher returns to the front after the game."""
        root = self.root
        try:
            root.deiconify()
            root.lift()
            root.attributes('-topmost', True)
            root.after(300, lambda: root.attributes('-topmost', False))
            root.focus_force()
        except self.tk.TclError:
            pass

    def stop_game(self):
        if self.job:
            self.job.terminate()

    def game_exited(self, code):
        self.process = None
        if self.job:
            self.job.close()
            self.job = None
        # The in-game menu may have changed gravityrush.ini: later saves start from the file.
        self.ini, self.ini_lines = self.logic.load_ini()
        self.close_modal()
        self.refresh_status()
        if getattr(self, 'stepped_aside', False):
            self.stepped_aside = False
            self.come_back()
        # Closing the window ends the game with code 0; anything else, or a game that never got
        # going, shows its last messages.
        if code != 0 or not getattr(self, 'reached_game', False):
            tail = ''.join(line for line in self.log_lines[-200:] if line.strip())
            last = [line.rstrip() for line in tail.splitlines() if line.strip()][-6:]
            title = t('The game closed unexpectedly') if getattr(self, 'reached_game', False) else \
                t('The game closed right away')
            self.modal(title, t('Exit code {}. Its last messages:').format(code) + '\n\n' + '\n'.join(last)[-700:],
                       [('Close', self.close_modal, False),
                        ('Open the log', lambda: (self.close_modal(), self.open_page('log')), True)])
            return
        self.toast(t('The game exited.'))


def run(logic, tk, filedialog):
    """Opens the launcher window (Tk is created here)."""
    try:  # its own taskbar button and icon, not Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('LucaPazienza.GravityRush.Launcher')
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    try:
        icon = ImageTk.PhotoImage(Image.open(HERE / 'gravityrush.png'))
        root.iconphoto(True, icon)
        root._launcher_icon = icon
    except (OSError, tk.TclError):
        pass
    LauncherWindow(root, tk, filedialog, logic)
    root.mainloop()
