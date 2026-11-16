import { ChevronDown, GripVertical, Mic, Pause, Play, Square, X } from 'lucide';
import { t } from '../i18n';
import tokens from '../core/design/tokens.css?raw';
import { icon, iconHtml } from './icons';

export interface RecordingUI {
  sessionId: string;
  paused: boolean;
  elapsedMs: number;
  segmentStartedAt?: number;
  showControlBar: boolean;
  micLabel?: string;
  micActive?: boolean;
}

// The same token file as the extension pages, resolved inside the shadow root through `:host`.
const styles = `
  ${tokens}
  :host { all: initial; color-scheme: light dark; font: var(--ds-text-base)/var(--ds-leading) var(--ds-font-sans); color: var(--ds-fg); }
  * { box-sizing: border-box; }
  button, select { font: inherit; cursor: pointer; min-height: var(--ds-target); border-radius: var(--ds-radius-md); padding: var(--ds-space-2) var(--ds-space-3); }
  button { border: 0; display: inline-flex; align-items: center; justify-content: center; min-width: var(--ds-target); }
  svg { display: block; flex: 0 0 auto; }
  button:focus-visible, select:focus-visible { outline: var(--ds-focus-width) solid var(--ds-focus); outline-offset: var(--ds-focus-offset); }
  [hidden] { display: none !important; }
  .dot { display: inline-block; flex: 0 0 auto; width: 12px; height: 12px; border-radius: 50%; background: var(--ds-recording); animation: pulse 1.4s infinite; }
  @keyframes pulse { 50% { opacity: .35; } }
  @media (prefers-reduced-motion: reduce) { .dot { animation: none; } }
  .notice { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); width: min(532px, calc(100vw - 24px)); display: flex; align-items: center; gap: var(--ds-space-3); padding: var(--ds-space-3) var(--ds-space-4); border-radius: var(--ds-radius-lg); border: 1px solid var(--ds-border-strong); background: var(--ds-surface-raised); color: var(--ds-fg); box-shadow: var(--ds-shadow-md); }
  .notice button { background: transparent; color: var(--ds-fg-muted); }
  .shade { position: fixed; inset: 0; background: var(--ds-scrim-strong); color: var(--ds-on-scrim); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--ds-space-3); text-align: center; padding: var(--ds-space-4); }
  .shade strong { font: 600 clamp(100px, 25vw, 200px)/1 var(--ds-font-sans); font-variant-numeric: tabular-nums; }
  .shade h2 { font-size: var(--ds-text-xl); font-weight: 600; margin: 0; }
  .shade button { margin-top: var(--ds-space-3); background: transparent; border: 1px solid var(--ds-on-scrim); color: var(--ds-on-scrim); padding: var(--ds-space-2) var(--ds-space-6); }
  .shade button:focus-visible { outline-color: var(--ds-on-scrim); }
  .bar { position: fixed; left: 24px; bottom: 28px; max-width: calc(100vw - 16px); display: flex; flex-wrap: wrap; align-items: center; gap: var(--ds-space-2); padding: var(--ds-space-2); border-radius: var(--ds-radius-lg); border: 1px solid var(--ds-border-strong); background: var(--ds-surface-raised); color: var(--ds-fg); box-shadow: var(--ds-shadow-md); }
  .bar button, .bar select { background: transparent; color: var(--ds-fg); }
  .bar .pause { background: var(--ds-fill); }
  .bar .save { background: var(--ds-accent); color: var(--ds-accent-fg); }
  .bar .dot { width: 10px; height: 10px; }
  .bar.paused .dot { animation: none; background: var(--ds-fg-subtle); }
  .time { font: var(--ds-text-base) var(--ds-font-mono); font-variant-numeric: tabular-nums; padding: 0 var(--ds-space-2); }
  .handle { touch-action: none; cursor: grab; }
  .bar select { max-width: 190px; border: 1px solid var(--ds-border-strong); background: var(--ds-surface); appearance: none; padding: var(--ds-space-2) 30px var(--ds-space-2) 36px; }
  .mic { position: relative; display: inline-flex; align-items: center; }
  .mic svg { position: absolute; pointer-events: none; }
  .mic .lead { left: var(--ds-space-3); }
  .mic .chevron { right: 10px; }
  .bar option { color: var(--ds-fg); background: var(--ds-surface-raised); }
  .confirmation { position: fixed; left: 24px; bottom: 100px; width: min(340px, calc(100vw - 32px)); padding: var(--ds-space-4); border-radius: var(--ds-radius-lg); border: 1px solid var(--ds-border-strong); background: var(--ds-surface-raised); color: var(--ds-fg); box-shadow: var(--ds-shadow-md); }
  .confirmation p { color: var(--ds-fg-muted); font-size: var(--ds-text-md); }
  .confirmation button { background: var(--ds-fill-hover); color: var(--ds-accent-text); margin: var(--ds-space-1); }
  .confirmation .discard { background: var(--ds-danger); color: var(--ds-danger-fg); }
  .error { flex-basis: 100%; color: var(--ds-danger-text); }
`;

