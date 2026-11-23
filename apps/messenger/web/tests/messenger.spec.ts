import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

test('contacts can exchange messages live and open a group', async ({ browser }, info) => {
  const options = { baseURL: info.project.use.baseURL }
  const alice = await browser.newPage(options)
  const bob = await browser.newPage(options)
  const carol = await browser.newPage(options)
  const tag = randomUUID().slice(0, 6)
  const email = (name: string) => name + '.' + tag + '@example.test'
  async function register(page: Page, name: string) {
    await page.goto('/')
    await page.getByRole('button', { name: 'Create an account' }).click()
    await page.getByLabel('Email').fill(email(name))
    await page.getByLabel('Password').fill('synthetic-only-password')
    await page.getByRole('button', { name: 'Register', exact: true }).click()
    await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible()
  }
  try {
    await Promise.all([register(alice, 'alex'), register(bob, 'sam'), register(carol, 'avery')])
    await alice.getByRole('button', { name: 'New chat' }).click()
    await alice.getByLabel('Contact emails').fill(email('sam'))
    await alice.getByRole('button', { name: 'Start chat' }).click()
    await expect(alice.getByRole('heading', { name: email('sam') })).toBeVisible()
    await bob.getByRole('navigation').getByRole('button', { name: new RegExp(email('alex')) }).click()
    await expect(bob.getByRole('status')).toHaveText('Live')
    await alice.getByRole('textbox', { name: 'Message', exact: true }).fill('Can we review the demo this afternoon?')
    await alice.getByRole('button', { name: 'Send' }).click()
    await expect(bob.getByText('Can we review the demo this afternoon?')).toBeVisible()
    await bob.reload()
    await bob.getByRole('navigation').getByRole('button', { name: new RegExp(email('alex')) }).click()
    await expect(bob.getByText('Can we review the demo this afternoon?')).toBeVisible()
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
    await alice.screenshot({ path: info.outputPath('messenger.png') })
  } finally {
    await Promise.all([alice.close(), bob.close(), carol.close()])
  }
})
