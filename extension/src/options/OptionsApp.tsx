// sauri settings — full tab (not side panel) to grant the microphone
// permission. getUserMedia() from the Side_Panel can't always show Chrome's
// native prompt; a regular options page does guarantee it. The permission is
// granted per origin (chrome-extension://<id>), so once granted here, the
// Side_Panel can use the microphone too.
import React, { useCallback, useEffect, useState } from "react";
import { COLOR_TOKENS, SPACING_TOKENS, TYPOGRAPHY_TOKENS, RADIUS_TOKENS } from "../core/design/tokens";

type PermissionStateOrUnknown = "unknown" | PermissionState;

export function OptionsApp() {
  const [state, setState] = useState<PermissionStateOrUnknown>("unknown");
  const [devices, setDevices] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const queryState = useCallback(async () => {
    try {
      const permission = await navigator.permissions.query({
        name: "microphone" as PermissionName,
      });
      setState(permission.state as PermissionStateOrUnknown);
    } catch {
      setState("unknown");
    }
  }, []);

  useEffect(() => {
    queryState();
  }, [queryState]);

  const requestPermission = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      const mediaDevices = await navigator.mediaDevices.enumerateDevices();
      setDevices(
        mediaDevices.filter((d) => d.kind === "audioinput").map((d) => d.label || "Microphone")
      );
      await queryState();
    } catch (e) {
      const name = e instanceof DOMException ? e.name : String(e);
      setError(
        name === "NotAllowedError"
          ? "Permission denied. Go to chrome://settings/content/microphone, find sauri, and change the permission to 'Allow'."
          : name === "NotFoundError"
            ? "No connected microphone was detected."
            : `Could not access the microphone (${name}).`
      );
      await queryState();
    }
  }, [queryState]);

  return (
    <div
      style={{
        maxWidth: "480px",
        margin: "0 auto",
        padding: SPACING_TOKENS.space5,
        fontFamily: TYPOGRAPHY_TOKENS.baseFont,
        color: COLOR_TOKENS.text,
        background: COLOR_TOKENS.background,
        minHeight: "100vh",
      }}
    >
      <h1 style={{ fontSize: TYPOGRAPHY_TOKENS.textXl }}>sauri settings</h1>

      <section
        style={{
          background: COLOR_TOKENS.surface,
          borderRadius: RADIUS_TOKENS.radiusMd,
          padding: SPACING_TOKENS.space4,
          marginTop: SPACING_TOKENS.space4,
        }}
      >
        <h2 style={{ fontSize: TYPOGRAPHY_TOKENS.textLg, marginTop: 0 }}>Microphone</h2>
        <p style={{ color: COLOR_TOKENS.textMuted, fontSize: TYPOGRAPHY_TOKENS.textSm }}>
          Current status:{" "}
          {state === "granted"
            ? "granted ✅"
            : state === "denied"
              ? "denied ❌"
              : state === "prompt"
                ? "not decided yet"
                : "unknown"}
        </p>

        <button type="button" onClick={requestPermission}>
          Enable microphone
        </button>

        {error && (
          <p role="alert" style={{ color: COLOR_TOKENS.error, fontSize: TYPOGRAPHY_TOKENS.textSm }}>
            {error}
          </p>
        )}

        {devices.length > 0 && (
          <ul>
            {devices.map((label, i) => (
              <li key={i} style={{ fontSize: TYPOGRAPHY_TOKENS.textSm }}>
                {label}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
