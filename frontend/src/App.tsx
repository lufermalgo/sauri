import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { LibraryWorkspace } from "./components/LibraryWorkspace";
import { LoginScreen } from "./components/LoginScreen";
import { UploadView } from "./components/UploadView";
import { PortalShell } from "./components/PortalShell";
import { Button } from "./components/ui";
import { SettingsView } from "./components/SettingsView";
import { navigate, routePath, useRoute, type Route } from "./router";
import { readLastMeetingId } from "./last-meeting";
import { canDetectLocalMode, detectLocalSession } from "./api";
import { readSessionUser, type SessionUser } from "./session-user";
import "./styles/shell.css";
import { useT } from "./i18n";

export function App() {
  const { t } = useT();
  // The route lives in the URL, so a protected deep link survives sign-in:
  // the login screen is rendered in place and the same route shows afterwards.
  const urlRoute = useRoute();
  const [authenticated, setAuthenticated] = useState(
    () => Boolean(localStorage.getItem("sauri_token"))
  );

  const [sessionReady, setSessionReady] = useState(() => !canDetectLocalMode());
  const [localUser, setLocalUser] = useState<SessionUser | null>(null);
  const [sessionError, setSessionError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!canDetectLocalMode()) return;
    let active = true;
    setSessionError(false);
    void detectLocalSession().then((user) => {
      if (!active) return;
      setLocalUser(user);
      setAuthenticated(user !== null || Boolean(localStorage.getItem("sauri_token")));
      setSessionReady(true);
    }).catch(() => { if (active) setSessionError(true); });
    return () => { active = false; };
  }, [attempt]);

  // The portal starts on the recording the user last explored. This applies once per start (and after an
  // explicit sign-out), only when it begins at `/`: later visits to `/` are the user's own choice, and
  // direct links are never redirected. The first paint already shows the recording, with no flash of the
  // library, and the URL is replaced (not pushed) so Back does not return to `/` and loop.
  const startRestorePending = useRef(true);
  const restoreId = sessionReady && !localUser && authenticated && startRestorePending.current && urlRoute.name === "library" ? readLastMeetingId() : null;
  const route: Route = restoreId ? { name: "meeting", meetingId: restoreId } : urlRoute;
  const [restoredId, setRestoredId] = useState<string | null>(null);
  useLayoutEffect(() => {
    if (!sessionReady || !authenticated) return;
    startRestorePending.current = false;
    if (restoreId) {
      setRestoredId(restoreId);
      navigate({ name: "meeting", meetingId: restoreId }, { replace: true });
    }
  }, [sessionReady, authenticated, restoreId]);
  // A reopened recording is only "restored" until the user moves elsewhere.
  useEffect(() => {
    if (restoredId !== null && !(route.name === "meeting" && route.meetingId === restoredId)) setRestoredId(null);
  }, [route, restoredId]);

  const user = useMemo(() => localUser ?? (authenticated ? readSessionUser() : null), [authenticated, localUser]);

  useEffect(() => {
    function handleUnauthorized() {
      if (!localUser) setAuthenticated(false);
    }

    window.addEventListener("sauri:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("sauri:unauthorized", handleUnauthorized);
  }, [localUser]);

  function handleLogout() {
    if (localUser) return;
    localStorage.removeItem("sauri_token");
    startRestorePending.current = true;
    setAuthenticated(false);
    navigate({ name: "library" });
  }

  if (!sessionReady) {
    return <main className="shell-login-stage" aria-busy={!sessionError}>
      {sessionError ? <div role="alert">
        <p>{t("shell:localSession.error")}</p>
        <Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>{t("shell:localSession.retry")}</Button>
      </div> : <p role="status">{t("shell:localSession.loading")}</p>}
    </main>;
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
          <h1 id="shell-not-found-title">{t("shell:notFound.title")}</h1>
          <p>{t("shell:notFound.description")}</p>
          <a
            href={routePath({ name: "library" })}
            onClick={(event) => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
              event.preventDefault();
              navigate({ name: "library" });
            }}
          >
            {t("shell:notFound.backToLibrary")}
          </a>
        </section>
      )}
    </PortalShell>
  );
}
