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
import time
import hashlib
import argparse
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://exclusivecarregistry.com"
CAPTCHA_API = "https://2captcha.com"
DEFAULT_DELAY = 1.5

# MD5 hashes of ECR placeholder images — skip these when scraping
PLACEHOLDER_HASHES = {
    "61b45e1a17a8686ef178943a642c2565",  # premium only
    "11c0618a16b0454bccfaacac5cb4d6ff",  # specialist only
    "2c95ad680cf03f312683ab9b8fb7481e",  # image not available
}

# Session expired — triggers re-login
LOGIN_PLACEHOLDER_HASH = "cb0eb6138919fa73bdee0a069f902666"


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
        self._auth_args = None  # stored for re-login on session expiry

    def _set_cookies(self, phpsessid):
        self.session.cookies.pop("PHPSESSID", None)
        self.session.cookies.set("PHPSESSID", phpsessid)
        self.session.cookies.set("cookies_performance", "1")
        self.session.cookies.set("cookies_ads", "1")
        self.session.cookies.set("cookies_functionality", "1")

    def auth_session(self, phpsessid):
        """Authenticate with a manually provided PHPSESSID."""
        self._set_cookies(phpsessid)
        self._auth_args = ("session", phpsessid)
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
        self._auth_args = ("login", username, password, captcha_key)
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

    def _reauth(self):
        """Re-authenticate using stored credentials."""
        if self._auth_args is None:
            raise ValueError("Session expired and no credentials stored for re-login")
        if self._auth_args[0] == "session":
            print("[auth] Session expired — re-applying manual session cookie")
            self.auth_session(self._auth_args[1])
        else:
            print("[auth] Session expired — re-logging in...")
            self.auth_login(self._auth_args[1], self._auth_args[2], self._auth_args[3])

    def _get(self, url, **kwargs):
        time.sleep(self.delay)
        return self.session.get(url, **kwargs)

    def _post(self, url, **kwargs):
        time.sleep(self.delay)
        return self.session.post(url, **kwargs)

    def get_models_for_make(self, make):
        """Return list of model slugs for a make."""
        r = self._get(f"{BASE_URL}/make/{make}")
        soup = BeautifulSoup(r.text, "html.parser")
        models = [el["data-info"] for el in soup.select(".car_item_line.model[data-info]")]
        return models

    def get_cars_for_model(self, make, model):
        """Yield (make, model_slug, car_id) for all cars of a make+model."""
        page = 1
        while True:
            print(f"  [list] {make}/{model} page {page}...")
            r = self._get(f"{BASE_URL}/list", params={"model": f"{make},{model}", "page": page})
            soup = BeautifulSoup(r.text, "html.parser")
            links = soup.select("a.content[href*='/details/']")
            if not links:
                break
            for link in links:
                parts = link["href"].strip("/").split("/")
                if len(parts) == 4:
                    yield parts[1], parts[2], parts[3]
            page += 1

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
        return [img["data-id"] for img in imgs]

    def download_image(self, image_id, dest_path):
        """Download a full-size image. Returns True if saved, False if placeholder or failed."""
        url = f"{BASE_URL}/images/gallery/car/full/{image_id}"
        r = self.session.get(url, stream=True)
        if r.status_code != 200:
            return False

        data = b"".join(r.iter_content(8192))
        h = hashlib.md5(data).hexdigest()

        if h == LOGIN_PLACEHOLDER_HASH:
            print("[auth] Got login placeholder — session expired, re-authenticating...")
            self._reauth()
            return False

        if h in PLACEHOLDER_HASHES:
            return False

        with open(dest_path, "wb") as f:
            f.write(data)
        return True


def scrape_model(client, make, model, out_dir, max_images, max_per_car):
    class_dir = Path(out_dir) / f"{make}_{model}"
    class_dir.mkdir(parents=True, exist_ok=True)

    new_images = 0
    skipped = 0
    placeholders = 0

    print(f"\n[scrape] {make}/{model} -> {class_dir}")

    for car_make, car_model_slug, car_id in client.get_cars_for_model(make, model):
        if max_images and new_images >= max_images:
            break

        image_ids = client.get_image_ids(car_make, car_model_slug, car_id)
        if not image_ids:
            continue

        if max_per_car:
            image_ids = image_ids[:max_per_car]

        for img_id in image_ids:
            if max_images and new_images >= max_images:
                break

            dest = class_dir / f"{car_id}_{img_id}.jpg"
            if dest.exists():
                skipped += 1
                continue

            ok = client.download_image(img_id, dest)
            if ok:
                new_images += 1
            else:
                placeholders += 1

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
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"Delay between requests in seconds (default: {DEFAULT_DELAY})")

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

    # Determine models to scrape
    if args.model:
        models = args.model
    else:
        print(f"[make] Fetching model list for {args.make}...")
        models = client.get_models_for_make(args.make)
        print(f"[make] Found {len(models)} models: {models}")

    # Scrape
    total = 0
    for model in models:
        total += scrape_model(client, args.make, model, args.out, args.max_images, args.max_per_car)

    print(f"\n[done] Total new images downloaded: {total}")


if __name__ == "__main__":
    main()
