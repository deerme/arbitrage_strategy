import logging

import orjson
import uvloop

from src.binance import Binance
from src.ftx import FTX
from src.strategy import InterExchangeArbitrationStrategy

format = "%(asctime)s: %(message)s"
logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")


def main():
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


if __name__ == "__main__":
    uvloop.install()
    main()
