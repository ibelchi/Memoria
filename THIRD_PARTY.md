# Recursos i dependències externes

## Crèdit de Van Neistat

El repositori no distribueix cap fotografia. La finestra d'informació mostra per defecte un símbol de cinema original (`web/van.svg`), inclòs en la llicència MIT del projecte.

Es pot afegir opcionalment `web/van.png` en una instal·lació local amb una imatge de la qual es tinguin els drets necessaris. Aquest fitxer està exclòs de Git i no forma part de la distribució ni de la llicència MIT del codi. Si no hi és, el servidor retorna el símbol neutre.

Crèdit d'inspiració: [Van Neistat](https://www.youtube.com/@vanneistat).

## FFmpeg i ffprobe

No es distribueixen binaris al repositori. El programa els executa com a processos locals per llegir metadades i generar miniatures. No inclou conversions de vídeos.

Descarrega’ls des dels enllaços del [web oficial](https://ffmpeg.org/download.html) i revisa la llicència de la compilació que utilitzis: [informació legal](https://ffmpeg.org/legal.html).

## Windows i Python

Les integracions de finestres i paperera utilitzen API del sistema de Windows. Python és una dependència externa; el projecte no redistribueix l’intèrpret ni les biblioteques del sistema.
