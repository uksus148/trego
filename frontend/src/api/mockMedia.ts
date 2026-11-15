import type { LandmarkPhoto, PlaceMedia } from '../types'
import { ApiError } from './realApi'

// Mock-mode media (docs/LANDMARK_PHOTOS_CONTRACT.md, section 8): synthetic responses only, no live photo search.
// The image is a local, visibly labelled illustration; the dummy Wikimedia paths from the contract are never fetched.
// Replace with the shared docs/contracts/landmark-photos.examples.json once it lands on main.

const ILLUSTRATION = '/mock-illustration.svg'
const FIXTURE_PAGE = 'https://commons.wikimedia.org/wiki/File:Fixture.jpg'

function illustration(id: string, title: string, caption: string | null): LandmarkPhoto {
  return {
    id,
    provider: 'wikimedia_commons',
    url: ILLUSTRATION,
    thumbUrl: ILLUSTRATION,
    title,
    description: caption === null ? null : { text: caption, sourceUrl: FIXTURE_PAGE },
    author: 'Fixture photographer (mock data)',
    license: 'CC BY-SA 3.0',
    licenseUrl: 'https://creativecommons.org/licenses/by-sa/3.0/',
    sourceUrl: FIXTURE_PAGE,
    associationSourceUrl: FIXTURE_PAGE,
    photoLocation: null,
  }
}

const ready = (placeId: string, photo: LandmarkPhoto): PlaceMedia => ({
  placeId,
  status: 'ready',
  fetchedAt: '2026-11-15T00:00:00Z',
  placeDescription: null,
  photos: [photo],
})

// Keyed by the mock demo place ids from src/data/tatras.ts. Popradské pleso stays empty on purpose (information-only card).
const FIXTURES: ReadonlyMap<string, PlaceMedia> = new Map([
  ['demo-strbske-pleso', ready('demo-strbske-pleso', illustration('commons:100001', 'Mock illustration: Štrbské Pleso', 'Synthetic caption for the lake.'))],
  ['demo-skok', ready('demo-skok', illustration('commons:100002', 'Mock illustration: Skok Waterfall', null))],
])

export function mockPlaceMedia(placeId: string, knownPlace: boolean): PlaceMedia {
  const fixture = FIXTURES.get(placeId)
  if (fixture) return fixture
  if (!knownPlace) throw new ApiError('Place not found.', 404, 'place_not_found')
  return { placeId, status: 'empty', fetchedAt: null, placeDescription: null, photos: [] }
}
