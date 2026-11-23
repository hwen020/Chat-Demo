import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

test('contacts can exchange messages live and open a group', async ({ browser }, info) => {
  const { baseURL, viewport, isMobile, hasTouch } = info.project.use
  const options = { baseURL, viewport, isMobile, hasTouch }
  const alice = await browser.newPage(options)
  const bob = await browser.newPage(options)
  const carol = await browser.newPage(options)
  const tag = randomUUID().slice(0, 6)
  const email = (name: string) => name + '.' + tag + '@example.test'
  async function register(page: Page, name: string) {
    await page.goto('/')
    if (process.env.CHATFLOW_EXPECT_PUBLIC_DEMO === '1') {
      await expect(page.getByText(/Demo \/ Synthetic Data/)).toBeVisible()
      expect((await page.request.get('/metrics')).status()).toBe(404)
      expect((await page.request.get('/openapi.json')).status()).toBe(404)
    }
    await page.getByRole('button', { name: 'Create an account' }).click()
    await page.getByLabel('Email').fill(email(name))
    await page.getByLabel('Password').fill('synthetic-only-password')
    await page.getByRole('button', { name: 'Register', exact: true }).click()
    await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible()
  }
  try {
    await Promise.all([register(alice, 'alex'), register(bob, 'sam'), register(carol, 'avery')])
    const peerMessage = 'I will send the agenda.'
    const ownMessage = 'I will read it before the meeting.'
    await alice.addInitScript((text) => {
      const NativeSocket = window.WebSocket
      window.WebSocket = class extends NativeSocket {
        constructor(url: string | URL, protocols?: string | string[]) {
          super(url, protocols)
          this.addEventListener('message', event => {
            if (document.documentElement.dataset.delayed || JSON.parse(event.data).content !== text) return
            event.stopImmediatePropagation()
            document.documentElement.dataset.delayed = 'true'
            window.addEventListener('deliver-delayed-chat', () => {
              for (let i = 0; i < 2; i++) this.dispatchEvent(new MessageEvent('message', { data: event.data }))
            }, { once: true })
          })
        }
      }
    }, peerMessage)
    await alice.reload()
    await alice.getByRole('button', { name: 'New chat' }).click()
    await alice.getByLabel('Contact emails').fill(email('sam'))
    await alice.getByRole('button', { name: 'Start chat' }).click()
    await expect(alice.getByRole('heading', { name: email('sam') })).toBeVisible()
    await bob.getByRole('navigation').getByRole('button', { name: new RegExp(email('alex')) }).click()
    await expect(bob.getByRole('status')).toHaveText('Live')
    await alice.getByRole('textbox', { name: 'Message', exact: true }).fill('Can we review the demo this afternoon?')
    await alice.getByRole('button', { name: 'Send' }).click()
    await expect(bob.getByText('Can we review the demo this afternoon?')).toBeVisible()
    await expect(alice.getByRole('status')).toHaveText('Live')
    await bob.getByRole('textbox', { name: 'Message', exact: true }).fill(peerMessage)
    await bob.getByRole('button', { name: 'Send' }).click()
    await expect(alice.locator('html')).toHaveAttribute('data-delayed', 'true')
    await alice.getByRole('textbox', { name: 'Message', exact: true }).fill(ownMessage)
    await alice.getByRole('button', { name: 'Send' }).click()
    await expect(alice.getByText(ownMessage)).toBeVisible()
    await alice.evaluate(() => window.dispatchEvent(new Event('deliver-delayed-chat')))
    await expect(alice.locator('.thread article p')).toHaveText([
      'Can we review the demo this afternoon?', peerMessage, ownMessage,
    ])
    await alice.getByRole('button', { name: 'Find messages' }).click()
    await alice.getByRole('searchbox', { name: 'Search messages' }).fill('AGENDA')
    await alice.getByRole('button', { name: 'Search', exact: true }).click()
    const result = alice.getByLabel('Message search results')
    await expect(result.getByText(peerMessage)).toBeVisible()
    await expect(result.getByText(ownMessage)).toHaveCount(0)
    await result.getByRole('button', { name: 'Close' }).click()
    await bob.reload()
    await bob.getByRole('navigation').getByRole('button', { name: new RegExp(email('alex')) }).click()
    await expect(bob.getByText('Can we review the demo this afternoon?')).toBeVisible()
    if (isMobile) await alice.getByRole('button', { name: 'Chats', exact: true }).click()
    await alice.getByRole('button', { name: 'New chat' }).click()
    await alice.getByLabel('Contact emails').fill([email('sam'), email('avery')].join(', '))
    await alice.getByLabel('Group name').fill('Design review')
    await alice.getByRole('button', { name: 'Start chat' }).click()
    await expect(alice.getByRole('heading', { name: 'Design review' })).toBeVisible()
    await carol.getByRole('searchbox', { name: 'Search chats' }).fill('design')
    await carol.getByRole('navigation').getByRole('button', { name: 'Design review Group' }).click()
    await expect(carol.getByRole('status')).toHaveText('Live')
    await alice.getByRole('textbox', { name: 'Message', exact: true }).fill('I added the updated prototype to the agenda.')
    await alice.getByRole('button', { name: 'Send' }).click()
    await expect(carol.getByText('I added the updated prototype to the agenda.')).toBeVisible()
    await carol.getByRole('textbox', { name: 'Message', exact: true }).fill('Thanks, I will walk through the mobile views.')
    await carol.getByRole('button', { name: 'Send' }).click()
    await expect(alice.getByText('Thanks, I will walk through the mobile views.')).toBeVisible()
    expect(await alice.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(viewport!.width)
    await alice.screenshot({ path: info.outputPath('messenger.png') })
  } finally {
    await Promise.all([alice.close(), bob.close(), carol.close()])
  }
})
