import { useEffect } from "react";
import { navigate } from "../router";
import { copy } from "../copy/es";
import { RecordingLibrary } from "./RecordingLibrary";
import { TranscriptView } from "./TranscriptView";
import { useLibraryPaneHidden, WORKSPACE_WIDE_QUERY } from "./useLibraryPane";
import { useMediaQuery } from "./useMediaQuery";
import "../styles/workspace.css";

export { WORKSPACE_WIDE_QUERY };

interface LibraryWorkspaceProps {
  /** The recording open in the detail pane; none shows a quiet hint on wide screens. */
  meetingId?: string;
}

/**
 * Master-detail workspace for `/` and `/meetings/:id`. Wide screens show the list pane (340px) and
 * the detail pane together; narrow ones show one at a time, with a back button in the detail header.
 * With a recording open the list pane can be hidden from the side panel (the choice is remembered);
 * it stays mounted, so its search, scroll and selection are still there when it comes back.
 */
export function LibraryWorkspace({ meetingId }: LibraryWorkspaceProps) {
  const wide = useMediaQuery(WORKSPACE_WIDE_QUERY);
  const showList = wide || meetingId === undefined;
  const showDetail = wide || meetingId !== undefined;
  const { hidden: remembered, setHidden } = useLibraryPaneHidden();
  // The list is the content on `/`, so it is never hidden there, and coming back to `/` shows it again.
  const hidden = wide && meetingId !== undefined && remembered;
  useEffect(() => {
    if (meetingId === undefined && remembered) setHidden(false);
  }, [meetingId, remembered, setHidden]);

  return (
    <div className="workspace" data-layout={wide ? "split" : "single"}>
      {showList && (
        <div className="workspace-list" data-hidden={hidden || undefined} aria-hidden={hidden || undefined}
          {...(hidden ? { inert: "" } : {})}>
          <RecordingLibrary
            refreshKey={0}
            selectedId={meetingId}
            onSelectMeeting={(item) => navigate({ name: "meeting", meetingId: item.id })}
          />
        </div>
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
