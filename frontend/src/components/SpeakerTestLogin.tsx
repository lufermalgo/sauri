import { useState, type FormEvent } from "react";
import { login } from "../api";

interface SpeakerTestLoginProps {
  onLogin: () => void;
}

export function SpeakerTestLogin({ onLogin }: SpeakerTestLoginProps) {
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
      const response = await login(email, password);
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
    <section aria-labelledby="speaker-test-login-heading">
      <h2 id="speaker-test-login-heading">Sign in</h2>
      <form onSubmit={handleSubmit}>
        <label>
          Email
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.currentTarget.value)}
            disabled={pending}
            required
          />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            disabled={pending}
            required
          />
        </label>
        <button type="submit" disabled={pending}>
          {pending ? "Signing in…" : "Log in"}
        </button>
        {error && <p role="alert">Sign-in failed. Check your details and try again.</p>}
      </form>
    </section>
  );
}
