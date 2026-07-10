// Prueba por ejemplo: Encabezado_Panel y Boton_Nueva_Nota (Req. 2.1, 2.2, 2.3, 2.5, 2.6)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EncabezadoPanel } from "./EncabezadoPanel";

describe("EncabezadoPanel", () => {
  it("muestra el título 'REC Notas' (Req. 2.1)", () => {
    render(<EncabezadoPanel estadoDeCaptura="inactiva" onNuevaNota={() => {}} />);
    expect(screen.getByText("REC Notas")).toBeInTheDocument();
  });

  it("muestra el Boton_Nueva_Nota con la etiqueta '+ Nueva nota REC' (Req. 2.2)", () => {
    render(<EncabezadoPanel estadoDeCaptura="inactiva" onNuevaNota={() => {}} />);
    expect(screen.getByRole("button", { name: "+ Nueva nota REC" })).toBeInTheDocument();
  });

  it("dispara onNuevaNota al activarse en estado inactiva (Req. 2.4)", () => {
    const onNuevaNota = vi.fn();
    render(<EncabezadoPanel estadoDeCaptura="inactiva" onNuevaNota={onNuevaNota} />);
    fireEvent.click(screen.getByRole("button", { name: "+ Nueva nota REC" }));
    expect(onNuevaNota).toHaveBeenCalledTimes(1);
  });

  it("deshabilita el Boton_Nueva_Nota mientras graba o detiene (Req. 2.5)", () => {
    render(<EncabezadoPanel estadoDeCaptura="grabando" onNuevaNota={() => {}} />);
    expect(screen.getByRole("button", { name: "+ Nueva nota REC" })).toBeDisabled();
  });

  it("muestra un mensaje de error si el inicio de la grabación falla (Req. 2.6)", () => {
    render(
      <EncabezadoPanel
        estadoDeCaptura="inactiva"
        onNuevaNota={() => {}}
        errorInicio="La grabación no pudo iniciarse"
      />
    );
    expect(screen.getByText("La grabación no pudo iniciarse")).toBeInTheDocument();
  });
});
