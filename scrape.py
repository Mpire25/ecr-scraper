#!/usr/bin/env python3
"""
ECR Scraper - Exclusive Car Registry image scraper

Usage:
  # Credentials from .env (recommended)
  python scrape.py --make lamborghini --model aventador

  # Override any .env value via CLI
  python scrape.py --make lamborghini --model aventador --session YOUR_PHPSESSID

.env keys:
  ECR_SESSION      PHPSESSID from browser DevTools
  ECR_USERNAME     ECR account email (for automated login)
  ECR_PASSWORD     ECR account password
  ECR_CAPTCHA_KEY  2captcha API key
  ECR_OUT          Output directory (default: ./data)
"""

import os
import math
import time
import random
import hashlib
import argparse
import concurrent.futures
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BASE_URL = "https://exclusivecarregistry.com"
CAPTCHA_API = "https://2captcha.com"
DEFAULT_DELAY = 0

# MD5 hashes of ECR placeholder images — skip these when scraping
PLACEHOLDER_HASHES = {
    "61b45e1a17a8686ef178943a642c2565",  # premium only
    "11c0618a16b0454bccfaacac5cb4d6ff",  # specialist only
    "2c95ad680cf03f312683ab9b8fb7481e",  # image not available
    "cb0eb6138919fa73bdee0a069f902666",  # log in (gated content, not session expiry)
}


