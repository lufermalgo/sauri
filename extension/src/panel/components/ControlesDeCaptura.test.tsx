// Prueba por ejemplo: Controles_De_Captura (Req. 3.1, 3.2, 3.7, 3.8, 3.9, 3.10)
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ControlesDeCaptura } from "./ControlesDeCaptura";

describe("ControlesDeCaptura", () => {
  it("ofrece 'Pantalla + audio' en el Selector_De_Fuente_De_Audio (Req. 3.1, 3.2)", () => {
    render(
      <ControlesDeCaptura
        estadoDeCaptura="inactiva"
        microfonos={[]}
        onToggleCaptura={() => {}}
        onAbrirAjustes={() => {}}
        tiempoTranscurridoMs={0}
      />
    );
    expect(screen.getByText("Pantalla + audio")).toBeInTheDocument();
  });

  it("muestra estado vacío si no hay micrófonos disponibles, sin bloquear el resto (Req. 3.7)", () => {
    render(
      <ControlesDeCaptura
        estadoDeCaptura="inactiva"
        microfonos={[]}
        onToggleCaptura={() => {}}
        onAbrirAjustes={() => {}}
        tiempoTranscurridoMs={0}
      />
    );
    expect(screen.getByText(/sin micrófonos/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ajustes/i })).toBeEnabled();
  });

  it("muestra el Boton_De_Ajustes y dispara onAbrirAjustes (Req. 3.8)", () => {
    const onAbrirAjustes = vi.fn();
    render(
      <ControlesDeCaptura
        estadoDeCaptura="inactiva"
        microfonos={[]}
        onToggleCaptura={() => {}}
        onAbrirAjustes={onAbrirAjustes}
        tiempoTranscurridoMs={0}
      />
    );
    screen.getByRole("button", { name: /ajustes/i }).click();
    expect(onAbrirAjustes).toHaveBeenCalledTimes(1);
  });

  it("muestra el cronómetro 'MM:SS' mientras graba (Req. 3.9)", () => {
    render(
      <ControlesDeCaptura
        estadoDeCaptura="grabando"
        microfonos={[]}
        onToggleCaptura={() => {}}
        onAbrirAjustes={() => {}}
        tiempoTranscurridoMs={65_000}
      />
    );
    expect(screen.getByText("01:05")).toBeInTheDocument();
  });

  it("muestra un error si el inicio de captura falla (Req. 3.10)", () => {
    render(
      <ControlesDeCaptura
        estadoDeCaptura="inactiva"
        microfonos={[]}
        onToggleCaptura={() => {}}
        onAbrirAjustes={() => {}}
        tiempoTranscurridoMs={0}
        errorInicio="La captura no pudo iniciarse"
      />
    );
    expect(screen.getByText("La captura no pudo iniciarse")).toBeInTheDocument();
  });
});
