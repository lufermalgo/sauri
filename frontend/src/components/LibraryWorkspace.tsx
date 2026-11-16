import { navigate } from "../router";
import { copy } from "../copy/es";
import { RecordingLibrary } from "./RecordingLibrary";
import { TranscriptView } from "./TranscriptView";
import { useMediaQuery } from "./useMediaQuery";
import "../styles/workspace.css";

/** From this width the list and the open recording sit side by side; below it they are two steps. */
export const WORKSPACE_WIDE_QUERY = "(min-width: 1100px)";

interface LibraryWorkspaceProps {
  /** The recording open in the detail pane; none shows a quiet hint on wide screens. */
  meetingId?: string;
}

/**
 * Master-detail workspace for `/` and `/meetings/:id`. Wide screens show the list pane (340px) and
 * the detail pane together; narrow ones show one at a time, with a back button in the detail header.
 */
export function LibraryWorkspace({ meetingId }: LibraryWorkspaceProps) {
  const wide = useMediaQuery(WORKSPACE_WIDE_QUERY);
  const showList = wide || meetingId === undefined;
  const showDetail = wide || meetingId !== undefined;

  return (
    <div className="workspace" data-layout={wide ? "split" : "single"}>
      {showList && (
        <RecordingLibrary
          refreshKey={0}
          selectedId={meetingId}
          onSelectMeeting={(item) => navigate({ name: "meeting", meetingId: item.id })}
        />
      )}
      {showDetail && (
        <div className="workspace-detail">
          {meetingId !== undefined ? (
            <TranscriptView
              meetingId={meetingId}
              onBack={wide ? undefined : () => navigate({ name: "library" })}
            />
          ) : (
            <p className="workspace-empty">{copy.library.selectHint}</p>
          )}
        </div>
      )}
    </div>
  );
}
