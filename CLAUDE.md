# ECR Scraper

## What this is
A standalone CLI scraper for Exclusive Car Registry (exclusivecarregistry.com). Built to collect car images for training the Carvis image classification model (separate repo: `carvis`).

## Purpose
Download car images from ECR organised into class folders (e.g. `lamborghini_aventador/`, `ferrari_f40/`) ready for use as a PyTorch ImageFolder dataset.

## Site structure
- `/list?model=lamborghini,aventador&page=N` — paginated list of cars (24 per page)
- `/details/[make]/[model-slug]/[car-id]` — individual car page with gallery
- Gallery overlay: POST to car detail URL with `open_gallery_overlay=[first_image_id]&open_gall_id=gallid_1` returns all image IDs
- Full image URL: `https://exclusivecarregistry.com/images/gallery/car/full/[image_id]`
- Make model list: `/make/[make]` — model names are in the text content of `.car_item_line.model` elements (lowercased); `data-info` is a URL slug and does NOT match what `/list` expects
- Auth: PHPSESSID session cookie required. Login endpoint is POST to `/info` with `action=login`

## Auth
Two modes supported in `scrape.py`:
1. **Manual** — provide `PHPSESSID` from browser DevTools (`--session`), or set `ECR_SESSION` env var
2. **Automated login** — provide ECR credentials + 2captcha API key (`--username`, `--password`, `--captcha-key`), or set `ECR_USERNAME`, `ECR_PASSWORD`, `ECR_CAPTCHA_KEY` env vars

## Placeholder images
ECR serves gated content (specialist/premium only) as placeholder images rather than 403s. On startup, `load_placeholder_hashes()` downloads known placeholder URLs and caches their MD5 hashes. Any downloaded image matching a known placeholder hash is discarded.

Known placeholder image IDs: `1034761` (specialist only). If you notice new placeholder images being saved, add their ECR image IDs to `KNOWN_PLACEHOLDERS` in `scrape.py`.

## Usage examples
```bash
pip install -r requirements.txt

# Test run
python scrape.py --make lamborghini --model aventador --out ./data --session PHPSESSID --max-images 3

# Full scrape of one model
python scrape.py --make lamborghini --model aventador --out /mnt/carvis-data/data --session PHPSESSID

# Multiple models
python scrape.py --make lamborghini --model aventador huracan gallardo --out /mnt/carvis-data/data --session PHPSESSID

# Even distribution across cars (e.g. 200 images spread across all cars)
python scrape.py --make lamborghini --model aventador --target-images 200 --out /mnt/carvis-data/data --session PHPSESSID

# Top up existing folders to a target without re-downloading
python scrape.py --make lamborghini --model aventador --target-images 200 --fill --out /mnt/carvis-data/data --session PHPSESSID

# Parallel downloads
python scrape.py --make lamborghini --model aventador --workers 4 --out /mnt/carvis-data/data --session PHPSESSID

# Diverse sampling: first image + 1 random from first N per car
python scrape.py --make lamborghini --model aventador --random-from-first-n 5 --out /mnt/carvis-data/data --session PHPSESSID

# Skip cars already partially downloaded
python scrape.py --make lamborghini --model aventador --skip-existing-cars --out /mnt/carvis-data/data --session PHPSESSID

# Automated login
python scrape.py --make lamborghini --model aventador --out /mnt/carvis-data/data \
  --username you@email.com --password yourpass --captcha-key YOUR_2CAPTCHA_KEY
```

## Development environment
- Written and edited on Mac
- Tested and run on Ubuntu PC (RTX 2070 Super) via SSH
- Python 3.10, run inside the `ml` conda environment
