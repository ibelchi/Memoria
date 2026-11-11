# Memòria

**Versió 1.0.1 · Catàleg local de vídeos per a Windows**

Memòria ajuda a retrobar moments enregistrats en vídeo, descriure’ls i seleccionar material per a muntatges. Consulta carpetes de diferents discos des d’una sola graella, amb descripcions, etiquetes, favorits i col·leccions.

Funciona a l’ordinador, amb una interfície en català. El repositori distribueix el programa i exemples ficticis: no inclou vídeos, fotografies familiars, captures de pantalla, miniatures ni catàlegs personals.

## Començar

Necessites Windows, Python 3.10 o posterior i FFmpeg/ffprobe per explorar vídeos reals.

1. Descarrega el repositori i extreu-lo en una carpeta local.
2. Instal·la Python amb accés a l’ordre `python`.
3. Situa `ffmpeg.exe` i `ffprobe.exe` a `tools/`, o afegeix-los al PATH. Consulta les [instruccions de FFmpeg](tools/README.md).
4. Des de l'Explorador de fitxers, fes doble clic a **Inicia-Memoria.cmd**. S'inicia el servei local i s'obre **http://127.0.0.1:8765/**. Deixa oberta la finestra del servei; no cal executar-lo com a administrador. Per aturar-lo, ves a **Configuració → Tanca l'aplicació**.
5. Prem **+**, selecciona una carpeta i tria el propietari abans de confirmar la incorporació.

Ordre equivalent, des de la carpeta del projecte:

```powershell
python app.py
```

Per consultar la demostració fictícia, sense vídeos reals ni necessitat de FFmpeg:

```powershell
python app.py --demo --port 8766
```

Tancar la pestanya no atura el servei. Utilitza **Configuració → Tanca l’aplicació**: crea una còpia del catàleg i tanca el procés. Després de reiniciar l’ordinador has de tornar a executar el llançador.

No obris `web/index.html` directament ni publiquis aquesta aplicació amb GitHub Pages: necessita el servei Python local i accés als fitxers del teu ordinador.

## Possibilitats

- Consulta de vídeos repetits per SHA-256 completa, agrupats amb rutes i anotacions independents.
- Cerca per descripcions i etiquetes, tolerant accents i majúscules.
- Carpetes i subcarpetes; filtre per propietari, dates, tipus Original/Muntatge, etiqueta, estat de catalogació i favorits.
- Desament automàtic i catalogació progressiva: pendent si falta descripció o etiqueta; excepció conscient per a vídeos sense anotacions.
- Col·leccions per preparar muntatges, sense copiar ni moure vídeos.
- Miniatures, metadades i reproducció al navegador dels formats compatibles. Si un HEVC no s'hi reprodueix, l'opció **Reprodueix en mode compatible** genera una còpia H.264/AAC a la memòria cau local i reprodueix aquesta còpia; l'original es conserva intacte. Les còpies reutilitzables tenen un límit de memòria cau de 3 GB.
- Identitat per contingut i recuperació explícita de vídeos o carpetes moguts.
- Correcció de data i hora només al catàleg, individual o per desplaçament en minuts de diversos vídeos.
- Exclusió reversible de vídeos o carpetes senceres, incloent vídeos futurs de les subcarpetes.
- Enviament explícit a la paperera de Windows, amb confirmació, comprovació del contingut i conservació d’anotacions.
- Activitat recent agrupada per carpetes, amb rutes completes i desplegable dels vídeos incorporats o modificats.
- Còpies SQLite, exportació JSON i canvi de carpeta del catàleg des de Configuració.
- Paginació superior i inferior, amb 25, 50, 100 o tots els vídeos per pàgina.

La [guia d’ús completa](docs/GUIA-US.md) explica els circuits pas a pas. També pots obrir **[Guia-Memoria.html](Guia-Memoria.html)** amb doble clic i imprimir-la o desar-la en PDF des del navegador.

**Catalogat** vol dir que el vídeo té una descripció no buida **o** almenys una etiqueta. Si no en té cap, és pendent; es pot marcar explícitament com a «Sense anotacions per decisió».

## Dades i privacitat

Els vídeos romanen a les carpetes originals. Explorar i anotar no els modifica. L’única operació que retira un original és **Envia a la paperera**, demanada i confirmada expressament.

La carpeta del catàleg conté:

| Element | Contingut |
| --- | --- |
| `catalog.sqlite3` | Metadades, anotacions, etiquetes, propietaris, col·leccions, correccions, exclusions i activitat |
| `thumbnails/` | Miniatures regenerables |
| `preview-cache/` o directori temporal | Còpies regenerables H.264/AAC per reproduir HEVC; fora de les carpetes escanejades i amb límit de 3 GB |
| `backups/` | Còpies consistents de SQLite; es conserven les deu més recents |
| `app.log` | Registre local de funcionament |

La ubicació inicial és `runtime-personal/`, al costat del programa. `runtime-settings.json` recorda la ubicació escollida a Configuració. La demostració utilitza dades i configuració separades.

