# Architecture

[Polski](../pl/architecture.md)

## Services

| Service | Role | Published port |
| --- | --- | --- |
| `mariadb` | the only database: metadata, vectors, full-text indexes, task queue, LLM cache, sessions | none |
| `migrate` | one-shot: schema migrations, model seed, admin account | none |
| `api` | FastAPI: RAGFlow-compatible and native routes, streaming, health checks | none (behind `web`) |
| `worker` | task queue: parsing, chunking, embeddings, integration scheduler | none |
| `web` | React and MUI single-page app, served by Bun, with a reverse proxy to `api` | 8080 |
| `searxng` | internal web search service for the planned agent; nothing uses it yet | none |

Optional Compose profiles: `mcp` (MCP server), `ocr` (local OCR model), `gpu` (agent that starts models on the server's GPU), `fake` (LLM stub for trying the system without a key).

Data lives in two volumes: `db-data` (database) and `app-data` (original documents and chunk images).

## How a document becomes an answer

```
upload ─► task in MariaDB ─► worker: convert to HTML ─► chunk ─► embed ─► vectors + full text
                                                                               │
question ─► hybrid retrieval (vectors + full text, optional rerank) ◄──────────┘
                    │
                    └─► LLM ─► streamed answer with citations
```

## Design decisions

- **MariaDB is the only database.** `VECTOR` columns, `FULLTEXT` indexes and a task queue using `FOR UPDATE SKIP LOCKED` replace a separate search engine and Redis.
- **Exact vector search.** Retrieval scans the vectors of the selected knowledge bases instead of using an approximate index. This costs memory and limits scale, but results stay correct after repeated re-parsing. Measured p95: 1.27 s for 100,000 vectors of 3072 dimensions with a 6 GB pool ([measurements](../perf/E5-1b.md)).
- **The compatible API is first-class.** Domain logic uses its own names. Presenters reproduce the exact RAGFlow response shapes, and input normalizers accept v0.27 and v0.24 forms.
- **One LLM client.** Everything goes through the OpenAI-compatible protocol, with a model registry in the database.
- **One chunker.** Every format is converted to HTML, then split according to the selected method.
- **Connectors behind one interface.** SharePoint is the first implementation of the `Connector` interface.

More detail, in Polish: [architecture map and all decisions](../ARCHITECTURE.md), [what was actually built](../BIG-PICTURE.md), [module documents](../modules/).
