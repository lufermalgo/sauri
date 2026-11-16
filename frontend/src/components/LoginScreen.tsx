import { useState, type FormEvent } from "react";
import { CircleAlert, Eye, EyeOff } from "lucide-react";
import { login as loginRequest } from "../api";
import { LanguageSelect } from "./LanguageSelect";
import { LoginProviders, useLoginProviders, type LoginProvider } from "./LoginProviders";
import { SoonLink } from "./LoginSoon";
import { BrandLogo, Button, Card, Icon, TextField } from "./ui";
import "../styles/login.css";
import { useT } from "../i18n";

interface LoginScreenProps {
  onLogin: () => void;
  /** External sign-in options under the form; defaults to the ones in LoginProviders (Google, not active yet). */
  providers?: readonly LoginProvider[];
}

export function LoginScreen({ onLogin, providers }: LoginScreenProps) {
  const { t } = useT();
  const defaultProviders = useLoginProviders();
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
        {/* The logo is the product name: the heading reads "Welcome to Sauri" for assistive technology. */}
        <h1 id="login-heading" className="login-title">
          <span className="login-title-lead">{t("login:titleLead")}</span>{" "}
          <BrandLogo className="login-title-logo" title={t("shell:brand")} />
        </h1>
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
          <p className="login-forgot"><SoonLink>{t("login:forgotPassword")}</SoonLink></p>
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
        <LoginProviders providers={providers ?? defaultProviders} disabled={pending} />
        <p className="login-join">
          {t("login:newToSauri")} <SoonLink>{t("login:joinFree")}</SoonLink>
        </p>
        <p className="login-legal">
          <SoonLink>{t("login:legalTerms")}</SoonLink>
          <span aria-hidden="true"> · </span>
          <SoonLink>{t("login:legalPrivacy")}</SoonLink>
          <span aria-hidden="true"> · </span>
          <SoonLink>{t("login:legalDataNotice")}</SoonLink>
        </p>
        <div className="login-language"><LanguageSelect /></div>
      </Card>
    </div>
  );
}
