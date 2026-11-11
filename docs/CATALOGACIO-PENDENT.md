# Catalogació progressiva

| Estat | Criteri |
| --- | --- |
| Pendent de catalogar | No té descripció ni etiquetes, sense excepció |
| Catalogat | Té una descripció no buida o almenys una etiqueta |
| Sense anotacions per decisió | Vídeo sense descripció ni etiquetes marcat expressament així |

El filtre de pendents inclou els vídeos buits i els que només tenen una anotació que després s'ha retirat. **Deixa sense anotacions**, al detall o per lots, només admet vídeos sense descripció ni etiquetes. No elimina contingut i rebutja tot el lot si algun vídeo ja té anotacions.

**Torna a pendents** retira la decisió. Afegir text o etiquetes també retira l'excepció. Una sola anotació ja marca el vídeo com a Catalogat.

L'antic camp `reviewed` es conserva per compatibilitat i història, però no determina els estats actuals. SQLite esquema 4 i JSON 4 conserven `omit_annotations`. El filtre de catàleg s'ha comprovat amb dades temporals per a vídeos amb només descripció, només etiqueta i sense anotacions.
