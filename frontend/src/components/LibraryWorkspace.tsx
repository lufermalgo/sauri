import { useEffect, useRef } from "react";
import { navigate } from "../router";
import { copy } from "../copy/es";
import { forgetLastMeeting, rememberLastMeeting } from "../last-meeting";
import { RecordingLibrary } from "./RecordingLibrary";
import { TranscriptView } from "./TranscriptView";
import { useLibraryPaneHidden, WORKSPACE_WIDE_QUERY } from "./useLibraryPane";
import { hiddenPaneAttributes, LIBRARY_PANE_ID } from "./useSecondaryPane";
import { useMediaQuery } from "./useMediaQuery";
import { Button } from "./ui";
import "../styles/workspace.css";

export { WORKSPACE_WIDE_QUERY };

interface LibraryWorkspaceProps {
  /** The recording open in the detail pane; none shows an empty state on wide screens. */
  meetingId?: string;
  /** The open recording was reopened by the portal at start, not chosen by the user: if it is gone, fall back to the library. */
  restored?: boolean;
}

/**
 * Master-detail workspace for `/` and `/meetings/:id`. Wide screens show the list pane (340px) and
 * the detail pane together; narrow ones show one at a time, with a back button in the detail header.
 * On wide screens the list pane can be hidden from the side panel, with or without a recording open
 * (the choice is remembered); it stays mounted, so its search, scroll and selection are still there
 * when it comes back. Opening a recording remembers it, so the portal can reopen it at the next start.
 */
export function LibraryWorkspace({ meetingId, restored = false }: LibraryWorkspaceProps) {
  const wide = useMediaQuery(WORKSPACE_WIDE_QUERY);
  const showList = wide || meetingId === undefined;
  const showDetail = wide || meetingId !== undefined;
  const { hidden: remembered, setHidden } = useLibraryPaneHidden();
  const hidden = wide && remembered;
  const focusListOnShow = useRef(false);

  // After the empty state's button brings the list back, the keyboard continues inside it.
  useEffect(() => {
    if (hidden || !focusListOnShow.current) return;
    focusListOnShow.current = false;
    const pane = document.getElementById(LIBRARY_PANE_ID);
    (pane?.querySelector<HTMLElement>("[data-row-id][tabindex='0']") ?? pane?.querySelector<HTMLElement>(".ui-pane-header"))?.focus();
  }, [hidden]);

  const latest = useRef({ meetingId, restored });
  latest.current = { meetingId, restored };

  const fallBackToLibrary = (id: string) => {
    forgetLastMeeting(id);
    if (latest.current.restored && latest.current.meetingId === id) navigate({ name: "library" }, { replace: true });
  };

  return (
    <div className="workspace" data-layout={wide ? "split" : "single"}>
      {showList && (
        <div className="workspace-list" {...hiddenPaneAttributes(hidden)}>
          <RecordingLibrary
            refreshKey={0}
            selectedId={meetingId}
            onSelectMeeting={(item) => navigate({ name: "meeting", meetingId: item.id })}
            onListLoaded={(ids) => {
              const open = latest.current.meetingId;
              if (open !== undefined && !ids.includes(open)) fallBackToLibrary(open);
            }}
          />
        </div>
      )}
      {showDetail && (
        <div className="workspace-detail">
          {meetingId !== undefined ? (
            <TranscriptView
              meetingId={meetingId}
              onBack={wide ? undefined : () => navigate({ name: "library" })}
              onResolved={(outcome) => (outcome === "found" ? rememberLastMeeting(meetingId) : fallBackToLibrary(meetingId))}
            />
          ) : hidden ? (
            <div className="workspace-empty workspace-empty--action">
              <h1 className="workspace-empty-title">{copy.library.chooseRecording}</h1>
              <Button
                variant="primary"
                onClick={() => { focusListOnShow.current = true; setHidden(false); }}
              >
                {copy.shell.libraryPane.show}
              </Button>
            </div>
          ) : (
            <p className="workspace-empty">{copy.library.selectHint}</p>
          )}
        </div>
      )}
    </div>
  );
}
