import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

const services = JSON.parse(readFileSync(process.env.E2E_CONFIG!, 'utf8'))
const corpus = JSON.parse(readFileSync(new URL('../../docs/contracts/baseline.examples.json', import.meta.url), 'utf8'))
const pixel = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64')

test.beforeEach(async ({ page }) => {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if ([services.api, services.agent, services.frontend].includes(url.origin)) return route.continue()
    if (url.href === 'https://tiles.openfreemap.org/styles/liberty') {
      return route.fulfill({ json: { version: 8, sources: {}, layers: [] } })
    }
    if (url.host === 'upload.wikimedia.org' && url.pathname.startsWith('/fixture-catalog-')) {
      return route.fulfill({ contentType: 'image/png', body: pixel })
    }
    if (url.host === 'fonts.googleapis.com' && url.pathname === '/css2') {
      return route.fulfill({ contentType: 'text/css', body: '' })
    }
    throw new Error(`Blocked unexpected browser host/path: ${url.host}${url.pathname}`)
  })
})

async function send(page: Page) {
  await page.getByRole('textbox').fill(corpus.message)
  await page.getByRole('button', { name: 'Go', exact: true }).click()
}

async function loaded(page: Page) {
  await expect(page.getByText('7.5 km', { exact: true })).toBeVisible()
}

