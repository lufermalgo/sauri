import React, { useState } from "react";
import type { Meeting } from "@sauri/shared-types";
import { RegisterForm } from "./components/RegisterForm";
import { MeetingList } from "./components/MeetingList";
import { TranscriptView } from "./components/TranscriptView";
import { SpeakerRecognitionTestScreen } from "./components/SpeakerRecognitionTestScreen";

type View = { type: "list" } | { type: "transcript"; meetingId: string } | { type: "speaker-test" };

export function App() {
  const [view, setView] = useState<View>({ type: "list" });
  const [refreshKey, setRefreshKey] = useState(0);

  function handleRegistered() {
    setRefreshKey((k) => k + 1);
  }

  function handleSelectMeeting(meeting: Meeting) {
    setView({ type: "transcript", meetingId: meeting.id });
  }

  function handleBack() {
    setView({ type: "list" });
  }

  return (
    <main style={{ maxWidth: "800px", margin: "0 auto", padding: "1rem" }}>
      <h1>sauri</h1>
      <p>Commercial meeting intelligence platform</p>
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
        <TranscriptView meetingId={view.meetingId} onBack={handleBack} />
      )}

      {view.type === "speaker-test" && (
        <>
          <button type="button" onClick={handleBack}>Back to meetings</button>
          <SpeakerRecognitionTestScreen />
        </>
      )}
    </main>
  );
}
