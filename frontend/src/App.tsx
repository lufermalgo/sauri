import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { LibraryWorkspace } from "./components/LibraryWorkspace";
import { LoginScreen } from "./components/LoginScreen";
import { UploadView } from "./components/UploadView";
import { PortalShell } from "./components/PortalShell";
import { SettingsView } from "./components/SettingsView";
import { copy } from "./copy/es";
import { navigate, routePath, useRoute, type Route } from "./router";
import { readLastMeetingId } from "./last-meeting";
import { readSessionUser } from "./session-user";
import "./styles/shell.css";

export function App() {
  // The route lives in the URL, so a protected deep link survives sign-in:
  // the login screen is rendered in place and the same route shows afterwards.
  const urlRoute = useRoute();
  const [authenticated, setAuthenticated] = useState(
    () => Boolean(localStorage.getItem("sauri_token"))
  );

  // The portal starts on the recording the user last explored. This applies once per start (and after an
  // explicit sign-out), only when it begins at `/`: later visits to `/` are the user's own choice, and
  // direct links are never redirected. The first paint already shows the recording, with no flash of the
  // library, and the URL is replaced (not pushed) so Back does not return to `/` and loop.
  const startRestorePending = useRef(true);
  const restoreId = authenticated && startRestorePending.current && urlRoute.name === "library" ? readLastMeetingId() : null;
  const route: Route = restoreId ? { name: "meeting", meetingId: restoreId } : urlRoute;
  const [restoredId, setRestoredId] = useState<string | null>(null);
  useLayoutEffect(() => {
    if (!authenticated) return;
    startRestorePending.current = false;
    if (restoreId) {
      setRestoredId(restoreId);
      navigate({ name: "meeting", meetingId: restoreId }, { replace: true });
    }
  }, [authenticated, restoreId]);
  // A reopened recording is only "restored" until the user moves elsewhere.
  useEffect(() => {
    if (restoredId !== null && !(route.name === "meeting" && route.meetingId === restoredId)) setRestoredId(null);
  }, [route, restoredId]);

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
    startRestorePending.current = true;
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
        <LibraryWorkspace
          meetingId={route.name === "meeting" ? route.meetingId : undefined}
          restored={route.name === "meeting" && route.meetingId === restoredId}
        />
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
