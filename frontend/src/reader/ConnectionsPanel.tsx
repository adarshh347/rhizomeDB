import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Columns3, Info, X } from "lucide-react";

import { api, type ConnSeed } from "../api/client";
import type { CompareResponse, ConnectItem, EngineCard } from "../api/types";
import type { ConnectionsState } from "./useConnections";
import { plainText } from "./text";
import { Tip } from "./Tip";

const STATUS_LABEL: Record<string, string> = {
  geometry: "asking the engine…",
  judging: "judging genuine vs forced…",
  synthesizing: "weaving a reading…",
  done: "",
  error: "",
};

const bookOf = (chunkId: string) => chunkId.split("#")[0];
const chunkHref = (chunkId: string) =>
  `/read/${encodeURIComponent(bookOf(chunkId))}?chunk=${encodeURIComponent(chunkId)}`;
const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n).trimEnd()}…` : s);
const pct = (x: number | null | undefined) => (x == null ? null : Math.round(x * 100));

// The reader talking to the retrieval engines (the point of RhizomeDB): from the
// passage — or the sentence — you're reading, what else in the library, by
// whichever geometry you pick. Geometry alone is useful without a key; with an
// LLM the genuine-vs-forced verdict and a synthesized reading follow. Every pick
// links back into its book via the R6 ?chunk= deep link, and discloses *why* it
// was picked and how non-obvious it is (rank in the full similarity sort).
// De-carded: quiet rows; similarity reads as a small meter, not just a number.
export function ConnectionsPanel({
  seed,
  fromLabel,
  onClose,
  state,
  engines,
  engineKey,
  onEngine,
  onOpenAnnotation,
}: {
  seed: ConnSeed;
  fromLabel: string;
  onClose: () => void;
  state: ConnectionsState;
  engines: EngineCard[];
  engineKey: string;
  onEngine: (key: string) => void;
  // "open note" on a *my marks* pick — the annotation the pick came from.
  onOpenAnnotation?: (annotationId: string, item: ConnectItem) => void;
}) {
  const { candidates, verdicts, exploration, notes, status, error } = state;
  const card = engines.find((e) => e.key === engineKey) ?? null;
  const engineLabel = state.engine?.label ?? card?.label ?? engineKey;
  const engineBlurb = state.engine?.blurb ?? card?.blurb ?? "";

  const [compareOn, setCompareOn] = useState(false);
  const [compare, setCompare] = useState<CompareResponse | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

  useEffect(() => {
    if (!compareOn) return;
    let live = true;
    setCompare(null);
    setCompareError(null);
    setCompareLoading(true);
    api
      .compareEngines({ mode: seed.mode, value: seed.value, candidates: 3 })
      .then((r) => live && setCompare(r))
      .catch((e: Error) => live && setCompareError(e.message))
      .finally(() => live && setCompareLoading(false));
    return () => {
      live = false;
    };
  }, [compareOn, seed.mode, seed.value]);

  // A walk renders as an ordered chain — picks carry `hop`.
  const isWalk = candidates.length > 0 && candidates.every((c) => c.hop != null);
  const ordered = isWalk
    ? [...candidates].sort((a, b) => (a.hop ?? 0) - (b.hop ?? 0))
    : candidates;

  return (
    <section className="rail-panel connections-rail" aria-label="Connections">
      <div className="rail-head">
        <span className="section-label">Connections</span>
        <span className="spacer" />
        <Tip label={compareOn ? "Hide the engine comparison" : "Compare engines on this seed"}>
          <button
            className={`btn-ghost icon ${compareOn ? "on" : ""}`}
            onClick={() => setCompareOn((v) => !v)}
            aria-label="Compare engines"
            aria-pressed={compareOn}
          >
            <Columns3 size={15} strokeWidth={1.75} aria-hidden />
          </button>
        </Tip>
        <Tip label="Close">
          <button className="btn-ghost icon" onClick={onClose} aria-label="Close connections">
            <X size={15} strokeWidth={2} aria-hidden />
          </button>
        </Tip>
      </div>

      <div className="conn-engine-row">
        <select
          className="conn-engine-select"
          aria-label="Retrieval engine"
          value={engineKey}
          onChange={(e) => onEngine(e.target.value)}
        >
          {engines.length === 0 && <option value={engineKey}>{engineKey}</option>}
          {engines.map((e) => (
            <option key={e.key} value={e.key}>
              {e.label}
              {e.ready ? "" : " · not ready"}
            </option>
          ))}
        </select>
        {engineBlurb && (
          <Tip label={plainText(engineBlurb)}>
            <button className="btn-ghost icon" aria-label={`About ${engineLabel}: ${engineBlurb}`}>
              <Info size={14} strokeWidth={1.75} aria-hidden />
            </button>
          </Tip>
        )}
      </div>

      <p className="conn-from">
        {seed.mode === "chunk" ? (
          <>
            from <span className="mono chunk-id">#{seed.value.split("#")[1]}</span> {fromLabel}
          </>
        ) : (
          <>
            from the selection <q className="conn-seed-quote">{clip(plainText(seed.value), 120)}</q>
          </>
        )}
      </p>
      {engineBlurb && <p className="conn-blurb">{plainText(engineBlurb)}</p>}
      {card && !card.ready && (
        <p className="rail-note conn-not-ready">
          {engineLabel} isn’t ready: {card.reason || "its side data is missing."}
        </p>
      )}

      {compareOn && (
        <CompareTable
          data={compare}
          loading={compareLoading}
          error={compareError}
          selected={engineKey}
        />
      )}

      {status !== "done" && status !== "error" && (
        <div className="conn-status" role="status">
          <span className="spinner" /> {STATUS_LABEL[status]}
        </div>
      )}
      {error && <div className="inline-error">{error}</div>}

      {exploration && (
        <div className="conn-synthesis">
          <span className="section-label">A reading</span>
          <p>{exploration}</p>
        </div>
      )}

      {isWalk && (
        <p className="conn-chain mono" aria-label="Walk order">
          {ordered.map((c, i) => (
            <span key={c.chunk_id}>
              {i > 0 && <span className="conn-chain-arrow" aria-hidden> → </span>}
              {c.hop}
            </span>
          ))}
        </p>
      )}

      <ul className={`rail-list ${isWalk ? "conn-walk" : ""}`}>
        {ordered.map((c) => {
          const v = verdicts[c.index];
          const sim = pct(c.similarity);
          const struct = pct(c.structural_similarity);
          const fused = c.path?.startsWith("fused");
          const paths = c.paths ?? (fused ? c.path.slice(c.path.indexOf(":") + 1).split(/[+,|]/) : []);
          const isMark = !!c.annotation_id;
          return (
            <li
              key={c.chunk_id}
              className={`row conn-row ${v && !v.genuine ? "forced" : ""} ${isWalk ? "hop" : ""}`}
            >
              {isWalk && (
                <span className="conn-hop-num mono" aria-label={`hop ${c.hop}`}>
                  {c.hop}
                </span>
              )}
              <div className="conn-title-line">
                <span className="conn-author">{c.author}</span>
                <span className="conn-book">{c.title}</span>
                {c.page != null && <span className="mono conn-page">p{c.page}</span>}
              </div>
              {isMark ? (
                <div className="conn-mark">
                  {c.quote && <em className="conn-mark-quote">“{plainText(c.quote)}”</em>}
                  {c.note && <span className="conn-mark-note">{plainText(c.note)}</span>}
                  {!c.quote && !c.note && <span className="conn-text">{clip(plainText(c.text), 240)}</span>}
                </div>
              ) : (
                <div className="conn-text">{clip(plainText(c.text), 240)}</div>
              )}
              {c.abstraction && (
                <div className="conn-abstraction">
                  <span className="section-label">move</span> {c.abstraction}
                </div>
              )}
              {c.concepts && c.concepts.length > 0 && (
                <div className="conn-concepts" aria-label="Shared concepts">
                  {c.concepts.map((k) => (
                    <span key={k} className="conn-tag mono">
                      {k}
                    </span>
                  ))}
                </div>
              )}
              {c.why && <div className="conn-why">{plainText(c.why)}</div>}
              {v?.genuine && v.bridge_concept && (
                <div className="conn-bridge">
                  <span className="badge-genuine">genuine</span> {v.bridge_concept}
                </div>
              )}
              <div className="conn-foot">
                {sim != null && (
                  <Tip label="resonance — surface similarity to the seed">
                    <span className="meter">
                      <span className="meter-track">
                        <span className="meter-fill" style={{ width: `${sim}%` }} />
                      </span>
                      {sim}%
                    </span>
                  </Tip>
                )}
                {struct != null && (
                  <Tip label="structural — same shape of thought, different words">
                    <span className="meter structural">
                      <span className="meter-track">
                        <span className="meter-fill" style={{ width: `${struct}%` }} />
                      </span>
                      {struct}%
                    </span>
                  </Tip>
                )}
                {c.rank != null && c.corpus_size > 0 && (
                  <Tip label="rank of this passage in the full similarity sort — how non-obvious the pick is">
                    <span className="conn-rank mono">
                      #{c.rank + 1} of {c.corpus_size}
                    </span>
                  </Tip>
                )}
                {fused && paths.length > 0 && (
                  <span className="conn-paths mono" aria-label="Fused from paths">
                    {paths.join(" + ")}
                  </span>
                )}
                {isMark && (
                  <button
                    className="conn-open conn-open-note"
                    onClick={() => onOpenAnnotation?.(c.annotation_id!, c)}
                    aria-label="Open this note"
                  >
                    open note
                  </button>
                )}
                <Link className="conn-open" to={chunkHref(c.chunk_id)}>
                  open in book <ArrowRight size={13} strokeWidth={2} aria-hidden />
                </Link>
              </div>
            </li>
          );
        })}
      </ul>

      {status === "done" && candidates.length === 0 && (
        <p className="rail-note">
          No picks from {engineLabel}
          {seed.mode === "chunk" ? " for this passage." : " for this selection."}
        </p>
      )}
      {notes.length > 0 && (
        <div className="conn-notes">
          {notes.map((n, i) => (
            <p key={i}>{n}</p>
          ))}
        </div>
      )}
      {state.seed?.embed_label && <p className="conn-embed">via {state.seed.embed_label}</p>}
    </section>
  );
}

// "Same question, different geometries": every ready engine's top-3 for the
// current seed, plus how much the selected engine agrees with each other one.
function CompareTable({
  data,
  loading,
  error,
  selected,
}: {
  data: CompareResponse | null;
  loading: boolean;
  error: string | null;
  selected: string;
}) {
  if (loading)
    return (
      <div className="conn-status" role="status">
        <span className="spinner" /> comparing engines…
      </div>
    );
  if (error) return <div className="inline-error">Compare failed: {error}</div>;
  if (!data) return null;
  const mine = data.results.find((r) => r.key === selected);
  const mineIds = new Set((mine?.items ?? []).map((i) => i.chunk_id));
  const n = Math.max(1, mine?.items?.length ?? 0);
  return (
    <div className="conn-compare">
      <ul className="conn-compare-list" aria-label="Top three picks per engine">
        {data.results.map((r) => {
          const items = (r.items ?? []).slice(0, 3);
          const shared = items.filter((i) => mineIds.has(i.chunk_id)).length;
          const isMine = r.key === selected;
          return (
            <li key={r.key} className={`conn-compare-row ${isMine ? "selected" : ""}`}>
              <div className="conn-compare-head">
                <span className="conn-compare-label">{r.label}</span>
                {!isMine && !r.error && items.length > 0 && (
                  <span className="conn-compare-shared mono" title={`picks shared with ${mine?.label ?? "the selected engine"}`}>
                    {shared}/{n} shared
                  </span>
                )}
              </div>
              {r.error ? (
                <div className="conn-compare-err">{r.error}</div>
              ) : items.length === 0 ? (
                <div className="conn-compare-empty">nothing</div>
              ) : (
                <div className="conn-compare-picks">
                  {items.map((it, i) => (
                    <Link
                      key={it.chunk_id}
                      to={chunkHref(it.chunk_id)}
                      className={mineIds.has(it.chunk_id) && !isMine ? "shared" : ""}
                      title={`${it.author} · ${it.title}${it.page != null ? ` p.${it.page}` : ""}`}
                    >
                      <span className="mono conn-compare-n">{i + 1}</span>
                      {clip(plainText(it.title), 22)}
                      {it.page != null && <span className="mono"> p.{it.page}</span>}
                    </Link>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
