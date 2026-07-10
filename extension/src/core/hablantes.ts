// Avatar_De_Hablante — Req. 8.4
import { PALETA_AVATAR } from "./design/tokens";

export { PALETA_AVATAR };

/**
 * Deriva hasta dos caracteres de iniciales a partir de una Etiqueta_De_Hablante.
 * Ej: "Hablante 1" -> "H1"; "" -> "".
 */
export function inicialesDeEtiqueta(etiqueta: string): string {
  if (!etiqueta) return "";
  const partes = etiqueta.trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "";
  if (partes.length === 1) {
    return partes[0].slice(0, 2).toUpperCase();
  }
  const primera = partes[0][0] ?? "";
  const segunda = partes[partes.length - 1][0] ?? "";
  return (primera + segunda).toUpperCase();
}

/**
 * Indexa PALETA_AVATAR de forma determinista y cíclica a partir del `orden`
 * del Hablante (1-indexado). Garantiza el mismo color para el mismo `orden`
 * y reutilización cíclica cuando hay más hablantes que colores.
 */
export function colorDeAvatar(orden: number): string {
  const n = PALETA_AVATAR.length;
  const idx = ((Math.trunc(orden) - 1) % n + n) % n;
  return PALETA_AVATAR[idx];
}
