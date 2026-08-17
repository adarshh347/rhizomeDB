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
  for (const [name, fn] of Object.entries(handlers)) {
    es.addEventListener(name, (e) => {
      let data: unknown = null;
      try {
        data = JSON.parse((e as MessageEvent).data);
      } catch {
        data = (e as MessageEvent).data;
      }
      fn(data);
    });
  }
  es.onerror = () => {
    if (finished) return;
    finished = true;
    es.close();
    onError("Connection lost.");
  };
  return { finish, stop };
}
