/**
 * A boolean preference remembered per device in localStorage and shared by every hook instance.
 * localStorage is the source of truth; `unsaved` only holds a choice the browser refused to store
 * (blocked storage), so it lasts for this visit. It is tied to the storage object it failed on, so
 * a different storage starts clean.
 */
export interface StoredFlag {
  /** The remembered value, or null when nothing was ever chosen. */
  read: () => boolean | null;
  write: (value: boolean) => void;
  subscribe: (notify: () => void) => () => void;
}

function currentStorage(): Storage | null {
  try {
    return localStorage;
  } catch {
    return null; // some browsers throw on access when site data is blocked
  }
}

export function createStoredFlag(key: string): StoredFlag {
  const subscribers = new Set<() => void>();
  let unsaved: { storage: Storage | null; value: boolean } | null = null;

  return {
    read() {
      const storage = currentStorage();
      try {
        const stored = storage?.getItem(key);
        if (stored === "1") return true;
        if (stored === "0") return false;
      } catch {
        // blocked storage: fall through to the unsaved choice
      }
      return unsaved && unsaved.storage === storage ? unsaved.value : null;
    },
    write(value) {
      const storage = currentStorage();
      try {
        if (!storage) throw new Error("storage unavailable");
        storage.setItem(key, value ? "1" : "0");
        unsaved = null;
      } catch {
        unsaved = { storage, value };
      }
      subscribers.forEach((notify) => notify());
    },
    subscribe(notify) {
      subscribers.add(notify);
      return () => subscribers.delete(notify);
    },
  };
}
