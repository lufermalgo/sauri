import { useState, type FormEvent } from "react";
import { CircleAlert, Eye, EyeOff } from "lucide-react";
import { login as loginRequest } from "../api";
import { LanguageSelect } from "./LanguageSelect";
import { LoginBrand } from "./LoginBrand";
import { ENABLED_LOGIN_PROVIDERS, LoginProviders, type LoginProvider } from "./LoginProviders";
import { Button, Card, Icon, TextField } from "./ui";
import "../styles/login.css";
import { useT } from "../i18n";

interface LoginScreenProps {
  onLogin: () => void;
  /** External sign-in options shown under the form; none today (see LoginProviders). */
  providers?: readonly LoginProvider[];
}

export function LoginScreen({ onLogin, providers = ENABLED_LOGIN_PROVIDERS }: LoginScreenProps) {
  const { t } = useT();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);

  const canSubmit = email.trim() !== "" && password !== "" && !pending;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;

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
        <LoginBrand />
        <h1 id="login-heading" className="login-title">{t("login:title")}</h1>
        <p className="login-subtitle">{t("login:subtitle")}</p>
        <form className="login-form" onSubmit={handleSubmit} aria-busy={pending}>
          <TextField
            label={t("login:emailLabel")}
            placeholder={t("login:emailLabel")}
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.currentTarget.value)}
            disabled={pending}
            autoFocus
            required
          />
          <TextField
            label={t("login:passwordLabel")}
            placeholder={t("login:passwordLabel")}
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            disabled={pending}
            required
            trailing={
              <button
                type="button"
                className="ui-icon-button ui-icon-button--ghost ui-icon-button--md"
                aria-label={showPassword ? t("login:hidePassword") : t("login:showPassword")}
                onClick={() => setShowPassword((visible) => !visible)}
              >
                <Icon icon={showPassword ? EyeOff : Eye} size={20} />
              </button>
            }
          />
          {error && (
            <p className="login-error" role="alert">
              <Icon icon={CircleAlert} size={16} />
              <span>{t("login:error")}</span>
            </p>
          )}
          <Button variant="primary" size="lg" type="submit" className="login-submit" disabled={!canSubmit}>
            {pending ? t("login:submitting") : t("login:submit")}
          </Button>
        </form>
        <LoginProviders providers={providers} disabled={pending} />
        <div className="login-language"><LanguageSelect /></div>
      </Card>
    </div>
  );
}
