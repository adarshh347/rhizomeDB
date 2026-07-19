import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type { Annotation, CreateAnnotationBody } from "../api/types";

// Load + mutate a book's annotations. Painting is each renderer's job (it knows
// its own coordinates); this hook is the shared source of truth for the list,
// the rail, and create/delete. Orphans stay in the list but never paint.
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

  const create = useCallback(async (body: CreateAnnotationBody) => {
    const res = await api.createAnnotation(body);
    setItems((prev) => [...prev, res.annotation]);
    return res;
  }, []);

  const remove = useCallback(async (id: string) => {
    await api.deleteAnnotation(id);
    setItems((prev) => prev.filter((a) => a.id !== id));
  }, []);

  return { items, loading, create, remove, reload };
}