**Les còpies del catàleg no inclouen els vídeos originals.** Fes còpies independents de les gravacions i guarda les còpies importants en un altre suport. L’exportació JSON no inclou l’historial d’activitat.

El servei escolta només a `127.0.0.1`. No hi ha núvol, IA externa, fonts remotes ni telemetria. Els enllaços al web de l’autor i al canal d’inspiració només s’obren si els prems. No exposis el servidor a internet o a la xarxa local.

## Dues persones al mateix ordinador

Aquesta versió té tres propietaris predefinits: **Belchi**, **Núria** i **Altres**, amb assignació obligatòria en incorporar carpetes. Són filtres de consulta, no comptes privats ni permisos.

Des de dos comptes Windows, utilitzeu una mateixa instal·lació, un mateix fitxer de configuració i una carpeta de dades accessible a tots dos. Cal verificar els permisos reals de cada compte. Eviteu editar simultàniament el mateix catàleg: encara no hi ha resolució de conflictes entre sessions.

## Configuració, trasllat i recuperació

**Trasllada aquest catàleg** fa una còpia consistent en una carpeta buida, comprova les dades i canvia la ubicació recordada, conservant l’origen. No mou les gravacions. **Obre un altre catàleg** no fusiona dades; **Crea un catàleg buit** crea una identitat independent.

Per restaurar una còpia, atura el servei i tria una carpeta nova:

```powershell
python app.py --data-dir "D:\CatalegRecuperat" --restore "D:\Copies\catalog.sqlite3"
python app.py --data-dir "D:\CatalegRecuperat"
```

Per importar JSON en una base buida:

```powershell
python app.py --data-dir "D:\CatalegImportat" --import-json "D:\Copies\anotacions.json"
```

L’esquema SQLite i l’exportació JSON tenen versió 4, amb extensions compatibles de la versió 1.0 de l’aplicació. S’admeten còpies i exportacions anteriors de les versions 1–4; les migracions fan còpia prèvia.

## Límits coneguts

- No hi ha exploració contínua ni programada: actualitza les carpetes després d’afegir-hi fitxers.
- No hi ha pausa/repreniment de l’exploració, còpia periòdica durant una sessió oberta ni restauració gràfica.
- El navegador no reprodueix tots els formats antics. Utilitza la carpeta i el reproductor del sistema.
- El mode compatible requereix FFmpeg amb suport per a H.264/AAC. Les proves automatitzades utilitzen conversió simulada; cal completar la comprovació d'instal·lació i reproducció al Windows habitual.
- Windows pot limitar l’activació de finestres externes; l’aplicació intenta restaurar-les i mostrar-les al davant, sense canviar la política del sistema.
- L’obertura externa no funciona des de processos amb escriptori restringit: inicia des de Windows amb el llançador.
- La instal·lació compartida necessita permisos comprovats i no ofereix edició simultània amb resolució de conflictes.
- El rendiment amb desenes de milers de vídeos no s’ha validat.

## Desenvolupament

No cal instal·lar paquets Python ni un framework web. Node només s’utilitza per comprovar sintaxi JavaScript durant el desenvolupament.

```powershell
python -m unittest discover -s tests -v
Get-Content -Raw -Encoding UTF8 web/app.js | node --check
```

La neteja de la memòria cau s'activa quan se'n genera una còpia: elimina primer les còpies H.264 menys utilitzades recentment fins a quedar dins dels 3 GB. Una còpia que s'està reproduint queda protegida. Els fitxers parcials de conversió no es consideren còpies acabades. Si una còpia individual supera el límit, es descarta.

### Nota per a un article futur

L'HEVC fallava al navegador, tot i que la pàgina afirmava admetre aquest còdec. El codi assignava l'URL `/stream` de l'original directament al reproductor; en observar que no hi havia una ruta alternativa ni conversió, vam confirmar que encara se servia l'HEVC original. La solució comprovada al codi és convertir-lo amb FFmpeg a H.264/AAC, desar i reutilitzar una còpia identificada per mida i data de modificació, i servir-la pel flux `preview-stream`; l'original no es modifica. La verificació automatitzada és sintètica; la validació final del navegador Windows queda pendent.

Consulta [arquitectura](docs/ARQUITECTURA.md), [contribució](CONTRIBUTING.md), [seguretat](SECURITY.md) i [canvis](CHANGELOG.md). Les proves utilitzen directoris temporals, dades fictícies i simulacions; no eliminen gravacions personals.

## Autoria i llicència

Creat per [Israel Belchi](https://ibelchi.github.io). Inspirat per la feina de [Van Neistat](https://www.youtube.com/@vanneistat).

El codi original es publica amb [llicència MIT](LICENSE). La fotografia opcional d’instal·lació local no es distribueix. Per als recursos i programes externs, consulta [THIRD_PARTY.md](THIRD_PARTY.md).

## Evolució possible

L'assistència amb IA i el reconeixement de persones **no formen part de la versió 1.0.0**. Consulta la [proposta per a una versió futura](docs/FUTUR-IA.md).
