// Ajustes de sauri — pestaña completa (no side panel) para conceder el permiso
// de micrófono. getUserMedia() desde el Side_Panel no siempre puede mostrar el
// prompt nativo de Chrome; una página de opciones normal sí lo garantiza. El
// permiso se concede por origen (chrome-extension://<id>), así que una vez
// otorgado aquí, el Side_Panel también puede usar el micrófono.
import React, { useCallback, useEffect, useState } from "react";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS, RADIUS_TOKENS } from "../core/design/tokens";

type EstadoPermiso = "desconocido" | PermissionState;

export function OptionsApp() {
  const [estado, setEstado] = useState<EstadoPermiso>("desconocido");
  const [dispositivos, setDispositivos] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const consultarEstado = useCallback(async () => {
    try {
      const permiso = await navigator.permissions.query({
        name: "microphone" as PermissionName,
      });
      setEstado(permiso.state as EstadoPermiso);
    } catch {
      setEstado("desconocido");
    }
  }, []);

  useEffect(() => {
    consultarEstado();
  }, [consultarEstado]);

  const solicitarPermiso = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      const devices = await navigator.mediaDevices.enumerateDevices();
      setDispositivos(
        devices.filter((d) => d.kind === "audioinput").map((d) => d.label || "Micrófono")
      );
      await consultarEstado();
    } catch (e) {
      const nombre = e instanceof DOMException ? e.name : String(e);
      setError(
        nombre === "NotAllowedError"
          ? "Permiso denegado. Ve a chrome://settings/content/microphone, busca sauri y cambia el permiso a 'Permitir'."
          : nombre === "NotFoundError"
            ? "No se detectó ningún micrófono conectado."
            : `No se pudo acceder al micrófono (${nombre}).`
      );
      await consultarEstado();
    }
  }, [consultarEstado]);

  return (
    <div
      style={{
        maxWidth: "480px",
        margin: "0 auto",
        padding: SPACING_TOKENS.esp5,
        fontFamily: TYPOGRAPHY_TOKENS.fuenteBase,
        color: COLOR_TOKENS.texto,
        background: COLOR_TOKENS.fondo,
        minHeight: "100vh",
      }}
    >
      <h1 style={{ fontSize: TYPOGRAPHY_TOKENS.textoXl }}>Ajustes de sauri</h1>

      <section
        style={{
          background: COLOR_TOKENS.superficie,
          borderRadius: RADIUS_TOKENS.radioMd,
          padding: SPACING_TOKENS.esp4,
          marginTop: SPACING_TOKENS.esp4,
        }}
      >
        <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textoLg, marginTop: 0 }}>Micrófono</h2>
        <p style={{ color: COLOR_TOKENS.textoTenue, fontSize: TYPOGRAPHY_TOKENS.textoSm }}>
          Estado actual:{" "}
          {estado === "granted"
            ? "concedido ✅"
            : estado === "denied"
              ? "denegado ❌"
              : estado === "prompt"
                ? "sin decidir aún"
                : "desconocido"}
        </p>

        <button type="button" onClick={solicitarPermiso}>
          Habilitar micrófono
        </button>

        {error && (
          <p role="alert" style={{ color: COLOR_TOKENS.error, fontSize: TYPOGRAPHY_TOKENS.textoSm }}>
            {error}
          </p>
        )}

        {dispositivos.length > 0 && (
          <ul>
            {dispositivos.map((label, i) => (
              <li key={i} style={{ fontSize: TYPOGRAPHY_TOKENS.textoSm }}>
                {label}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
