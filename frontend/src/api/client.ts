// Typed client for the Rhizome backend (/api/v2). One thin fetch wrapper; each
// call is a one-liner over it. In dev, Vite proxies /api to the FastAPI server.
import type {
  Annotation,
  BookFormat,
  BookPayload,
  BookSummary,
  CreateAnnotationBody,
  CreateAnnotationResult,
  ResolveResult,
  SpinePayload,
} from "./types";

export interface UploadResult {
  book_id: string;
  title: string;
  author: string;
  n_chunks: number;
  formats: BookFormat[];
}

const BASE = "/api/v2";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? body.error ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => req<{ status: string; version: number }>("/health"),

  books: () => req<{ books: BookSummary[] }>("/books").then((r) => r.books),

  book: (bookId: string) => req<BookPayload>(`/books/${encodeURIComponent(bookId)}`),

  spine: (bookId: string) =>
    req<SpinePayload>(`/books/${encodeURIComponent(bookId)}/spine`),

  bookAnnotations: (bookId: string) =>
    req<{ items: Annotation[] }>(
      `/books/${encodeURIComponent(bookId)}/annotations`,
    ).then((r) => r.items),

  resolve: (body: { book_id: string; quote: string; prefix?: string; suffix?: string }) =>
    req<ResolveResult>("/anchors/resolve", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  createAnnotation: (body: CreateAnnotationBody) =>
    req<CreateAnnotationResult>("/annotations", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  deleteAnnotation: (id: string) =>
    req<{ ok: boolean }>(`/annotations/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  // Multipart upload — let the browser set the boundary Content-Type, so this
  // bypasses the JSON `req` helper.
  uploadBook: async (file: File): Promise<UploadResult> => {
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`${BASE}/books/upload`, { method: "POST", body });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* non-JSON */
      }
      throw new ApiError(res.status, detail);
    }
    return res.json() as Promise<UploadResult>;
  },
};
