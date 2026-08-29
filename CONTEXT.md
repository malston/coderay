# coderay

Crawls a target repo, extracts its core concepts via an LLM, and writes a Tour explaining them.

## Language

**Abstraction**:
One of the ~5-10 core concepts the Analyze step identifies in the target codebase (a class, a pattern, a subsystem). Has a name and a description.
_Avoid_: Concept, topic

**Chapter**:
The artifact written for one Abstraction: `{name, filename, content}`. There is exactly one Chapter per Abstraction, placed in Order. A Chapter's shape doesn't change based on how it was authored.
_Avoid_: Section, page, tutorial (only accurate under the `beginner-tutorial` Lens — three of the four Lenses produce something else entirely: an audit, a review, an onboarding guide)

**Lens**:
One of `beginner-tutorial`, `architecture-review`, `security-audit`, `onboarding-guide` — a file in `workflow/instructions/`, selected with `--instructions`. Its content is appended verbatim as the trailing `## Instructions` section of every Chapter's prompt, after the abstraction description, prior Chapters, chapter list, and codebase. It never reaches SmartCrawl, Analyze, or Relate — Abstractions, Order, and Relationships are identical across Lenses; only Chapter content changes. Each Lens states a reader persona, then rules that govern both what to focus on in the codebase for that reader (e.g. trade-offs, trust boundaries, files a new hire touches) and how to translate it back to them (tone, analogies allowed or banned, diagram rules, output format).
_Avoid_: Instructions (the CLI flag and file-system name for the same thing)

**Manifest**:
The first-pass preview of the target repo shown to the LLM for file selection: every candidate file's path plus a truncated preview, each with an index. Untrusted, since it echoes the target repo's own content. When candidate files exceed `preview_budget`, the Manifest is cut to the first N in directory-walk order (alphabetical per directory) — a plain prefix cut, not a relevance ranking. A file past that cutoff never gets a chance to be selected, regardless of importance.

**Narrative continuity**:
A property of how a Chapter is authored, not of the Chapter itself: whether its prompt included the actual prose of prior Chapters (so it can continue or refer back to them) versus only their titles. The current WriteChapters design authors every Chapter with narrative continuity, one at a time, using a sliding window of recent Chapters' content. A Chapter authored without it is still a Chapter — it just can't reference what came before.
_Avoid_: Sequential context, chapter dependency

**Order**:
The sequence Abstractions are taught in, decided by the Relate step from the Relationships between them. Chapters are written and numbered in this sequence.

**Relationship**:
A directed edge between two Abstractions (`from`, `to`, `label`), found by the Relate step. Rendered as the Tour's architecture diagram.

**Tour**:
The full output for one repo and one Lens: an index page (summary, architecture diagram, chapter list) plus one Chapter per Abstraction. Two Tours for the same repo under different Lenses are independent — separate output directories, no shared state.
