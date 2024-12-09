import asyncio
import json
import os
import random
from time import sleep
import requests
from playwright.async_api import Page, async_playwright
from tqdm import tqdm
import argparse

from constants import STATE_DIR, TRACKING_DIR, DOMAIN, DOWNLOAD_TIMEOUT

DOWNLOAD_RESULT_SUCCESS = 1
DOWNLOAD_RESULT_DAILY_LIMIT_REACHED = 2
DOWNLOAD_RESULT_FAILED = 3


class ZLibraryBooklistDownloader():
    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        self.state_files = [os.path.join(STATE_DIR, f) for f in os.listdir(STATE_DIR) if f.endswith('.json')]
        self.cur_state_idx = -1
        self.cur_state_download_today = 0
        self.cur_state_daily_limit = 0

    def fetch_bookinfos(self, url: str):
        base_url = f'{DOMAIN}/papi/booklist/{url.split("/")[-3]}/get-books/'
        page = 1
        all_books = []
        while True:
            url = f'{base_url}{page}?order=date_savedA'
            print(url)
            headers = {
                'accept': '*/*',
                'accept-language': 'en',
                'priority': 'u=1, i',
                'referer': url,
                'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
                'sec-ch-ua-mobile': '?0',
                'sec-ch-ua-platform': '"Windows"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-origin',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            }

            response = requests.get(url, headers=headers)
            data = response.json()  # Assuming the response is in JSON format

            if data.get("success") == 1:
                all_books.extend(data.get("books", []))
                if data.get("pagination", {}).get("next"):
                    page += 1
                    sleep(random.randint(1, 3))
                else:
                    break
            else:
                break
        return all_books
        
    async def download_booklist(self, url: str):
        # parse booklist name from url
        booklist_name = url.split('/')[-1].split('.')[0]
        booklist_dir = os.path.join(self.output_dir, booklist_name)
        ensure_dir(booklist_dir)

        tracking_dir = os.path.join(TRACKING_DIR, booklist_name)
        ensure_dir(tracking_dir)
        # check if books.json exists
        books_file = os.path.join(tracking_dir, 'books.json')
        if os.path.exists(books_file):
            with open(books_file, 'r', encoding='utf-8') as f:
                books = json.load(f)
        else:
            books = self.fetch_bookinfos(url)
            with open(books_file, 'w', encoding='utf-8') as f:
                json.dump(books, f, ensure_ascii=False)

        print(f'books count: {len(books)}')
        # filter out downloaded books by check downloaded.txt
        downloaded_books = []
        downloaded_file = os.path.join(tracking_dir, 'downloaded.txt')
        if os.path.exists(downloaded_file):
            with open(downloaded_file, 'r', encoding='utf-8') as f:
                downloaded_books = f.read().splitlines()
                downloaded_books = [int(book_id) for book_id in downloaded_books]
                print(f'downloaded books count: {len(downloaded_books)}')

        # filter out downloaded books by check invalid.txt
        invalid_books = []
        invalid_file = os.path.join(tracking_dir, 'invalid.txt')
        if os.path.exists(invalid_file):
            with open(invalid_file, 'r', encoding='utf-8') as f:
                invalid_books = f.read().splitlines()
                invalid_books = [int(book_id) for book_id in invalid_books]
                print(f'invalid books count: {len(invalid_books)}')

        to_download_books = [book for book in books if book['book']['id'] not in downloaded_books and book['book']['id'] not in invalid_books]
        print(f'books to download count: {len(to_download_books)}')

        # download books
        # use playwright to download book
        for book in tqdm(to_download_books, desc='Downloading books', unit='book'):
            await self.find_valid_state_file()
            if not self.is_current_state_valid():
                print('daily limit reached!')
                break

            result = await self.download_book(booklist_dir, book)
            if result == DOWNLOAD_RESULT_SUCCESS:
                # add book id to downloaded.txt
                with open(downloaded_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n{book['book']['id']}")
                self.cur_state_download_today += 1
            else:
                print(f'download {book["book"]["title"]} failed')
                # add book id to invalid.txt
                with open(invalid_file, 'a', encoding='utf-8') as f:
                    f.write(f"\n{book['book']['id']}")
    
    async def find_valid_state_file(self):
        while self.cur_state_idx < len(self.state_files):
            if self.is_current_state_valid():
                break
            await self.next_state_file()
    
    async def next_state_file(self):
        self.cur_state_idx += 1
        if self.cur_state_idx >= len(self.state_files):
            print('no valid state file found!')
            return

        print(f'switch to state file: {self.state_files[self.cur_state_idx]}')
        await self.refresh_daily_limit()

    async def refresh_daily_limit(self):
        state_file = self.state_files[self.cur_state_idx]
        profile_url = f'{DOMAIN}'
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=state_file, accept_downloads=True, viewport={'width': 960, 'height': 1080})
            page: Page = await context.new_page()
            await page.goto(profile_url, wait_until='load', timeout=0)
            daily_limit_text = await page.locator('div.user-card div.caret-scroll__title').first.text_content()
            download_today, daily_limit = daily_limit_text.strip().split('/')
            await context.close()
            await browser.close()
            self.cur_state_download_today = int(download_today)
            self.cur_state_daily_limit = int(daily_limit)

    def is_current_state_valid(self):
        if self.cur_state_idx == -1 or self.cur_state_idx >= len(self.state_files):
            return False
        if self.cur_state_download_today >= self.cur_state_daily_limit:
            return False
        return True

    async def download_book(self, booklist_dir: str, book: dict):
        book_url = f'{DOMAIN}{book["book"]["href"]}'
        print(book_url)

        book_path = os.path.join(booklist_dir, f"{book['book']['id']}.{book['book']['extension']}") 
        real_book_path = os.path.join(booklist_dir, sanitize_file_name(f"{book['book']['title']}.{book['book']['extension']}"))
        sanitized_book_path = real_book_path

        state_file = self.state_files[self.cur_state_idx]
        browser = None
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(storage_state=state_file, accept_downloads=True, viewport={'width': 960, 'height': 1080})
            page: Page = await context.new_page()
            await page.goto(book_url, wait_until='load', timeout=0)
            try:
                download_link = await page.locator('a.btn.btn-default.addDownloadedBook').get_attribute('href')
                real_book_url = f'{DOMAIN}{download_link}'
                print(real_book_url)
            except:
                print('no download link found')
                await browser.close()
                return DOWNLOAD_RESULT_FAILED

            async with page.expect_download(timeout=DOWNLOAD_TIMEOUT) as download_info:
                # Hack
                try:
                    await page.goto(real_book_url, wait_until='commit', timeout=0)
                except:
                    download = await download_info.value
                    print(await download.path())
                    await download.save_as(book_path)
                    
                    os.rename(book_path, sanitized_book_path)

            await browser.close()
            return DOWNLOAD_RESULT_SUCCESS
            
def ensure_dir(dir_path: str):
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

def sanitize_file_name(file_name: str) -> str:
    # Replace invalid characters for file names
    invalid_chars = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
    for char in invalid_chars:
        file_name = file_name.replace(char, '')
    return file_name

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Download books from z-lib')
    parser.add_argument('--output_dir', type=str, default='downloads', help='output directory')
    parser.add_argument('--booklist_url', type=str, help='booklist url')
    args = parser.parse_args()
    output_dir = args.output_dir
    booklist_url = args.booklist_url

    ensure_dir(output_dir)
    ensure_dir(STATE_DIR)
    ensure_dir(TRACKING_DIR)
    downloader = ZLibraryBooklistDownloader(output_dir)
    asyncio.run(downloader.download_booklist(booklist_url))