// Vista_De_Autenticacion — Req. 13.2, 13.3, 13.4, 13.6, 13.7
import React, { useState } from "react";
import { estaBloqueado } from "../../core/authBloqueo";
import type { IntentoDeAutenticacion } from "../../core/types";
import { COLOR_TOKENS, SPACING_TOKENS, RADIUS_TOKENS } from "../../core/design/tokens";

export interface VistaDeAutenticacionProps {
  onLogin: (email: string, password: string) => Promise<void>;
  indisponible?: boolean;
  sesionExpirada?: boolean;
}

export function VistaDeAutenticacion({ onLogin, indisponible, sesionExpirada }: VistaDeAutenticacionProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [intentos, setIntentos] = useState<IntentoDeAutenticacion[]>([]);
  const [error, setError] = useState<string | null>(null);

  const bloqueado = estaBloqueado(intentos, Date.now());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (bloqueado) return;
    setError(null);
    try {
      await onLogin(email, password);
      setIntentos((prev) => [...prev, { exito: true, enMs: Date.now() }]);
    } catch (err) {
      setIntentos((prev) => [...prev, { exito: false, enMs: Date.now() }]);
      setError(err instanceof Error ? err.message : "No se pudo iniciar sesión");
    }
  };

  return (
    <div style={{ padding: SPACING_TOKENS.esp4, display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp2 }}>
      <h2>Iniciar sesión</h2>

      {sesionExpirada && <p style={{ color: COLOR_TOKENS.error }}>Tu sesión expiró. Vuelve a iniciar sesión.</p>}
      {indisponible && <p style={{ color: COLOR_TOKENS.error }}>Servicio no disponible en este momento.</p>}
      {bloqueado && (
        <p role="alert" style={{ color: COLOR_TOKENS.error }}>
          Acceso bloqueado temporalmente por demasiados intentos fallidos. Intenta de nuevo en unos segundos.
        </p>
      )}
      {error && !bloqueado && <p role="alert" style={{ color: COLOR_TOKENS.error }}>{error}</p>}

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.esp2 }}>
        <label htmlFor="auth-email">Correo</label>
        <input
          id="auth-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ padding: SPACING_TOKENS.esp2, borderRadius: RADIUS_TOKENS.radioSm }}
        />

        <label htmlFor="auth-password">Contraseña</label>
        <input
          id="auth-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ padding: SPACING_TOKENS.esp2, borderRadius: RADIUS_TOKENS.radioSm }}
        />

        <button
          type="submit"
          disabled={bloqueado || indisponible}
          style={{
            padding: SPACING_TOKENS.esp2,
            borderRadius: RADIUS_TOKENS.radioMd,
            border: "none",
            backgroundColor: COLOR_TOKENS.primario,
            color: COLOR_TOKENS.texto,
            cursor: bloqueado || indisponible ? "not-allowed" : "pointer",
          }}
        >
          Iniciar sesión
        </button>
      </form>
    </div>
  );
}
