import asyncio

import orjson
import uvloop

from init_logging import setup_logging
from src.binance import Binance
from src.ftx import FTX
from src.strategy import InterExchangeArbitrationStrategy


async def main():
    with open("config.json") as f:
        config = orjson.loads(f.read())
    pair = config.get("pair")
    profit_size = config.get("profit_size")
    demo = config.get("demo")

    binance = Binance(pair=pair)
    ftx = FTX(pair=pair)
    strategy = InterExchangeArbitrationStrategy(
        pair=pair,
        profit_size=profit_size,
        demo=demo,
        binance=binance,
        ftx=ftx,
    )
    strategy.start()
    while True:
        # TODO: прослушивать порт на сигнал для отсановки
        await asyncio.sleep(60 * 60 * 24)


if __name__ == "__main__":
    uvloop.install()
    setup_logging()
    asyncio.run(main())
