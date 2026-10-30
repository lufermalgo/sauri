import React, { useEffect, useState } from "react";
import type { MeetingListItem } from "@sauri/shared-types";
import { RegisterForm } from "./components/RegisterForm";
import { MeetingList } from "./components/MeetingList";
import { TranscriptView } from "./components/TranscriptView";
import { SpeakerRecognitionTestScreen } from "./components/SpeakerRecognitionTestScreen";
import { SpeakerTestLogin } from "./components/SpeakerTestLogin";

type View = { type: "list" } | { type: "transcript"; meetingId: string } | { type: "speaker-test" };

export function App() {
  const [view, setView] = useState<View>({ type: "list" });
  const [refreshKey, setRefreshKey] = useState(0);
  const [authenticated, setAuthenticated] = useState(
    () => Boolean(localStorage.getItem("sauri_token"))
  );

  useEffect(() => {
    function handleUnauthorized() {
      setAuthenticated(false);
      setView({ type: "list" });
    }

    window.addEventListener("sauri:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("sauri:unauthorized", handleUnauthorized);
  }, []);

  function handleRegistered() {
    setRefreshKey((key) => key + 1);
  }

  function handleSelectMeeting(meeting: MeetingListItem) {
    setView({ type: "transcript", meetingId: meeting.id });
  }

  function handleLogout() {
    localStorage.removeItem("sauri_token");
    setAuthenticated(false);
    setView({ type: "list" });
  }

  if (!authenticated) {
    return (
      <main style={{ maxWidth: "800px", margin: "0 auto", padding: "1rem" }}>
        <h1>sauri</h1>
        <p>Commercial meeting intelligence platform</p>
        <hr />
        <SpeakerTestLogin onLogin={() => setAuthenticated(true)} />
      </main>
    );
  }

  return (
    <main style={{ maxWidth: "800px", margin: "0 auto", padding: "1rem" }}>
      <h1>sauri</h1>
      <p>Commercial meeting intelligence platform</p>
      <button type="button" onClick={handleLogout}>Log out</button>
      <hr />

      {view.type === "list" && (
        <>
          <RegisterForm onRegistered={handleRegistered} />
          <button type="button" onClick={() => setView({ type: "speaker-test" })}>
            Open speaker recognition test
          </button>
          <MeetingList
            refreshKey={refreshKey}
            onSelectMeeting={handleSelectMeeting}
          />
        </>
      )}

      {view.type === "transcript" && (
        <TranscriptView
          meetingId={view.meetingId}
          onBack={() => setView({ type: "list" })}
        />
      )}

      {view.type === "speaker-test" && (
        <>
          <button type="button" onClick={() => setView({ type: "list" })}>
            Back to meetings
          </button>
          <SpeakerRecognitionTestScreen />
        </>
      )}
    </main>
  );
}
