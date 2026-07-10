// Prueba por ejemplo: Vista_De_Autenticacion (Req. 13.2, 13.6, 13.7)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { VistaDeAutenticacion } from "./VistaDeAutenticacion";

describe("VistaDeAutenticacion", () => {
  it("presenta el flujo de login (Req. 13.2)", () => {
    render(<VistaDeAutenticacion onLogin={vi.fn()} />);
    expect(screen.getByLabelText(/correo/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/contraseña/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /iniciar sesión/i })).toBeInTheDocument();
  });

  it("un login válido invoca onLogin con las credenciales", async () => {
    const onLogin = vi.fn().mockResolvedValue(undefined);
    render(<VistaDeAutenticacion onLogin={onLogin} />);
    fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: "a@summan.com" } });
    fireEvent.change(screen.getByLabelText(/contraseña/i), { target: { value: "clave" } });
    fireEvent.click(screen.getByRole("button", { name: /iniciar sesión/i }));

    await waitFor(() => expect(onLogin).toHaveBeenCalledWith("a@summan.com", "clave"));
  });

  it("bloquea nuevos intentos tras 5 fallos consecutivos (Req. 13.6)", async () => {
    const onLogin = vi.fn().mockRejectedValue(new Error("Credenciales inválidas"));
    render(<VistaDeAutenticacion onLogin={onLogin} />);

    for (let i = 0; i < 5; i++) {
      fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: "a@summan.com" } });
      fireEvent.change(screen.getByLabelText(/contraseña/i), { target: { value: "mala" } });
      fireEvent.click(screen.getByRole("button", { name: /iniciar sesión/i }));
      await waitFor(() => expect(onLogin).toHaveBeenCalledTimes(i + 1));
    }

    expect(screen.getByText(/bloqueado/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /iniciar sesión/i })).toBeDisabled();
  });

  it("indica indisponibilidad del servicio (Req. 13.7)", () => {
    render(<VistaDeAutenticacion onLogin={vi.fn()} indisponible />);
    expect(screen.getByText(/no disponible/i)).toBeInTheDocument();
  });
});
