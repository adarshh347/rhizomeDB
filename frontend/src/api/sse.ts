// A small EventSource wrapper: named events → JSON-parsed handlers, one error
// callback, and a stop() that closes the stream. The server closes the stream
// after its final event; a bare EventSource reads that close as an error and
// reconnects (re-running the whole job), so handlers mark the stream finished
// via the returned control before that happens.
export type SseHandlers = Record<string, (data: any) => void>;

export interface SseControl {
  // Mark the stream as finished so the server's close is not treated as an error.
  finish: () => void;
  // Close the socket (also marks finished).
  stop: () => void;
}

export function sse(url: string, handlers: SseHandlers, onError: (message: string) => void): SseControl {
  const es = new EventSource(url);
  let finished = false;
  const finish = () => {
    finished = true;
  };
  const stop = () => {
    finished = true;
    es.close();
  };
  // The transport failed: the request never opened (the server is down, or it
  // answered 4xx/5xx before the stream began — EventSource gives up and reports
  // CLOSED) or an open stream dropped (readyState CONNECTING: it would silently
  // reconnect and re-run the whole job). Either way, close it for good and say
  // so — an unreported transport error leaves the panel spinning.
  const transportError = () => {
    if (finished) return;
    finished = true;
    const refused = es.readyState === 2; // CLOSED — never opened / not retrying
    es.close();
    onError(refused ? "Could not open the connection stream." : "Connection lost.");
  };
  for (const [name, fn] of Object.entries(handlers)) {
    es.addEventListener(name, (e) => {
      // EventSource fires its *own* transport failure under the name "error"
      // too — a plain Event with no `data`, nothing to do with the server's
      // app-level `event: error` (which carries JSON). Routing it into the
      // named handler would throw inside the listener and strand the stream
      // marked finished, so nothing would ever be shown. Transport goes to the
      // transport path.
      const raw: unknown = (e as MessageEvent).data;
      if (typeof raw !== "string") {
        transportError();
        return;
      }
      let data: unknown;
      try {
        data = JSON.parse(raw);
      } catch {
        data = raw;
      }
      fn(data);
    });
  }
  es.onerror = transportError;
  return { finish, stop };
}
