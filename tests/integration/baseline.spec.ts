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
  test.fail(true, 'Known main defect, owned by #82: ready answer precedes readback; remove annotation when fixed.')
  expect(await page.getByText(/Your hike is ready/).count()).toBe(replies)
  if (retained) {
    await expect(page.getByRole('status').filter({ hasText: /previous route/i })).toBeVisible()
  }
})

test('invalid route 200 remains recoverable without blanking React (#82)', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route(`${services.api}/api/routes/*`, route => route.fulfill({ json: { id: services.route.id } }))
  await page.goto(services.frontend)
  await send(page)
  await expect.poll(async () => errors.length + await page.getByRole('alert').count()).toBeGreaterThan(0)
  if (errors.length) expect(errors[0]).toMatch(/Cannot read properties.*map/)
  test.fail(true, 'Known main defect, owned by #82: invalid Route blanks React; remove annotation when fixed.')
  expect(errors).toEqual([])
  await expect(page.getByRole('textbox')).toBeVisible()
})
