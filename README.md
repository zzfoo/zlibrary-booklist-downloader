# zlibrary-booklist-downloader

Download books from [zlibrary](https://z-lib.fm/) by booklist.

## Installation

```bash
pip install -r requirements.txt
playwright install
```

## How to use
1. Run `python login.py` to save your login state. It will open zlibrary in browser for you to login. After you login and close the browser, it will save the login state to `states/` directory. You can repeat this process for every account. (The downloader will automatically switch account after current account reach daily limit.)
2. Run `python download_booklist.py --booklist_url <booklist_url> --output_dir <output_dir>` to download books.

## Example

```bash
python download_booklist.py --booklist_url https://z-lib.fm/booklist/337935/0d3d12/vocabulary-for-children.html --output_dir downloads
```

