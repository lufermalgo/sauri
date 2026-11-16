import { Puzzle } from "lucide-react";
import { copy } from "../../copy/es";
import { Card, Icon } from "../ui";

/** Informational only: these options live in the Chrome extension, so there is nothing to change here. */
export function RecordingSettings() {
  return (
    <Card className="settings-card" aria-labelledby="settings-recording-title">
      <h3 id="settings-recording-title" className="settings-card-title settings-card-title--icon">
        <Icon icon={Puzzle} />
        {copy.settings.recording.title}
      </h3>
      <p className="settings-help">{copy.settings.recording.body}</p>
    </Card>
  );
}
