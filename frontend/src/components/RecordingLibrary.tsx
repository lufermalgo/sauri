import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { ProcessState } from "@sauri/shared-types";
import type { MeetingListItem } from "@sauri/shared-types";
import { deleteMeeting, listMeetings, renameMeeting } from "../api";
import { copy } from "../copy/es";
import { meeting as meetingText } from "../copy/meeting";
import { applyLibraryQuery, type LibraryQuery } from "../library-query";
import { LIBRARY_CHANGED_EVENT, notifyLibraryChanged } from "../library-events";
import { navigate } from "../router";
import { downloadMeetingMedia } from "../media-download";
import { downloadMeetingSummary } from "../summary-download";
import { downloadMeetingTranscript } from "../transcript-download";
import { Button, ConfirmDialog, Skeleton } from "./ui";
import { LibraryBulkBar } from "./LibraryBulkBar";
import { LibraryBulkDialog } from "./LibraryBulkDialog";
import { LibraryRow, hasSummary, isReady, type RowDownloadKind } from "./LibraryRow";
import { LibraryToolbar } from "./LibraryToolbar";
import { useLibraryBulk, type BulkKind } from "./useLibraryBulk";
import { useLibrarySelection } from "./useLibrarySelection";
import "../styles/library.css";
import "../styles/processing.css";

const text = copy.library;

// Rows still being worked on; while any is visible the list refreshes quietly.
const IN_PROGRESS_STATES: ReadonlySet<ProcessState> = new Set([
  ProcessState.Queued, ProcessState.Joining, ProcessState.Recording, ProcessState.Transcribing,
]);
const LIBRARY_REFRESH_MS = 10_000;

const EMPTY_QUERY: LibraryQuery = { text: "", from: null, to: null, sort: "newest" };

function isQueryActive(query: LibraryQuery): boolean {
  return query.text.trim() !== "" || query.from !== null || query.to !== null || query.sort !== "newest";
}

type GroupKey = "today" | "thisWeek" | "earlier";

const GROUP_ORDER: GroupKey[] = ["today", "thisWeek", "earlier"];

const MS_PER_DAY = 24 * 60 * 60 * 1000;
const WEEK_DAYS = 7;
const SKELETON_ROWS = [
  { title: "38%", topic: "62%" },
  { title: "46%", topic: "54%" },
  { title: "32%", topic: "68%" },
];

function startOfLocalDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Groups by the local calendar date of createdAt, relative to `now`. Missing dates are "earlier". */
function groupKeyFor(createdAt: string | null, now: Date): GroupKey {
  if (!createdAt) return "earlier";
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return "earlier";
  const daysAgo = Math.round((startOfLocalDay(now) - startOfLocalDay(date)) / MS_PER_DAY);
  if (daysAgo <= 0) return "today";
  return daysAgo < WEEK_DAYS ? "thisWeek" : "earlier";
}

function groupMeetings(
  items: MeetingListItem[],
  now: Date,
): Array<{ key: GroupKey; items: MeetingListItem[] }> {
  const buckets: Record<GroupKey, MeetingListItem[]> = { today: [], thisWeek: [], earlier: [] };
  for (const item of items) buckets[groupKeyFor(item.createdAt, now)].push(item);
  return GROUP_ORDER.filter((key) => buckets[key].length > 0).map((key) => ({ key, items: buckets[key] }));
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
    </svg>
  );
}

/** A quiet refresh keeps each row's current preview link: a new signature would reload the image. */
function keepThumbnailUrls(previous: MeetingListItem[], next: MeetingListItem[]): MeetingListItem[] {
  const urls = new Map(previous.map((item) => [item.id, item.thumbnailUrl]));
  return next.map((item) => {
    const current = urls.get(item.id);
    return current && item.thumbnailUrl ? { ...item, thumbnailUrl: current } : item;
  });
}

function LibrarySkeleton() {
  return (
    <ul className="library-list library-skeleton" aria-hidden="true">
      {SKELETON_ROWS.map((row) => (
        <li key={row.title} className="library-skeleton-row">
          <Skeleton className="library-skeleton-thumb" />
          <span className="library-skeleton-main">
            <Skeleton height={14} width={row.title} />
            <Skeleton height={12} width={row.topic} />
          </span>
        </li>
      ))}
    </ul>
  );
}

interface RecordingLibraryProps {
  refreshKey: number;
  onSelectMeeting: (meeting: MeetingListItem) => void;
  /** The recording open in the detail pane, marked in the list. */
  selectedId?: string;
}

/** More transcripts or summaries than this are downloaded only after the user confirms: browsers may block bursts. */
const DOWNLOAD_CONFIRM_ABOVE = 5;

type BulkConfirm = { kind: BulkKind; ids: string[]; skipped: number };

