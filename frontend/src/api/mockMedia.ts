import type { LandmarkPhoto, PlaceMedia } from '../types'
import { ApiError } from './realApi'

// Mock-mode media uses a local, visibly labelled illustration. Fixture URLs are never fetched.
const ILLUSTRATION = '/mock-illustration.svg'
const FIXTURE_PAGE = 'https://commons.wikimedia.org/wiki/File:Fixture.jpg'

function illustration(id: string, title: string, caption: string | null): LandmarkPhoto {
  return {
    id, provider: 'wikimedia_commons', url: ILLUSTRATION, thumbUrl: ILLUSTRATION, title,
    description: caption === null ? null : { text: caption, sourceUrl: FIXTURE_PAGE },
    author: 'Fixture photographer (mock data)', license: 'CC BY-SA 3.0',
    licenseUrl: 'https://creativecommons.org/licenses/by-sa/3.0/', sourceUrl: FIXTURE_PAGE,
    associationSourceUrl: FIXTURE_PAGE, photoLocation: null,
  }
}
const ready = (placeId: string, photo: LandmarkPhoto): PlaceMedia => ({
  placeId, status: 'ready', fetchedAt: '2026-11-15T00:00:00Z', placeDescription: null, photos: [photo],
})
// Popradské pleso stays empty on purpose (information-only card).
const FIXTURES: ReadonlyMap<string, PlaceMedia> = new Map([
  ['00000000-0000-4000-8000-000000000001', ready('00000000-0000-4000-8000-000000000001', illustration('commons:100001', 'Mock illustration: Štrbské Pleso', 'Synthetic caption for the lake.'))],
  ['00000000-0000-4000-8000-000000000002', ready('00000000-0000-4000-8000-000000000002', illustration('commons:100002', 'Mock illustration: Skok Waterfall', null))],
])
export function mockPlaceMedia(placeId: string, knownPlace: boolean): PlaceMedia {
  const fixture = FIXTURES.get(placeId)
  if (fixture) return fixture
  if (!knownPlace) throw new ApiError('Place not found.', 404, 'place_not_found')
  return { placeId, status: 'empty', fetchedAt: null, placeDescription: null, photos: [] }
}
