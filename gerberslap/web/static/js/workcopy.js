// The working copy: the project as of the last Save, kept in this browser (IndexedDB) and nowhere else. The server keeps nothing of the user: it
// only caches the Gerber files it is given, and the page can always give them again from here.
//
// There is one copy per tab, named by an id the tab keeps in sessionStorage (so it survives a reload, and a closed tab that is brought back with
// Ctrl+Shift+T finds its copy again). A tab holds a Web Lock named after its id for as long as it lives, which is how another tab can tell a copy
// whose tab was closed (free lock: offered for restoring) from one whose tab is still open (never offered). All of this is a function of its
// arguments (the store, the locks, the tab's own storage, the clock), so it can be tried without a browser; `indexedDbStore` and `webLocks` are
// the real ones.

export const STALE_MS = 7 * 24 * 3600 * 1000;          // a copy nobody came back for in a week is deleted

export function createWorkCopy({ store, locks, tabStorage, now = () => Date.now(), makeId = () => crypto.randomUUID() }) {
  const lockName = (id) => `gerberslap-tab-${id}`;
  let tabId = null;
  return {
    get tabId() { return tabId; },

    // Take the id of this tab: the one kept in sessionStorage if nobody else holds it, else a new one (a duplicated tab starts with its parent's id).
    async claim() {
      let id = tabStorage.get('gs-tab');
      for (;;) {
        id ||= makeId();
        if (!locks || await locks.hold(lockName(id))) break;
        id = null;
      }
      tabStorage.set('gs-tab', id); tabId = id;
      return id;
    },

    // Keep `bytes` (a project file) as this tab's copy, replacing the previous one. Returns the time it was saved.
    async save({ name, boards, bytes }) {
      const savedAt = now();
      await store.put({ tabId, name, boards, bytes, savedAt });
      return savedAt;
    },

    load: async () => (tabId ? (await store.get(tabId)) ?? null : null),

    // The copy of a tab that is gone, if there is one, the most recent first. Copies that nobody holds and are older than a week are deleted on the way.
    // Without Web Locks there is no telling a closed tab from an open one: nothing is offered and nothing is deleted.
    async offer() {
      if (!locks) return null;
      const dead = [];
      for (const entry of await store.all()) {
        if (entry.tabId === tabId || !(await locks.isFree(lockName(entry.tabId)))) continue;
        if (now() - entry.savedAt > STALE_MS) await store.delete(entry.tabId); else dead.push(entry);
      }
      return dead.sort((a, b) => b.savedAt - a.savedAt)[0] ?? null;
    },

    // Make the copy of a closed tab this tab's own (it is moved, not copied), or throw it away.
    async adopt(entry) { await store.put({ ...entry, tabId }); if (entry.tabId !== tabId) await store.delete(entry.tabId); },
    discard: (entry) => store.delete(entry.tabId),
  };
}

// "14:32" for a time today, "12 Oct, 14:32" for another day, in the language of the page; `full` is the whole date and time with seconds.
export function formatWhen(ts, nowTs, locale, timeZone) {
  const d = new Date(ts), n = new Date(nowTs), tz = timeZone ? { timeZone } : {};
  const day = (x) => x.toLocaleDateString('en-CA', tz);
  const time = d.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', ...tz });
  const short = day(d) === day(n) ? time : `${d.toLocaleDateString(locale, { day: 'numeric', month: 'short', ...tz })}, ${time}`;
  return { short, full: d.toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'medium', ...tz }) };
}

// What the status bar says about saving: always when the project was last saved, and "Unsaved" besides when there are changes since.
// `t` is the page's translator. Returns the text, the tooltip and whether it is a warning.
export function saveStatus({ dirty, savedAt, now, locale, t, timeZone }) {           // timeZone: the browser's own unless a test fixes it
  const when = savedAt ? formatWhen(savedAt, now, locale, timeZone) : null;
  // `main` is always shown; `extra` (when it was last saved, next to "Unsaved") can be dropped where the status bar is short of room
  const main = dirty ? `● ${t('st_unsaved')}` : when ? t('st_saved', { time: when.short }) : t('st_never');
  const extra = dirty && when ? t('st_last', { time: when.short }) : '';
  return { main, extra, text: extra ? `${main} · ${extra}` : main, title: when ? t('st_title', { when: when.full }) : t('st_title_never'), warn: dirty };
}

// ---- the real store and locks of the browser ------------------------------------------------------------------------------
export function indexedDbStore(name = 'gerberslap', version = 1) {
  let opened = null;
  const open = () => (opened ||= new Promise((resolve, reject) => {
    const r = indexedDB.open(name, version);
    r.onupgradeneeded = () => r.result.createObjectStore('copies', { keyPath: 'tabId' });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => { opened = null; reject(r.error); };
  }));
  const run = async (mode, fn) => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('copies', mode), request = fn(tx.objectStore('copies'));
      tx.oncomplete = () => resolve(request.result);
      tx.onerror = tx.onabort = () => reject(tx.error);
    });
  };
  return { put: (v) => run('readwrite', (s) => s.put(v)), get: (k) => run('readonly', (s) => s.get(k)), all: () => run('readonly', (s) => s.getAll()), delete: (k) => run('readwrite', (s) => s.delete(k)) };
}

export function webLocks() {
  if (typeof navigator === 'undefined' || !navigator.locks) return null;
  return {
    // true if the lock was free: it is then held until the tab goes away
    hold: (lock) => new Promise((resolve) => { navigator.locks.request(lock, { ifAvailable: true }, (l) => { resolve(!!l); return l ? new Promise(() => {}) : undefined; }); }),
    isFree: (lock) => navigator.locks.request(lock, { ifAvailable: true }, (l) => !!l),
  };
}