test('actual chat → Java readback → React; media failure retries only one GET', async ({ page }) => {
  const errors: string[] = [], posts: string[] = [], media: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('request', req => { if (req.method() === 'POST') posts.push(req.url()) })
  const falls = services.chat.places.find((p: { name: string }) => p.name === 'Fixture Falls')
  let fail = true
  await page.route(`${services.api}/api/places/${falls.id}/media`, route => {
    media.push(route.request().method())
    if (fail) return route.fulfill({ status: 503, json: { detail: 'Injected media-only failure' } })
    return route.continue()
  })
  await page.goto(services.frontend)
  const chatResponsePromise = page.waitForResponse(response =>
    response.url() === `${services.agent}/api/chat` && response.request().method() === 'POST')
  const routeResponsePromise = page.waitForResponse(response =>
    response.url().startsWith(`${services.api}/api/routes/`) && response.request().method() === 'GET')
  await send(page)
  const chatResponse = await chatResponsePromise
  expect(chatResponse.status()).toBe(200)
  const browserChat = await chatResponse.json()
  const routeResponse = await routeResponsePromise
  expect(routeResponse.url()).toBe(`${services.api}/api/routes/${browserChat.routeId}`)
  expect(routeResponse.status()).toBe(200)
  expect(await routeResponse.json()).toEqual({ ...services.route, id: browserChat.routeId })
  await loaded(page)
  await page.getByRole('button', { name: 'Fixture Falls: show details', exact: true }).click()
  await expect(page.getByText('Photo unavailable right now.')).toBeVisible()
  expect(media).toEqual(['GET'])
  expect(posts).toEqual([`${services.agent}/api/chat`])
  fail = false
  await page.getByRole('button', { name: 'Retry', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Open photo: Synthetic catalog image' }).first()).toBeVisible()
  await loaded(page)
  expect(media).toEqual(['GET', 'GET'])
  expect(posts).toHaveLength(1)
  expect(errors).toEqual([])
})

test('readback 404 does not associate a new ready answer with an old route (#82)', async ({ page }) => {
  await page.goto(services.frontend)
  await send(page)
  await loaded(page)
  const replies = await page.getByText(/Your hike is ready/).count()
  let getCount = 0, postCount = 0
  page.on('request', req => { if (req.method() === 'POST') postCount++ })
  await page.route(`${services.api}/api/routes/*`, route => {
    getCount++
    return route.fulfill({ status: 404, json: { detail: 'Injected route readback failure' } })
  })
  await send(page)
  await expect(page.getByRole('alert')).toContainText('Injected route readback failure')
  expect(getCount).toBe(1)
  expect(postCount).toBe(1)
  const retained = await page.getByText('7.5 km', { exact: true }).isVisible()
  expect(await page.getByText(/Your hike is ready/).count()).toBe(replies)
  if (retained) {
    await expect(page.getByRole('status').filter({ hasText: /previous route/i })).toBeVisible()
  }
})

test('invalid route 200 remains recoverable without blanking React (#82)', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route(`${services.api}/api/routes/*`, route => {
    const requestedId = new URL(route.request().url()).pathname.split('/').at(-1)
    return route.fulfill({ status: 200, json: { id: requestedId } })
  })
  await page.goto(services.frontend)
  await send(page)
  await expect(page.getByRole('alert')).toContainText('The server returned invalid route data.')
  expect(errors).toEqual([])
  await expect(page.getByRole('textbox')).toBeVisible()
})


test('manual stop changes label the saved route as previous until the next build', async ({ page }) => {
  const stopIds: string[][] = []
  const addedPlaces: Array<(typeof corpus.places)[number]> = []
  const cors = { 'Access-Control-Allow-Origin': services.frontend }
  await page.route(`${services.api}/api/places`, async route => {
    const input = route.request().postDataJSON()
    const place = { ...input, id: crypto.randomUUID(), source: 'manual', photos: [] }
    addedPlaces.push(place)
    await route.fulfill({ status: 201, headers: cors, json: place })
  })
  await page.route(`${services.api}/api/places/*/media`, route => route.fulfill({
    headers: cors,
    json: { placeId: new URL(route.request().url()).pathname.split('/')[3],
      status: 'empty', fetchedAt: null, placeDescription: null, photos: [] },
  }))
  await page.route(`${services.api}/api/routes`, async route => {
    const { start, end, placeIds } = route.request().postDataJSON()
    stopIds.push(placeIds)
    await route.fulfill({ status: 201, headers: cors, json: {
      ...corpus.route,
      id: crypto.randomUUID(),
      distanceKm: stopIds.length === 1 ? 12.3 : 5.2,
      geojson: { type: 'LineString', coordinates: [[start.lon, start.lat], [end.lon, end.lat]] },
      places: placeIds.map((id: string) => addedPlaces.find(place => place.id === id)),
    } })
  })

  await page.goto(services.frontend)
  await page.getByRole('tab', { name: 'Plan on map' }).click()
  const map = page.locator('canvas.maplibregl-canvas')
  await page.getByRole('button', { name: /Start \(A\)/ }).click()
  await map.click({ position: { x: 250, y: 300 } })
  await page.getByRole('button', { name: /Finish \(B\)/ }).click()
  await map.click({ position: { x: 500, y: 330 } })
  const pickStop = async () => {
    await page.getByRole('button', { name: '+ Add on map', exact: true }).click()
    await map.click({ position: { x: 380, y: 310 } })
  }
  const saveStop = async (name: string) => {
    await page.getByPlaceholder('Name, e.g. Skok waterfall').fill(name)
    await page.getByRole('button', { name: 'Save place', exact: true }).click()
    await expect(page.getByRole('button', { name: `Remove ${name}`, exact: true })).toBeVisible()
  }
  const build = page.getByRole('button', { name: 'Build route', exact: true })
  const previous = page.getByRole('status').filter({ hasText: 'Showing a previous route.' })
  const firstMarker = page.getByRole('button', { name: 'Manual stop: show details', exact: true })
  await pickStop()
  await saveStop('Manual stop')
  await build.click()
  await expect(page.getByText('12.3 km', { exact: true })).toBeVisible()
  await expect(previous).toHaveCount(0)

  await page.getByRole('button', { name: 'Remove Manual stop', exact: true }).click()
  await expect(page.getByText('No places yet.')).toBeVisible()
  await expect(previous).toBeVisible()
  await expect(page.getByText('12.3 km', { exact: true })).toBeVisible()
  await expect(firstMarker).toBeVisible()
  expect(stopIds).toEqual([[addedPlaces[0].id]])

  await build.click()
  await expect(page.getByText('5.2 km', { exact: true })).toBeVisible()
  await expect(previous).toHaveCount(0)
  await expect(firstMarker).toHaveCount(0)

  await pickStop()
  await expect(previous).toBeVisible()
  await saveStop('Pending stop')
  await expect(previous).toBeVisible()
  await expect(page.getByText('5.2 km', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Pending stop: show details', exact: true })).toHaveCount(0)
  expect(stopIds).toEqual([[addedPlaces[0].id], []])
})

if (process.env.E2E_EDITOR === '1') {
  test('chat-origin editor confirms a retry after an ambiguous save and starts a fresh session on success', async ({ page }) => {
    const chatUrl = `${services.agent}/api/chat`
    const routeUrl = `${services.api}/api/routes`
    const chatPosts: Array<{ sessionId: string; message: string }> = []
    const rebuildPosts: unknown[] = []
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('request', request => {
      if (request.url() === chatUrl && request.method() === 'POST') chatPosts.push(request.postDataJSON())
    })
    await page.route(routeUrl, route => {
      if (route.request().method() !== 'POST') return route.continue()
      rebuildPosts.push(route.request().postDataJSON())
      if (rebuildPosts.length === 1) {
        return route.fulfill({
          status: 504,
          contentType: 'text/html',
          headers: { 'Access-Control-Allow-Origin': services.frontend },
          body: '<html>Gateway timeout</html>',
        })
      }
      return route.continue()
    })

    await page.goto(services.frontend)
    await send(page)
    await loaded(page)
    const activeRouteId = () => page.evaluate(() => sessionStorage.getItem('trego.activeRouteId'))
    const originalId = await activeRouteId()
    expect(originalId).toBeTruthy()
    await page.getByRole('button', { name: 'Edit route', exact: true }).click()
    await expect(page.getByRole('combobox', { name: 'Start place', exact: true })).toHaveValue('')
    await expect(page.getByRole('combobox', { name: 'Finish place', exact: true })).toHaveValue('')
    const stops = page.getByRole('list', { name: 'Intermediate visits' })
    await stops.getByRole('button', { name: 'Remove Fixture Falls', exact: true }).first().click()
    const rebuild = page.getByRole('button', { name: 'Rebuild route', exact: true })
    await rebuild.click()
    await expect(page.getByRole('alert')).toContainText('The route may have been saved.')
    await loaded(page)
    expect(await activeRouteId()).toBe(originalId)
    await expect(stops.getByRole('listitem')).toHaveCount(2)
    expect(rebuildPosts).toHaveLength(1)
    expect(chatPosts).toHaveLength(1)

    await Promise.all([
      page.waitForEvent('dialog').then(async dialog => {
        const message = dialog.message()
        await dialog.dismiss()
        expect(message).toContain('Submitting again can create another route.')
      }),
      rebuild.click(),
    ])
    expect(rebuildPosts).toHaveLength(1)
    expect(await activeRouteId()).toBe(originalId)

    const saving = page.waitForResponse(response => response.url() === routeUrl && response.request().method() === 'POST')
    await Promise.all([
      page.waitForEvent('dialog').then(dialog => dialog.accept()),
      rebuild.click(),
    ])
    const response = await saving
    expect(response.status()).toBe(201)
    const saved = await response.json()
    expect(saved.id).not.toBe(originalId)
    expect(rebuildPosts).toHaveLength(2)
    expect(rebuildPosts[1]).toEqual(rebuildPosts[0])
    expect(rebuildPosts[1]).toMatchObject({ startPlaceId: null, endPlaceId: null })
    expect(chatPosts).toHaveLength(1)
    await expect.poll(activeRouteId).toBe(saved.id)
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    await page.getByRole('tab', { name: 'Ask', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Original plan, read only' })).toBeVisible()
    const nextChat = page.waitForResponse(reply => reply.url() === chatUrl && reply.request().method() === 'POST')
    await send(page)
    const nextReply = await nextChat
    expect(nextReply.status()).toBe(200)
    const nextRoute = await nextReply.json()
    await expect.poll(activeRouteId).toBe(nextRoute.routeId)
    expect(chatPosts).toHaveLength(2)
    expect(chatPosts[1]).toEqual({ sessionId: expect.any(String), message: corpus.message })
    expect(chatPosts[1].sessionId).not.toBe(chatPosts[0].sessionId)
    expect(rebuildPosts).toHaveLength(2)
    expect(errors).toEqual([])
  })

  test('manual editor rebuilds a new snapshot and restores bindings without agent calls', async ({ page }) => {
    const oldContext = await (await page.request.get(`${services.api}/api/routes/${services.route.id}/editing-context`)).json()
    const seed = await page.request.post(`${services.api}/api/routes`, { data: {
      start: { lat: oldContext.start.lat, lon: oldContext.start.lon },
      end: { lat: oldContext.end.lat, lon: oldContext.end.lon },
      placeIds: oldContext.stops.map((p: { id: string }) => p.id), preferences: oldContext.preferences,
    } })
    expect(seed.status()).toBe(201)
    const original = await seed.json()
    const originalContext = await (await page.request.get(`${services.api}/api/routes/${original.id}/editing-context`)).json()
    const agentCalls: string[] = []
    await page.route(`${services.agent}/**`, route => { agentCalls.push(route.request().url()); return route.abort() })
    await page.addInitScript(id => {
      if (!sessionStorage.getItem('trego.activeRouteId')) sessionStorage.setItem('trego.activeRouteId', id)
    }, original.id)
    await page.goto(services.frontend)
    await loaded(page)
    await page.getByRole('button', { name: 'Edit route', exact: true }).click()
    const visits = page.getByRole('list', { name: 'Intermediate visits' })
    await expect(visits.getByRole('listitem')).toHaveCount(3)
    await visits.getByRole('button', { name: 'Remove Fixture Falls', exact: true }).first().click()
    await expect(visits.getByRole('listitem')).toHaveCount(2)
    await visits.getByRole('button', { name: 'Move Fixture Falls up', exact: true }).click()
    await page.getByRole('button', { name: 'Swap start and finish', exact: true }).click()
    const bound = services.chat.places.find((p: { name: string }) => p.name === 'Fixture Falls')
    await page.getByRole('combobox', { name: 'Start place', exact: true }).selectOption(bound.id)
    expect(await page.evaluate(() => sessionStorage.getItem('trego.activeRouteId'))).toBe(original.id)
    await loaded(page)
    const saving = page.waitForResponse(r => r.url() === `${services.api}/api/routes` && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'Rebuild route', exact: true }).click()
    const response = await saving
    expect(response.status()).toBe(201)
    const saved = await response.json()
    expect(saved.id).not.toBe(original.id)
    const submitted = response.request().postDataJSON()
    expect(submitted.startPlaceId).toBe(bound.id)
    expect(submitted.placeIds).toEqual([originalContext.stops[2].id, originalContext.stops[1].id])
    const savedContext = await (await page.request.get(`${services.api}/api/routes/${saved.id}/editing-context`)).json()
    expect(savedContext.start.place.id).toBe(bound.id)
    expect(savedContext.end).toEqual(originalContext.start)
    expect(savedContext.preferences).toEqual(originalContext.preferences)
    expect(savedContext.stops.map((p: { id: string }) => p.id)).toEqual(submitted.placeIds)
    expect(await (await page.request.get(`${services.api}/api/routes/${original.id}`)).json()).toEqual(original)
    expect(await (await page.request.get(`${services.api}/api/routes/${original.id}/editing-context`)).json()).toEqual(originalContext)
    await expect.poll(() => page.evaluate(() => sessionStorage.getItem('trego.activeRouteId'))).toBe(saved.id)
    await page.reload()
    await loaded(page)
    await page.getByRole('button', { name: 'Edit route', exact: true }).click()
    await expect(page.getByRole('combobox', { name: 'Start place', exact: true })).toHaveValue(bound.id)
    await expect(page.getByRole('list', { name: 'Intermediate visits' }).getByRole('listitem')).toHaveCount(2)
    await expect(page.getByRole('button', { name: 'Open photo: Synthetic catalog image' }).first()).toBeVisible()
    expect(agentCalls).toEqual([])
  })
}
