# ECR Scraper

## What this is
A standalone CLI scraper for Exclusive Car Registry (exclusivecarregistry.com). Built to collect car images for training the Carvis image classification model (separate repo: `carvis`).

## Purpose
Download car images from ECR organised into class folders (e.g. `lamborghini_aventador/`, `ferrari_f40/`) ready for use as a PyTorch ImageFolder dataset.

## Site structure (already researched)
- `/list?model=lamborghini,aventador&page=N` — paginated list of cars (24 per page)
- `/details/[make]/[model-slug]/[car-id]` — individual car page with gallery
- Gallery overlay: POST to car detail URL with `open_gallery_overlay=[first_image_id]&open_gall_id=gallid_1` returns all image IDs
- Full image URL: `https://exclusivecarregistry.com/images/gallery/car/full/[image_id]`
- Make model list: `/make/[make]` — model slugs are in `data-info` attributes on `.car_item_line.model` elements
- Auth: PHPSESSID session cookie required. Login endpoint is POST to `/info` with `action=login`

## Auth
Two modes supported in `scrape.py`:
1. **Manual** — provide `PHPSESSID` from browser DevTools (`--session`)
2. **Automated login** — provide ECR credentials + 2captcha API key (`--username`, `--password`, `--captcha-key`). Login uses reCAPTCHA which is solved via 2captcha.

## Placeholder images
ECR serves gated content (specialist/premium only) as placeholder images rather than 403s. On startup, `load_placeholder_hashes()` downloads known placeholder URLs and caches their MD5 hashes. Any downloaded image matching a known placeholder hash is discarded.

Known placeholder image IDs: `1034761` (specialist only)
There may be others — if you notice images being saved that are clearly placeholders (text overlay saying "specialist only" or "premium only"), add their ECR image IDs to `KNOWN_PLACEHOLDERS` in `scrape.py`.

## Current state
- `scrape.py` is written and committed but **not yet tested against the live site**
- The first task is to test it end-to-end on a small scrape (e.g. `--make lamborghini --model aventador --max-images 3`) and fix any issues
- Then run the full scrape for the target classes

## Target classes for carvis (from car count research)
These are the 10 models with the most registered cars on ECR, chosen for the carvis training dataset:

| Make | Model slug | Cars on ECR |
|------|-----------|-------------|
| lamborghini | aventador | 4,119 |
| lamborghini | murcielago | 2,974 |
| lamborghini | diablo | 1,964 |
| lamborghini | huracan | 1,929 |
| lamborghini | gallardo | 1,604 |
| lamborghini | countach | 1,504 |
| ferrari | 488 | 1,483 |
| ferrari | sf90 | 1,028 |
| ferrari | f40 | 974 |
| ferrari | 458 | 959 |

Output should go to `/mnt/carvis-data/data/` on the Ubuntu PC (that's where the carvis training pipeline reads from).

## Usage examples
```bash
pip install -r requirements.txt

# Test run - single model, few images
python scrape.py --make lamborghini --model aventador --out ./data --session PHPSESSID --max-images 3

# Full scrape of one model
python scrape.py --make lamborghini --model aventador --out /mnt/carvis-data/data --session PHPSESSID

# Multiple models
python scrape.py --make lamborghini --model aventador huracan gallardo --out /mnt/carvis-data/data --session PHPSESSID

# Automated login
python scrape.py --make lamborghini --model aventador --out /mnt/carvis-data/data \
  --username you@email.com --password yourpass --captcha-key YOUR_2CAPTCHA_KEY
```

## Known issues / things to verify during testing
- Confirm `get_image_ids()` gallery overlay POST returns all images correctly
- Confirm pagination stops correctly when no more cars
- Confirm placeholder detection is working (watch for placeholder count in output)
- Session may expire — if you get empty results or auth errors, grab a fresh PHPSESSID

## Development environment
- Written and edited on Mac
- Tested and run on Ubuntu PC (RTX 2070 Super) via SSH
- Python 3.10, run inside the `ml` conda environment
