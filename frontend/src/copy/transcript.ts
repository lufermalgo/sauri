export const transcript = {
  unknownSpeaker: "Hablante ?",
  legacyUnknownSpeaker: "Hablante N",
  ambiguous: "Atribución de hablante incierta",
  numberedSpeaker: (number: string) => `Hablante ${number}`,
  playAt: (time: string) => `Reproducir desde este turno (${time})`,
  play: "Reproducir turno",
} as const;
