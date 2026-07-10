// URL de la Vista_De_Detalle — Req. 6.2
const PARAM_REUNION_ID = "reunionId";

/** Construye la URL relativa de detail.html con el reunion_id como query param (Req. 6.2) */
export function construirUrlDetalle(reunionId: string): string {
  const params = new URLSearchParams({ [PARAM_REUNION_ID]: reunionId });
  return `detail.html?${params.toString()}`;
}

/** Lee el reunion_id de una URL de detail.html; null si ausente (Req. 6.2, 6.5) */
export function leerReunionId(url: string): string | null {
  try {
    const parsed = new URL(url, "http://localhost/");
    return parsed.searchParams.get(PARAM_REUNION_ID);
  } catch {
    return null;
  }
}
