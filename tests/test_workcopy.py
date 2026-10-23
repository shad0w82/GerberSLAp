"""The working copy kept in the browser: the logic that decides whose copy is whose and what is offered after a tab is closed, run for real with
node against a store, locks and clock that stand in for the browser's. IndexedDB and Web Locks themselves are tried in the browser."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = (Path(__file__).resolve().parent.parent / "gerberslap" / "web" / "static" / "js" / "workcopy.js").as_uri()
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

PRELUDE = """
import * as w from %r;
const memStore = () => { const m = new Map(); return {
  put: async (v) => { m.set(v.tabId, structuredClone(v)); }, get: async (k) => (m.has(k) ? structuredClone(m.get(k)) : undefined),
  all: async () => [...m.values()].map((v) => structuredClone(v)), delete: async (k) => { m.delete(k); }, keys: () => [...m.keys()].sort() }; };
const memLocks = () => { const held = new Set(); return { hold: async (n) => (held.has(n) ? false : (held.add(n), true)), isFree: async (n) => !held.has(n),
  release: (n) => held.delete(n), holds: (n) => held.has(n) }; };
const memTab = (init = {}) => { const m = { ...init }; return { get: (k) => m[k] ?? null, set: (k, v) => { m[k] = v; }, all: () => ({ ...m }) }; };
let clock = 1_000_000, n = 0;
const world = () => ({ store: memStore(), locks: memLocks() });
const tab = (wd, storage = memTab(), locks = wd.locks) => w.createWorkCopy({ store: wd.store, locks, tabStorage: storage, now: () => clock, makeId: () => 'id' + (++n) });
const DAY = 24 * 3600 * 1000;
const bytes = (s) => new TextEncoder().encode(s).buffer;
""" % MODULE


def run(script):
    r = subprocess.run(["node", "--input-type=module", "-e", PRELUDE + script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_a_tab_keeps_its_id_through_a_reload_and_a_duplicated_tab_gets_its_own():
    got = run("""
      const wd = world(), storage = memTab();
      const a = tab(wd, storage); const id = await a.claim();
      const stored = storage.get('gs-tab');
      wd.locks.release('gerberslap-tab-' + id);                         // the tab is reloaded: the lock goes with the old page
      const reloaded = tab(wd, storage); const again = await reloaded.claim();
      const copy = memTab(storage.all());                                // "duplicate tab": sessionStorage is copied while the first tab lives
      const twin = tab(wd, copy); const other = await twin.claim();
      console.log(JSON.stringify({ id, stored, again, other, twinStored: copy.get('gs-tab'), held: wd.locks.holds('gerberslap-tab-' + other) }));""")
    assert got["id"] == got["stored"] == got["again"] and got["other"] != got["id"] and got["twinStored"] == got["other"] and got["held"]


def test_a_copy_is_saved_replaced_and_loaded_by_its_own_tab():
    got = run("""
      const wd = world(), a = tab(wd), b = tab(wd);
      const before = await a.load();                                      // before the tab has an id there is nothing
      await a.claim(); await b.claim();
      const t1 = await a.save({ name: 'one', boards: 1, bytes: bytes('first') });
      clock += 5000;
      const t2 = await a.save({ name: 'two', boards: 2, bytes: bytes('second') });
      const mine = await a.load(), theirs = await b.load();
      console.log(JSON.stringify({ before, t1, t2, name: mine.name, boards: mine.boards, savedAt: mine.savedAt, text: new TextDecoder().decode(mine.bytes), theirs, keys: wd.store.keys().length }));""")
    assert got["before"] is None and got["t2"] - got["t1"] == 5000 and got["savedAt"] == got["t2"]
    assert (got["name"], got["boards"], got["text"]) == ("two", 2, "second") and got["theirs"] is None and got["keys"] == 1


def test_the_copy_of_a_closed_tab_is_offered_and_the_copy_of_an_open_tab_never_is():
    got = run("""
      const wd = world(), a = tab(wd), b = tab(wd), c = tab(wd);
      await a.claim(); await b.claim();
      await a.save({ name: 'from a', boards: 1, bytes: bytes('A') });
      const whileOpen = await b.offer();                                  // a is still open
      wd.locks.release('gerberslap-tab-' + a.tabId);                      // a is closed
      await c.claim();
      const offered = await c.offer();
      console.log(JSON.stringify({ whileOpen, name: offered?.name, from: offered?.tabId === a.tabId }));""")
    assert got["whileOpen"] is None and got["name"] == "from a" and got["from"]


def test_restoring_a_copy_makes_it_the_tabs_own_and_it_is_not_offered_again():
    got = run("""
      const wd = world(), a = tab(wd), b = tab(wd);
      await a.claim(); await a.save({ name: 'x', boards: 3, bytes: bytes('payload') }); const was = a.tabId;
      wd.locks.release('gerberslap-tab-' + was);
      await b.claim();
      const offered = await b.offer(); await b.adopt(offered);
      const mine = await b.load();
      console.log(JSON.stringify({ name: mine.name, boards: mine.boards, owner: mine.tabId === b.tabId, text: new TextDecoder().decode(mine.bytes), keys: wd.store.keys().length, again: await b.offer(), oldGone: !(wd.store.keys().includes(was)) }));""")
    assert got == {"name": "x", "boards": 3, "owner": True, "text": "payload", "keys": 1, "again": None, "oldGone": True}


def test_discarding_a_copy_deletes_it_and_the_next_most_recent_one_is_offered_after():
    got = run("""
      const wd = world(), tabs = [tab(wd), tab(wd), tab(wd)], fresh = tab(wd);
      for (const [i, t] of tabs.entries()) { await t.claim(); clock += 1000; await t.save({ name: 'copy ' + i, boards: i, bytes: bytes('x') }); }
      for (const t of tabs) wd.locks.release('gerberslap-tab-' + t.tabId);
      await fresh.claim();
      const first = await fresh.offer(); await fresh.discard(first);
      const second = await fresh.offer(); await fresh.discard(second);
      const third = await fresh.offer(); await fresh.discard(third);
      console.log(JSON.stringify({ order: [first.name, second.name, third.name], after: await fresh.offer(), keys: wd.store.keys().length }));""")
    assert got == {"order": ["copy 2", "copy 1", "copy 0"], "after": None, "keys": 0}                         # the most recent first


def test_own_copy_is_never_offered_back_to_its_own_tab():
    got = run("""
      const wd = world(), a = tab(wd); await a.claim();
      await a.save({ name: 'mine', boards: 1, bytes: bytes('x') });
      console.log(JSON.stringify({ offered: await a.offer() }));""")
    assert got["offered"] is None


def test_a_copy_nobody_came_back_for_in_a_week_is_deleted_but_a_live_tabs_is_not():
    got = run("""
      const wd = world(), old = tab(wd), live = tab(wd), mine = tab(wd), recent = tab(wd);
      for (const t of [old, live, mine, recent]) await t.claim();
      await old.save({ name: 'old', boards: 1, bytes: bytes('x') });
      await live.save({ name: 'live', boards: 1, bytes: bytes('x') });
      await mine.save({ name: 'mine', boards: 1, bytes: bytes('x') });
      clock += 8 * DAY;                                                    // eight days later
      await recent.save({ name: 'recent', boards: 1, bytes: bytes('x') });
      for (const t of [old, recent]) wd.locks.release('gerberslap-tab-' + t.tabId);   // old and recent are closed; live (open for eight days) and mine are not
      const offered = await mine.offer();
      console.log(JSON.stringify({ offered: offered?.name, left: (await wd.store.all()).map((e) => e.name).sort() }));""")
    assert got == {"offered": "recent", "left": ["live", "mine", "recent"]}                                  # only the old closed one is gone


def test_without_web_locks_nothing_is_offered_or_deleted_and_the_copy_still_works():
    got = run("""
      const wd = world(), a = w.createWorkCopy({ store: wd.store, locks: null, tabStorage: memTab(), now: () => clock, makeId: () => 'solo' });
      const b = w.createWorkCopy({ store: wd.store, locks: null, tabStorage: memTab(), now: () => clock, makeId: () => 'other' });
      await a.claim(); await b.claim();
      await a.save({ name: 'a', boards: 1, bytes: bytes('x') });
      clock += 30 * DAY;
      console.log(JSON.stringify({ offer: await b.offer(), mine: (await a.load()).name, keys: wd.store.keys().length }));""")
    assert got == {"offer": None, "mine": "a", "keys": 1}


def test_the_time_of_a_save_is_short_today_and_has_the_day_on_another_day():
    got = run("""
      const at = Date.UTC(2026, 9, 13, 14, 32, 5), sameDay = Date.UTC(2026, 9, 13, 18, 0, 0), nextDay = Date.UTC(2026, 9, 14, 9, 0, 0), midnight = Date.UTC(2026, 9, 14, 0, 1, 0);
      const f = (now, loc) => w.formatWhen(at, now, loc, 'UTC');
      console.log(JSON.stringify({ today: f(sameDay, 'en-GB').short, tomorrow: f(nextDay, 'en-GB').short, tomorrowIt: f(nextDay, 'it-IT').short,
        lateAtNight: w.formatWhen(Date.UTC(2026, 9, 13, 23, 59, 0), midnight, 'en-GB', 'UTC').short, full: f(sameDay, 'en-GB').full, fullIt: f(sameDay, 'it-IT').full }));""")
    assert got["today"] == "14:32" and got["tomorrow"] == "13 Oct, 14:32" and got["tomorrowIt"] == "13 ott, 14:32"
    assert got["lateAtNight"] == "13 Oct, 23:59"                                                              # two minutes ago, but yesterday
    assert "14:32:05" in got["full"] and "14:32:05" in got["fullIt"]
