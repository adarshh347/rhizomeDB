// Display-only Markdown stripping for previews (notes rail, marginalia, the
// connections text clip). Stored quotes stay raw — anchoring depends on exact
// spine offsets — so this is applied at render time only, never to the spine.
export function plainText(md: string): string {
  if (!md) return "";
  let s = md;
  // fenced / inline code → the code text
  s = s.replace(/```[\w-]*\n?([\s\S]*?)```/g, "$1");
  s = s.replace(/`([^`\n]+)`/g, "$1");
  // images and links → the label
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1");
  s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
  // headings and blockquotes at line start
  s = s.replace(/^[ \t]{0,3}#{1,6}[ \t]+/gm, "");
  s = s.replace(/^[ \t]{0,3}>[ \t]?/gm, "");
  // strong / em: **x** __x__ *x* _x_ (only when flanking a word, so snake_case
  // and mid-word underscores are left alone)
  s = s.replace(/(\*\*|__)(?=\S)([\s\S]*?\S)\1/g, "$2");
  s = s.replace(/(^|[\s(“"'])\*(?=\S)([^*\n]*?\S)\*(?=$|[\s.,;:!?)”"'’])/g, "$1$2");
  s = s.replace(/(^|[\s(“"'])_(?=\S)([^_\n]*?\S)_(?=$|[\s.,;:!?)”"'’])/g, "$1$2");
  // an emphasis marker left unpaired because the excerpt was cut inside the
  // span (a quote that starts at "_come into" but ends before the closing
  // "_"): drop a lone marker at a word boundary. Mid-word underscores
  // (snake_case) still survive because they touch letters on both sides.
  s = s.replace(/(^|[\s(“"'])[*_](?=[\p{L}\p{N}])/gu, "$1");
  s = s.replace(/(?<=[\p{L}\p{N}.,;:!?)])[*_](?=$|[\s.,;:!?)”"'’])/gu, "");
  // whitespace
  return s.replace(/\s+/g, " ").trim();
}
