# Large Workspace Performance Architecture

The application keeps Markdown as the source of truth and uses a disposable SQLite read index. The 2026-10-15 optimization replaces the remaining request-time scans and duplicate write paths.

## Runtime behavior after the architecture review

- Workspace paths are normalized and the directory layout is initialized once per Workspace. Explicit Reload/repair resets this cache.
- Configuration is loaded on first use, rather than during module import. Importing the indexer no longer migrates personal configuration or depends on import order.
- Startup synchronizes the index once. A daemon worker then checks external file changes every 30 seconds. Document reads, lists, graphs and searches use the current SQLite snapshot and never start a periodic filesystem scan. External edits may take one interval to appear; in-app writes are indexed before returning success.
- `indexer.create_doc/update_doc/delete_doc/delete_docs` form the common document service used by HTTP, Agent tools and literature. Markdown codecs and atomic file writes stay in `store.py`.
- Schema 3 maps FTS rowids to document rowids, indexes normalized titles/link tokens and adds indexes matching the list sort expression. Schema migration sets a persistent rebuild marker, so an interrupted migration retries on restart.
- Ordinary writes update only affected graph sources, including incoming title/ID references, unresolved links and duplicate-title fallback. Full graph rebuild remains an explicit repair operation. Batch deletion shares a transaction and refreshes affected sources once.
- SQLite connection contexts close connections, and schema setup is cached per database. Read requests do not acquire the Python writer lock. Manual rebuild uses a transaction so concurrent readers keep their previous committed snapshot.
- Literature metadata joins query SQLite in batches instead of loading all Markdown bodies. Related-knowledge title/tag dictionaries are cached against `documents_version`; todo/activity-only updates do not invalidate them.
- The graph route mounts the optimized renderer directly with its already fetched data. The canvas replacement observer, old graph renderer, unused research-overview renderer and unused milestone fishbone/3D implementation are removed. Existing old bookmarks redirect to the current overview.
- MathJax and Mermaid load only when needed, with shared load promises, local assets and the previous CDN fallbacks. Math typesetting is serialized. This removes about 4.68 MB of raw scripts from the initial load list.

## Measured comparison

Windows / Python 3.10, 10,000 generated documents, about 600 body characters each, two tags and one project per document (30,000 graph edges). Three-sample medians; separate runs on the same host, not a strict performance guarantee.

| Operation | Review baseline | Optimized |
| --- | ---: | ---: |
| List 50 documents | 75.31 ms | 11.34 ms |
| Dashboard | 356.89 ms | 198.06 ms |
| Graph, 300 document nodes | 78.10 ms | 39.26 ms |
| Global search, no match | 105.21 ms | 17.37 ms |
| Unchanged filesystem reconciliation | 80,659.90 ms | 423.17 ms |
| Index one document | 833.05 ms | 106.66 ms |

The baseline index initialization expanded an existing 1,000-document index, while the new synthetic benchmark initialized a fresh 10,000-document index in about 13 seconds; these initialization workloads are not identical and are not included in the comparison table. Browser regression tests verify one graph request per visit, deferred/deduplicated library loads, real MathJax/Mermaid rendering, and existing document/todo/navigation behavior.

Remaining work for larger deployments includes indexing long Agent transcripts, SQL pagination of the literature registry itself, separate total graph-node/edge budgets, and consolidating remaining CSS/DOM decoration patches. Worker-based graph layout should be driven by browser profiling.

## Invariants

- Markdown and normal Workspace files remain the source of truth.
- `Workspace/System/Cache/index.sqlite` is disposable. Deleting it does not delete user data; the service rebuilds it from the Workspace.
- No third-party database/runtime dependency is added. The index uses Python's built-in `sqlite3` module and SQLite FTS5.
- Existing document/project/todo file formats remain readable outside the application.

## Data path

```text
Markdown / projects.json / todos.json / activity.jsonl
                    |
                    | incremental synchronization
                    v
       System/Cache/index.sqlite
                    |
        +-----------+-----------+----------------+
        |           |           |                |
      metadata     FTS5      graph_edges    aggregations
        |           |           |                |
        +-----------+-----------+----------------+
                    |
                    v
          bounded / paged APIs
                    |
                    v
       browser loads only visible data
```

## Indexed structures

`app/indexer.py` exposes the disposable index. The implementation is split into DB/schema, synchronization, query, graph and runtime/write modules. Main tables:

