import { useEffect, useRef, useState } from "react";

/**
 * Follows one value the desktop app pushes: the getter's answer first, then each event. An event that arrives
 * before the getter answers wins over that (older) answer.
 */
export function usePushed<T>(read: (() => Promise<T>) | undefined, listen: ((listener: (value: T) => void) => () => void) | undefined) {
  const [value, setValue] = useState<T | null>(null);
  const pushed = useRef(false);
  useEffect(() => {
    if (!read) return;
    let live = true;
    const stop = listen?.((next) => {
      pushed.current = true;
      setValue(next);
    });
    read().then(
      (first) => {
        if (live && !pushed.current) setValue(first);
      },
      () => undefined,
    );
    return () => {
      live = false;
      stop?.();
    };
  }, [read, listen]);
  return [value, setValue] as const;
}
