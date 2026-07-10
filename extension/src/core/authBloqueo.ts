// Bloqueo de autenticación por intentos fallidos — Req. 13.6
import type { IntentoDeAutenticacion } from "./types";

const MAX_FALLOS_CONSECUTIVOS = 5;
const VENTANA_BLOQUEO_MS = 60_000;

/**
 * Determina si la autenticación está bloqueada: verdadero sii se acumularon
 * al menos 5 fallos consecutivos al final de la secuencia (sin éxito posterior)
 * y han transcurrido menos de 60s desde el quinto fallo (Req. 13.6).
 * `intentos` se asume ordenado ascendentemente por `enMs`.
 */
export function estaBloqueado(intentos: IntentoDeAutenticacion[], ahora: number): boolean {
  let consecutivos = 0;
  for (let i = intentos.length - 1; i >= 0; i--) {
    if (!intentos[i].exito) {
      consecutivos++;
    } else {
      break;
    }
  }

  if (consecutivos < MAX_FALLOS_CONSECUTIVOS) return false;

  const quintoDesdeElFinal = intentos[intentos.length - MAX_FALLOS_CONSECUTIVOS].enMs;
  return ahora - quintoDesdeElFinal < VENTANA_BLOQUEO_MS;
}
