"""Polite HTTP: normal browser UA, ≥2 s between requests to one host, backoff on 429/5xx."""
from __future__ import annotations

import random
import threading
import time
from urllib.parse import urlparse

import httpx

from .log import get

log = get("http")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MIN_INTERVAL = 2.0


class HttpError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class RobotsBlocked(HttpError):
    pass


class Http:
    def __init__(self, min_interval: float = MIN_INTERVAL, timeout: float = 20.0, retries: int = 3,
                 client: httpx.Client | None = None, sleep=time.sleep):
        self.min_interval = min_interval
        self.retries = retries
        self.sleep = sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self.client = client or httpx.Client(
            timeout=timeout, follow_redirects=True,
            headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                     "Accept-Language": "en-US,en;q=0.9,nb;q=0.8"})
        self.requests = 0
        self.guards: list = []  # callables(url) -> None or raise RobotsBlocked

    def _wait(self, host: str) -> None:
        with self._lock:
            last = self._last.get(host)
            if last is not None:
                delta = time.monotonic() - last
                if delta < self.min_interval:
                    self.sleep(self.min_interval - delta)
            self._last[host] = time.monotonic()

    def request(self, method: str, url: str, **kw) -> httpx.Response:
        for g in self.guards:
            g(url)
        host = urlparse(url).netloc
        backoff = 5.0
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._wait(host)
            self.requests += 1
            try:
                r = self.client.request(method, url, **kw)
            except httpx.HTTPError as e:
                last_exc = e
                log.warning("%s %s failed: %r", method, url, e)
                if attempt < self.retries:
                    self.sleep(backoff); backoff *= 2
                    continue
                raise HttpError(f"could not reach {host} ({e.__class__.__name__})") from None
            if r.status_code == 429 or r.status_code >= 500:
                log.warning("%s %s -> %s (attempt %d)", method, url, r.status_code, attempt + 1)
                if attempt < self.retries:
                    ra = r.headers.get("Retry-After", "")
                    wait = float(ra) if ra.isdigit() else backoff + random.uniform(0, 1)
                    self.sleep(min(wait, 120)); backoff *= 2
                    continue
                msg = "the site says we're asking too often (429) — try again later" if r.status_code == 429 \
                    else f"{host} had a server error ({r.status_code})"
                raise HttpError(msg, r.status_code)
            return r
        raise HttpError(f"could not reach {host}: {last_exc}")

    def get(self, url: str, **kw) -> httpx.Response:
        return self.request("GET", url, **kw)

    def get_text(self, url: str, **kw) -> str:
        r = self.get(url, **kw)
        if r.status_code >= 400:
            raise HttpError(f"{urlparse(url).netloc} answered {r.status_code}", r.status_code)
        return r.text

    def head(self, url: str, **kw) -> httpx.Response:
        return self.request("HEAD", url, **kw)

    def close(self) -> None:
        self.client.close()
