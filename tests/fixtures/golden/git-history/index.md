# toy_repo: git history

_2 commits, read as eras and a graveyard._

toy_repo is nine years of one product changing its mind twice.

## The eras

### Era 1: The blog engine <script>alert(1)</script> (2013-05 → 2016-02)

One Ghost-shaped product, one author, publishing only.

**Turning point:** The first paid theme lands and billing appears in `core/server/`.

### Era 2: Going multi-tenant (2016-03 → 2019-11)

Members, subscriptions and a second runtime.

**Turning point:** `apps/` is born and the monolith stops growing.

## Cast & mood

### Era 1: The blog engine <script>alert(1)</script>

**Cast:**

_One founder writes 80% of it, at night._

**Mood:**
- direct-to-master (?%)

_Fast, unreviewed, and cheerful about it._

### Era 2: Going multi-tenant

**Cast:**

_A team of six, with review as the default._

**Mood:**
- migration-heavy (?%)

_Slower, and deliberately so._

## The graveyard

### ⚰ Remove the AMP renderer
_2018-04-11 · `9f2c1ab` · 34 files · `core/frontend/`_

**What it was.** A parallel AMP render path, kept in step with the main one by hand.

```
core/frontend/apps/amp/
```

**Why it died.** Google stopped requiring it and nobody owned the duplication. <script>alert(1)</script>

### ⚰ Drop the legacy importer
_2017-01-30 · `3ba77de` · 12 files · `core/server/`_

**What it was.** A one-shot WordPress importer.
