"""Bounded successful-response cache. Failures are never cached."""

import asyncio
import copy
from collections import OrderedDict
from time import monotonic

import httpx

from infrastructure.metadata.common import TIMEOUT


class MetadataHTTPClient:
    def __init__(
        self, user_agent: str = "Scriva/1.6", size: int = 256
    ) -> None:
        self._user_agent = user_agent
        self._size = size
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()

    async def get_json(self, url: str, params: dict | None = None) -> dict:
        key = str(httpx.URL(url, params=params))
        cached = self._cache.get(key)
        if cached and monotonic() - cached[0] < 3600:
            self._cache.move_to_end(key)
            return copy.deepcopy(cached[1])
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": self._user_agent}
        ) as client:
            response = await asyncio.wait_for(
                client.get(url, params=params), TIMEOUT
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Metadata response must be a JSON object.")
        self._cache[key] = (monotonic(), copy.deepcopy(data))
        while len(self._cache) > self._size:
            self._cache.popitem(last=False)
        return data
