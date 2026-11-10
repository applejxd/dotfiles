# Evaluation Report

Evaluation date: 2026-09-11

## Success condition

The skill is accepted when three materially different tasks each have at least one
skill-guided output that:

- passes plan, OOXML, geometry, text-fit, image, font, and render checks;
- beats the no-skill baseline in blind comparison;
- satisfies the task-specific requirements;
- reaches zero observable actionable findings in an independent final review.

## Corpus

| Eval | Stress case | Configurations |
| --- | --- | --- |
| 1 | Six-slide Japanese corporate-template proposal | baseline, skill strict, skill visual |
| 2 | Eight-slide English experiment/research deck | baseline, skill strict, skill visual |
| 3 | Five-slide Japanese screenshot-heavy customer demo | baseline, skill strict, skill visual |

Nine generation configurations were launched. All produced outputs. The strict research
variant exposed severe text-box failures and was retained as a negative regression case;
the visual variant was repaired into the final winner.

## Final results

| Eval | Final skill output | Blind result | Mechanical result |
| --- | --- | --- | --- |
| 1 | `evals/runs/eval1/with_skill_strict/deck.pptx` | Winner, 5.0/5, 0 findings | errors 0, warnings 0, template differences 0 |
| 2 | `evals/runs/eval2/with_skill_visual/accuracy-without-guesswork.pptx` | Winner, 5.0/5, 0 findings | OOXML 0, hard errors 0, native editable method map |
| 3 | `evals/runs/eval3/with_skill_visual/northstar-customer-demo-ja.pptx` | Winner, 4.875/5, 0 findings | OOXML 0, hard errors 0, image geometry/resolution pass |

Representative blind reports:

- `evals/blind/eval1/comparison-bc.json`
- `evals/blind/eval2/comparison-ab.json`
- `evals/blind/eval3/comparison-bc.json`

## Defects found by the loop

The loop found issues that the generating agents' initial self-reviews missed:

- text boxes that visually spill outside their OOXML bounds;
- rules crossing text;
- one-character Japanese orphan lines;
- unsupported topology implied by arrows;
- raw counts compared across unequal windows;
- undefined denominators and survey aggregation;
- raster method diagrams where vector/editable output was required;
- PptxGenJS `notesMasterIdLst` schema ordering;
- clipped text inside source screenshots;
- excessive callouts and unreadably small screenshot thumbnails;
- illustrative values framed as observed customer outcomes.

Each generalized failure produced a skill rule, validation check, or regression test.

## Trigger evaluation

GitHub Copilot CLI was run non-interactively with only the `skill` tool available.
The 20-query set contains ten substantive creation/redesign requests and ten adjacent
near-misses such as text extraction, one-word replacement, HTML slides, diagram-only work,
and Google Slides permission automation.

- should trigger: 10/10 invoked `powerpoint-studio`
- should not trigger: 10/10 did not invoke `powerpoint-studio`
- total: 20/20, 100%

## Remaining non-blocking warnings

The research and screenshot winners contain 9-10.5pt chart labels, source notes, and UI
microcopy. Independent full-size review found them readable. They remain warnings rather
than hard failures; main titles and body text use substantially larger sizes.

## Source-grounded 45-minute pilot

A 21-slide Japanese deck was produced from the RAG From Scratch and Agentic RAG for
Dummies marimo notebooks and original OSS repositories. User feedback and independent
reviews added these generalized gates:

- text containment inside pills, badges, tags, and callouts;
- one surface background with base/main/accent color roles;
- title, concise agenda, visible section position, and final summary for long talks;
- meaningful line breaking, grids, proximity, whitespace, and one-slide-one-message review;
- minimum displayed size for evidence screenshots;
- source fidelity for implementation identifiers and control flow;
- QA summaries bound to PPTX, plan, source, and style-policy SHA-256;
- optional Claude Code + Bedrock cost checkpoints after research and planning.

The final pilot passed the current mechanical gate with zero errors and warnings. Two
independent reviewers gave zero actionable findings after checking all 21 full-size slides,
the full Haltasaki article, all 68 pages of the referenced SlideShare deck, source fidelity,
timing, hyperlinks, and PPTX/PDF parity.

## Diagram regression: 2026-09-13

User review of the pilot's pages 15 and 16 found defects despite the earlier
zero-finding review. Those earlier results are historical, not evidence that
the diagrams were defect-free. Replaying page 15's DOT produces
`Warning: the bounding boxes of some nodes touch - falling back to straight line edges`.
Page 16 emits no such warning, but its condition labels touch routes and its
return annotations resemble extra executable nodes.

The repair introduces measured layout JSON, deterministic SVG rendering, actual
node/label/edge/arrow geometry checks, and contain-scaled text measurements. The
deck gate checks every registered diagram's actual PPTX placement and embedded
image, plus layout/SVG/image/renderer provenance. Failed geometry does not update
the output SVG. `route: outside` is no longer treated as geometric evidence.

Verification of this change:

- Full Python suite: **167 passed**.
- Existing JavaScript helper test: **1 passed**.
- Pilot node/edge/condition-label correspondence tests: **2 passed**.
- Both repaired diagrams: **0 geometry errors**, final minimum text sizes
  **11.267pt** and **12.694pt**.
- Full 21-slide strict deck QA, PDF/PPTX raster parity, hyperlinks, and artifact
  freshness: **passed**.
- The bundled `examples/diagram-layout.json` also passes actual-font measurement.
- Independent final-PDF visual review of p15/p16, with p14/p17 as context:
  **0 actionable findings**; old label collisions and extra return boxes resolved.
