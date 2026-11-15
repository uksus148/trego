import { describe, expect, it } from 'vitest'
import { firstPhoto, MediaContractError, nextMediaRequests, parsePlaceMedia, type MediaState } from './media'

const PLACE_ID = '00000000-0000-4000-8000-000000000002'

// The synthetic ready example from docs/LANDMARK_PHOTOS_CONTRACT.md, section 5.
const photo = {
  id: 'commons:123456',
  provider: 'wikimedia_commons',
  url: 'https://upload.wikimedia.org/fixture-full.jpg',
  thumbUrl: 'https://upload.wikimedia.org/fixture-thumb.jpg',
  title: 'Synthetic landmark image',
  description: { text: 'Synthetic source caption identifying the landmark.', sourceUrl: 'https://commons.wikimedia.org/wiki/File:Fixture.jpg' },
  author: 'Fixture photographer',
  license: 'CC BY-SA 3.0',
  licenseUrl: 'https://creativecommons.org/licenses/by-sa/3.0/',
  sourceUrl: 'https://commons.wikimedia.org/wiki/File:Fixture.jpg',
  associationSourceUrl: 'https://commons.wikimedia.org/wiki/File:Fixture.jpg',
  photoLocation: null,
}
const ready = { placeId: PLACE_ID, status: 'ready', fetchedAt: '2026-11-15T00:00:00Z', placeDescription: null, photos: [photo] }
const empty = { placeId: PLACE_ID, status: 'empty', fetchedAt: null, placeDescription: null, photos: [] }

const withPhoto = (patch: Record<string, unknown>) => ({ ...ready, photos: [{ ...photo, ...patch }] })
const { description: _omitted, ...photoWithoutDescription } = photo

describe('parsePlaceMedia', () => {
  it('accepts the contract ready example', () => {
    const media = parsePlaceMedia(PLACE_ID, ready)

    expect(media.status).toBe('ready')
    expect(media.photos[0].url).toBe(photo.url)
  })

  it('accepts an empty gallery with a sourced place description', () => {
    const description = { text: 'A glacial lake.', sourceUrl: 'https://en.wikipedia.org/wiki/Lake' }

    const media = parsePlaceMedia(PLACE_ID, { ...empty, placeDescription: description })

    expect(media.photos).toEqual([])
    expect(media.placeDescription).toEqual(description)
  })

  it('accepts a photo without caption or geotag', () => {
    const media = parsePlaceMedia(PLACE_ID, withPhoto({ description: null, photoLocation: null }))

    expect(media.photos[0].description).toBeNull()
  })

  it.each([
    ['a different placeId', { ...ready, placeId: 'other' }],
    ['ready without photos', { ...ready, photos: [] }],
    ['empty with a photo', { ...empty, photos: [photo] }],
    ['more than one photo', { ...ready, photos: [photo, photo] }],
    ['an unknown status', { ...ready, status: 'partial' }],
    ['a missing placeDescription key', { placeId: PLACE_ID, status: 'empty', fetchedAt: null, photos: [] }],
    ['an image on another host', withPhoto({ url: 'https://evil.example/full.jpg' })],
    ['a non-HTTPS thumbnail', withPhoto({ thumbUrl: 'http://upload.wikimedia.org/t.jpg' })],
    ['credentials in a URL', withPhoto({ sourceUrl: 'https://user:pw@commons.wikimedia.org/x' })],
    ['an explicit port', withPhoto({ url: 'https://upload.wikimedia.org:8443/f.jpg' })],
    ['a javascript source link', withPhoto({ sourceUrl: 'javascript:alert(1)' })],
    ['a blank author', withPhoto({ author: '  ' })],
    ['an empty license', withPhoto({ license: '' })],
    ['a bad Commons id', withPhoto({ id: 'commons:abc' })],
    ['a missing description key', { ...ready, photos: [photoWithoutDescription] }],
    ['an out-of-range geotag', withPhoto({ photoLocation: { lat: 91, lon: 0 } })],
  ])('rejects %s', (_, body) => {
    expect(() => parsePlaceMedia(PLACE_ID, body)).toThrow(MediaContractError)
  })
})

describe('nextMediaRequests', () => {
  const loading: MediaState = { status: 'loading' }

  it('requests the selected place first and at most two at once', () => {
    expect(nextMediaRequests(['a', 'b', 'c'], 'c', new Map())).toEqual(['c', 'a'])
  })

  it('skips places already requested and respects in-flight requests', () => {
    const states = new Map<string, MediaState>([['a', loading]])

    expect(nextMediaRequests(['a', 'b', 'c'], null, states)).toEqual(['b'])
  })

  it('requests nothing while two are in flight', () => {
    const states = new Map<string, MediaState>([['a', loading], ['b', loading]])

    expect(nextMediaRequests(['a', 'b', 'c'], 'c', states)).toEqual([])
  })

  it('requests repeated visits once', () => {
    expect(nextMediaRequests(['a', 'a'], null, new Map())).toEqual(['a'])
  })

  it('ignores a selected place that is not on the map', () => {
    expect(nextMediaRequests(['a'], 'gone', new Map())).toEqual(['a'])
  })
})

describe('firstPhoto', () => {
  it('returns the photo only for loaded media', () => {
    expect(firstPhoto({ status: 'ready', media: parsePlaceMedia(PLACE_ID, ready) })?.id).toBe('commons:123456')
    expect(firstPhoto({ status: 'loading' })).toBeUndefined()
    expect(firstPhoto(undefined)).toBeUndefined()
  })
})