class ECRClient:
    def __init__(self, delay=DEFAULT_DELAY):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/146.0.0.0 Safari/537.36"
            ),
        })
        self.delay = delay

    def _set_cookies(self, phpsessid):
        self.session.cookies.pop("PHPSESSID", None)
        self.session.cookies.set("PHPSESSID", phpsessid)
        self.session.cookies.set("cookies_performance", "1")
        self.session.cookies.set("cookies_ads", "1")
        self.session.cookies.set("cookies_functionality", "1")

    def auth_session(self, phpsessid):
        """Authenticate with a manually provided PHPSESSID."""
        self._set_cookies(phpsessid)
        print(f"[auth] Using manual session: {phpsessid[:8]}...")

    def auth_login(self, username, password, captcha_key):
        """Authenticate by logging in, solving reCAPTCHA via 2captcha."""
        print("[auth] Fetching login form...")
        r = self.session.post(
            f"{BASE_URL}/info",
            data={"open_login_form": "1"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        soup = BeautifulSoup(r.text, "html.parser")

        # Extract reCAPTCHA site key from the formlogin hidden input
        site_key_input = soup.find("input", {"name": "formlogin"})
        if not site_key_input:
            raise ValueError("Could not find reCAPTCHA site key in login form")
        site_key = site_key_input["value"]

        print(f"[auth] reCAPTCHA site key: {site_key}")

        # Solve reCAPTCHA — response goes in the `token` field
        recaptcha_token = self._solve_recaptcha(captcha_key, site_key, f"{BASE_URL}/info")

        # Submit login
        print("[auth] Submitting login...")
        r = self.session.post(
            f"{BASE_URL}/info",
            data={
                "formlogin": site_key,
                "fusername": username,
                "fpass": password,
                "token": recaptcha_token,
                "action": "login",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        if "PHPSESSID" not in self.session.cookies:
            raise ValueError("Login failed — no session cookie received. Check credentials.")

        self._set_cookies(self.session.cookies["PHPSESSID"])
        print("[auth] Login successful")

    def _solve_recaptcha(self, api_key, site_key, page_url, max_retries=3):
        """Submit reCAPTCHA to 2captcha and poll for solution. Retries on ERROR_CAPTCHA_UNSOLVABLE."""
        for attempt in range(1, max_retries + 1):
            print(f"[captcha] Submitting to 2captcha (attempt {attempt}/{max_retries})...")
            r = requests.post(f"{CAPTCHA_API}/in.php", data={
                "key": api_key,
                "method": "userrecaptcha",
                "googlekey": site_key,
                "pageurl": page_url,
                "json": 1,
            })
            data = r.json()
            if data.get("status") != 1:
                raise ValueError(f"2captcha submission failed: {data}")

            task_id = data["request"]
            print(f"[captcha] Task submitted (id={task_id}), waiting for solution...")

            for _ in range(30):
                time.sleep(5)
                r = requests.get(f"{CAPTCHA_API}/res.php", params={
                    "key": api_key,
                    "action": "get",
                    "id": task_id,
                    "json": 1,
                })
                data = r.json()
                if data.get("status") == 1:
                    print("[captcha] Solved!")
                    return data["request"]
                if data.get("request") == "ERROR_CAPTCHA_UNSOLVABLE":
                    print(f"[captcha] Unsolvable, retrying in 10s...")
                    time.sleep(10)
                    break
                if data.get("request") != "CAPCHA_NOT_READY":
                    raise ValueError(f"2captcha error: {data}")
            else:
                raise TimeoutError("2captcha did not solve within 150 seconds")

        raise ValueError(f"2captcha failed after {max_retries} attempts (ERROR_CAPTCHA_UNSOLVABLE)")

    def _get(self, url, retries=4, **kwargs):
        for attempt in range(retries):
            try:
                time.sleep(self.delay)
                return self.session.get(url, **kwargs)
            except requests.exceptions.ConnectionError:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

    def _post(self, url, retries=4, **kwargs):
        for attempt in range(retries):
            try:
                time.sleep(self.delay)
                return self.session.post(url, **kwargs)
            except requests.exceptions.ConnectionError:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)

    def _extract_list_slug(self, soup, fallback):
        """Extract the make slug as used in /list?model= from the meta keywords on the make page.

        The first keyword is always the make name in its natural form (spaces/hyphens preserved),
        which matches what the /list endpoint expects.
        """
        meta = soup.find("meta", {"name": "keywords"})
        if meta:
            return meta["content"].split(",")[0].strip()
        return fallback

    def get_list_slug(self, make):
        """Return the make slug as expected by /list?model= (may differ from the URL path slug)."""
        r = self._get(f"{BASE_URL}/make/{make}")
        soup = BeautifulSoup(r.text, "html.parser")
        return self._extract_list_slug(soup, make)

    def get_models_for_make(self, make):
        """Return (list_slug, model_names) for a make.

        list_slug is the make string as expected by /list?model= — it can differ from the
        URL path slug (e.g. 'aston martin' vs 'aston-martin').
        """
        r = self._get(f"{BASE_URL}/make/{make}")
        soup = BeautifulSoup(r.text, "html.parser")
        models = [next(el.stripped_strings).lower() for el in soup.select(".car_item_line.model[data-info]")]
        return self._extract_list_slug(soup, make), models

    def get_cars_for_model(self, make, model, show_progress=False):
        """Return list of (make, model_slug, car_id) for all cars of a make+model."""
        cars = []
        page = 1
        with tqdm(desc=f"  [list] {make}/{model}", unit="pg", leave=False, disable=not show_progress) as pbar:
            while True:
                if not show_progress:
                    print(f"  [list] {make}/{model} page {page}...", end="\r", flush=True)
                r = self._get(f"{BASE_URL}/list", params={"model": f"{make},{model}", "page": page})
                soup = BeautifulSoup(r.text, "html.parser")
                links = soup.select("a.content[href*='/details/']")
                if not links:
                    break
                for link in links:
                    parts = link["href"].strip("/").split("/")
                    if len(parts) == 4:
                        cars.append((parts[1], parts[2], parts[3]))
                page += 1
                if show_progress:
                    pbar.update(1)
        if not show_progress:
            print(f"  [list] {make}/{model} — {page - 1} pages, {len(cars)} cars found")
        return cars

    def get_image_ids(self, make, model_slug, car_id):
        """Return all gallery image IDs for a specific car."""
        url = f"{BASE_URL}/details/{make}/{model_slug}/{car_id}"
        r = self._get(url)
        soup = BeautifulSoup(r.text, "html.parser")

        thumbs = soup.select(".banner_gallery .thumb[data-id]")
        if not thumbs:
            return []

        first_id = thumbs[0]["data-id"]

        # POST to get full gallery (more images than shown in preview)
        r2 = self._post(url, data={
            "open_gallery_overlay": first_id,
            "open_gall_id": "gallid_1",
        }, headers={"X-Requested-With": "XMLHttpRequest"})

        soup2 = BeautifulSoup(r2.text, "html.parser")
        imgs = soup2.select(".nav_thumbs img[data-id]")
        return [img["data-id"] for img in imgs if img["data-id"] != "0"]

    def download_image(self, image_id, dest_path):
        """Download a full-size image. Returns True if saved, False if placeholder or failed."""
        url = f"{BASE_URL}/images/gallery/car/full/{image_id}"
        r = self.session.get(url, stream=True)
        if r.status_code != 200:
            return False

        data = b"".join(r.iter_content(8192))
        h = hashlib.md5(data).hexdigest()

        if h in PLACEHOLDER_HASHES:
            return False

        with open(dest_path, "wb") as f:
            f.write(data)
        return True


def sanitize_name(name):
    """Strip characters that are invalid or problematic in folder names and URLs."""
    return (name
            .replace("/", "-")
            .replace("\\", "-")
            .replace("'", "")   # ASCII apostrophe
            .replace("\u2018", "")  # left curly quote '
            .replace("\u2019", "")  # right curly quote '
            .strip())


def scrape_model(client, make, list_slug, model, out_dir, max_images, max_per_car, target_images=None, fill=False, workers=1, random_from_first_n=None, skip_existing_cars=False):
    safe_model = sanitize_name(model)
    class_dir = Path(out_dir) / f"{make}_{safe_model}"
    class_dir.mkdir(parents=True, exist_ok=True)

    new_images = 0
    skipped = 0
    placeholders = 0

    existing = len(list(class_dir.glob("*.jpg")))
    print(f"\n[scrape] {make}/{model} -> {class_dir} ({existing} existing)")

    if target_images:
        if fill and existing >= target_images:
            print(f"  [skip] Already has {existing} images (target {target_images}) — skipping")
            return 0
        effective_target = target_images - existing if fill else target_images

        # Pre-count cars so we can distribute images evenly across examples
        print(f"  [count] Listing cars for {make}/{model}...")
        all_cars = client.get_cars_for_model(list_slug, model)
        car_count = len(all_cars)
        if car_count == 0:
            print(f"  [count] No cars found")
            class_dir.rmdir()
            return 0
        computed_per_car = math.ceil(effective_target / car_count)
        effective_per_car = min(computed_per_car, max_per_car) if max_per_car else computed_per_car
        print(f"  [count] {car_count} cars — targeting {effective_per_car} img/car to reach ~{effective_target} new images")
        cars_list = all_cars
        total_cap = effective_target
    else:
        effective_per_car = max_per_car
        print(f"  [count] Listing cars for {make}/{model}...")
        cars_list = client.get_cars_for_model(list_slug, model)
        if not cars_list:
            print(f"  [count] No cars found")
            class_dir.rmdir()
            return 0
        total_cap = max_images

    def _process_car(car_make, car_model_slug, car_id, per_car):
        """Fetch image IDs and download images for one car. Returns (new, skipped, placeholders)."""
        if skip_existing_cars and any(class_dir.glob(f"{car_id}_*.jpg")):
            return 0, 1, 0
        image_ids = client.get_image_ids(car_make, car_model_slug, car_id)
        if not image_ids:
            return 0, 0, 0
        if random_from_first_n is not None:
            selected = [image_ids[0]]
            pool = image_ids[1:random_from_first_n]
            if pool:
                selected.append(random.choice(pool))
            image_ids = selected
        elif per_car:
            image_ids = image_ids[:per_car]
        n = s = p = 0
        for img_id in image_ids:
            dest = class_dir / f"{car_id}_{img_id}.jpg"
            if dest.exists():
                s += 1
                continue
            ok = client.download_image(img_id, dest)
            if ok:
                n += 1
            else:
                p += 1
        return n, s, p

    def _per_car_limit(i):
        """Compute per-car image limit, rebalancing for remaining cars if using --target-images."""
        if target_images:
            remaining_images = total_cap - new_images
            remaining_cars = len(cars_list) - i
            per_car = math.ceil(remaining_images / remaining_cars)
            return min(per_car, max_per_car) if max_per_car else per_car
        return effective_per_car

    car_iter = iter(enumerate(cars_list))
    pending = {}  # future -> car index

    def _submit_next():
        if total_cap and new_images >= total_cap:
            return
        try:
            i, (car_make, car_model_slug, car_id) = next(car_iter)
        except StopIteration:
            return
        f = executor.submit(_process_car, car_make, car_model_slug, car_id, _per_car_limit(i))
        pending[f] = i

    bar_format = "{l_bar}{bar}| {n_fmt}/{total_fmt} cars [{elapsed}<{remaining}, {rate_fmt}]{postfix}"
    with tqdm(total=len(cars_list), unit="car", bar_format=bar_format, dynamic_ncols=True) as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for _ in range(workers):
                _submit_next()

            while pending:
                done, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    del pending[future]
                    n, s, p = future.result()
                    new_images += n
                    skipped += s
                    placeholders += p
                    pbar.update(1)
                    pbar.set_postfix(new=new_images, skip=skipped, ph=placeholders)
                    _submit_next()

    if new_images == 0 and skipped == 0:
        class_dir.rmdir()
        print(f"[scrape] No images — removed empty folder {class_dir}")
    else:
        print(f"[scrape] Done: {new_images} new, {skipped} already existed, {placeholders} placeholders skipped")
    return new_images


def main():
    parser = argparse.ArgumentParser(description="ECR image scraper")

    # Target
    parser.add_argument("--make", required=True, help="Make slug (e.g. lamborghini)")
    parser.add_argument("--model", nargs="+", help="Model slug(s) (e.g. aventador huracan). Omit to scrape all models.")
    parser.add_argument("--out", default=os.getenv("ECR_OUT", "./data"), help="Output directory for images")
    parser.add_argument("--max-images", type=int, default=None, help="Max total images to download per model (omit for no limit)")
    parser.add_argument("--max-per-car", type=int, default=None, help="Max images per individual car (omit for no limit)")
    parser.add_argument("--target-images", type=int, default=None, help="Target total images per model, distributed evenly across cars (pre-counts cars, then sets per-car limit dynamically)")
    parser.add_argument("--fill", action="store_true", help="With --target-images, count existing images and only download enough to reach the target. Skips folders that already meet the target.")
    parser.add_argument("--workers", type=int, default=1, help="Number of cars to download in parallel (default: 1)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"Delay between requests in seconds (default: {DEFAULT_DELAY})")
    parser.add_argument("--random-from-first-n", type=int, default=None, metavar="N", help="Per car: always take image 0, then pick 1 random image from indices 1..N-1 (or all available if fewer). Overrides --max-per-car.")
    parser.add_argument("--skip-existing-cars", action="store_true", help="Skip any car that already has at least one downloaded image, rather than filling in missing images.")

    # Auth (all optional — fall back to .env)
    parser.add_argument("--session", default=os.getenv("ECR_SESSION"), help="Manual PHPSESSID (or set ECR_SESSION in .env)")
    parser.add_argument("--username", default=os.getenv("ECR_USERNAME"), help="ECR account email (or set ECR_USERNAME in .env)")
    parser.add_argument("--password", default=os.getenv("ECR_PASSWORD"), help="ECR account password (or set ECR_PASSWORD in .env)")
    parser.add_argument("--captcha-key", default=os.getenv("ECR_CAPTCHA_KEY"), help="2captcha API key (or set ECR_CAPTCHA_KEY in .env)")

    args = parser.parse_args()

    client = ECRClient(delay=args.delay)

    # Authenticate
    if args.session:
        client.auth_session(args.session)
    elif args.username:
        if not args.password or not args.captcha_key:
            parser.error("ECR_PASSWORD and ECR_CAPTCHA_KEY must be set (in .env or via CLI) when using username login")
        client.auth_login(args.username, args.password, args.captcha_key)
    else:
        parser.error("No auth provided — set ECR_SESSION or ECR_USERNAME/ECR_PASSWORD/ECR_CAPTCHA_KEY in .env")

    # Determine models to scrape and resolve the /list query slug for this make
    if args.model:
        models = args.model
        print(f"[make] Resolving list slug for {args.make}...")
        list_slug = client.get_list_slug(args.make)
    else:
        print(f"[make] Fetching model list for {args.make}...")
        list_slug, models = client.get_models_for_make(args.make)
        print(f"[make] Found {len(models)} models: {models}")
    print(f"[make] List query slug: '{list_slug}'")

    # Scrape
    total = 0
    for model in models:
        total += scrape_model(client, args.make, list_slug, model, args.out, args.max_images, args.max_per_car, args.target_images, args.fill, args.workers, args.random_from_first_n, args.skip_existing_cars)

    print(f"\n[done] Total new images downloaded: {total}")


if __name__ == "__main__":
    main()
