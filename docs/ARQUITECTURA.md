# Arquitectura — Memòria 1.0

## Execució

Python 3.10+, biblioteca estàndard, HTTP local amb ThreadingHTTPServer i SQLite. HTML/CSS/JavaScript sense framework. FFmpeg/ffprobe són processos externs per a metadades i miniatures.

No hi ha dependències Python per instal·lar. El desplegament previst és una sessió d’escriptori Windows, no un servidor web públic.

## Mòduls

| Fitxer | Responsabilitat |
| --- | --- |
| app.py | Arrencada, configuració de dades, recuperació CLI, servei i tancament |
| catalog/core.py | SQLite, consulta, exploració, anotacions, metadades, còpies i exportació |
| catalog/identity.py | Empremtes parcial/completa, substitucions, revinculació i recuperació |
| catalog/groups.py | Col·leccions i pertinences |
| catalog/workflow.py | Propietaris i catalogació progressiva |
| catalog/curation.py | Tipus, correccions de data i exclusions de carpeta |
| catalog/removal.py | Confirmacions d’exclusió i paperera |
| catalog/recycle.py | IFileOperation de Windows amb reciclatge, sense alternativa permanent |
| catalog/activity.py | Activitat transaccional i resum d’exploracions per carpeta |
| catalog/desktop.py | Validació d’accés a l’escriptori i obertures externes |
| catalog/foreground.py | Identificació, restauració i activació de finestres |
| catalog/storage.py | Selecció, transferència i canvi de la carpeta de dades |
| catalog/server.py | Rutes HTTP, validació de peticions i streaming amb Range |
| web/ | Interfície local i recursos de marca |
| tests/ | Proves amb dades temporals i simulacions |

## Persistència

SQLite conserva arrels i vídeos identificats amb UUID, anotacions, etiquetes, propietaris, col·leccions, regles d’exclusió i activitat. L’esquema base i JSON són versió 4; els camps additius de la versió 1.0 es creen amb còpia prèvia quan falta l’extensió.

Una correcció de data no substitueix la data detectada a la taula de vídeos: la capa de consulta aplica l’override per ordenar i filtrar. Les exclusions de carpeta s’avaluen també per a vídeos incorporats posteriorment.

L’activitat utilitza triggers per a canvis puntuals i snapshots abans/després de l’exploració per agrupar incorporacions i actualitzacions de carpeta. El detall anterior a aquesta funció no es reconstrueix de manera especulativa. SQLite conserva l’historial; JSON no l’exporta.

## Seguretat de fitxers

Les rutes de reproducció i accions externes parteixen d’un identificador del catàleg i es validen dins de l’arrel autoritzada. No hi ha una API genèrica per executar ordres o servir qualsevol fitxer.

L’exploració evita symlinks i reparse points de subcarpetes. Una substitució de contingut no hereta automàticament anotacions. Les recuperacions ambigües requereixen elecció explícita.

L’enviament a la paperera fa preview, token d’un sol ús amb caducitat, comprovació de ruta/contingut/estat, bloqueig d’exploració i còpia del catàleg. Conserva anotacions i marca l’entrada exclosa. Si falla i el fitxer continua present, restaura el seu estat d’exclusió anterior.

## Ubicació de dades

El fitxer de configuració recorda la carpeta activa. Un trasllat fa backup SQLite consistent i copia miniatures i còpies abans de validar i canviar el pointer de manera atòmica. L’origen es conserva. No es mouen gravacions.

Els esborranys pendents i la mida de pàgina es desen al navegador per identificador de catàleg. No hi ha resolució de conflictes entre sessions.

## Verificació

La CI utilitza Windows i Python 3.10, sense gravacions personals. Les proves simulen les accions de paperera i finestres; això no substitueix la validació de la interfície amb Windows.

La suite cobreix cerca, migracions, exportació/importació, identitat, col·leccions, propietaris, dates, exclusions, activitat, HTTP i les condicions de fallada de les operacions importants.
