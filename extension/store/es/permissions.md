# Justificación de permisos

| Permiso | Justificación |
| --- | --- |
| `tabCapture` | Capturar el audio y el video de la pestaña que el usuario elige grabar. |
| `offscreen` | Mantener la grabación y guardar sus fragmentos aunque el usuario cierre el panel lateral. |
| `storage` | Conservar los ajustes de grabación e idioma, el estado de la captura y la credencial de conexión con Sauri en este navegador, sin sincronizarla con una cuenta de Google. |
| `tabs` | Leer la URL y el título de la pestaña elegida, detectar su cierre para finalizar la grabación y localizar una revisión ya abierta para no duplicarla. No se recopila un historial de navegación. |
| `scripting` | Mostrar la barra de controles y los avisos de grabación en la pestaña grabada cuando la página lo permite. |
| `activeTab` | Obtener acceso temporal a la pestaña tras pulsar el icono de Sauri, para capturarla e insertar sus controles sin pedir acceso permanente a todos los sitios. |
| `alarms` | Reintentar automáticamente las subidas pendientes y recuperar el estado de procesamiento si se interrumpe la app o el navegador. |
| `sidePanel` | Mostrar los controles de grabación, los ajustes y la lista de grabaciones sin abandonar la pestaña. |

## Accesos de host

| Acceso | Justificación |
| --- | --- |
| `https://meet.google.com/*` | Mostrar el aviso de grabación y los controles en la reunión de Google Meet. El script permanente se limita a este sitio. |
| `http://localhost:41750/*` | Detectar y conectar la app Sauri del mismo Mac (su puerto propio), enviarle grabaciones pendientes y consultar su lista y resultados. No envía grabaciones a un servidor externo. |
| `http://localhost:8000/*` | El mismo uso con versiones anteriores de la app, que escuchan en este puerto, mientras dura la transición. La extensión solo habla con un programa que se identifica como Sauri. |

### Actualización desde 0.9.1 (sin aviso de permisos nuevos)
Chrome desactiva una extensión actualizada hasta que el usuario acepta los permisos nuevos que generan aviso ([Permission warnings](https://developer.chrome.com/docs/extensions/develop/concepts/permission-warnings)). Para los accesos de host, Chrome compara solo los nombres de host, sin puerto ni ruta: `IsHostPrivilegeIncrease` usa `GetDistinctHosts`, que guarda `pattern.host()` (código de Chromium: `chrome/common/extensions/permissions/chrome_permission_message_provider.cc` y `extensions/common/permissions/permission_message_util.cc`). Añadir `http://localhost:41750/*` mantiene el host `localhost`, que ya estaba concedido, así que no hay escalada. `http://localhost/*` también conservaría el host, pero cubre todos los puertos ([Match patterns](https://developer.chrome.com/docs/extensions/develop/concepts/match-patterns): «Matches any localhost port»), así que se eligen los dos puertos explícitos, que es lo más acotado. Comprobación pendiente antes de publicar: actualizar un paquete 0.9.1 instalado con el 0.9.2 (Extension Update Testing Tool o paquete `.crx` firmado con la misma clave) y confirmar que no aparece el diálogo.

## Datos y privacidad
La extensión trata el audio y el video elegidos por el usuario, el micrófono si está habilitado, el título y enlace de la pestaña grabada, los ajustes y una credencial local. Los fragmentos y la cola permanecen en el navegador hasta completar el envío; los fragmentos se borran tras confirmar la subida. Las grabaciones y resultados recibidos quedan en la app local. La credencial se guarda solo en este perfil y se restringe a contextos de confianza de la extensión, nunca a páginas ni scripts de contenido. No se vende información ni se utiliza para publicidad, crédito o fines ajenos a grabar y revisar reuniones. No hay analítica en la extensión.

La política pública debe explicar estos datos, su retención y eliminación en Sauri. Su URL y contacto dependen del dueño; no se inventan aquí. El permiso `notifications` se retiró: la interfaz informa del estado sin notificaciones del sistema.