- `documents`: metadata, path, dates, excerpt and file signature.
- `document_projects`: document-to-project relations.
- `document_tags`: document-to-tag relations.
- `document_marks`: classification marks.
- `document_links`: parsed Wikilink tokens.
- `graph_edges`: materialized Wikilink/project/tag graph edges.
- `documents_fts`: FTS5 title/body/tag/project search index.
- `todos_index`: lightweight todo query table.
- `activity_daily`: incremental daily activity aggregation.

The index records file `mtime_ns` and size. Background synchronization uses `os.scandir` metadata and reparses only new or changed files; in-app document saves update the affected document immediately. The periodic scan holds the writer lock but does not block snapshot readers.

## API behavior

### Documents

`GET /api/docs` accepts existing filters plus `page`, `page_size`, and `paged=1`. Default page size is 50 and the hard API maximum is 200.

Paged response:

```json
{
  "items": [],
  "total": 3268,
  "page": 1,
  "page_size": 50,
  "pages": 66,
  "next_page": 2,
  "prev_page": null
}
```

`GET /api/docs/{id}` uses SQLite to resolve ID to path and only then reads that Markdown body.

### Search

Markdown document search is served from FTS5 rather than rereading every file. Short queries use one FTS-content substring scan, avoiding an N-by-N correlated lookup; list and global search consult the actual database tokenizer. Literal `%` and `_` are escaped. The browser performance layer aborts superseded global-search requests. TODO metadata is indexed; Agent chat keeps its previous transcript-search behavior.

### Dashboard

Counts, recent documents, project statistics, milestone windows and activity aggregates are queried from SQLite. Dashboard no longer reconstructs those values by repeatedly parsing the full Markdown collection.

### Knowledge graph

- `GET /api/graph/overview?limit=80`: bounded research-overview graph.
- `GET /api/graph?limit=300`: bounded full graph, hard maximum 500 document nodes.
- `GET /api/graph/neighborhood?root=...&depth=1|2`: indexed BFS; it no longer constructs the global graph first.

The graph response includes `meta.total_documents`, `meta.shown_documents` and `meta.truncated` so the UI can show the protection limit and progressively request more nodes.

### Workspace tree

- `GET /api/workspace/tree`: Workspace root plus direct children only.
- `GET /api/workspace/children?path=Knowledge`: one directory level on demand.
- `GET /api/workspace/tree?full=1`: compatibility/debug path for the old bounded recursive tree.

### Index maintenance

- `GET /api/system/index`: status and counts.
- `POST /api/system/index/rebuild`: delete and fully rebuild the disposable index.
- Workspace UI exposes the same rebuild action.

## Workspace migration behavior

`System/schema.json` records the Workspace/index schema. The expensive legacy project-ID migration remains available, but startup only invokes it when the schema/registry indicates migration is required. Manual Workspace migration and system reload are explicit full-repair paths and rebuild the index afterward.

## Browser protection

`web/v260922-performance.js` is loaded before the existing application script and provides:

- 50-row server-side document pages (milestones use a bounded 200-row page for timeline usability);
- previous/next page controls;
- aborting superseded global-search requests;
- 80-node research-overview graph;
- 300-node initial graph with progressive loading up to a hard 500-node browser cap;
- lazy Workspace directory expansion;
- index status/rebuild UI.

This bounds the existing `state.docs` and `state.graph` data without requiring a risky full rewrite of `web/app.js` in the same performance branch.

## Validation

Run the existing self-check first, then the non-destructive benchmark:

```bash
python tools/self_check.py
python tools/performance_benchmark.py
python tools/performance_benchmark.py --query transformer --repeat 5
```

For a cold-index measurement:

```bash
python tools/performance_benchmark.py --rebuild --repeat 3
```

For reproducible checks without personal configuration or research data:

```bash
python tools/test_index_architecture.py
python tools/test_bulk_delete.py
python tools/self_check.py
python tools/performance_benchmark.py --synthetic 10000 --query zzzznomatch --repeat 3
node tools/ui_usability_check.js
```

The browser check requires Playwright and a local Edge installation. The synthetic benchmark keeps its generated Workspace and JSON results under `.scratch/performance-*` for inspection. Self-check now uses isolated temporary configuration, rather than saving and restoring the user's config files.

The benchmark does not create or modify research documents. `--rebuild` only deletes/recreates the disposable SQLite cache.

## Intended scale

The design follows the performance manual's target class of 10,000+ Markdown records, 100+ projects, 10,000+ todos and a global graph with 10,000+ document nodes while keeping a browser-visible graph in the low hundreds. Actual latency depends on disk, CPU, Markdown body size and OS file-cache state.
