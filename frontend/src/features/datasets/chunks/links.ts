/**
 * Link do strony chunków dokumentu (08 §7.4 — kolumna Nazwa, §7.5): trasa-szkielet
 * `/chunk/parsed/chunks?id=<dataset>&doc_id=<dokument>` (kontrakt WP E3-3b §T4).
 * `to` jest typem literałowym, więc `Link`/`navigate` przyjmują wynik bez rzutu.
 */

/** Propsy linku-routera do strony chunków — `to` jako literał trasy. */
export type ChunksLinkProps = {
  to: '/chunk/parsed/chunks'
  search: { id: string; doc_id: string }
}

export function chunksLinkProps(datasetId: string, docId: string): ChunksLinkProps {
  return {
    to: '/chunk/parsed/chunks',
    search: { id: datasetId, doc_id: docId },
  }
}
