import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { copy } from './overlay/copy';
import { cancelCountdown, hideRecordingUI, showCountdown, showNotice, syncRecordingUI, type RecordingUI } from './overlay/recording';

const state: RecordingUI = { sessionId: 'current', paused: false, elapsedMs: 0, segmentStartedAt: 1000, showControlBar: true, micLabel: 'Test input' };
const host = () => document.getElementById('sauri-recording-host');
const root = () => host()!.shadowRoot!;

beforeEach(() => {
  vi.stubGlobal('chrome', { runtime: { sendMessage: vi.fn(async () => ({ ok: true })) } });
});
afterEach(() => {
  cancelCountdown();
  hideRecordingUI();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe('Meet isolated recording UI', () => {
  it('replaces a stale closed banner and deduplicates even across script reloads', async () => {
    const stale = document.createElement('div');
    stale.id = 'sauri-consent-banner-host';
    stale.attachShadow({ mode: 'closed' });
    document.body.append(stale);
    expect(showNotice()).toBe(true);
    vi.resetModules();
    const reloaded = await import('./overlay/recording');
    expect(reloaded.showNotice()).toBe(false);
    expect(document.querySelectorAll('#sauri-consent-banner-host')).toHaveLength(1);
    const banner = document.getElementById('sauri-consent-banner-host')!;
    expect(banner.shadowRoot!.textContent).toContain(copy.notice);
    expect(banner.shadowRoot!.textContent).toContain(copy.noticeHint);
    banner.shadowRoot!.querySelector('button')!.click();
    expect(document.getElementById('sauri-consent-banner-host')).toBeNull();
  });

  it('counts down three seconds and cleans up the open shadow host', async () => {
    vi.useFakeTimers();
    const done = showCountdown(3, 'countdown');
    const countdown = document.getElementById('sauri-countdown-host')!;
    expect(countdown.shadowRoot!.querySelector('strong')!.textContent).toBe('3');
    await vi.advanceTimersByTimeAsync(1000);
    expect(countdown.shadowRoot!.querySelector('strong')!.textContent).toBe('2');
    await vi.advanceTimersByTimeAsync(2000);
    expect(await done).toEqual({ ok: true });
    expect(document.getElementById('sauri-countdown-host')).toBeNull();
  });

  it('cancels the countdown without completing it and restores focus', async () => {
    const trigger = document.createElement('button');
    document.body.append(trigger);
    trigger.focus();
    const done = showCountdown(3, 'countdown');
    document.getElementById('sauri-countdown-host')!.shadowRoot!.querySelector('button')!.click();
    expect(await done).toEqual({ ok: false });
    expect(document.activeElement).toBe(trigger);
  });

  it('keeps controls hidden without hiding the recording notice', () => {
    showNotice();
    syncRecordingUI({ ...state, showControlBar: false });
    expect(host()).toBeNull();
    expect(document.getElementById('sauri-consent-banner-host')).not.toBeNull();
  });

  it('sends bound pause/resume/stop commands and displays only the active microphone', async () => {
    syncRecordingUI(state);
    root().querySelector<HTMLButtonElement>('.pause')!.click();
    await vi.waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'pause-capture', sessionId: 'current' }));
    await vi.waitFor(() => expect(root().querySelector('.pause')).not.toBeDisabled());
    syncRecordingUI({ ...state, paused: true, elapsedMs: 5000 });
    expect(root().querySelector('.pause')).toHaveAccessibleName(copy.resume);
    root().querySelector<HTMLButtonElement>('.pause')!.click();
    await vi.waitFor(() => expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'resume-capture', sessionId: 'current' }));
    await vi.waitFor(() => expect(root().querySelector('.save')).not.toBeDisabled());
    root().querySelector<HTMLButtonElement>('.save')!.click();
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'stop-capture', sessionId: 'current' });
    expect(root().querySelectorAll('option')).toHaveLength(1);
    expect(root().querySelector('option')!.textContent).toBe('Test input');
  });

  it('draws Lucide icons in the bar while icon-only buttons keep their accessible names', () => {
    syncRecordingUI(state);
    const names: Record<string, string> = { handle: copy.drag, cancel: copy.cancelRecording, pause: copy.pause, save: copy.stop };
    for (const [name, label] of Object.entries(names)) {
      const button = root().querySelector<HTMLButtonElement>(`.${name}`)!;
      expect(button.querySelector('svg[aria-hidden="true"]')).not.toBeNull();
      expect(button).toHaveAccessibleName(label);
      expect(button.textContent).toBe('');
    }
    const pauseIcon = root().querySelector('.pause svg')!.innerHTML;
    syncRecordingUI({ ...state, paused: true, elapsedMs: 5000 });
    expect(root().querySelectorAll('.pause svg')).toHaveLength(1);
    expect(root().querySelector('.pause svg')!.innerHTML).not.toBe(pauseIcon);
    expect(root().querySelector('.pause')).toHaveAccessibleName(copy.resume);
    expect(root().querySelectorAll('.mic svg')).toHaveLength(2);
  });

  it('draws an icon in the notice close button', () => {
    showNotice();
    const close = document.getElementById('sauri-consent-banner-host')!.shadowRoot!.querySelector('button')!;
    expect(close.querySelector('svg')).not.toBeNull();
    expect(close).toHaveAccessibleName(copy.close);
  });

  it('requires explicit confirmation before discarding and keeps recording on dismissal', async () => {
    syncRecordingUI(state);
    root().querySelector<HTMLButtonElement>('.cancel')!.click();
    expect(root().querySelector('[role="alertdialog"]')).toHaveAccessibleName(copy.confirm);
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    root().querySelector<HTMLButtonElement>('.keep')!.click();
    expect(root().querySelector('.confirmation')).toBeNull();
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalled();
    root().querySelector<HTMLButtonElement>('.cancel')!.click();
    root().querySelector<HTMLButtonElement>('.discard')!.click();
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'cancel-capture', sessionId: 'current' });
  });

  it('leaves controls available and reports a rejected or unsupported pause', async () => {
    vi.mocked(chrome.runtime.sendMessage).mockResolvedValue({ ok: false });
    syncRecordingUI(state);
    root().querySelector<HTMLButtonElement>('.pause')!.click();
    await vi.waitFor(() => expect(root().querySelector('[role="alert"]')!.textContent).toBe(copy.controlError));
    expect(root().querySelector('.pause')).not.toBeDisabled();
    expect(root().querySelector('.pause')).toHaveAccessibleName(copy.pause);
  });

  it('constrains drag and keyboard movement to the tab and clamps on resize', () => {
    syncRecordingUI(state);
    const bar = root().querySelector<HTMLElement>('.bar')!;
    const handle = root().querySelector<HTMLButtonElement>('.handle')!;
    Object.defineProperties(bar, { offsetWidth: { value: 400 }, offsetHeight: { value: 60 } });
    vi.spyOn(bar, 'getBoundingClientRect').mockReturnValue({ left: 24, top: 500 } as DOMRect);
    handle.setPointerCapture = vi.fn();
    handle.dispatchEvent(new MouseEvent('pointerdown', { clientX: 30, clientY: 505 }));
    handle.dispatchEvent(new MouseEvent('pointermove', { clientX: 3000, clientY: -500 }));
    expect(bar.style.left).toBe(`${window.innerWidth - 400}px`);
    expect(bar.style.top).toBe('0px');
    handle.dispatchEvent(new Event('pointerup'));
    handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }));
    expect(bar.style.left).toBe('14px');
    window.dispatchEvent(new Event('resize'));
    expect(bar.style.left).toBe('24px');
    expect(document.body.style.cssText).toBe('');
    hideRecordingUI();
    expect(host()).toBeNull();
  });
});


