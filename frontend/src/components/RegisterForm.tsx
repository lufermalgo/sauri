import React, { useState } from "react";
import { registrarReunion } from "../api";

const MEET_LINK_PATTERN = /^https:\/\/meet\.google\.com\/.+$/;

interface RegisterFormProps {
  onRegistered: () => void;
}

export function RegisterForm({ onRegistered }: RegisterFormProps) {
  const [enlaceMeet, setEnlaceMeet] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const isValid = MEET_LINK_PATTERN.test(enlaceMeet.trim());

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!isValid) {
      setError("El enlace debe ser una URL válida de Google Meet (https://meet.google.com/...)");
      return;
    }

    setLoading(true);
    try {
      await registrarReunion(enlaceMeet.trim());
      setEnlaceMeet("");
      onRegistered();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al registrar la reunión");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section>
      <h2>Registrar Reunión</h2>
      <form onSubmit={handleSubmit}>
        <label htmlFor="enlace-meet">Enlace de Google Meet</label>
        <input
          id="enlace-meet"
          type="url"
          placeholder="https://meet.google.com/abc-defg-hij"
          value={enlaceMeet}
          onChange={(e) => setEnlaceMeet(e.target.value)}
          required
          aria-invalid={enlaceMeet.length > 0 && !isValid ? true : undefined}
        />
        <button type="submit" disabled={!isValid || loading}>
          {loading ? "Registrando..." : "Registrar"}
        </button>
        {error && <p role="alert" style={{ color: "red" }}>{error}</p>}
      </form>
    </section>
  );
}