function createHost(id: string): ShadowRoot {
  const host = document.createElement('div');
  host.id = id;
  host.style.cssText = 'all:initial;color-scheme:light dark;position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = `${styles} .notice, .shade, .bar, .confirmation { pointer-events: auto; }`;
  shadow.append(style);
  document.documentElement.append(host);
  return shadow;
}

/** "meeting" keeps the Google Meet wording; "tab" is neutral for any other page. */
export type OverlayVariant = 'meeting' | 'tab';

export function showNotice(variant: OverlayVariant = 'meeting'): boolean {
  const existing = document.getElementById('sauri-consent-banner-host');
  if (existing?.shadowRoot) return false;
  // A previous extension version may have left a closed shadow root behind.
  existing?.remove();
  const shadow = createHost('sauri-consent-banner-host');
  const notice = document.createElement('div');
  notice.className = 'notice';
  notice.setAttribute('role', 'status');
  const [title, hint] = variant === 'tab' ? [t('overlay:tabNotice'), t('overlay:tabNoticeHint')] : [t('overlay:notice'), t('overlay:noticeHint')];
  notice.innerHTML = `<span class="dot" aria-hidden="true"></span><span><b>${title}</b> ${hint}</span><button aria-label="${t('overlay:close')}">${iconHtml(X, 16)}</button>`;
  notice.querySelector('button')!.onclick = () => shadow.host.remove();
  shadow.append(notice);
  return true;
}

let countdownCancel: (() => void) | undefined;
export function cancelCountdown(): void { countdownCancel?.(); }

export function showCountdown(seconds: number, requestId: string, variant: OverlayVariant = 'meeting'): Promise<{ ok: boolean }> {
  cancelCountdown();
  const shadow = createHost('sauri-countdown-host');
  const dialog = document.createElement('div');
  dialog.className = 'shade';
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-label', t('overlay:countdown'));
  dialog.innerHTML = `<h2>${t('overlay:countdown')}</h2><strong aria-live="polite"></strong><span>${variant === 'tab' ? t('overlay:tabCountdownHint') : t('overlay:countdownHint')}</span><button>${t('overlay:cancel')}</button>`;
  shadow.append(dialog);
  const previousFocus = document.activeElement as HTMLElement | null;
  return new Promise(resolve => {
    const endsAt = Date.now() + seconds * 1000;
    const finish = (ok: boolean) => {
      clearInterval(timer);
      window.removeEventListener('pagehide', cancel);
      dialog.removeEventListener('keydown', onKey);
      shadow.host.remove();
      countdownCancel = undefined;
      previousFocus?.focus();
      resolve({ ok });
    };
    const cancel = () => finish(false);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') cancel();
      if (event.key === 'Tab') { event.preventDefault(); dialog.querySelector('button')!.focus(); }
    };
    const update = () => {
      const remaining = Math.ceil((endsAt - Date.now()) / 1000);
      if (remaining <= 0) finish(true);
      else dialog.querySelector('strong')!.textContent = String(remaining);
    };
    const timer = setInterval(update, 100);
    countdownCancel = cancel;
    dialog.dataset.requestId = requestId;
    dialog.querySelector('button')!.onclick = cancel;
    dialog.addEventListener('keydown', onKey);
    window.addEventListener('pagehide', cancel, { once: true });
    update();
    dialog.querySelector('button')!.focus();
  });
}

let timer: ReturnType<typeof setInterval> | undefined;
let removeDrag: (() => void) | undefined;
let currentUI: RecordingUI | undefined;

export function hideRecordingUI(): void {
  clearInterval(timer);
  removeDrag?.();
  removeDrag = undefined;
  currentUI = undefined;
  document.getElementById('sauri-recording-host')?.remove();
  document.getElementById('sauri-consent-banner-host')?.remove();
}

function enableDrag(bar: HTMLElement, handle: HTMLButtonElement): () => void {
  let origin: { x: number; y: number; left: number; top: number } | undefined;
  const move = (left: number, top: number) => {
    bar.style.left = `${Math.max(0, Math.min(left, window.innerWidth - bar.offsetWidth))}px`;
    bar.style.top = `${Math.max(0, Math.min(top, window.innerHeight - bar.offsetHeight))}px`;
    bar.style.bottom = 'auto';
  };
  handle.addEventListener('pointerdown', event => {
    const rect = bar.getBoundingClientRect();
    origin = { x: event.clientX, y: event.clientY, left: rect.left, top: rect.top };
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (origin) move(origin.left + event.clientX - origin.x, origin.top + event.clientY - origin.y);
  });
  const release = () => { origin = undefined; };
  handle.addEventListener('pointerup', release);
  handle.addEventListener('pointercancel', release);
  handle.addEventListener('lostpointercapture', release);
  handle.onkeydown = event => {
    const directions: Record<string, [number, number]> = { ArrowLeft: [-10, 0], ArrowRight: [10, 0], ArrowUp: [0, -10], ArrowDown: [0, 10] };
    if (!directions[event.key]) return;
    event.preventDefault();
    const rect = bar.getBoundingClientRect();
    const [x, y] = directions[event.key];
    move(rect.left + x, rect.top + y);
  };
  const resize = () => { const rect = bar.getBoundingClientRect(); move(rect.left, rect.top); };
  window.addEventListener('resize', resize);
  return () => window.removeEventListener('resize', resize);
}

