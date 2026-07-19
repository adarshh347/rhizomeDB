import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { BookSummary } from "../api/types";
import "./library.css";

const ACCEPT = ".pdf,.epub,.mobi";

export function Library() {
  const [books, setBooks] = useState<BookSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .books()
      .then(setBooks)
      .catch((e: ApiError) => setError(e.message));
  }, []);

  async function upload(file: File) {
    setUploadError(null);
    setUploading(file.name);
    try {
      const result = await api.uploadBook(file);
      navigate(`/read/${encodeURIComponent(result.book_id)}`);
    } catch (e) {
      setUploadError(`Couldn’t add “${file.name}”: ${(e as ApiError).message}`);
      setUploading(null);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) upload(file);
  }

  const dropzone = (
    <div
      className={`dropzone ${dragging ? "over" : ""} ${uploading ? "busy" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      onClick={() => !uploading && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) upload(file);
          e.target.value = "";
        }}
      />
      {uploading ? (
        <span>
          <span className="spinner" /> Converting “{uploading}” — this can take a
          moment for large books…
        </span>
      ) : (
        <span>
          <strong>Add a book</strong> — drop a PDF, EPUB or MOBI here, or click to
          choose. It converts and opens natively; annotations resolve to the spine.
        </span>
      )}
    </div>
  );

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

  return (
    <main className="library">
      <div className="library-head">
        <h1>The Library</h1>
        <p className="sub">
          {books.length} {books.length === 1 ? "book" : "books"}, read natively —
          every highlight resolves to the spine.
        </p>
      </div>

      {dropzone}
      {uploadError && <div className="upload-error">{uploadError}</div>}

      {books.length === 0 ? (
        <div className="center-note">
          <p>No books yet — add one above, or convert into <code>data/converted/</code>{" "}
            and run <code>rhizome build</code>.</p>
        </div>
      ) : (
        <ul className="book-grid">
          {books.map((b) => (
            <li key={b.book_id}>
              <Link to={`/read/${encodeURIComponent(b.book_id)}`} className="book-card">
                <div className="book-fmt">
                  {b.formats.find((f) => f.native && f.available)?.format.toUpperCase() ?? "MD"}
                </div>
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
      )}
    </main>
  );
}
