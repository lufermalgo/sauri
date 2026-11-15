import { useState, type FormEvent } from "react";
import { login as loginRequest } from "../api";
import { copy } from "../copy/es";
import { Button, Card, TextField } from "./ui";
import "../styles/login.css";

interface LoginScreenProps {
  onLogin: () => void;
}

const text = copy.login;

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    setPending(true);
    setError(false);
    try {
      const response = await loginRequest(email, password);
      localStorage.setItem("sauri_token", response.access_token);
      setPassword("");
      onLogin();
    } catch {
      setError(true);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="login-page">
      <Card className="login-card" aria-labelledby="login-heading">
        <div className="login-brand">
          <svg className="login-mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
            <circle cx="16" cy="16" r="16" className="login-mark-disc" />
            <g className="login-mark-bars">
              <rect x="8" y="13" width="2.5" height="6" rx="1.25" />
              <rect x="12.5" y="9" width="2.5" height="14" rx="1.25" />
              <rect x="17" y="11" width="2.5" height="10" rx="1.25" />
              <rect x="21.5" y="14" width="2.5" height="4" rx="1.25" />
            </g>
          </svg>
          <span className="login-brand-name">{text.brand}</span>
        </div>
        <h1 id="login-heading" className="login-title">{text.title}</h1>
        <p className="login-subtitle">{text.subtitle}</p>
        <form className="login-form" onSubmit={handleSubmit}>
          <TextField
            label={text.emailLabel}
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.currentTarget.value)}
            disabled={pending}
            required
          />
          <TextField
            label={text.passwordLabel}
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            disabled={pending}
            required
          />
          {error && <p className="login-error" role="alert">{text.error}</p>}
          <Button variant="primary" type="submit" className="login-submit" disabled={pending}>
            {pending ? text.submitting : text.submit}
          </Button>
        </form>
      </Card>
    </div>
  );
}
