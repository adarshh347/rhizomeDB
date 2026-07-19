import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import type { Annotation, CreateAnnotationBody } from "../api/types";
import type { HighlightSpan } from "./spine";

// Load + mutate a book's annotations, and project the anchored ones into
// HighlightSpans the renderer paints. Orphans (no resolved position) are kept
// in the list for the rail but never painted — nothing is silently dropped.
export function useAnnotations(bookId: string) {
  const [items, setItems] = useState<Annotation[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    return api.bookAnnotations(bookId).then((rows) => {
      setItems(rows);
      setLoading(false);
    });
  }, [bookId]);

  useEffect(() => {
    setLoading(true);
    reload();
  }, [reload]);

  const create = useCallback(
    async (body: CreateAnnotationBody) => {
      const res = await api.createAnnotation(body);
      setItems((prev) => [...prev, res.annotation]);
      return res;
    },
    [],
  );

  const remove = useCallback(async (id: string) => {
    await api.deleteAnnotation(id);
    setItems((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const highlights: HighlightSpan[] = useMemo(() => {
    const spans: HighlightSpan[] = [];
    for (const a of items) {
      const pos = a.selector?.text_position;
      if (a.orphaned || !pos) continue;
      spans.push({
        id: a.id,
        spine_start: pos.spine_start,
        spine_end: pos.spine_end,
        color: a.color || "amber",
        approximate: !!a.selector?.approximate,
      });
    }
    return spans;
  }, [items]);

  return { items, highlights, loading, create, remove, reload };
}
