import asyncio
import logging
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable

import orjson
from aiohttp import ClientSession
from websockets.client import WebSocketClientProtocol, connect
from websockets.extensions.permessage_deflate import ClientPerMessageDeflateFactory

if TYPE_CHECKING:
    from src.strategy import InterExchangeArbitrationStrategy


@dataclass
class Value:
    price: float
    qty: float


class Values(dict[float, float]):

    def __init__(self, *args, value_setter: Callable, order: str, override_qty: Counter, **kwargs):
        super().__init__(*args, **kwargs)
        self._lowest = float("inf")
        self._highest = float("-inf")
        self._value_setter = value_setter
        self._update_funk = getattr(self, f"update_{order}")
        self._more0qty = set()
        self._override_qty = override_qty

    def __setitem__(self, k: float, v: float) -> None:
        v -= self._override_qty[k]
        if v > 0:
            self._more0qty.add(k)
            if k > self._highest:
                self._highest = k
            elif k < self._lowest:
                self._lowest = k
        elif v <= 0:
            self._more0qty.discard(k)
            if k == self._highest:
                self._highest = max(self._more0qty or [float("-inf")])
            elif k == self._lowest:
                self._lowest = min(self._more0qty or [float("inf")])
        return super().__setitem__(k, v)

    async def update_bid(self, highest: float, lowest: float) -> None:
        if highest != self._highest:
            await self._value_setter(Value(highest, self.get(highest, 0.0)))

    async def update_ask(self, highest: float, lowest: float) -> None:
        if lowest != self._lowest:
            await self._value_setter(Value(lowest, self.get(lowest, 0.0)))

    async def _update(self, values: Iterable[tuple[float, ...]]) -> None:
        lowest = self._lowest
        highest = self._highest
        for price, qty in values:
            self[price] = qty
        await self._update_funk(highest, lowest)

EXTENSIONS = [ClientPerMessageDeflateFactory(client_max_window_bits=True)]
DEFAULT_VALUE = Value(0.0, 0.0)
TVALUES = list[Value]


class Exchange:

    exchange_name = ""
    template_subscribe_msg = ""
    ws_host = "wss://ws.exchange.com/ws"
    template_data_url = "https://www.exchange.com/"
    asks_key = ""
    bids_key = ""

    def __init__(
        self,
        pair: str,
    ) -> None:
        self.pair = pair
        self.strategy: "InterExchangeArbitrationStrategy" = None  # type: ignore
        self.timestamp = None
        self.subscribe_msg: str = self.template_subscribe_msg.format(self.format_pair_to_subscribe())
        self.data_url = self.template_data_url.format(self.format_pair_to_data_url())
        self._connection: WebSocketClientProtocol = None  # type: ignore
        self.ticker1, self.ticker2 = self.parse_pair()
        self.to_close = False

        self._override_bids_qty = Counter()
        self._override_asks_qty = Counter()
        self._bids = Values(value_setter=self.set_best_bid, order="bid", override_qty=self._override_bids_qty)
        self._asks = Values(value_setter=self.set_best_ask, order="ask", override_qty=self._override_asks_qty)

        self._best_ask: Value = Value(0.0, 0.0)
        self._best_bid: Value = Value(0.0, 0.0)

    @property
    def best_ask(self) -> Value:
        return self._best_ask

    @property
    def best_bid(self) -> Value:
        return self._best_bid

    async def set_best_ask(self, value: Value) -> None:
        self._best_ask = value
        await self.strategy.notify_updated_ask(self)

    async def set_best_bid(self, value: Value) -> None:
        self._best_bid = value
        await self.strategy.notify_updated_bid(self)

    def update_ask_qty(self, price: float, qty: float) -> None:
        self._override_asks_qty[price] += qty

    def update_bid_qty(self, price: float, qty: float) -> None:
        self._override_bids_qty[price] += qty

    def attach(self, strategy: "InterExchangeArbitrationStrategy") -> None:
        self.strategy = strategy

    async def _set_data(self) -> None:
        async with ClientSession() as session:
            async with session.get(self.data_url) as response:
                response = await response.json()
                response = self.format_response(response)

                await self.update_values(response, "bids", "asks")

    async def _set_connection(self) -> None:
        self._connection = await connect(self.ws_host, extensions=EXTENSIONS)
        await self._subscribe_channel()

    def format_response(self, data: dict) -> dict:
        return data

    def format_data(self, data: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
        return data

    def format_pair_to_subscribe(self) -> str:
        return self.pair

    def format_pair_to_data_url(self) -> str:
        return self.pair

    def parse_pair(self):
        return self.pair.split("/")

    async def _subscribe_channel(self) -> None:
        await self._connection.send(self.subscribe_msg)
        await self._connection.recv()

    async def start(self) -> None:
        await self._set_data()
        await self._set_connection()
        while True:
            try:
                async for data in self._connection:
                    data = orjson.loads(data).get("data")
                    await self.update_values(data)
                    if self.to_close:
                        await self.close()
                        return
            except asyncio.exceptions.IncompleteReadError as e:
                logging.error(e)
                await self._set_data()
                await self._set_connection()

    async def update_values(
        self,
        data: dict,
        bids_key: str | None = None,
        asks_key: str | None = None
    ) -> None:
        await self._bids._update(self.format_data(data[bids_key or self.bids_key]))
        await self._asks._update(self.format_data(data[asks_key or self.asks_key]))

    async def close(self):
        await self._connection.close()

    def stop(self) -> None:
        self.to_close = True

    async def purchase(self, qty: float) -> None:
        await asyncio.sleep(0.01)

    async def sale(self, qty: float) -> None:
        await asyncio.sleep(0.01)
