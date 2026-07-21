// Cliente_De_API compartido (Side_Panel + Vista_De_Detalle) — Req. 13.1, 13.3,
// 13.4, 13.5, 14.1, 14.4, 14.5
import type { NotaDTO, TranscripcionDTO, DiarizacionDTO } from "../types";

export const BACKEND_URL_DEFECTO = "http://localhost:8000";
const TIMEOUT_MS = 10_000;
const CLAVE_SESION = "authToken";

export class ErrorSesionInvalida extends Error {
  constructor() {
    super("Sesión inválida o expirada");
    this.name = "ErrorSesionInvalida";
  }
}

export class ErrorTransporteNoSeguro extends Error {
  constructor(url: string) {
    super(`El backend debe usarse por HTTPS (o http://localhost en desarrollo): ${url}`);
    this.name = "ErrorTransporteNoSeguro";
  }
}

/** Recurso ausente (404) — distinto de un fallo real, para derivar Estado_De_Vista "vacio" (Req. 7.6, 8.8, 10.5) */
export class ErrorNoEncontrado extends Error {
  constructor() {
    super("Recurso no encontrado");
    this.name = "ErrorNoEncontrado";
  }
}

/** Exige https:// salvo en http://localhost (desarrollo) — Req. 13.5 */
function validarTransporte(backendUrl: string): void {
  const url = new URL(backendUrl);
  const esLocalhost = url.hostname === "localhost" || url.hostname === "127.0.0.1";
  if (url.protocol === "https:") return;
  if (url.protocol === "http:" && esLocalhost) return;
  throw new ErrorTransporteNoSeguro(backendUrl);
}

async function leerSesion(): Promise<string | undefined> {
  const result = await chrome.storage.sync.get(CLAVE_SESION);
  return result[CLAVE_SESION] as string | undefined;
}

async function descartarSesion(): Promise<void> {
  await chrome.storage.sync.remove(CLAVE_SESION);
}

/** Almacena la Sesion_De_Usuario en chrome.storage (Req. 13.3) */
export async function almacenarSesion(token: string): Promise<void> {
  await chrome.storage.sync.set({ [CLAVE_SESION]: token });
}

