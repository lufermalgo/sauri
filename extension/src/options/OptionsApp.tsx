import React, { useCallback, useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { Trans } from "react-i18next";
import { useT } from "../i18n";
import { LanguageSelect } from "./LanguageSelect";
import { Icon } from "../core/design/Icon";
import { PanelHeader } from "../panel/components/PanelHeader";
import "../core/design/base.css";
import "../panel/panel.css";
import "./options.css";

type MicrophonePermission = "waiting" | "granted" | "denied";
const STEPS = ["stepIcon", "stepAllow", "stepReturn"] as const;

export function OptionsApp() {
  const { t } = useT();
  const [state, setState] = useState<MicrophonePermission>("waiting");
  const [device, setDevice] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [remaining, setRemaining] = useState(3);
  const mounted = useRef(false);
  const pending = useRef(false);

  const close = useCallback(async () => {
    try {
      const tab = await chrome.tabs.getCurrent();
      if (tab?.id === undefined) throw new Error("Permission tab unavailable");
      await chrome.tabs.remove(tab.id);
    } catch { if (mounted.current) setError(t("permission:closeError")); }
  }, []);

  const checkPermission = useCallback(async () => {
    if (pending.current) return;
    pending.current = true;
    setState("waiting");
    setError(null);
    setDevice("");
    let stream: MediaStream | undefined;
    try {
      let permission: PermissionState = "prompt";
      try { permission = (await navigator.permissions.query({ name: "microphone" as PermissionName })).state; }
      catch { /* A request from this extension page can still obtain permission. */ }
      if (!mounted.current) return;
      if (permission === "denied") { setState("denied"); return; }
      if (permission !== "granted") {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        // Release the hardware even if the tab unmounted while Chrome prompted.
        stream.getTracks().forEach(track => track.stop());
        if (!mounted.current) return;
        const label = stream.getAudioTracks()[0]?.label;
        if (label) setDevice(label);
      }
      if (mounted.current) {
        setRemaining(3);
        setState("granted");
      }
    } catch (failure) {
      if (!mounted.current) return;
      let denied = failure instanceof DOMException && failure.name === "NotAllowedError";
      try { denied ||= (await navigator.permissions.query({ name: "microphone" as PermissionName })).state === "denied"; }
      catch { /* Keep the concrete request failure instead of exposing raw errors. */ }
      if (!mounted.current) return;
      setState("denied");
      if (!denied) setError(t("permission:deviceError"));
    } finally { pending.current = false; }
  }, []);

  useEffect(() => { document.title = t("permission:documentTitle"); }, [t]);

  useEffect(() => {
    mounted.current = true;
    void checkPermission();
    return () => { mounted.current = false; };
  }, [checkPermission]);

  useEffect(() => {
    if (state !== "granted") return;
    const timer = setTimeout(() => { void close(); }, 3000);
    const tick = setInterval(() => setRemaining(value => Math.max(0, value - 1)), 1000);
    return () => { clearTimeout(timer); clearInterval(tick); };
  }, [state, close]);

  return <div className="permission-page">
    <PanelHeader />
    <main className="permission-main panel-stack">
      <h1>{t("permission:heading")}</h1>
      <p>{t("permission:introduction")}</p>
      <section className="permission-card panel-stack panel-card">
        <span className={`panel-badge panel-badge-${state === "granted" ? "success" : state === "denied" ? "error" : "progress"}`}>{state === "granted" ? t("permission:granted") : state === "denied" ? t("permission:denied") : t("permission:waiting")}</span>
        {state === "waiting" && <><h2>{t("permission:waitingHeading")}</h2><p>{t("permission:waitingHelp")}</p><p role="status">{t("permission:waitingStatus")}</p></>}
        {state === "granted" && <><span className="permission-check" aria-hidden="true"><Icon icon={Check} size={28} strokeWidth={2.25} /></span><h2>{t("permission:grantedHeading")}</h2><p>{device ? t("permission:grantedDevice", { device }) : t("permission:grantedHelp")}</p><p role="status"><Trans ns="permission" i18nKey="closing" values={{ seconds: remaining }} components={{ time: <b className="permission-time" /> }} /></p><button onClick={() => { void close(); }}>{t("permission:close")}</button></>}
        {state === "denied" && <><h2>{t("permission:deniedHeading")}</h2><ol>{STEPS.map(step => <li key={step}>{t(`permission:${step}`)}</li>)}</ol><p><Trans ns="permission" i18nKey="settingsHelp" components={{ code: <code /> }} /></p><button className="panel-primary" onClick={() => { void checkPermission(); }}>{t("permission:retry")}</button></>}
        {error && <p role="alert">{error}</p>}
      </section>
      <p>{t("permission:systemHelp")}</p>
      <LanguageSelect />
    </main>
  </div>;
}
