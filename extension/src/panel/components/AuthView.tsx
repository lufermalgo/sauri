// Auth_View — Req. 13.2, 13.3, 13.4, 13.6, 13.7
import React, { useState } from "react";
import { isLocked } from "../../core/authLock";
import type { AuthAttempt } from "../../core/types";
import { COLOR_TOKENS, SPACING_TOKENS, RADIUS_TOKENS } from "../../core/design/tokens";

export interface AuthViewProps {
  onLogin: (email: string, password: string) => Promise<void>;
  unavailable?: boolean;
  sessionExpired?: boolean;
}

export function AuthView({ onLogin, unavailable, sessionExpired }: AuthViewProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [attempts, setAttempts] = useState<AuthAttempt[]>([]);
  const [error, setError] = useState<string | null>(null);

  const locked = isLocked(attempts, Date.now());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (locked) return;
    setError(null);
    try {
      await onLogin(email, password);
      setAttempts((prev) => [...prev, { success: true, atMs: Date.now() }]);
    } catch (err) {
      setAttempts((prev) => [...prev, { success: false, atMs: Date.now() }]);
      setError(err instanceof Error ? err.message : "Could not sign in");
    }
  };

  return (
    <div style={{ padding: SPACING_TOKENS.space4, display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space2 }}>
      <h2>Sign in</h2>

      {sessionExpired && <p style={{ color: COLOR_TOKENS.error }}>Your session expired. Please sign in again.</p>}
      {unavailable && <p style={{ color: COLOR_TOKENS.error }}>Service unavailable at this time.</p>}
      {locked && (
        <p role="alert" style={{ color: COLOR_TOKENS.error }}>
          Access temporarily locked after too many failed attempts. Try again in a few seconds.
        </p>
      )}
      {error && !locked && <p role="alert" style={{ color: COLOR_TOKENS.error }}>{error}</p>}

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: SPACING_TOKENS.space2 }}>
        <label htmlFor="auth-email">Email</label>
        <input
          id="auth-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={{ padding: SPACING_TOKENS.space2, borderRadius: RADIUS_TOKENS.radiusSm }}
        />

        <label htmlFor="auth-password">Password</label>
        <input
          id="auth-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={{ padding: SPACING_TOKENS.space2, borderRadius: RADIUS_TOKENS.radiusSm }}
        />

        <button
          type="submit"
          disabled={locked || unavailable}
          style={{
            padding: SPACING_TOKENS.space2,
            borderRadius: RADIUS_TOKENS.radiusMd,
            border: "none",
            backgroundColor: COLOR_TOKENS.primary,
            color: COLOR_TOKENS.text,
            cursor: locked || unavailable ? "not-allowed" : "pointer",
          }}
        >
          Sign in
        </button>
      </form>
    </div>
  );
}