async function solicitar<T>(backendUrl: string, ruta: string, init?: RequestInit): Promise<T> {
  validarTransporte(backendUrl);

  const sesion = await leerSesion();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (sesion) {
    headers["Authorization"] = `Bearer ${sesion}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const response = await fetch(`${backendUrl}${ruta}`, {
      ...init,
      headers,
      signal: controller.signal,
    });

    if (response.status === 401) {
      await descartarSesion();
      throw new ErrorSesionInvalida();
    }

    if (response.status === 404) {
      throw new ErrorNoEncontrado();
    }

    if (!response.ok) {
      throw new Error(`Solicitud fallida: ${response.status}`);
    }

    return (await response.json()) as T;
  } finally {
    clearTimeout(timeoutId);
  }
}

/** GET /api/v1/reuniones/ — historial de Notas (Req. 4.1) */
export async function listarReuniones(backendUrl: string = BACKEND_URL_DEFECTO): Promise<NotaDTO[]> {
  const crudo = await solicitar<
    Array<{
      reunion_id: string;
      titulo: string | null;
      estado_proceso: string;
      creada_en: string | null;
    }>
  >(backendUrl, "/api/v1/reuniones/");

  return crudo.map((r) => ({
    reunionId: r.reunion_id,
    titulo: r.titulo ?? null,
    estadoProceso: r.estado_proceso,
    creadaEn: r.creada_en,
  }));
}

/** GET /api/v1/reuniones/{id} — estado de procesamiento (Vista_De_Detalle → polling mientras transcribe) */
export async function obtenerReunion(
  reunionId: string,
  backendUrl: string = BACKEND_URL_DEFECTO
): Promise<{ reunionId: string; estadoProceso: string }> {
  const crudo = await solicitar<{ reunion_id: string; estado_proceso: string }>(
    backendUrl,
    `/api/v1/reuniones/${reunionId}`
  );
  return { reunionId: crudo.reunion_id, estadoProceso: crudo.estado_proceso };
}

/** GET /api/v1/reuniones/{id}/transcripcion (Req. 6.3) */
export async function obtenerTranscripcion(
  reunionId: string,
  backendUrl: string = BACKEND_URL_DEFECTO
): Promise<TranscripcionDTO> {
  const crudo = await solicitar<{
    transcripcion_id: string;
    reunion_id: string;
    segmentos: Array<{ id: string; texto: string; inicio_ms: number; fin_ms: number; orden: number }>;
  }>(backendUrl, `/api/v1/reuniones/${reunionId}/transcripcion`);

  return {
    transcripcionId: crudo.transcripcion_id,
    reunionId: crudo.reunion_id,
    segmentos: crudo.segmentos.map((s) => ({
      id: s.id,
      texto: s.texto,
      inicioMs: s.inicio_ms,
      finMs: s.fin_ms,
      orden: s.orden,
    })),
  };
}

/** GET /api/v1/reuniones/{id}/diarizacion (Req. 6.3, endpoint nuevo) */
export async function obtenerDiarizacion(
  reunionId: string,
  backendUrl: string = BACKEND_URL_DEFECTO
): Promise<DiarizacionDTO> {
  const crudo = await solicitar<{
    diarizacion_id: string;
    reunion_id: string;
    estado_diarizacion: string;
    num_hablantes: number;
    hablantes: Array<{ id: string; etiqueta: string; orden: number }>;
    asignaciones: Array<{ turno_id: string; hablante_id: string }>;
  }>(backendUrl, `/api/v1/reuniones/${reunionId}/diarizacion`);

  return {
    diarizacionId: crudo.diarizacion_id,
    reunionId: crudo.reunion_id,
    estadoDiarizacion: crudo.estado_diarizacion,
    numHablantes: crudo.num_hablantes,
    hablantes: crudo.hablantes,
    asignaciones: crudo.asignaciones.map((a) => ({
      turnoId: a.turno_id,
      hablanteId: a.hablante_id,
    })),
  };
}

/** PATCH /api/v1/reuniones/{id} — renombra una nota (Mis_Notas → renombrar) */
export async function renombrarReunion(
  reunionId: string,
  nuevoTitulo: string,
  backendUrl: string = BACKEND_URL_DEFECTO
): Promise<void> {
  await solicitar<{ reunion_id: string; titulo: string }>(
    backendUrl,
    `/api/v1/reuniones/${reunionId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ titulo: nuevoTitulo }),
    }
  );
}

/** DELETE /api/v1/reuniones/{id} — elimina una nota (Mis_Notas → eliminar) */
export async function eliminarReunion(
  reunionId: string,
  backendUrl: string = BACKEND_URL_DEFECTO
): Promise<void> {
  validarTransporte(backendUrl);

  const sesion = await leerSesion();
  const headers: Record<string, string> = {};
  if (sesion) {
    headers["Authorization"] = `Bearer ${sesion}`;
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    // Respuesta 204 sin cuerpo — no reutiliza solicitar<T>() porque esa
    // función siempre intenta parsear JSON de la respuesta.
    const response = await fetch(`${backendUrl}/api/v1/reuniones/${reunionId}`, {
      method: "DELETE",
      headers,
      signal: controller.signal,
    });

    if (response.status === 401) {
      await descartarSesion();
      throw new ErrorSesionInvalida();
    }
    if (response.status === 404) {
      throw new ErrorNoEncontrado();
    }
    if (!response.ok) {
      throw new Error(`Solicitud fallida: ${response.status}`);
    }
  } finally {
    clearTimeout(timeoutId);
  }
}

/** POST /api/v1/auth/login (Req. 13.2, 13.3) */
export async function login(
  email: string,
  password: string,
  backendUrl: string = BACKEND_URL_DEFECTO
): Promise<{ accessToken: string; expiresIn: number }> {
  validarTransporte(backendUrl);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000);
  try {
    const response = await fetch(`${backendUrl}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error("Credenciales inválidas");
    }

    const body = (await response.json()) as { access_token: string; expires_in: number };
    await almacenarSesion(body.access_token);
    return { accessToken: body.access_token, expiresIn: body.expires_in };
  } finally {
    clearTimeout(timeoutId);
  }
}
