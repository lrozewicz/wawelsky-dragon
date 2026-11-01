# RAGFlow compatibility

[Polski](../pl/ragflow-compatibility.md)

Wawelsky Dragon is a drop-in replacement for the parts of RAGFlow that it implements, not a fork of the whole product.

## What is compatible

- `/api/v1` from RAGFlow v0.27.2: knowledge bases, documents, chunks, chats, sessions, search apps, files and retrieval. Routes, error codes and response shapes match.
- A shim for v0.24 clients.
- The OpenAI-compatible chat endpoint and the Dify external knowledge endpoint.

Compatibility is tested in two ways: response shapes are compared with recordings from a real RAGFlow v0.27.2 server, and the upstream API test suites are ported to this repository. Skipped and expected-to-fail cases are listed with reasons in [`SKIPPED.md`](../../backend/tests/contract/upstream/SKIPPED.md).

## How it differs

| | RAGFlow (default setup) | Wawelsky Dragon |
| --- | --- | --- |
| Metadata | MySQL | MariaDB |
| Chunks and vectors | Elasticsearch | MariaDB |
| Files | MinIO | volume |
| Queue and cache | Redis/Valkey | MariaDB |
| LLM providers | a class per provider | one OpenAI-compatible client |

## What is left out

- Knowledge graph, RAPTOR, tag sets and parent-child chunking. These settings are accepted and stored for API compatibility, but they do nothing.
- The `tag`, `knowledge_graph`, `resume` and `audio` chunking methods, which return an error.
- Agents and the canvas, memory, text-to-speech and speech recognition.
- Most of RAGFlow's data source connectors: SharePoint is the only one.

## Migrating

A migration tool copies users, knowledge bases, documents, chats and sessions from an existing RAGFlow instance. See [section 8 of the administrator runbook](../runbooks/admin.md#8-migracja-z-ragflow) (in Polish).
