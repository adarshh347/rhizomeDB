import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { BookSummary } from "../api/types";
import "./library.css";

export function Library() {
  const [books, setBooks] = useState<BookSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .books()
      .then(setBooks)
      .catch((e: ApiError) =>
        setError(
          e.status === 0 || e.name === "ApiError"
            ? e.message
            : "Could not reach the backend.",
        ),
      );
  }, []);

  if (error) {
    return (
      <div className="center-note">
        <p>{error}</p>
        <p>
          Is the backend running? <code>rhizome serve --reload</code>, and build
          the index with <code>rhizome build</code>.
        </p>
      </div>
    );
  }
  if (!books) return <div className="center-note">Loading the library…</div>;
  if (books.length === 0)
    return (
      <div className="center-note">
        <p>No books in the corpus yet.</p>
        <p>
          Convert some into <code>data/converted/</code> and run{" "}
          <code>rhizome build</code>.
        </p>
      </div>
    );

  return (
    <main className="library">
      <div className="library-head">
        <h1>The Library</h1>
        <p className="sub">
          {books.length} {books.length === 1 ? "book" : "books"}, read natively —
          every highlight resolves to the spine.
        </p>
      </div>
      <ul className="book-grid">
        {books.map((b) => (
          <li key={b.book_id}>
            <Link to={`/read/${encodeURIComponent(b.book_id)}`} className="book-card">
              <div className="book-fmt">MD</div>
              <h2 className="book-title">{b.title}</h2>
              <div className="book-author">{b.author}</div>
              <div className="book-stats">
                <span>{b.n_chunks.toLocaleString()} passages</span>
                {b.n_annotations > 0 && (
                  <span className="ann-count">{b.n_annotations} notes</span>
                )}
                {b.year && <span>{b.year}</span>}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
