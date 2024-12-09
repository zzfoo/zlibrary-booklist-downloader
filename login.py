import asyncio
import os
from playwright.async_api import async_playwright
import json

from constants import DOMAIN, STATE_DIR

async def save_state():
    terminated = False
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)

        context = await browser.new_context()

        page = await context.new_page()
        await page.goto(DOMAIN)

        print(f"Browser opened. Close the browser window to save the storage state.")

        async def save_storage_state():
            nonlocal terminated
            state = await context.storage_state()
            print('Saving storage state', state)

            cookies = state['cookies']
            userid = next((cookie['value'] for cookie in cookies if cookie['name'] == 'remix_userid'), None)
            if userid is not None:
                state_file_path = os.path.join(STATE_DIR, f'{userid}.json')
                with open(state_file_path, 'w') as f:
                    json.dump(state, f, indent=4)
            await context.close()
            terminated = True

        page.on('close', save_storage_state)

        try:
            while not terminated:
                await asyncio.sleep(1)
            await browser.close()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    asyncio.run(save_state())
