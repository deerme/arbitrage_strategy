import asyncio
from decimal import Decimal
from time import time

from loguru import logger
from websockets.connection import State

from src.exchange import Exchange

TWOPLACES = Decimal("0.01")
SPACES = " "*31


class InterExchangeArbitrationStrategy:
    def __init__(
        self,
        *,
        pair: str,
        profit_size: float,
        demo: bool = False,
        binance: Exchange,
        ftx: Exchange,
    ) -> None:
        self.pair = pair
        self.profit_size = profit_size
        self.total_profit = Decimal("0.00")
        self.total_deal = 0
        self.demo = demo

        self.binance = binance
        self.binance.attach(self)
        self._reload_binance = 0
        self._binance_task: asyncio.Task | None = None
        self._binance_start_time = 0.0
        self._binance_stop_time = 0.0

        self.ftx = ftx
        self.ftx.attach(self)
        self._reload_ftx = 0
        self._ftx_task: asyncio.Task | None = None
        self._ftx_start_time = 0.0
        self._ftx_stop_time = 0.0

        self.start_time: float = 0.0

        self._observer_cnt = 0
        self._observer_task: asyncio.Task | None = None

    def start(self) -> None:
        logger.info(
            f"Started watching of the pair of currencies {self.pair} on the exchanges ftx and binance"
        )
        self.binance_start()
        self.ftx_start()
        self.observer_start()
        self.start_time = time()

    async def stop(self) -> None:
        await self.binance_stop()
        await self.ftx_stop()
        self.observer_stop()

    async def binance_stop(self) -> None:
        if self._binance_task and self._binance_task.cancelled():
            await self.binance.stop()
            self._binance_task.cancel()
            self._binance_stop_time = time()

    async def ftx_stop(self) -> None:
        if self._ftx_task and self._ftx_task.cancelled():
            await self.ftx.stop()
            self._ftx_task.cancel()
            self._ftx_stop_time = time()

    def observer_stop(self) -> None:
        if self._observer_task and not self._observer_task.cancelled():
            self._observer_task.cancel()

    def binance_start(self) -> None:
        if not self._binance_task or self._binance_task.cancelled:
            self._binance_task = asyncio.create_task(self.binance.start())
            self._binance_start_time = time()

    def ftx_start(self) -> None:
        if not self._ftx_task or self._ftx_task.cancelled:
            self._ftx_task = asyncio.create_task(self.ftx.start())
            self._ftx_start_time = time()

    def observer_start(self) -> None:
        if not self._observer_task:
            self._observer_task = asyncio.create_task(self.run_observer())

    async def binance_reload(self) -> None:
        await self.binance_stop()
        self.binance_start()

    async def ftx_reload(self) -> None:
        await self.ftx_stop()
        self.ftx_start()

    async def notify_updated_ask(self, exchange: Exchange) -> None:
        other = self.get_other_exchange(exchange)
        if (
            0
            < (best_ask_price := exchange.best_ask.price)
            < (best_bid_price := other.best_bid.price)
        ):
            await self.make_deals(exchange, best_ask_price, other, best_bid_price)

    async def notify_updated_bid(self, exchange: Exchange) -> None:
        other = self.get_other_exchange(exchange)
        if (
            0
            < (best_ask_price := other.best_ask.price)
            < (best_bid_price := exchange.best_bid.price)
        ):
            await self.make_deals(other, best_ask_price, exchange, best_bid_price)

    async def run_observer(self) -> None:
        logger.info("Started obsrver")
        while True:
            self._observer_cnt += 1
            t = time()
            if (
                (t_ftx := t - self.ftx.timestamp) > 5
                and self.ftx.state_con > State.OPEN
            ) or t_ftx > 10:
                await self.ftx_reload()
                self._reload_ftx += 1
            if (
                (t_binance := t - self.binance.timestamp) > 5
                and self.binance.state_con > State.OPEN
            ) or t_binance > 10:
                await self.binance_reload()
                self._reload_binance += 1
            await asyncio.sleep(5)

    def get_other_exchange(self, exchange: Exchange) -> Exchange:
        if exchange.exchange_name == "ftx":
            return self.binance
        return self.ftx

    async def make_deals(
        self,
        efp: Exchange,  # exchange_for_purchase
        best_ask_price: float,
        efs: Exchange,  # exchange_for_sale
        best_bid_price: float,
    ) -> None:
        qty = min(efp.best_ask.qty, efs.best_bid.qty)
        if qty <= 0:
            return
        purchase_price = Decimal(qty * best_ask_price).quantize(TWOPLACES)
        sale_price = Decimal(qty * best_bid_price).quantize(TWOPLACES)
        profit = sale_price - purchase_price
        if profit >= self.profit_size:
            self.notify(efp, efs, profit)
            if self.demo:
                purchase = efp.purchase(qty)
                sale = efs.sale(qty)
                await asyncio.gather(purchase, sale)
                self.fix_profit(
                    efp,
                    best_ask_price,
                    efs,
                    best_bid_price,
                    qty,
                    purchase_price,
                    sale_price,
                    profit,
                )

                # Имитация уменьшения объема валюты в ордерах
                await efp.update_ask_qty(best_ask_price, qty)
                await efs.update_bid_qty(best_bid_price, qty)

    def fix_profit(
        self,
        efp: Exchange,
        best_ask_price: float,
        efs: Exchange,
        best_bid_price: float,
        qty: float,
        purchase_price: Decimal,
        sale_price: Decimal,
        profit: Decimal,
    ) -> None:
        self.total_profit += profit
        self.total_deal += 1
        logger.info(
            f"Куплено {qty} {efp.ticker1} за {purchase_price} ({best_ask_price}) {efp.ticker2} на бирже {efp.exchange_name}.\n"
            f"{SPACES}Продано {qty} {efs.ticker1} за {sale_price} ({best_bid_price}) {efs.ticker2} на бирже {efs.exchange_name}.\n"
            f"{SPACES}Выгода от сделки {profit} {efp.ticker2} без учета комиссий.\n"
            f"{SPACES}Общее количество сделок {self.total_deal}.\n"
            f"{SPACES}Общая выгода от сделок {self.total_profit} {efp.ticker2} без учета комиссий."
        )

    def notify(
        self,
        efp: Exchange,
        efs: Exchange,
        profit: Decimal,
    ) -> None:
        purchase_msg = f"Покупка: {efp.best_ask.price} {efp.ticker2}"
        sale_msg = f"Продажа: {efs.best_bid.price} {efp.ticker2}"
        msg = (
            f"На бирже {efp.exchange_name} появилось предложение на покупку дешевле,\n"
            f"{SPACES}чем лучшее предложение на продажу на бирже {efs.exchange_name}.\n"
            f"{SPACES}{purchase_msg:<30} | {sale_msg:<30}\n"
            f"{SPACES}Возможная выгода от сделок {profit} {efp.ticker2} без учета комиссий."
        )
        logger.info(msg)
