# Memòria

**Versió 1.0.0 · Catàleg local de vídeos per a Windows**

Memòria ajuda a retrobar moments enregistrats en vídeo, descriure’ls i seleccionar material per a muntatges. Consulta carpetes de diferents discos des d’una sola graella, amb descripcions, etiquetes, favorits i col·leccions.

Funciona a l’ordinador, amb una interfície en català. El repositori distribueix el programa i exemples ficticis: no inclou vídeos, fotografies familiars, captures de pantalla, miniatures ni catàlegs personals.

## Començar

Necessites Windows, Python 3.10 o posterior i FFmpeg/ffprobe per explorar vídeos reals.

1. Descarrega el repositori i extreu-lo en una carpeta local.
2. Instal·la Python amb accés a l’ordre `python`.
3. Situa `ffmpeg.exe` i `ffprobe.exe` a `tools/`, o afegeix-los al PATH. Consulta les [instruccions de FFmpeg](tools/README.md).
4. Fes doble clic a **Inicia-Memoria.cmd** des de Windows. Deixa oberta la finestra del servei. No cal executar-lo com a administrador.
5. S’obrirà **http://127.0.0.1:8765/**. Prem **+**, selecciona una carpeta i tria el propietari abans de confirmar la incorporació.

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

- Cerca per descripcions i etiquetes, tolerant accents i majúscules.
- Carpetes i subcarpetes; filtre per propietari, dates, tipus Original/Muntatge, etiqueta, estat de catalogació i favorits.
- Desament automàtic i catalogació progressiva: pendent si falta descripció o etiqueta; excepció conscient per a vídeos sense anotacions.
- Col·leccions per preparar muntatges, sense copiar ni moure vídeos.
- Miniatures, metadades i reproducció directa dels formats compatibles. Els formats antics s’obren des de la seva carpeta amb el programari de Windows. **No es generen conversions ni còpies completes dels vídeos.**
- Identitat per contingut i recuperació explícita de vídeos o carpetes moguts.
- Correcció de data i hora només al catàleg, individual o per desplaçament en minuts de diversos vídeos.
- Exclusió reversible de vídeos o carpetes senceres, incloent vídeos futurs de les subcarpetes.
- Enviament explícit a la paperera de Windows, amb confirmació, comprovació del contingut i conservació d’anotacions.
- Activitat recent agrupada per carpetes, amb rutes completes i desplegable dels vídeos incorporats o modificats.
- Còpies SQLite, exportació JSON i canvi de carpeta del catàleg des de Configuració.
- Paginació superior i inferior, amb 25, 50, 100 o tots els vídeos per pàgina.

La [guia d’ús completa](docs/GUIA-US.md) explica els circuits pas a pas. També pots obrir **[Guia-Memoria.html](Guia-Memoria.html)** amb doble clic i imprimir-la o desar-la en PDF des del navegador.

## Dades i privacitat

Els vídeos romanen a les carpetes originals. Explorar i anotar no els modifica. L’única operació que retira un original és **Envia a la paperera**, demanada i confirmada expressament.

La carpeta del catàleg conté:

| Element | Contingut |
| --- | --- |
| `catalog.sqlite3` | Metadades, anotacions, etiquetes, propietaris, col·leccions, correccions, exclusions i activitat |
| `thumbnails/` | Miniatures regenerables |
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

Consulta [arquitectura](docs/ARQUITECTURA.md), [contribució](CONTRIBUTING.md), [seguretat](SECURITY.md) i [canvis](CHANGELOG.md). Les proves utilitzen directoris temporals, dades fictícies i simulacions; no eliminen gravacions personals.

## Autoria i llicència

Creat per [Israel Belchi](https://ibelchi.github.io). Inspirat per la feina de [Van Neistat](https://www.youtube.com/@vanneistat).

El codi original es publica amb [llicència MIT](LICENSE). El retrat de Van Neistat i els programes externs tenen un tractament independent: consulta [THIRD_PARTY.md](THIRD_PARTY.md).

## Evolució possible

L'assistència amb IA i el reconeixement de persones **no formen part de la versió 1.0.0**. Consulta la [proposta per a una versió futura](docs/FUTUR-IA.md).
