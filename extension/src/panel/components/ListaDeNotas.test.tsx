// Prueba por ejemplo: Lista_De_Notas, Tarjeta_De_Nota, Buscador y Filtro (Req. 4, 5)
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ListaDeNotas } from "./ListaDeNotas";
import type { NotaDTO } from "../../core/types";

const notas: NotaDTO[] = [
  { reunionId: "r1", titulo: "Reunión con cliente A", estadoProceso: "completado", creadaEn: "2024-05-01T10:00:00Z" },
  { reunionId: "r2", titulo: null, estadoProceso: "completado", creadaEn: "2024-05-02T10:00:00Z" },
];

describe("ListaDeNotas", () => {
  it("muestra el Estado_De_Vista 'cargando' mientras espera (Req. 4.7)", () => {
    render(<ListaDeNotas estado="cargando" notas={[]} onReintentar={() => {}} onAbrirNota={() => {}} />);
    expect(screen.getByText(/cargando/i)).toBeInTheDocument();
  });

  it("renderiza una Tarjeta_De_Nota por Nota con título/placeholder y fecha (Req. 4.2-4.5)", () => {
    render(<ListaDeNotas estado="con_datos" notas={notas} onReintentar={() => {}} onAbrirNota={() => {}} />);
    expect(screen.getByText("Reunión con cliente A")).toBeInTheDocument();
    expect(screen.getByText(/nota sin título/i)).toBeInTheDocument();
    expect(screen.getAllByText(/, \d{2}:\d{2}/).length).toBe(2);
  });

  it("Estado_De_Vista 'vacio' invita a crear la primera nota (Req. 4.8)", () => {
    render(<ListaDeNotas estado="vacio" notas={[]} onReintentar={() => {}} onAbrirNota={() => {}} />);
    expect(screen.getByText(/primera nota/i)).toBeInTheDocument();
  });

  it("Estado_De_Vista 'error' ofrece reintentar (Req. 4.9)", () => {
    const onReintentar = vi.fn();
    render(<ListaDeNotas estado="error" notas={[]} onReintentar={onReintentar} onAbrirNota={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: /reintentar/i }));
    expect(onReintentar).toHaveBeenCalledTimes(1);
  });

  it("filtra por texto tras 300ms de debounce (Req. 5.1)", async () => {
    render(<ListaDeNotas estado="con_datos" notas={notas} onReintentar={() => {}} onAbrirNota={() => {}} />);
    const input = screen.getByPlaceholderText(/buscar/i);
    fireEvent.change(input, { target: { value: "cliente A" } });

    await waitFor(
      () => {
        expect(screen.queryByText(/nota sin título/i)).not.toBeInTheDocument();
      },
      { timeout: 1000 }
    );
    expect(screen.getByText("Reunión con cliente A")).toBeInTheDocument();
  });

  it("abre la nota seleccionada (Req. 6.1)", () => {
    const onAbrirNota = vi.fn();
    render(<ListaDeNotas estado="con_datos" notas={notas} onReintentar={() => {}} onAbrirNota={onAbrirNota} />);
    fireEvent.click(screen.getByText("Reunión con cliente A"));
    expect(onAbrirNota).toHaveBeenCalledWith("r1");
  });
});
