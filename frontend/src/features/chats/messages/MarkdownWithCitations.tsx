/**
 * Markdown odpowiedzi asystenta ze znacznikami cytowań (kontrakt WP E3-5b §T5a).
 *
 * Metoda jest DOSŁOWNA z kontraktu: `tokenizeCitations` dzieli tekst na segmenty (znaczniki
 * wewnątrz bloku kodu i kodu inline zostają tekstem — patrz `lib/citations.ts`), a znaczniki
 * zamieniamy na linki `[n](cite:i)` i oddajemy jako JEDEN dokument markdown do `ReactMarkdown`.
 * `urlTransform` przepuszcza własny schemat `cite:` (domyślny transformator by go wyciął),
 * a komponent `a` rozpoznaje go i renderuje `CitationChip`; zwykłe linki dostają `target="_blank"`
 * i `rel="noopener noreferrer"`.
 *
 * Surowy HTML w odpowiedzi (`<p>…` z bloków wiedzy) NIE jest parsowany — `remarkNoHtml` wyłącza
 * tokeny `htmlFlow`/`htmlText`, więc tag zostaje tekstem, a znacznik cytowania w tej samej linii
 * nadal działa (zmiana kontraktu T5a, WP E3-5b).
 */

import { createContext, useContext } from 'react'
import type { ComponentProps, JSX } from 'react'
import Link from '@mui/material/Link'
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { tokenizeCitations } from '../../../lib/citations'
import type { Citation } from '../../chat-stream/reducer'

import { CitationChip } from './CitationChip'

export type MarkdownWithCitationsProps = {
  text: string
  citations: Citation[]
  onOpenDocument: (docId: string, docName: string) => void
}

/** Schemat adresu, którym oznaczamy cytowania w złożonym markdownie. */
const CITE_SCHEME = 'cite:'

/**
 * Minimalny widok procesora `unified`, jakiego potrzebuje `remarkNoHtml`. Typ lokalny, bo ani
 * `unified`, ani `micromark-util-types` nie są bezpośrednią zależnością frontendu
 * (`frontend/package.json`) — sięganie po typy zależności przechodniej byłoby kruche.
 */
type ProcessorData = { data: () => Record<string, unknown[] | undefined> }

/**
 * Wyłącza rozpoznawanie HTML w treści odpowiedzi (bloki `htmlFlow` i tagi w linii `htmlText`).
 *
 * Treść z bloków wiedzy bywa surowym HTML-em (`<p>…`). Gdy linia zaczyna się od tagu, `micromark`
 * otwiera blok HTML i połyka resztę akapitu — razem ze znacznikiem cytowania. Po wyłączeniu tych
 * tokenów tag zostaje zwykłym tekstem, a `[n](cite:i)` w tej samej linii nadal tworzy chip.
 */
function remarkNoHtml(this: ProcessorData): void {
  const data = this.data()
  const extensions = (data.micromarkExtensions ??= [])
  extensions.push({ disable: { null: ['htmlFlow', 'htmlText'] } })
}

/** Typ listy pluginów remark przyjmowany przez `react-markdown`; rzutujemy nań `remarkNoHtml`. */
type RemarkPluginList = ComponentProps<typeof ReactMarkdown>['remarkPlugins']

/** Składa segmenty tokenizera z powrotem w markdown: cytowanie → link `[n+1](cite:indeks)`. */
function toMarkdown(text: string, chunkCount: number): string {
  return tokenizeCitations(text, chunkCount)
    .map((segment) =>
      segment.type === 'text'
        ? segment.text
        : `[${segment.index + 1}](${CITE_SCHEME}${segment.index})`,
    )
    .join('')
}

/** Indeks cytowania z adresu `cite:n`; `null` dla zwykłych adresów i adresów bez numeru. */
function citeIndex(href: string | undefined): number | null {
  if (href === undefined || !href.startsWith(CITE_SCHEME)) return null
  const index = Number(href.slice(CITE_SCHEME.length))
  return Number.isInteger(index) && index >= 0 ? index : null
}

/**
 * Dane dla komponentu linku, dostarczane kontekstem.
 *
 * `react-markdown` traktuje wpisy `components` jako TYPY elementów Reacta: komponent zdefiniowany
 * w ciele `MarkdownWithCitations` ma nową tożsamość przy każdym renderze, więc React odmontowywał
 * i montował od nowa całe poddrzewo markdownu — chip cytowania tracił stan i węzeł DOM, a fokus
 * (np. po Esc w szufladzie podglądu) lądował na `body` (MINOR QA E5-H3 #7). Dane idą kontekstem,
 * dzięki czemu lista `components` jest STAŁĄ modułową, a tożsamość komponentu linku nie zmienia się.
 */
type CitationsContextValue = {
  citations: Citation[]
  onOpenDocument: (docId: string, docName: string) => void
}

const CitationsContext = createContext<CitationsContextValue>({
  citations: [],
  onOpenDocument: () => undefined,
})

/** Komponent linku markdownu: rozpoznaje schemat `cite:` i renderuje `CitationChip`. */
function CitationLink({ href, children }: ComponentProps<'a'>): JSX.Element {
  const { citations, onOpenDocument } = useContext(CitationsContext)
  const index = citeIndex(href)
  if (index === null) {
    return (
      <Link href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </Link>
    )
  }
  const citation = citations[index]
  // Link `cite:` wpisany ręcznie może wskazywać poza zakres cytowań — wtedy sam tekst.
  if (citation === undefined) return <>{children}</>
  return <CitationChip index={index} citation={citation} onOpenDocument={onOpenDocument} />
}

const COMPONENTS = { a: CitationLink }

export function MarkdownWithCitations(props: MarkdownWithCitationsProps): JSX.Element {
  const { text, citations, onOpenDocument } = props

  return (
    <CitationsContext.Provider value={{ citations, onOpenDocument }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkNoHtml] as RemarkPluginList}
        urlTransform={(url) => (url.startsWith(CITE_SCHEME) ? url : defaultUrlTransform(url))}
        components={COMPONENTS}
      >
        {toMarkdown(text, citations.length)}
      </ReactMarkdown>
    </CitationsContext.Provider>
  )
}