- All **19 unmodified pages are pixel-identical** to the previous PDF at 144 DPI.
- Rebuilding with the deployed skill preserves the final diagram/provenance hashes.

The pilot's `qa/diagram-review.html` contains a static old/new comparison;
`qa/diagram-visual-review-20260913.json` records the independent review and its
limits. Renderer warnings were checked from stderr, not inferred from a PNG.

Evals 4 and 5 preserve the long-identifier/human-return and two-return-agent
stress cases. This iteration replays the actual failed deliverable and its
repair; it is **not** a fresh-agent A/B benchmark and makes no claim about
generation-time, token-cost, or general success-rate improvements.

Scope: the geometric validator handles its explicit orthogonal-layout schema,
not arbitrary SVG, Graphviz output, or quoted screenshots. SVG consumers still
need the declared font. Provenance does not replace a full-size final-PDF review.

## Whole-deck layout follow-up: 2026-09-13

After approving the repaired diagrams, the user requested a review of all slide
layouts and the corresponding skill sections. All 21 full-size pages were
reviewed. The observed visual defect was the ColBERT score label touching a
diagonal dotted line on page 8; other refinements addressed title term wrapping,
column-header alignment, evidence/sidebar balance, metric-list starting
positions, redundant outer frames, and roomy cards with small primary labels.

The revision changes pages 1, 2, 5, 6, 7, 8, 10, 11, 17, 18, and 19. Approved
pages 15 and 16 remain pixel-identical. Claims, words (apart from whitespace and
Part/name separators), source links, notes, timing, palette, shared helper
defaults, and the existing typography/chrome policies are preserved.

Opt-in `meta.layout_checks` adds exact-name alignment and primary-text checks;
it does not impose new global font sizes. The same ten declarations produce
53 findings on the old layout and zero after repair. Findings include repeated
run-level font and autofit violations: this is **not a claim of 53 visual bugs**.
The audit explicitly rejects missing targets and unsupported transforms instead
of silently skipping them.

Verification performed before final visual acceptance:

- Full Python suite: **250 passed**; JavaScript helper: **1 passed**; process
  correspondence tests: **2 passed**.
- Full 21-slide strict QA, PDF/PPTX render parity, links, and report freshness:
  **passed**.
- Nine unmodified pages are pixel-identical. Page 14 has a 183-pixel difference
  confined to the title's digit `1`, while its slide XML, relationships, and
  assets are byte-identical; this rendering-only difference is recorded rather
  than reported as pixel identity.

Evals 6 and 7 cover long agenda/method names and table/role alignment. As with
the diagram regression, before/after artifacts are a replay of this concrete
deliverable, not an independent fresh-agent generation benchmark.

The first independent re-review found one remaining issue: p18's equal-y text
boxes used vertical middle alignment, putting the two-line list's first line
22px below the three-line list. Both lists now use explicit top anchoring,
rather than a compensating y-offset. The opt-in `text_anchor` assertion and
12 new tests prevent this regression; the initial failing tests confirmed that
box-anchor checks alone did not detect it.

Final independent acceptance: **0 findings**. The corrected first-line visible
tops are 711px and 712px (1px difference), compared with 22px previously.
`qa/layout-review.html` contains the 11-page before/after comparison.

## Japanese wording follow-up: 2026-09-14

The user asked what p16's "調査予算" meant, then requested a full wording pass
and natural Japanese for translatable English. Native text and speaker notes
on all 21 pages, plus the three active custom diagrams, were revised.
Official names, code identifiers, source-reference keys, URLs, numeric
conditions, and timing remain unchanged.

P16 now labels the exit condition `回数上限` and describes
`fallback_response` as `取得済み情報で回答`. Its title/notes distinguish the
search/compression loop from the fallback exit. P15/p16 node boxes, ports,
routes, and fonts are unchanged, but their revised labels intentionally change
the pixels.

The wording glossary/checker is a regression aid, not a general language
quality score. It checks native text, notes, and active SVG text rather than
relying on PDF text extraction, which misses rasterized diagrams.

Regenerating the translated feedback-loop SVG exposed a validator defect:
Graphviz's negative local y coordinates were tested without applying its
group transform. The validator now composes ancestor/element affine transform
attributes and checks the transformed text origin. Fourteen regression cases
cover the actual Graphviz form, nested order, valid and out-of-bounds results,
and malformed/unsupported transforms. This remains an origin check, not a
complete glyph-bound or CSS-layout validator.

Mechanical verification:

- Full skill Python suite: **264 passed**; JavaScript helper: **1 passed**.
- Deck process/terminology tests: **5 passed**.
- All three active SVG checks: **0 errors, 0 warnings**.
- Full 21-slide strict QA, PDF/PPTX render parity, hyperlinks, and source/timing/
  diagram-geometry preservation checks: **passed**.
- Known awkward-phrase regression: **0 findings** after rebuilding.

Eval 8 covers count-budget ambiguity, descriptive Japanese versus code
identifiers, and checking diagram/notes text. Naturalness and faithful meaning
also require the independent contextual review; an English-word count is not
used as an acceptance criterion.

Final independent wording/visual acceptance: **0 findings** across the
21-page review, notes, and custom diagram labels. The reviewer requested one
last clarification on p10 (`原典の介入群` to `原典のパート`); it was added to
the terminology regression and rechecked after rebuilding. The final
comparison is `qa/wording-review.html`.
