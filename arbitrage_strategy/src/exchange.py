import asyncio
from asyncio.exceptions import IncompleteReadError
from collections import Counter
from dataclasses import dataclass
from time import time
from typing import TYPE_CHECKING, Callable, Iterable

import orjson
from aiohttp import ClientSession
from loguru import logger
from websockets.client import WebSocketClientProtocol, connect
from websockets.connection import State
from websockets.exceptions import ConnectionClosedError
from websockets.extensions.permessage_deflate import \
    ClientPerMessageDeflateFactory

if TYPE_CHECKING:
    from src.strategy import InterExchangeArbitrationStrategy


EXTENSIONS = [ClientPerMessageDeflateFactory(client_max_window_bits=True)]
INFINITY = float("inf")
MINFINITY = float("-inf")


@dataclass
class Order:
    price: float
    qty: float


class Orders(dict[float, float]):
    """Хранилище для цен и количества валюты лимитных ордеров"""

    def __init__(
        self, *args, value_setter: Callable, order: str, override_qty: Counter, **kwargs
    ) -> None:
        super().__init__(*args, **kwargs)
        self.lowest_price = INFINITY
        self.highest_price = MINFINITY
        self._value_setter = value_setter
        self._update_funk = getattr(self, f"update_{order}")

        # отдельно храним цены на валюту с не нулевым количеством в ордерах
        # для расчета best_bid и best_ask
        self._more0qty = set()

        # т.к. реальных сделок не совершается, необходимо отдельно учитывать
        # объёмы "купленной"/"проданной" валюты, чтобы исключить повторные сделки
        # при нулевом количестве в ответе АПИ - счетчик также сбрасывается
        self._override_qty = override_qty

    def __setitem__(self, price: float, qty: float) -> None:
        if qty == 0:
            self._override_qty[price] = 0
        else:
            qty = round(qty - self._override_qty[price], 5)
        if qty > 0:
            self._more0qty.add(price)
            if price > self.highest_price:
                self.highest_price = price
            elif price < self.lowest_price:
                self.lowest_price = price
        elif qty <= 0:
            self._more0qty.discard(price)
            if price == self.highest_price:
                self.highest_price = max(self._more0qty or [MINFINITY]) or MINFINITY
            elif price == self.lowest_price:
                self.lowest_price = min(self._more0qty or [INFINITY]) or INFINITY
        return super().__setitem__(price, qty)

    async def update_bid(self, highest_price: float, lowest_price: float) -> None:
        if highest_price != self.highest_price:
            await self._value_setter(Order(highest_price, self.get(highest_price, 0.0)))

    async def update_ask(self, highest_price: float, lowest_price: float) -> None:
        if lowest_price != self.lowest_price:
            await self._value_setter(Order(lowest_price, self.get(lowest_price, 0.0)))

    async def _update(self, values: Iterable[tuple[float, ...]]) -> None:
        lowest_price = self.lowest_price
        highest_price = self.highest_price
        for price, qty in values:
            self[price] = qty
        await self._update_funk(highest_price, lowest_price)


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
        self.subscribe_msg: str = self.template_subscribe_msg.format(
            self.format_pair_to_subscribe()
        )
        self.data_url = self.template_data_url.format(self.format_pair_to_data_url())
        self.ticker1, self.ticker2 = self.parse_pair()

        self.to_reload = False
        self.to_close = False

        self._override_bids_qty = Counter()
        self._override_asks_qty = Counter()

        self._bids = Orders(
            value_setter=self.set_best_bid,
            order="bid",
            override_qty=self._override_bids_qty,
        )
        self._asks = Orders(
            value_setter=self.set_best_ask,
            order="ask",
            override_qty=self._override_asks_qty,
        )

        self._best_ask: Order = Order(0.0, 0.0)
        self._best_bid: Order = Order(0.0, 0.0)

        self.timestamp = time()

        self._con: WebSocketClientProtocol | None = None
        self._data_gained = 0

    @property
    def state_con(self) -> int:
        if not self._con:
            return State.CLOSED
        return self._con.state

    @property
    def best_ask(self) -> Order:
        return self._best_ask

    @property
    def best_bid(self) -> Order:
        return self._best_bid

    async def set_best_ask(self, value: Order) -> None:
        self._best_ask = value
        await self.strategy.notify_updated_ask(self)

    async def set_best_bid(self, value: Order) -> None:
        self._best_bid = value
        await self.strategy.notify_updated_bid(self)

    async def update_ask_qty(self, price: float, qty: float) -> None:
        self._override_asks_qty[price] += qty
        await self._asks._update([(price, self._asks[price])])

    async def update_bid_qty(self, price: float, qty: float) -> None:
        self._override_bids_qty[price] += qty
        await self._bids._update([(price, self._bids[price])])

    def attach(self, strategy: "InterExchangeArbitrationStrategy") -> None:
        self.strategy = strategy

    async def _set_data(self) -> None:
        async with ClientSession() as session:
            async with session.get(self.data_url) as response:
                response = await response.json()
                response = self.format_response(response)

                await self.update_values(response, "bids", "asks")

    def format_response(self, data: dict) -> dict:
        return data

    def format_data(self, data: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
        return data

    def format_pair_to_subscribe(self) -> str:
        return self.pair

    def format_pair_to_data_url(self) -> str:
        return self.pair

    def parse_pair(self) -> list[str]:
        return self.pair.split("/")

    async def _subscribe_ws(self, con: WebSocketClientProtocol) -> None:
        await con.send(self.subscribe_msg)
        await con.recv()

    async def start(self) -> None:
        logger.info(f"Started {self.exchange_name}")
        await self._set_data()
        try:
            async with connect(self.ws_host, extensions=EXTENSIONS) as con:
                self._con = con
                await self._subscribe_ws(con)
                async for data in self._con:
                    data = orjson.loads(data).get("data")
                    self.timestamp = time()
                    self._data_gained += 1
                    await self.update_values(data)
        except (IncompleteReadError, ConnectionClosedError) as e:
            logger.error(e)

    async def stop(self) -> None:
        if self._con is not None:
            await self._con.close()
            self._con = None

    async def update_values(
        self, data: dict, bids_key: str | None = None, asks_key: str | None = None
    ) -> None:
        await self._bids._update(self.format_data(data[bids_key or self.bids_key]))
        await self._asks._update(self.format_data(data[asks_key or self.asks_key]))

    async def purchase(self, qty: float) -> None:
        await asyncio.sleep(0.01)

    async def sale(self, qty: float) -> None:
        await asyncio.sleep(0.01)
