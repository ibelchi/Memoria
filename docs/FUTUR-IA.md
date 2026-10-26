# Proposta d'assistència amb IA

**Estat: proposta per a una versió futura. Memòria 1.0.0 no incorpora IA ni reconeixement facial.** No s'han instal·lat models ni enviat vídeos a cap servei.

## Objectiu i límits

Preparar un índex una sola vegada a partir de fotogrames és una bona manera de buscar en un arxiu gran. Redueix el treball de cada consulta i permet fer el processament localment. La mida de l'índex no mesura la seva qualitat: les descripcions són una aproximació amb informació perduda.

Mostrejar només l'inici, el final i cada trenta segons pot funcionar amb plans curts, però omet accions i persones que apareixen entre les mostres. Una descripció visual tampoc identifica els familiars pel nom ni explica tot el que es diu. Les estimacions de cost i temps d'un altre arxiu no són transferibles sense mesurar el maquinari, la durada, la resolució i el model.

## Implementació proposada

1. Pilot amb 30–50 vídeos variats: curts, llargs, antics, foscos, amb moviment i amb so. Mesurar temps, espai, falsos positius i moments que no es troben.
2. Extracció local amb FFmpeg: mostreig temporal combinat amb canvis d'escena i descart de fotogrames redundants. Els intervals s'ajusten al pilot; cap mostreig es garanteix exhaustiu. Conservar el segon exacte i la identitat del vídeo, sense crear còpies completes de reproducció.
3. Model visual local que produeixi descripcions i etiquetes proposades. Fixar-ne versió i llicència, i verificar el funcionament en català i al maquinari real. Afegir transcripció local opcional quan la parla sigui útil; no confondre paraules pronunciades amb identitats visibles.
4. Taules separades per a resultats automàtics: vídeo, segon, contingut proposat, model/versió, estat de revisió i errors. No sobreescriure descripcions, etiquetes ni correccions manuals. Una proposta no marca un vídeo com a catalogat; cal acceptar-la o revisar-la.
5. Cua de treball amb pausa, cancel·lació i represa; processar només continguts nous o modificats, reutilitzant la identitat existent. Límit de memòria cau i còmput; excloure de la publicació fotogrames, models i resultats personals. Fer còpia de les dades confirmades i permetre regenerar l'índex.
6. Inicialment cercar també dins dels suggeriments, indicant-ne l'origen i el moment del vídeo. Per créixer, valorar SQLite FTS5. Més endavant, provar cerca semàntica multilingüe amb vectors per trobar conceptes encara que la consulta utilitzi paraules diferents.

## Persones

El propietari representa la procedència o agrupació del vídeo, no qui hi surt. Un vídeo d'Altres pot mostrar qualsevol membre de la família.

Ara ja es poden afegir noms com a etiquetes i fer-ho a diversos vídeos alhora. Com a convenció, es pot utilitzar `persona:Nom`. Encara són etiquetes de text; no hi ha una categoria de persones implementada.

Una versió posterior pot incorporar persones amb identificador estable, nom editable i relació amb múltiples vídeos i moments. El reconeixement assistit hauria de detectar cares en diversos fotogrames, agrupar semblances i deixar que l'usuari assigni els noms i confirmi propostes. Ha de permetre separar grups incorrectes, unir duplicats, rebutjar coincidències i deixar cares sense identificar. No ha d'endevinar identitats a partir d'un descriptor visual general.

S'ha de provar especialment amb infants de diferents edats, perfils, cares petites, desenfocament i familiars semblants. L'absència d'una coincidència no prova que una persona no surti al vídeo. Els descriptors facials i els retalls són dades personals locals i no han d'entrar al repositori.

## Referències tècniques

- [Moondream: inferència local i requisits](https://docs.moondream.ai/running-locally/). Comprovar compatibilitat abans de triar motor; no totes les GPU admeten el motor recomanat.
- [Moondream 2: fitxa oficial del model](https://huggingface.co/vikhyatk/moondream2).
- [PySceneDetect: detectors d'escenes](https://www.scenedetect.com/docs/latest/api/detectors.html).
- [SQLite FTS5](https://www.sqlite.org/fts5.html).
- [Immich: agrupació i gestió de cares](https://docs.immich.app/features/facial-recognition/) i [limitació del mostreig de vídeos](https://docs.immich.app/FAQ/): la miniatura sola no cobreix totes les cares del vídeo.

La selecció d'eines és una decisió posterior al pilot. Aquesta proposta no compromet a instal·lar un producte concret ni garanteix reconeixement exhaustiu.
