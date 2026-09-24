# RAG Recall v2

Experimental branch: `feature/rag-recall-v2`

## Goal

Improve retrieval recall without replacing Markdown as the source of truth.

The retrieval path is now:

1. Query analysis and deterministic multi-query expansion.
2. Three retrieval levels:
   - document representation;
   - Markdown section;
   - smaller chunk.
3. Metadata retrieval from title / heading / tags / project.
4. Optional WikiLink expansion.
5. Optional Embedding semantic retrieval.
6. Reciprocal Rank Fusion (RRF).
7. Deterministic rerank and per-document diversification.
8. Coverage check.
9. If coverage is insufficient, pseudo-relevance feedback derives extra terms from the best first-pass candidates and performs a second retrieval pass.
10. Chunk hits are expanded back to the parent Markdown section before being supplied to the Agent.

## Project scope modes

- `prefer`: search the whole Workspace, but boost the selected project. Recommended for recall.
- `strict`: selected project is a hard filter.
- `all`: search the whole Workspace without project weighting.

Tag filters remain hard filters.

## RAG index

The original Markdown files are never rewritten.

Derived cache data is stored in the existing SQLite index:

- `rag_units`
- `rag_units_fts`
- `rag_embeddings`

The cache is rebuildable from the Workspace.

### Retrieval units

Each document can generate:

- one document-level representation;
- one unit per Markdown section;
- chunk units for long sections.

Embedding text is context-enriched with document title, project, tags and heading path.

## Optional Embedding

Embedding is disabled by default.

When enabled, the workbench reuses the active Agent API profile's Base URL and API Key and calls its `/embeddings` endpoint with the separately configured embedding model.

The user must explicitly click **构建 / 更新** before Workspace units are sent for embedding.

Vectors are cached locally in SQLite and only changed/missing units are embedded again.

## Testing

In Agent:

1. Type a question but do not send it.
2. Open **自动检索**.
3. Recommended initial settings:
   - project strategy: 项目优先;
   - final results: 8;
   - candidate pool: 80;
   - Multi-Query: enabled;
   - adaptive second pass: enabled;
   - WikiLink: enabled;
   - tag filters: empty;
   - Embedding: disabled for the first comparison.
4. Click **用当前输入测试检索**.
5. Inspect:
   - generated query variants;
   - candidate pool size;
   - first-pass and final coverage;
   - whether a second pass was triggered;
   - feedback terms;
   - per-result retrieval routes.

Then enable Embedding, build the semantic index, and repeat the same questions for an A/B comparison.

## Suggested evaluation set

Create 30-50 questions for which the expected source documents are already known. For every query record:

- expected document IDs/titles;
- expected project;
- whether cross-project retrieval is required;
- expected section if known.

Compare the old branch and this branch using Top-5 / Top-10 source recall before judging answer quality.
