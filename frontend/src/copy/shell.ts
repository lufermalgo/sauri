export const shell = {
  brand: "Sauri",
  navLabel: "Navegación principal",
  library: "Biblioteca",
  upload: "Subir grabación",
  logout: "Cerrar sesión",
  sidebar: {
    region: "Panel lateral",
    toggle: "Panel lateral",
    open: "Abrir panel lateral",
    close: "Cerrar panel lateral",
  },
  profile: {
    fallbackName: "Cuenta",
    menu: (account: string) => `Cuenta de ${account}`,
    settings: "Configuración",
  },
  notFound: {
    title: "No encontramos esa página",
    description: "La dirección no existe o ya no está disponible.",
    backToLibrary: "Volver a la biblioteca",
  },
} as const;
