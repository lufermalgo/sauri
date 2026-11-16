import { useEffect, useMemo, useState } from "react";
import { LibraryWorkspace } from "./components/LibraryWorkspace";
import { LoginScreen } from "./components/LoginScreen";
import { UploadView } from "./components/UploadView";
import { PortalShell } from "./components/PortalShell";
import { SettingsView } from "./components/SettingsView";
import { copy } from "./copy/es";
import { navigate, routePath, useRoute } from "./router";
import { readSessionUser } from "./session-user";
import "./styles/shell.css";

export function App() {
  // The route lives in the URL, so a protected deep link survives sign-in:
  // the login screen is rendered in place and the same route shows afterwards.
  const route = useRoute();
  const [authenticated, setAuthenticated] = useState(
    () => Boolean(localStorage.getItem("sauri_token"))
  );

  const user = useMemo(() => (authenticated ? readSessionUser() : null), [authenticated]);

  useEffect(() => {
    function handleUnauthorized() {
      setAuthenticated(false);
    }

    window.addEventListener("sauri:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("sauri:unauthorized", handleUnauthorized);
  }, []);

  function handleLogout() {
    localStorage.removeItem("sauri_token");
    setAuthenticated(false);
    navigate({ name: "library" });
  }

  if (!authenticated) {
    return (
      <main className="shell-login-stage">
        <LoginScreen onLogin={() => setAuthenticated(true)} />
      </main>
    );
  }

  return (
    <PortalShell route={route} user={user} onLogout={handleLogout}>
      {(route.name === "library" || route.name === "meeting") && (
        <LibraryWorkspace meetingId={route.name === "meeting" ? route.meetingId : undefined} />
      )}

      {route.name === "upload" && (
        <UploadView
          onUploaded={(meetingId) => navigate({ name: "meeting", meetingId })}
          onBack={() => navigate({ name: "library" })}
        />
      )}

      {route.name === "settings" && <SettingsView route={route} user={user} onLogout={handleLogout} />}

      {route.name === "notFound" && (
        <section className="shell-not-found" aria-labelledby="shell-not-found-title">
          <h1 id="shell-not-found-title">{copy.shell.notFound.title}</h1>
          <p>{copy.shell.notFound.description}</p>
          <a
            href={routePath({ name: "library" })}
            onClick={(event) => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              navigate({ name: "library" });
            }}
          >
            {copy.shell.notFound.backToLibrary}
          </a>
        </section>
      )}
    </PortalShell>
  );
}
