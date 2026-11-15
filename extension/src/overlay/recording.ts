import { copy } from './copy';

export interface RecordingUI {
  sessionId: string;
  paused: boolean;
  elapsedMs: number;
  segmentStartedAt?: number;
  showControlBar: boolean;
  micLabel?: string;
  micActive?: boolean;
}

const styles = `
  :host { all: initial; font: 15px 'Nunito Sans', system-ui, sans-serif; color: #2e3230; }
  * { box-sizing: border-box; }
  button, select { font: inherit; cursor: pointer; min-height: 44px; border-radius: 12px; padding: 8px 12px; }
  button { border: 0; }
  button:focus-visible, select:focus-visible { outline: 3px solid #78a886; outline-offset: 3px; }
  [hidden] { display: none !important; }
  .dot { display: inline-block; flex: 0 0 auto; width: 12px; height: 12px; border-radius: 50%; background: #b83230; animation: pulse 1.4s infinite; }
  @keyframes pulse { 50% { opacity: .35; } }
  @media (prefers-reduced-motion: reduce) { .dot { animation: none; } }
  .notice { position: fixed; top: 20px; left: 50%; transform: translateX(-50%); width: min(532px, calc(100vw - 24px)); display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-radius: 14px; background: #faf6f0; box-shadow: 0 8px 28px #0005; }
  .notice button { background: transparent; color: #4a4e4a; }
  .shade { position: fixed; inset: 0; background: #202421b8; color: white; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; padding: 16px; }
  .shade strong { font: 600 clamp(100px, 25vw, 200px)/1 'Literata', Georgia, serif; }
  .shade h2 { font-size: 20px; font-weight: 600; margin: 0; }
  .shade button { margin-top: 14px; background: transparent; border: 1px solid #fff9; color: white; padding: 10px 22px; }
  .bar { position: fixed; left: 24px; bottom: 28px; max-width: calc(100vw - 16px); display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 8px; border-radius: 18px; background: #232826; color: white; box-shadow: 0 10px 34px #0007; }
  .bar button, .bar select { background: transparent; color: white; }
  .bar .pause { background: #ffffff1a; }
  .bar .save { background: #4a7c59; }
  .bar .dot { width: 10px; height: 10px; background: #ef6b63; }
  .bar.paused .dot { animation: none; background: #c4c8bc; }
  .time { font: 16px 'JetBrains Mono', monospace; padding: 0 8px; }
  .handle { touch-action: none; cursor: grab; }
  .bar select { max-width: 150px; border: 1px solid #ffffff33; }
  .bar option { color: #2e3230; background: #faf6f0; }
  .confirmation { position: fixed; left: 24px; bottom: 100px; width: min(340px, calc(100vw - 32px)); padding: 18px; border-radius: 16px; background: white; box-shadow: 0 12px 38px #0006; }
  .confirmation p { color: #4a4e4a; font-size: 14px; }
  .confirmation button { background: #f0e8db; color: #3b6a49; margin: 4px; }
  .confirmation .discard { background: #b83230; color: white; }
  .error { flex-basis: 100%; color: #ffb4ab; }
`;

function createHost(id: string): ShadowRoot {
  const host = document.createElement('div');
  host.id = id;
  host.style.cssText = 'all:initial;position:fixed;inset:0;z-index:2147483647;pointer-events:none;';
  const shadow = host.attachShadow({ mode: 'open' });
  const style = document.createElement('style');
  style.textContent = `${styles} .notice, .shade, .bar, .confirmation { pointer-events: auto; }`;
  shadow.append(style);
  document.documentElement.append(host);
  return shadow;
}

export function showNotice(): boolean {
  const existing = document.getElementById('sauri-consent-banner-host');
  if (existing?.shadowRoot) return false;
  // A previous extension version may have left a closed shadow root behind.
  existing?.remove();
  const shadow = createHost('sauri-consent-banner-host');
  const notice = document.createElement('div');
  notice.className = 'notice';
  notice.setAttribute('role', 'status');
  notice.innerHTML = `<span class="dot" aria-hidden="true"></span><span><b>${copy.notice}</b> ${copy.noticeHint}</span><button aria-label="${copy.close}">✕</button>`;
  notice.querySelector('button')!.onclick = () => shadow.host.remove();
  shadow.append(notice);
  return true;
}

let countdownCancel: (() => void) | undefined;
export function cancelCountdown(): void { countdownCancel?.(); }

export function showCountdown(seconds: number, requestId: string): Promise<{ ok: boolean }> {
  cancelCountdown();
  const shadow = createHost('sauri-countdown-host');
  const dialog = document.createElement('div');
  dialog.className = 'shade';
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.setAttribute('aria-label', copy.countdown);
  dialog.innerHTML = `<h2>${copy.countdown}</h2><strong aria-live="polite"></strong><span>${copy.countdownHint}</span><button>${copy.cancel}</button>`;
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
    bar.setAttribute('aria-label', copy.controls);
    bar.innerHTML = `<button class="handle" aria-label="${copy.drag}">⠿</button><span class="dot" aria-hidden="true"></span><span class="time" role="timer"></span><span class="status"></span><button class="cancel" aria-label="${copy.cancelRecording}">✕</button><button class="pause"></button><button class="save" aria-label="${copy.stop}" title="${copy.stop}">■</button><select aria-label="${copy.microphone}" title="${copy.microphoneHint}"></select><span class="error" role="alert"></span>`;
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
        root.querySelector('.error')!.textContent = copy.controlError;
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
      confirmation.setAttribute('aria-label', copy.confirm);
      confirmation.innerHTML = `<b>${copy.confirm}</b><p>${copy.discardHint}</p><button class="keep">${copy.keep}</button><button class="discard">${copy.discard}</button>`;
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
  root.querySelector('.status')!.textContent = state.paused ? copy.paused : '';
  const pause = root.querySelector<HTMLButtonElement>('.pause')!;
  pause.textContent = state.paused ? '▶' : 'Ⅱ';
  pause.setAttribute('aria-label', state.paused ? copy.resume : copy.pause);
  pause.title = state.paused ? copy.resume : copy.pause;
  // Only the active device is shown. Device changes apply to the next session.
  const select = root.querySelector('select')!;
  select.replaceChildren(new Option(state.micLabel || (state.micActive ? copy.defaultMicrophone : copy.noMicrophone)));
  clearInterval(timer);
  update();
  timer = setInterval(update, 250);
}
