# Resumen con los nombres de los hablantes (#1190)

## Problema
El resumen se genera con etiquetas anónimas («Hablante 2», «Speaker 2» en otros idiomas) y esas etiquetas quedan escritas en el texto guardado. Cuando el usuario asigna un nombre («Pedro Pablo») la transcripción lo muestra, pero el resumen sigue diciendo «Hablante 2».

## Decisión
El texto guardado del resumen **no se modifica**. El nombre se aplica **al leer** el resumen (`GET /api/v1/meetings/{id}/summary`), por lo que sirve a todos los clientes (portal, exportación, extensión) y se actualiza solo cuando el usuario cambia un nombre. Sin llamadas al modelo, sin costo, sin cola.

## Requisitos (EARS)
1. Cuando el usuario haya elegido un nombre para un hablante, la respuesta del resumen sustituirá toda aparición de la etiqueta anónima de ese hablante por el nombre elegido, en `topic`, `conclusion` y en todo el texto de `key_points` (bloques, puntos y cadenas heredadas, en cualquier nivel de anidación).
2. Si el hablante no tiene nombre elegido, o el nombre es vacío, la etiqueta se deja como está.
3. La etiqueta que se busca es «Hablante N» si el idioma de la transcripción es español y «Speaker N» en cualquier otro caso (misma regla que `app/copy/speaker_labels.py`; reutilizar sus funciones, no duplicar la regla). Coincidencia solo de la palabra completa y del número completo: «Hablante 2» no debe tocar «Hablante 20» ni «Hablante 2x»; «Hablante ?» no se toca. Insensible a mayúsculas.
4. N es el `sequence` del `Speaker` de la **última diarización completada** (la misma que usa `summaries.repository.transcript_passages`). El nombre es el `chosen_label` del `SpeakerReviewItem` de esa revisión (misma resolución que usa `meetings/router.py` para la transcripción: `speaker_key == Speaker.id`, mismo `processing_revision`).
5. Si la última diarización completada es **posterior** a la generación del resumen (el resumen se escribió con otra numeración), no se sustituye nada: es preferible dejar «Hablante N» que atribuir mal un nombre. Verificar qué campos de fecha existen y documentar la regla elegida.
6. La sustitución no persiste nada, no cambia `generation`/`updated_at` y no afecta a la solicitud de regeneración ni al texto que ve el modelo.
7. Los nombres se insertan como texto literal (el cliente ya escapa); el backend no interpreta el nombre. Usar sustitución de función (no plantillas de `re.sub` con cadenas de reemplazo) para que `\1`, `\g<0>` o `\` en un nombre no se interpreten.
8. En el portal, al guardar o cambiar el nombre de un hablante, el resumen mostrado se vuelve a pedir y se actualiza sin recargar la página. La exportación del resumen usa los nombres.
9. Textos de interfaz en español y en los demás idiomas existentes si se añade alguno (no debería hacer falta).

## Fuera de alcance
Botón «Actualizar resumen con los nombres» (regenerar con el modelo): queda para después. Cambiar la redacción de plural («Hablantes 1 y 2» → «Ana y Luis» queda correcto por sustitución de cada número; no se reescribe gramática).

## Criterios de aceptación
- Prueba unitaria de la función de sustitución: español/inglés, borde de número, `?`, nombre con `\1`, `$1`, `&`, `<b>`, comillas, mayúsculas; sin nombre → sin cambio; texto anidado.
- Prueba de API: meeting con dos hablantes, uno nombrado → el resumen devuelve el nombre solo para ese; cambiar el nombre y volver a pedir → cambia; resumen más antiguo que la última diarización → sin sustitución.
- Prueba de frontend: tras guardar un nombre el panel del resumen vuelve a pedir y muestra el nombre.
- No hay migraciones.
