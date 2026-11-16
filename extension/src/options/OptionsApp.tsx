import React, { useCallback, useEffect, useRef, useState } from "react";
import { permissionCopy as copy } from "./copy";
import { PanelHeader } from "../panel/components/PanelHeader";
import "../core/design/base.css";
import "../panel/panel.css";
import "./options.css";

type MicrophonePermission = "waiting" | "granted" | "denied";

export function OptionsApp() {
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
    } catch { if (mounted.current) setError(copy.closeError); }
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
      if (!denied) setError(copy.deviceError);
    } finally { pending.current = false; }
  }, []);

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
      <h1>{copy.heading}</h1>
      <p>{copy.introduction}</p>
      <section className="permission-card panel-stack panel-card">
        <span className={`panel-badge panel-badge-${state === "granted" ? "success" : state === "denied" ? "error" : "progress"}`}>{state === "granted" ? copy.granted : state === "denied" ? copy.denied : copy.waiting}</span>
        {state === "waiting" && <><h2>{copy.waitingHeading}</h2><p>{copy.waitingHelp}</p><p role="status">{copy.waitingStatus}</p></>}
        {state === "granted" && <><span className="permission-check" aria-hidden="true">✓</span><h2>{copy.grantedHeading}</h2><p>{device ? `${copy.devicePrefix}${device}${copy.deviceSuffix}` : copy.grantedHelp}</p><p role="status">{copy.closingPrefix} <b className="permission-time">{remaining}</b> {copy.closingSuffix}</p><button onClick={() => { void close(); }}>{copy.close}</button></>}
        {state === "denied" && <><h2>{copy.deniedHeading}</h2><ol>{copy.steps.map(step => <li key={step}>{step}</li>)}</ol><p>{copy.settingsPrefix} <code>chrome://settings/content/microphone</code> {copy.settingsSuffix}</p><button className="panel-primary" onClick={() => { void checkPermission(); }}>{copy.retry}</button></>}
        {error && <p role="alert">{error}</p>}
      </section>
      <p>{copy.systemHelp}</p>
    </main>
  </div>;
}
