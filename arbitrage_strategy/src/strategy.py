import asyncio
import logging
from decimal import Decimal
from time import time

from websockets.connection import State

from src.exchange import Exchange

TWOPLACES = Decimal("0.01")


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
        self.ftx = ftx
        self.binance.attach(self)
        self.ftx.attach(self)

    async def start(self) -> None:
        logging.info(
            f"Started watching of the pair of currencies {self.pair} on the exchanges ftx and binance"
        )
        # self.binance_task = asyncio.create_task(self.binance.start())
        # self.ftx_task = asyncio.create_task(self.ftx.start())
        await asyncio.gather(self.binance.start(), self.ftx.start(), self.observer())

    def stop(self) -> None:
        self.binance.stop()
        self.ftx.stop()

    async def notify_updated_ask(self, exchange: Exchange) -> None:
        other = self.get_other_exchange(exchange)
        if (
            0
            < (best_ask_price := exchange.best_ask.price)
            < (best_bid_price := other.best_bid.price)
        ):
            await self.make_deals(exchange, best_ask_price, other, best_bid_price)

    async def observer(self) -> None:
        while True:
            t = time()
            if (
                t_ftx := t - self.ftx.timestamp
            ) > 5 and self.ftx.state_con > State.OPEN:
                logging.debug(f"call reload ftx {t_ftx=}")
                self.ftx.reload()
            if (
                t_binance := t - self.binance.timestamp
            ) > 5 and self.binance.state_con > State.OPEN:
                logging.debug(f"call reload binance {t_binance=}")
                self.binance.reload()
            await asyncio.sleep(5)

    async def notify_updated_bid(self, exchange: Exchange) -> None:
        other = self.get_other_exchange(exchange)
        if (
            0
            < (best_ask_price := other.best_ask.price)
            < (best_bid_price := exchange.best_bid.price)
        ):
            await self.make_deals(other, best_ask_price, exchange, best_bid_price)

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
        else:
            logging.info(
                f"Выгодных ордеров нет | {best_ask_price=} | {best_bid_price=} | {profit=:.2f}"
            )

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
        logging.info(
            f"Куплено {qty} {efp.ticker1} за {purchase_price} ({best_ask_price}) {efp.ticker2} на бирже {efp.exchange_name}.\n"
            f"          Продано {qty} {efs.ticker1} за {sale_price} ({best_bid_price}) {efs.ticker2} на бирже {efs.exchange_name}.\n"
            f"          Выгода от сделки {profit} {efp.ticker2} без учета комиссий.\n"
            f"          Общее количество сделок {self.total_deal}.\n"
            f"          Общая выгода от сделок {self.total_profit} {efp.ticker2} без учета комиссий."
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
            f"          чем лучшее предложение на продажу на бирже {efs.exchange_name}.\n"
            f"          {purchase_msg:<30} | {sale_msg:<30}\n"
            f"          Возможная выгода от сделок {profit} {efp.ticker2} без учета комиссий."
        )
        logging.info(msg)
