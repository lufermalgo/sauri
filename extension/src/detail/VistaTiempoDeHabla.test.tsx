// Prueba por ejemplo: Vista_Tiempo_De_Habla (Req. 10.1, 10.3, 10.4, 10.5, 10.6, 10.7)
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { VistaTiempoDeHabla } from "./VistaTiempoDeHabla";
import type { EntradaTiempoDeHabla } from "../core/types";

const entradas: EntradaTiempoDeHabla[] = [
  { hablante: { id: "h1", etiqueta: "Ana Pérez", orden: 1 }, tiempoMs: 5000 },
  { hablante: { id: "h2", etiqueta: "Beto Ruiz", orden: 2 }, tiempoMs: 0 },
];

describe("VistaTiempoDeHabla", () => {
  it("presenta una entrada por Hablante, incluidos los de tiempo 0 (Req. 10.1)", () => {
    render(<VistaTiempoDeHabla estado="con_datos" entradas={entradas} onReintentar={vi.fn()} />);
    expect(screen.getByText("Ana Pérez")).toBeInTheDocument();
    expect(screen.getByText("Beto Ruiz")).toBeInTheDocument();
    expect(screen.getByText("00:05")).toBeInTheDocument();
    expect(screen.getByText("00:00")).toBeInTheDocument();
  });

  it("ordena de mayor a menor Tiempo_De_Habla (Req. 10.4)", () => {
    render(<VistaTiempoDeHabla estado="con_datos" entradas={entradas} onReintentar={vi.fn()} />);
    const nombres = screen.getAllByText(/Ana Pérez|Beto Ruiz/).map((el) => el.textContent);
    expect(nombres).toEqual(["Ana Pérez", "Beto Ruiz"]);
  });

  it("Estado_De_Vista vacio cuando la Reunion no tiene Diarizacion (Req. 10.5)", () => {
    render(<VistaTiempoDeHabla estado="vacio" entradas={[]} onReintentar={vi.fn()} />);
    expect(screen.getByText(/no está disponible/i)).toBeInTheDocument();
  });

  it("Estado_De_Vista cargando (Req. 10.6)", () => {
    render(<VistaTiempoDeHabla estado="cargando" entradas={[]} onReintentar={vi.fn()} />);
    expect(screen.getByText(/cargando/i)).toBeInTheDocument();
  });

  it("Estado_De_Vista error con acción de reintento (Req. 10.7)", () => {
    const onReintentar = vi.fn();
    render(<VistaTiempoDeHabla estado="error" entradas={[]} onReintentar={onReintentar} />);
    screen.getByRole("button", { name: /reintentar/i }).click();
    expect(onReintentar).toHaveBeenCalled();
  });
});
