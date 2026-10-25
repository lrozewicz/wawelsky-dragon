// Odpowiednik `DatasetListed` z backend/openapi.json — pola używane przez karty Home (08 §7.2).
export type FixtureDataset = {
  id: string
  name: string
  description: string | null
  document_count: number
}

// Odpowiednik `ChatListItem` z backend/openapi.json — pola używane przez karty Home.
export type FixtureChat = {
  id: string
  name: string
  description: string
}

export const fixtureDataset: FixtureDataset = {
  id: 'ds-1',
  name: 'Baza testowa',
  description: 'Opis bazy testowej',
  document_count: 3,
}

export const fixtureChat: FixtureChat = {
  id: 'chat-1',
  name: 'Czat testowy',
  description: 'Opis czatu testowego',
}
