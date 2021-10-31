import asyncio
from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

import orjson
from websockets.client import WebSocketClientProtocol, connect
from websockets.extensions.permessage_deflate import \
    ClientPerMessageDeflateFactory

if TYPE_CHECKING:
    from src.strategy import InterExchangeArbitrationStrategy


@dataclass
class Value:
    price: float
    qty: float


EXTENSIONS = [ClientPerMessageDeflateFactory(client_max_window_bits=True)]
DEFAULT_VALUE = Value(0.0, 0.0)
TVALUES = list[Value]


class Exchange:

    exchange_name = ""
    template_subscribe_msg = ""
    host = "wss://ws.exchange.com/ws"
    asks_key = ""
    bids_key = ""

    def __init__(
        self,
        pair: str,
    ) -> None:
        self.pair = pair
        self.strategy: "InterExchangeArbitrationStrategy" = None  # type: ignore
        self.timestamp = None
        self.subscribe_msg: str = self.template_subscribe_msg.format(
            self.format_pair()
        )
        self._connection: WebSocketClientProtocol = None  # type: ignore
        self.ticker1, self.ticker2 = self.parse_pair()
        self.asks: TVALUES = [DEFAULT_VALUE]
        self.bids: TVALUES = [DEFAULT_VALUE]
        self.to_close = False

        self._best_ask: Value | None = None
        self._best_bid: Value | None = None

    @property
    def best_ask(self) -> Value:
        if not self._best_ask:
            self._best_ask = self._calc_best_ask()
        return self._best_ask

    def update_best_ask_qty(self, qty: float) -> None:
        if not self._best_ask:
            return
        self._best_ask.qty = round(self._best_ask.qty - qty, 2)
        self._best_ask = None

    def update_best_bid_qty(self, qty: float) -> None:
        if not self._best_bid:
            return
        self._best_bid.qty = round(self._best_bid.qty - qty, 2)
        self._best_bid = None

    @property
    def best_bid(self) -> Value:
        if not self._best_bid:
            self._best_bid = self._calc_best_bid()
        return self._best_bid

    def attach(self, strategy: "InterExchangeArbitrationStrategy") -> None:
        self.strategy = strategy

    async def _set_connection(self) -> None:
        self._connection = await connect(self.host, extensions=EXTENSIONS)
        await self._subscribe_channel()

    def format_pair(self) -> str:
        return self.pair

    def parse_pair(self):
        return self.pair.split("/")

    async def _subscribe_channel(self) -> None:
        await self._connection.send(self.subscribe_msg)
        await self._connection.recv()

    async def start(self) -> None:
        await self._set_connection()
        try:
            async for data in self._connection:
                data = orjson.loads(data).get("data")
                self.update_values(data)
                await self.notify()
                if self.to_close:
                    await self.close()
                    return
        except asyncio.exceptions.IncompleteReadError as e:
            logging.error(e)
            self.update_values({})
            await self.start()

    def update_values(self, data: dict) -> None:
        self.asks = self.get_values(data, self.asks_key)
        self.bids = self.get_values(data, self.bids_key)
        self._best_ask = None
        self._best_bid = None

    def get_values(self, data: dict, key: str) -> list[Value]:
        return [
            Value(*(float(i[0]), qty))
            for i in data[key]
            if (qty := float(i[1])) > 0
        ]

    def _calc_best_ask(self) -> Value:
        return (
            min(self.asks, key=lambda v: v.price)
            if len(self.asks)
            else DEFAULT_VALUE
        )

    def _calc_best_bid(self) -> Value:
        return (
            max(self.bids, key=lambda v: v.price)
            if len(self.bids)
            else DEFAULT_VALUE
        )

    async def close(self):
        await self._connection.close()

    def stop(self) -> None:
        self.to_close = True

    async def notify(self) -> None:
        await self.strategy.update(self)

    async def purchase(self, qty: float) -> None:
        await asyncio.sleep(0.01)

    async def sale(self, qty: float) -> None:
        await asyncio.sleep(0.01)
