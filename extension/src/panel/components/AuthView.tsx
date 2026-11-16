import React, { useState } from "react";
import { isLocked } from "../../core/authLock";
import type { AuthAttempt } from "../../core/types";
import { PanelHeader } from "./PanelHeader";
import { useT } from "../../i18n";

export interface AuthViewProps {
  onLogin: (email: string, password: string) => Promise<void>;
  unavailable?: boolean;
  sessionExpired?: boolean;
}

export function AuthView({ onLogin, unavailable, sessionExpired }: AuthViewProps) {
  const { t } = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [attempts, setAttempts] = useState<AuthAttempt[]>([]);
  const [error, setError] = useState(false);
  const [pending, setPending] = useState(false);
  const locked = isLocked(attempts, Date.now());
  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (locked || pending || unavailable) return;
    setPending(true);
    setError(false);
    try {
      await onLogin(email, password);
      setAttempts(previous => [...previous, { success: true, atMs: Date.now() }]);
    } catch {
      setAttempts(previous => [...previous, { success: false, atMs: Date.now() }]);
      setError(true);
    } finally { setPending(false); }
  };
  return <div className="panel-app"><PanelHeader /><main className="panel-stack panel-auth">
    <h1>{t("panel:loginHeading")}</h1>
    {sessionExpired && <><p>{t("panel:sessionExpired")}</p><p className="panel-warning" role="alert">{t("panel:sessionAlert")}</p></>}
    {unavailable && <p role="alert">{t("panel:unavailable")}</p>}
    {locked && <p role="alert">{t("panel:locked")}</p>}
    {error && !locked && <p role="alert">{t("panel:loginError")}</p>}
    <form className="panel-stack" onSubmit={handleSubmit}>
      <label className="panel-stack">{t("panel:email")}<input type="email" autoComplete="username" value={email} onChange={event => setEmail(event.target.value)} required /></label>
      <label className="panel-stack">{t("panel:password")}<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label>
      <button className="panel-primary" type="submit" disabled={locked || unavailable || pending}>{t("panel:login")}</button>
    </form>
  </main></div>;
}
