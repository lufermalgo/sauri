import type { Reunion, Transcripcion, TurnoDeHabla } from "@sauri/shared-types";

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_KEY = "sauri_token";

function getAuthHeaders(): HeadersInit {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    throw new Error("No autenticado: token no encontrado");
  }
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new Error(`Error ${response.status}: ${body}`);
  }
  return response.json() as Promise<T>;
}

export async function registrarReunion(enlaceMeet: string): Promise<Reunion> {
  const response = await fetch(`${BASE_URL}/api/v1/reuniones`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ enlace_meet: enlaceMeet }),
  });
  return handleResponse<Reunion>(response);
}

export async function listarReuniones(): Promise<Reunion[]> {
  const response = await fetch(`${BASE_URL}/api/v1/reuniones`, {
    method: "GET",
    headers: getAuthHeaders(),
  });
  return handleResponse<Reunion[]>(response);
}

export async function obtenerTranscripcion(
  reunionId: string
): Promise<Transcripcion & { turnos: TurnoDeHabla[] }> {
  const response = await fetch(
    `${BASE_URL}/api/v1/reuniones/${reunionId}/transcripcion`,
    {
      method: "GET",
      headers: getAuthHeaders(),
    }
  );
  return handleResponse<Transcripcion & { turnos: TurnoDeHabla[] }>(response);
}
