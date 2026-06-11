import React, { useState } from "react";
import type { Reunion } from "@sauri/shared-types";
import { RegisterForm } from "./components/RegisterForm";
import { ReunionList } from "./components/ReunionList";
import { TranscripcionView } from "./components/TranscripcionView";

type View = { type: "list" } | { type: "transcripcion"; reunionId: string };

export function App() {
  const [view, setView] = useState<View>({ type: "list" });
  const [refreshKey, setRefreshKey] = useState(0);

  function handleRegistered() {
    setRefreshKey((k) => k + 1);
  }

  function handleSelectReunion(reunion: Reunion) {
    setView({ type: "transcripcion", reunionId: reunion.id });
  }

  function handleBack() {
    setView({ type: "list" });
  }

  return (
    <main style={{ maxWidth: "800px", margin: "0 auto", padding: "1rem" }}>
      <h1>sauri</h1>
      <p>Plataforma de inteligencia de reuniones comerciales</p>
      <hr />

      {view.type === "list" && (
        <>
          <RegisterForm onRegistered={handleRegistered} />
          <ReunionList
            refreshKey={refreshKey}
            onSelectReunion={handleSelectReunion}
          />
        </>
      )}

      {view.type === "transcripcion" && (
        <TranscripcionView reunionId={view.reunionId} onBack={handleBack} />
      )}
    </main>
  );
}