describe('content message bridge', () => {
  async function loadContent(recordingState?: RecordingUI) {
    vi.resetModules();
    let listener!: (message: object, sender: object, reply: (value: unknown) => void) => boolean;
    vi.stubGlobal('MutationObserver', class { observe() {} });
    const send = vi.fn(async (message: { type: string }) => message.type === 'get-recording-ui' ? { state: recordingState } : { ok: true });
    vi.stubGlobal('chrome', { runtime: {
      onMessage: { addListener: (handler: typeof listener) => { listener = handler; } },
      sendMessage: send,
    } });
    await import('./content');
    const overlay = await import('./overlay/recording');
    return { listener, overlay, send };
  }

  it('restores recording controls after loading a Meet tab and cleans up on finish', async () => {
    const { listener, overlay, send } = await loadContent(state);
    try {
      expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({ type: 'get-recording-ui' });
      expect(host()).not.toBeNull();
      listener({ type: 'show-consent-banner' }, {}, vi.fn());
      listener({ type: 'show-consent-banner' }, {}, vi.fn());
      expect(document.querySelectorAll('#sauri-consent-banner-host')).toHaveLength(1);
      expect(send.mock.calls.filter(([message]) => message.type === 'notification-emitted')).toHaveLength(1);
      listener({ type: 'recording-ui', state: { ...state, paused: true } }, {}, vi.fn());
      expect(root().querySelector('.pause')).toHaveAccessibleName(copy.resume);
      listener({ type: 'hide-consent-banner' }, {}, vi.fn());
      expect(host()).toBeNull();
      expect(document.getElementById('sauri-consent-banner-host')).toBeNull();
    } finally { overlay.hideRecordingUI(); }
  });

  it('holds the countdown response until completion or cancellation', async () => {
    const { listener, overlay } = await loadContent();
    const reply = vi.fn();
    try {
      expect(listener({ type: 'show-countdown', seconds: 3, requestId: 'request' }, {}, reply)).toBe(true);
      expect(reply).not.toHaveBeenCalled();
      listener({ type: 'cancel-countdown' }, {}, vi.fn());
      await vi.waitFor(() => expect(reply).toHaveBeenCalledWith({ ok: false }));
      expect(document.getElementById('sauri-countdown-host')).toBeNull();
    } finally { overlay.cancelCountdown(); }
  });
});
