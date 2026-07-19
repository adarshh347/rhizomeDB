# Vendored fonts

Self-hosted WOFF2, served locally at `/fonts/*` (no CDN, per the PRD). Declared
in `src/styles/fonts.css`; families/stacks in `src/styles/tokens.css`. Only the
weights/styles the UI actually uses are checked in. Latin subset. All three
families are licensed under the **SIL Open Font License 1.1** — full texts in
`licenses/`.

| Family | Role | Files (weights/styles) | License | Source |
|---|---|---|---|---|
| **Fraunces** | display / editorial headings | `fraunces-latin-wght-normal.woff2` (variable weight, roman) | OFL 1.1 — `licenses/Fraunces-OFL.txt` | [undercasetype/Fraunces](https://github.com/undercasetype/Fraunces) |
| **Inter** | interface + supporting prose | `inter-latin-{400,500,600}-normal.woff2`, `inter-latin-400-italic.woff2` | OFL 1.1 — `licenses/Inter-OFL.txt` | [rsms/inter](https://github.com/rsms/inter) |
| **JetBrains Mono** | ids, offsets, scores, machine metadata | `jetbrains-mono-latin-400-normal.woff2` | OFL 1.1 — `licenses/JetBrainsMono-OFL.txt` | [JetBrains/JetBrainsMono](https://github.com/JetBrains/JetBrainsMono) |

WOFF2 files were obtained from the Fontsource distribution of these OFL fonts
(latin subset, per-weight). Total payload ≈ 160 KB across 6 files.

Adding a weight/style: vendor the WOFF2 here, add an `@font-face` in
`src/styles/fonts.css`, and — if it is needed for first paint — a `<link
rel="preload">` in `index.html`. Keep the set minimal.
