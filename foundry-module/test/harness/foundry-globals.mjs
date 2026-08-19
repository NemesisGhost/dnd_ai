/**
 * Minimal fakes for the Foundry globals this module's non-UI code
 * touches (`game`, `Hooks`, `ui`, and a generic `Document`-like base for
 * actors/combats/scenes/items). Deliberately not a full Foundry
 * simulation — only what `sync-engine.mjs`/`hooks.mjs`/`settings.mjs`
 * actually call, kept in one place so every test file gets an identical,
 * predictable environment rather than each hand-rolling its own partial
 * mock.
 */

function applyDottedChanges(target, changes) {
  for (const [dottedKey, value] of Object.entries(changes)) {
    const parts = dottedKey.split(".");
    let node = target;
    for (let i = 0; i < parts.length - 1; i += 1) {
      node[parts[i]] ??= {};
      node = node[parts[i]];
    }
    node[parts.at(-1)] = value;
  }
}

export class FakeDocument {
  constructor({ id, name = id, system = {}, flags = {} } = {}) {
    this.id = id;
    this.name = name;
    this.system = system;
    this.flags = flags;
    this.updateCalls = [];
  }

  getFlag(scope, key) {
    return this.flags?.[scope]?.[key];
  }

  async setFlag(scope, key, value) {
    this.flags[scope] ??= {};
    this.flags[scope][key] = value;
    return this;
  }

  async update(changes) {
    this.updateCalls.push(changes);
    applyDottedChanges(this, changes);
    return this;
  }
}

export class FakeCombat extends FakeDocument {
  constructor({ id, round = 1, turn = 0, ...rest } = {}) {
    super({ id, ...rest });
    this.round = round;
    this.turn = turn;
  }
}

export class FakeCollection {
  constructor(items = []) {
    this._items = items;
  }

  get contents() {
    return this._items;
  }

  get(id) {
    return this._items.find((item) => item.id === id);
  }

  filter(predicate) {
    return this._items.filter(predicate);
  }

  [Symbol.iterator]() {
    return this._items[Symbol.iterator]();
  }
}

export class FakeSettings {
  constructor() {
    this._definitions = new Map();
    this._values = new Map();
    this._menus = new Map();
  }

  register(namespace, key, config) {
    this._definitions.set(`${namespace}.${key}`, config);
    this._values.set(`${namespace}.${key}`, config.default);
  }

  registerMenu(namespace, key, config) {
    this._menus.set(`${namespace}.${key}`, config);
  }

  get(namespace, key) {
    return this._values.get(`${namespace}.${key}`);
  }

  async set(namespace, key, value) {
    this._values.set(`${namespace}.${key}`, value);
    return value;
  }
}

export function createFakeGame({
  isGM = true,
  userId = "user-1",
  worldTime = 1000,
  actors = [],
  combat = null,
} = {}) {
  return {
    user: { isGM, id: userId },
    settings: new FakeSettings(),
    actors: new FakeCollection(actors),
    i18n: { localize: (key) => key },
    time: { worldTime },
    combat,
  };
}

export function createFakeUi() {
  const calls = { info: [], warn: [], error: [] };
  return {
    notifications: {
      info: (message) => calls.info.push(message),
      warn: (message) => calls.warn.push(message),
      error: (message) => calls.error.push(message),
    },
    calls,
  };
}

export class FakeHooks {
  constructor() {
    this._handlers = new Map();
  }

  on(name, fn) {
    this._push(name, fn, false);
  }

  once(name, fn) {
    this._push(name, fn, true);
  }

  _push(name, fn, once) {
    if (!this._handlers.has(name)) {
      this._handlers.set(name, []);
    }
    this._handlers.get(name).push({ fn, once });
  }

  /** Synchronously invokes every registered handler for `name`, awaiting
   * each in turn (real Foundry hooks are fired synchronously and do not
   * await async handlers, but awaiting here makes test assertions that
   * follow a `call()` deterministic without an extra `await
   * Promise.resolve()` at every call site). */
  async call(name, ...args) {
    const handlers = this._handlers.get(name) ?? [];
    const toRun = [...handlers];
    for (const handler of toRun) {
      await handler.fn(...args);
    }
    if (toRun.some((h) => h.once)) {
      this._handlers.set(
        name,
        handlers.filter((h) => !toRun.includes(h) || !h.once),
      );
    }
  }
}
