# ECR Scraper

Scrapes car images from [Exclusive Car Registry](https://exclusivecarregistry.com) into class folders ready for use as a PyTorch `ImageFolder` dataset.

Built to collect training data for the [Carvis](https://github.com/mpire25/carvis) image classification model.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in your credentials (see Auth below)
```

## Auth

ECR requires a login. Two options:

**Option 1 — Manual session (easiest)**
1. Log in to ECR in your browser
2. Open DevTools → Application → Cookies → copy `PHPSESSID`
3. Pass it via `--session <value>` or set `ECR_SESSION=<value>` in `.env`

**Option 2 — Automated login via 2captcha** *(currently broken)*
Set `ECR_USERNAME`, `ECR_PASSWORD`, and `ECR_CAPTCHA_KEY` in `.env`. ECR's invisible reCAPTCHA tokens are rejected server-side by Google when solved via 2captcha — use Option 1 instead.

## Usage

```bash
# Test run — 3 total images
python scrape.py --make lamborghini --model aventador --max-images 3

# Full scrape, max 15 images per car
python scrape.py --make lamborghini --model aventador --max-per-car 15

# Multiple models
python scrape.py --make lamborghini --model aventador huracan gallardo --max-per-car 15

# Target 600 images per model, distributed evenly across cars
python scrape.py --make lamborghini --target-images 600 --max-per-car 20

# Top up existing folders to 600 (skips models that already have enough)
python scrape.py --make lamborghini --target-images 600 --max-per-car 20 --fill

# Download 5 cars in parallel
python scrape.py --make lamborghini --model aventador --workers 5

# Override output dir
python scrape.py --make lamborghini --model aventador --out /mnt/carvis-data/data
```

Output is organised as `<out>/<make>_<model>/<car_id>_<image_id>.jpg`.

## Target classes

| Make | Model | Cars on ECR |
|------|-------|-------------|
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

## Notes

- ECR serves placeholder images for gated content instead of 403s. The scraper detects and discards these by MD5 hash.
- Some images are gated behind higher account tiers and served as placeholders — these are detected and discarded the same way.
- Default delay between requests is 0s (network latency alone is sufficient). Use `--delay` if you get rate limited.
- Use `--workers` to download from multiple individual car listings in parallel. Keeps N listings in-flight simultaneously — useful when scraping models with few images per listing.