export function syncRecordingUI(state: RecordingUI): void {
  currentUI = state;
  if (!state.showControlBar) {
    clearInterval(timer);
    removeDrag?.();
    removeDrag = undefined;
    document.getElementById('sauri-recording-host')?.remove();
    return;
  }
  let shadow = document.getElementById('sauri-recording-host')?.shadowRoot;
  if (!shadow) {
    shadow = createHost('sauri-recording-host');
    const bar = document.createElement('div');
    bar.className = 'bar';
    bar.setAttribute('role', 'toolbar');
    bar.setAttribute('aria-label', t('overlay:controls'));
    bar.innerHTML = `<button class="handle" aria-label="${t('overlay:drag')}">${iconHtml(GripVertical)}</button><span class="dot" aria-hidden="true"></span><span class="time" role="timer"></span><span class="status"></span><button class="cancel" aria-label="${t('overlay:cancelRecording')}">${iconHtml(X)}</button><button class="pause"></button><button class="save" aria-label="${t('overlay:stop')}" title="${t('overlay:stop')}">${iconHtml(Square, 16)}</button><span class="mic">${iconHtml(Mic, 16, 'lead')}<select aria-label="${t('overlay:microphone')}" title="${t('overlay:microphoneHint')}"></select>${iconHtml(ChevronDown, 14, 'chevron')}</span><span class="error" role="alert"></span>`;
    shadow.append(bar);
    const root = shadow;
    const command = async (type: string) => {
      const sessionId = currentUI?.sessionId;
      root.querySelector('.error')!.textContent = '';
      const buttons = root.querySelectorAll<HTMLButtonElement>('button');
      buttons.forEach(button => { button.disabled = true; });
      try {
        const response = await chrome.runtime.sendMessage({ type, sessionId });
        if (!response?.ok) throw new Error('Capture control rejected');
      } catch {
        root.querySelector('.error')!.textContent = t('overlay:controlError');
      } finally { buttons.forEach(button => { button.disabled = false; }); }
    };
    bar.querySelector<HTMLButtonElement>('.pause')!.onclick = () => { void command(currentUI?.paused ? 'resume-capture' : 'pause-capture'); };
    bar.querySelector<HTMLButtonElement>('.save')!.onclick = () => { void command('stop-capture'); };
    bar.querySelector<HTMLButtonElement>('.cancel')!.onclick = () => {
      if (root.querySelector('.confirmation')) return;
      const confirmation = document.createElement('div');
      confirmation.className = 'confirmation';
      confirmation.setAttribute('role', 'alertdialog');
      confirmation.setAttribute('aria-modal', 'true');
      confirmation.setAttribute('aria-label', t('overlay:confirm'));
      confirmation.innerHTML = `<b>${t('overlay:confirm')}</b><p>${t('overlay:discardHint')}</p><button class="keep">${t('overlay:keep')}</button><button class="discard">${t('overlay:discard')}</button>`;
      const close = () => { confirmation.remove(); bar.querySelector<HTMLButtonElement>('.cancel')!.focus(); };
      confirmation.querySelector<HTMLButtonElement>('.keep')!.onclick = close;
      confirmation.querySelector<HTMLButtonElement>('.discard')!.onclick = () => { void command('cancel-capture'); };
      confirmation.onkeydown = event => {
        if (event.key === 'Escape') close();
        if (event.key === 'Tab') {
          event.preventDefault();
          const target = event.composedPath()[0];
          confirmation.querySelector<HTMLButtonElement>(target === confirmation.querySelector('.keep') ? '.discard' : '.keep')!.focus();
        }
      };
      root.append(confirmation);
      confirmation.querySelector<HTMLButtonElement>('.keep')!.focus();
    };
    removeDrag = enableDrag(bar, bar.querySelector('.handle')!);
  }
  const root = shadow;
  const update = () => {
    if (!currentUI) return;
    const elapsed = currentUI.elapsedMs + (!currentUI.paused && currentUI.segmentStartedAt ? Math.max(0, Date.now() - currentUI.segmentStartedAt) : 0);
    const seconds = Math.floor(elapsed / 1000);
    root.querySelector('.time')!.textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  };
  root.querySelector('.bar')!.classList.toggle('paused', state.paused);
  root.querySelector('.status')!.textContent = state.paused ? t('overlay:paused') : '';
  const pause = root.querySelector<HTMLButtonElement>('.pause')!;
  pause.replaceChildren(icon(state.paused ? Play : Pause));
  pause.setAttribute('aria-label', state.paused ? t('overlay:resume') : t('overlay:pause'));
  pause.title = state.paused ? t('overlay:resume') : t('overlay:pause');
  // Only the active device is shown. Device changes apply to the next session.
  const select = root.querySelector('select')!;
  select.replaceChildren(new Option(state.micLabel || (state.micActive ? t('overlay:defaultMicrophone') : t('overlay:noMicrophone'))));
  clearInterval(timer);
  update();
  timer = setInterval(update, 250);
}
