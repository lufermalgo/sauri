// Sistema_De_Diseno: tokens de color, tipografía, espaciado, radios, elevaciones
// y paleta de avatares, compartidos por el Side_Panel y la Vista_De_Detalle.
// Requisitos: 12.1, 12.2, 12.4

export const COLOR_TOKENS = {
  fondo: "#0f1115",
  superficie: "#181b21",
  superficieAlterna: "#20242c",
  primario: "#5b8cff",
  texto: "#f2f4f8",
  textoTenue: "#9aa3b2",
  error: "#ff6b6b",
  grabando: "#ff5c5c",
  foco: "#ffd166",
} as const;

/** Alias exportados individualmente para pruebas de contraste (Req. 12.4) */
export const FOCUS_RING_COLOR = COLOR_TOKENS.foco;
export const SURFACE_COLOR = COLOR_TOKENS.superficie;

export const TYPOGRAPHY_TOKENS = {
  fuenteBase:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  textoSm: "12px",
  textoBase: "14px",
  textoLg: "16px",
  textoXl: "20px",
  pesoRegular: 400,
  pesoMedio: 500,
  pesoSemibold: 600,
} as const;

export const SPACING_TOKENS = {
  esp1: "4px",
  esp2: "8px",
  esp3: "12px",
  esp4: "16px",
  esp5: "24px",
  esp6: "32px",
} as const;

export const RADIUS_TOKENS = {
  radioSm: "4px",
  radioMd: "8px",
  radioLg: "16px",
} as const;

export const ELEVATION_TOKENS = {
  sombraSm: "0 1px 2px rgba(0,0,0,0.24)",
  sombraMd: "0 4px 12px rgba(0,0,0,0.32)",
} as const;

/**
 * Paleta ordenada de colores para el Avatar_De_Hablante (Req. 8.4).
 * `colorDeAvatar(orden)` indexa esta paleta de forma cíclica.
 */
export const PALETA_AVATAR: string[] = [
  "#5b8cff",
  "#ff8a5b",
  "#5bffb0",
  "#c65bff",
  "#ffd15b",
  "#5bd4ff",
  "#ff5b8a",
  "#8aff5b",
];

/** Anillo de foco visible derivado de los tokens (Req. 12.4) */
export const FOCUS_RING = {
  color: COLOR_TOKENS.foco,
  width: "2px",
  offset: "2px",
} as const;
