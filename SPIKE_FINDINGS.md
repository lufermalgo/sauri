# SPIKE/PoC Findings: Captura A/V por extensión de Chrome (Tarea 2.2)

## Resumen

Se validó la viabilidad de capturar audio y video de una pestaña de Google Meet usando una extensión Chrome MV3, grabar con MediaRecorder en un documento offscreen, y subir el archivo resultante a un backend FastAPI local.

**Conclusión: el enfoque es viable para el MVP.**

---

## Cómo funciona tabCapture + offscreen recording

1. **`chrome.tabCapture.getMediaStreamId`** se llama desde el service worker (background), pasando el `targetTabId` de la pestaña activa de Meet. Retorna un `streamId` opaco.
2. El service worker crea (o reutiliza) un **documento offscreen** con razón `USER_MEDIA`.
3. El documento offscreen recibe el `streamId` vía messaging y llama a `navigator.mediaDevices.getUserMedia` con constraints especiales `{ chromeMediaSource: 'tab', chromeMediaSourceId: streamId }` para obtener un `MediaStream` con pistas de audio y video de la pestaña.
4. Se crea un **`MediaRecorder`** sobre ese stream con mimeType `video/webm;codecs=vp8,opus` y se graba con `timeslice` de 5 segundos (genera chunks periódicos).
5. Al detener la grabación, los chunks se ensamblan en un único Blob `video/webm`.

---

## Requisito de gesto de usuario para getMediaStreamId

`chrome.tabCapture.getMediaStreamId` **requiere un gesto de usuario** para funcionar. En MV3, el click del usuario en el botón "Grabar" del side panel cuenta como gesto válido. Sin gesto, la API lanza un error.

**Implicación:** no se puede iniciar la grabación de forma programática/automática sin interacción del usuario. Para el flujo de sauri esto es aceptable (el Usuario_Comercial presiona "Grabar").

---

## Requisito de loopback de audio (AudioContext.destination)

Cuando se captura el audio de una pestaña con `tabCapture`, Chrome **silencia el audio de la pestaña para el usuario** por defecto. Para evitar esto, es **obligatorio** crear un `AudioContext`, conectar el stream de audio como source, y enrutarlo a `audioCtx.destination` (los altavoces del sistema).

```typescript
const audioCtx = new AudioContext();
const source = audioCtx.createMediaStreamSource(tabStream);
source.connect(audioCtx.destination);
```

Sin este paso, el usuario dejaría de escuchar la reunión durante la grabación.

---

## Transferencia de datos: limitación base64 entre offscreen y background

El documento offscreen y el service worker se comunican exclusivamente vía `chrome.runtime.sendMessage`. Los mensajes deben ser **serializables a JSON** — no se pueden pasar Blobs, ArrayBuffers ni URLs de blob directamente.

### Enfoque PoC (actual)
- Convertir el Blob a base64 string y enviarlo en el mensaje.
- Funciona para grabaciones cortas (< ~50 MB antes de encoding).
- Base64 incrementa el tamaño ~33%.

### Enfoque producción (Tarea 14)
- Persistir chunks en **IndexedDB** desde el offscreen document (acceso directo).
- El background lee desde IndexedDB para ensamblar y subir.
- Elimina la limitación de tamaño del mensaje y reduce presión de memoria.

---

## Riesgos conocidos

### 1. Tamaño de archivo para video
- Video WebM (vp8) + audio (opus) a resolución de pestaña: ~2-5 MB/minuto dependiendo de la actividad visual.
- Una reunión de 60 minutos: ~120-300 MB.
- **Mitigación en producción:** troceo en IndexedDB + subida por chunks al backend (streaming multipart). Para el PoC, la grabación completa se mantiene en memoria.

### 2. Uso de memoria del navegador durante reuniones largas
- Acumular todos los chunks en un array antes de ensamblar el Blob consume memoria proporcional a la duración.
- **Mitigación en producción:** persistir cada chunk en IndexedDB inmediatamente (`ondataavailable`) y ensamblar solo al momento de la subida, o subir chunks individualmente.

### 3. Service worker efímero (MV3)
- El service worker puede ser descargado por Chrome tras ~30 segundos de inactividad.
- La grabación ocurre en el **offscreen document** (no en el SW), que permanece vivo mientras exista.
- El estado se persiste en `chrome.storage.session`, que sobrevive reinicios del SW.
- **No es un riesgo bloqueante** para la grabación en sí.

### 4. Compatibilidad de codecs
- `video/webm;codecs=vp8,opus` es soportado universalmente en Chrome.
- Se incluye fallback a `video/webm` genérico como precaución.
- VP9 también es una opción viable si se necesita mejor compresión.

### 5. Pérdida de grabación ante cierre inesperado
- Si el usuario cierra la pestaña o el navegador durante la grabación, se pierden los chunks en memoria.
- **Mitigación en producción:** persistencia inmediata en IndexedDB + recuperación por `chrome.alarms` / `onStartup`.

---

## Confirmación de viabilidad

| Aspecto | Estado |
|---------|--------|
| Captura de audio de pestaña | ✅ Viable via tabCapture + offscreen |
| Captura de video de pestaña | ✅ Viable (mismo stream) |
| Audio loopback (usuario sigue escuchando) | ✅ Viable via AudioContext.destination |
| Grabación con MediaRecorder | ✅ Viable (webm/vp8+opus) |
| Transferencia offscreen → background | ✅ Viable (base64 para PoC, IndexedDB para prod) |
| Subida al backend FastAPI | ✅ Viable (multipart/form-data) |
| Gesto de usuario requerido | ✅ Compatible con el flujo (botón "Grabar") |

**El enfoque de captura por extensión de Chrome es viable para el MVP de sauri.** Los riesgos identificados tienen mitigaciones claras que se implementarán en las tareas de producción (Tarea 14).