/** The list pane: header strip, icon toolbar and compact rows (DESIGN.md 6, master-detail). */
export function RecordingLibrary({ refreshKey, onSelectMeeting, selectedId }: RecordingLibraryProps) {
  const [meetings, setMeetings] = useState<MeetingListItem[]>([]);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState<LibraryQuery>(EMPTY_QUERY);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [rowNotices, setRowNotices] = useState<Record<string, string>>({});
  const [pendingDelete, setPendingDelete] = useState<MeetingListItem | null>(null);
  const [bulkConfirm, setBulkConfirm] = useState<BulkConfirm | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const headerRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  // Row to focus once a deletion has re-rendered the list.
  const focusAfterRemoval = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(false);

    listMeetings()
      .then((data) => {
        // The API can return a null title for recordings that never had one.
        if (!cancelled) setMeetings(data.map((item) => ({ ...item, title: item.title ?? "" })));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [refreshKey, attempt]);

  const inProgress = meetings.some((meeting) => IN_PROGRESS_STATES.has(meeting.processState));
  // Quiet refresh: no loading state, and a failed refresh keeps the current list.
  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      listMeetings()
        .then((data) => {
          if (!cancelled) {
            const refreshed = data.map((item) => ({ ...item, title: item.title ?? "" }));
            setMeetings((current) => keepThumbnailUrls(current, refreshed));
          }
        })
        .catch(() => undefined);
    };
    // The open recording can be renamed or deleted from the detail pane beside this list.
    window.addEventListener(LIBRARY_CHANGED_EVENT, refresh);
    const timer = inProgress
      ? setInterval(() => { if (!document.hidden) refresh(); }, LIBRARY_REFRESH_MS)
      : undefined;
    return () => {
      cancelled = true;
      window.removeEventListener(LIBRARY_CHANGED_EVENT, refresh);
      clearInterval(timer);
    };
  }, [inProgress]);

  // Without criteria the list keeps the order received from the API and is grouped by date;
  // any search, filter or non-default sort shows a flat list.
  const active = isQueryActive(query);
  const visible = useMemo(() => (active ? applyLibraryQuery(meetings, query) : meetings), [active, meetings, query]);
  const groups = useMemo(() => (active ? null : groupMeetings(visible, new Date())), [active, visible]);
  const order = useMemo(
    () => (groups ? groups.flatMap((group) => group.items) : visible).map((meeting) => meeting.id),
    [groups, visible],
  );
  const knownIds = useMemo(() => meetings.map((meeting) => meeting.id), [meetings]);
  const selection = useLibrarySelection(order, knownIds);
  const selectedCount = selection.selected.size;

  const meetingsRef = useRef(meetings);
  meetingsRef.current = meetings;

  /** Deletes on the server, then takes the recording out of the list, the selection and, if open, the detail. */
  const removeMeeting = useCallback(async (id: string, focusNext?: string) => {
    await deleteMeeting(id);
    if (focusNext !== undefined) focusAfterRemoval.current = focusNext;
    setMeetings((current) => current.filter((meeting) => meeting.id !== id));
    selection.remove([id]);
    if (id === selectedId) navigate({ name: "library" });
  }, [selection.remove, selectedId]);

  const bulk = useLibraryBulk(async (kind, id) => {
    if (kind === "delete") {
      await removeMeeting(id);
    } else {
      const meeting = meetingsRef.current.find((candidate) => candidate.id === id);
      if (kind === "downloadSummary") await downloadMeetingSummary(id, meeting?.title);
      else await downloadMeetingTranscript(id, meeting?.title);
    }
  });

  // After a deletion the keyboard lands on the neighbouring row, or on the header when none is left.
  useEffect(() => {
    const id = focusAfterRemoval.current;
    if (id === null) return;
    focusAfterRemoval.current = null;
    const rows = Array.from(bodyRef.current?.querySelectorAll<HTMLElement>("[data-row-id]") ?? []);
    (rows.find((row) => row.dataset.rowId === id) ?? headerRef.current)?.focus();
  }, [meetings]);

  const setRowError = (id: string, message: string | null) => setRowErrors((current) => {
    const { [id]: _removed, ...rest } = current;
    return message === null ? rest : { ...rest, [id]: message };
  });

  const goToUpload = () => navigate({ name: "upload" });

  const openRow = (meeting: MeetingListItem, modifiers: { range: boolean; toggle: boolean }) => {
    if (modifiers.range) selection.selectRange(meeting.id);
    else if (modifiers.toggle) selection.toggle(meeting.id);
    else onSelectMeeting(meeting);
  };

  const toggleChecked = (id: string, range: boolean) => {
    if (range) selection.selectRange(id);
    else selection.toggle(id);
  };

  const renameRow = async (id: string, title: string) => {
    const result = await renameMeeting(id, title);
    setMeetings((current) => current.map((meeting) => (meeting.id === id ? { ...meeting, title: result.title } : meeting)));
    setRenamingId(null);
    notifyLibraryChanged();
  };

  const setRowNotice = (id: string, message: string | null) => setRowNotices((current) => {
    const { [id]: _removed, ...rest } = current;
    return message === null ? rest : { ...rest, [id]: message };
  });

  // Recordings whose video is being saved: a second click must not open a second file picker.
  const mediaDownloads = useRef(new Set<string>());

  const downloadMedia = async (meeting: MeetingListItem) => {
    if (mediaDownloads.current.has(meeting.id)) return;
    mediaDownloads.current.add(meeting.id);
    setRowNotice(meeting.id, meetingText.mediaProgress(null));
    try {
      const outcome = await downloadMeetingMedia(meeting.id, meeting.title,
        (percent) => setRowNotice(meeting.id, meetingText.mediaProgress(percent)));
      setRowNotice(meeting.id, outcome === "opened" ? meetingText.mediaOpened : null);
    } catch {
      setRowNotice(meeting.id, null);
      setRowError(meeting.id, text.row.downloadMediaFailed);
    } finally {
      mediaDownloads.current.delete(meeting.id);
    }
  };

  const downloadRow = async (meeting: MeetingListItem, kind: RowDownloadKind) => {
    setRowError(meeting.id, null);
    setRowNotice(meeting.id, null);
    if (kind === "media") { await downloadMedia(meeting); return; }
    try {
      if (kind === "summary") await downloadMeetingSummary(meeting.id, meeting.title);
      else await downloadMeetingTranscript(meeting.id, meeting.title);
    } catch {
      setRowError(meeting.id, kind === "summary" ? text.row.downloadSummaryFailed : text.row.downloadFailed);
    }
  };

  const confirmRowDelete = async () => {
    const meeting = pendingDelete;
    setPendingDelete(null);
    if (!meeting) return;
    setRowError(meeting.id, null);
    const index = order.indexOf(meeting.id);
    try {
      await removeMeeting(meeting.id, order[index + 1] ?? order[index - 1] ?? "");
      setAnnouncement(text.row.deleted(meeting.title.trim() || text.untitled));
    } catch {
      setRowError(meeting.id, text.row.deleteFailed);
    }
  };

  /** Selected ids in the order the rows are shown. */
  const selectedIds = () => [
    ...order.filter((id) => selection.selected.has(id)),
    ...[...selection.selected].filter((id) => !order.includes(id)),
  ];

  const startBulkDownload = (kind: "download" | "downloadSummary") => {
    const applies = kind === "downloadSummary" ? hasSummary : isReady;
    const ready = selectedIds().filter((id) => {
      const meeting = meetings.find((candidate) => candidate.id === id);
      return meeting !== undefined && applies(meeting);
    });
    const skipped = selectedCount - ready.length;
    if (ready.length === 0) bulk.showEmpty(kind, skipped);
    else if (ready.length > DOWNLOAD_CONFIRM_ABOVE) setBulkConfirm({ kind, ids: ready, skipped });
    else void bulk.start(kind, ready, skipped);
  };

  const runConfirmedBulk = () => {
    const confirmed = bulkConfirm;
    setBulkConfirm(null);
    if (confirmed) void bulk.start(confirmed.kind, confirmed.ids, confirmed.skipped);
  };

  const modalOpen = pendingDelete !== null || bulkConfirm !== null || bulk.run !== null;

  // Escape clears the selection unless something inside the list already used it (a menu, a rename).
  const onSectionKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape" && !event.defaultPrevented && selectedCount > 0 && !modalOpen) {
      event.preventDefault();
      selection.clear();
    }
  };

  // Up/Down/Home/End move between rows; only one row is in the tab order, so the list is one Tab stop.
  const onListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!(event.target instanceof HTMLElement) || !event.target.matches(".library-item")) return;
    const rows = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(".library-item"));
    const index = rows.indexOf(event.target);
    const target = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: rows.length - 1 }[event.key];
    if (target === undefined) return;
    event.preventDefault();
    rows[Math.min(Math.max(target, 0), rows.length - 1)]?.focus();
  };

  // The search tools belong to a list that exists: not while loading, on error or with no recordings.
  const showToolbar = !loading && !failed && meetings.length > 0;
  // With a recording open beside the list the page title belongs to that recording, so the list
  // title is a plain label: one h1 per screen.
  const Title = selectedId === undefined ? "h1" : "p";
  const selecting = showToolbar && selectedCount > 0;
  const header = selecting ? (
    <LibraryBulkBar count={selectedCount} allState={selection.allState} headerRef={headerRef}
      onToggleAll={selection.toggleAllVisible} onClear={selection.clear}
      onDownload={() => startBulkDownload("download")}
      onDownloadSummaries={() => startBulkDownload("downloadSummary")} onDelete={() => setBulkConfirm({ kind: "delete", ids: selectedIds(), skipped: 0 })} />
  ) : (
    <>
      <div ref={headerRef} tabIndex={-1} className="ui-pane-header">
        <Title className="ui-pane-title" id="library-title">{text.title}</Title>
        <Button variant="primary" size="sm" onClick={goToUpload}>
          <PlusIcon />
          {text.upload}
        </Button>
      </div>
      {showToolbar && (
        <LibraryToolbar query={query} onChange={setQuery}
          selectAll={{ state: selection.allState, disabled: order.length === 0, onChange: selection.toggleAllVisible }} />
      )}
    </>
  );

  let body: React.ReactNode;
  if (loading) {
    body = (
      <>
        <p role="status" className="library-message">{text.loading}</p>
        <LibrarySkeleton />
      </>
    );
  } else if (failed) {
    body = (
      <div className="library-state">
        <p role="alert" className="library-message">{text.error}</p>
        <Button variant="secondary" onClick={() => setAttempt((value) => value + 1)}>
          {text.retry}
        </Button>
      </div>
    );
  } else if (meetings.length === 0) {
    body = (
      <div className="library-state">
        <p className="library-message">{text.empty}</p>
        <Button variant="primary" onClick={goToUpload}>{text.upload}</Button>
      </div>
    );
  } else {
    const tabbableId = activeId !== null && order.includes(activeId) ? activeId
      : selectedId !== undefined && order.includes(selectedId) ? selectedId : order[0];
    const renderRow = (meeting: MeetingListItem) => (
      <LibraryRow key={meeting.id} meeting={meeting} open={meeting.id === selectedId}
        checked={selection.selected.has(meeting.id)} tabbable={meeting.id === tabbableId}
        renaming={meeting.id === renamingId} error={rowErrors[meeting.id] ?? null} notice={rowNotices[meeting.id] ?? null}
        onOpen={openRow} onToggleChecked={toggleChecked} onFocusRow={setActiveId}
        onStartRename={(id) => { setRowError(id, null); setRenamingId(id); }}
        onRename={renameRow} onCancelRename={() => setRenamingId(null)}
        onDownload={(target, kind) => { void downloadRow(target, kind); }} onDelete={setPendingDelete} />
    );

    if (visible.length === 0) {
      body = <p role="status" className="library-message">{text.noMatch}</p>;
    } else if (groups === null) {
      body = <ul className="library-list" aria-label={text.listLabel}>{visible.map(renderRow)}</ul>;
    } else {
      body = groups.map((group) => (
        <section key={group.key} className="library-group" aria-labelledby={`library-group-${group.key}`}>
          <h2 id={`library-group-${group.key}`} className="library-group-title">{text.groups[group.key]}</h2>
          <ul className="library-list">{group.items.map(renderRow)}</ul>
        </section>
      ));
    }
  }

  const deleteBulk = bulkConfirm?.kind === "delete";
  const summariesBulk = bulkConfirm?.kind === "downloadSummary";
  return (
    <section className="ui-pane library" id="library-pane" aria-labelledby="library-title"
      data-selecting={selecting || undefined} onKeyDown={onSectionKeyDown}>
      {header}
      <div ref={bodyRef} className="ui-pane-body library-body" onKeyDown={onListKeyDown}>{body}</div>
      <p role="status" className="library-sr-only">{announcement}</p>
      {pendingDelete && (
        <ConfirmDialog title={text.row.deleteTitle} body={text.row.deleteBody} confirmLabel={text.row.delete}
          cancelLabel={text.row.cancel} onConfirm={() => { void confirmRowDelete(); }}
          onCancel={() => setPendingDelete(null)} />
      )}
      {bulkConfirm && (
        <ConfirmDialog
          title={deleteBulk ? text.bulk.deleteConfirmTitle(bulkConfirm.ids.length)
            : summariesBulk ? text.bulk.downloadSummariesConfirmTitle(bulkConfirm.ids.length)
              : text.bulk.downloadConfirmTitle(bulkConfirm.ids.length)}
          body={deleteBulk ? text.bulk.deleteConfirmBody
            : summariesBulk ? text.bulk.downloadSummariesConfirmBody : text.bulk.downloadConfirmBody}
          confirmLabel={deleteBulk ? text.bulk.deleteConfirm : text.bulk.downloadConfirm}
          cancelLabel={text.bulk.cancel} onConfirm={runConfirmedBulk} onCancel={() => setBulkConfirm(null)} />
      )}
      {bulk.run && (
        <LibraryBulkDialog run={bulk.run} onStop={bulk.stop} onRetry={bulk.retry} onClose={bulk.close}
          returnFocus={() => headerRef.current} />
      )}
    </section>
  );
}
