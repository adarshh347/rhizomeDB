// node --test src/__tests__/  (Node ≥22 strips the types; no runner dependency)
//
// The transport-vs-app "error" split. EventSource fires its own failures under
// the same event name the server uses for `event: error`, and the two must not
// be confused: an app error carries JSON, a transport error carries nothing and
// has to reach onError or the panel spins forever.
import { test } from "node:test";
import assert from "node:assert/strict";

import { sse } from "../api/sse.ts";

const CONNECTING = 0;
const CLOSED = 2;

class FakeEventSource {
  static last: FakeEventSource | null = null;
  readyState = CONNECTING;
  closed = 0;
  onerror: ((e: Event) => void) | null = null;
  url: string;
  private listeners = new Map<string, ((e: Event) => void)[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.last = this;
  }
  addEventListener(name: string, fn: (e: Event) => void) {
    const list = this.listeners.get(name) ?? [];
    list.push(fn);
    this.listeners.set(name, list);
  }
  close() {
    this.closed += 1;
    this.readyState = CLOSED;
  }
  // Listeners registered with addEventListener run before the `onerror`
  // property handler, which sse() assigns last — as in a real EventSource.
  emit(name: string, event: Event) {
    for (const fn of this.listeners.get(name) ?? []) fn(event);
    if (name === "error") this.onerror?.(event);
  }
  // A named server event: `event: <name>` + a JSON `data:` line.
  message(name: string, data: unknown) {
    this.emit(name, { data: JSON.stringify(data) } as unknown as Event);
  }
  // A transport failure: a plain Event, no data.
  fail(readyState: number) {
    this.readyState = readyState;
    this.emit("error", { type: "error" } as Event);
  }
}

function withFakeEventSource<T>(fn: () => T): T {
  const real = (globalThis as { EventSource?: unknown }).EventSource;
  (globalThis as { EventSource?: unknown }).EventSource = FakeEventSource;
  try {
    return fn();
  } finally {
    (globalThis as { EventSource?: unknown }).EventSource = real;
  }
}

// Handlers shaped like useConnections': the named "error" handler stops the
// stream and reads d.text, which is exactly what a native Event cannot supply.
function harness() {
  const seen: { app: unknown[]; transport: string[]; candidates: unknown[] } = {
    app: [],
    transport: [],
    candidates: [],
  };
  const control = sse(
    "/api/v2/explore?mode=chunk&value=x",
    {
      candidates: (d) => seen.candidates.push(d.items),
      error: (d) => {
        control.stop();
        seen.app.push(d.text);
      },
    },
    (message) => seen.transport.push(message),
  );
  return { seen, control, es: FakeEventSource.last! };
}

test("a native transport failure never reaches the app-level error handler", () => {
  withFakeEventSource(() => {
    const { seen, es } = harness();
    es.fail(CLOSED); // e.g. /explore answered 400 before the stream opened
    assert.deepEqual(seen.app, [], "the named 'error' handler must not see a native Event");
    assert.equal(seen.transport.length, 1, "the transport error must be surfaced");
    assert.match(seen.transport[0], /connection stream|Connection lost/);
    assert.ok(es.closed > 0, "the stream is closed, not left to reconnect");
  });
});

test("a mid-stream drop is reported as a lost connection", () => {
  withFakeEventSource(() => {
    const { seen, es } = harness();
    es.fail(CONNECTING); // open stream dropped; EventSource would retry
    assert.deepEqual(seen.transport, ["Connection lost."]);
    assert.deepEqual(seen.app, []);
  });
});

test("the server's own `event: error` still reaches the named handler", () => {
  withFakeEventSource(() => {
    const { seen, es } = harness();
    es.message("error", { text: "Index not built." });
    assert.deepEqual(seen.app, ["Index not built."]);
    assert.deepEqual(seen.transport, [], "an app error is not a transport error");
  });
});

test("named events are JSON-parsed, and a finished stream's close is silent", () => {
  withFakeEventSource(() => {
    const { seen, control, es } = harness();
    es.message("candidates", { items: [{ chunk_id: "a#1" }] });
    assert.deepEqual(seen.candidates, [[{ chunk_id: "a#1" }]]);
    control.finish();
    es.fail(CONNECTING); // the server closing after `done`
    assert.deepEqual(seen.transport, []);
  });
});
