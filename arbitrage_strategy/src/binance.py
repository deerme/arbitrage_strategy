from src.exchange import Exchange


class Binance(Exchange):
    exchange_name = "binance"
    template_subscribe_msg = '{{"method":"SUBSCRIBE","params":["{}"], "id": 1}}'
    host = "wss://stream.binance.com/stream"
    asks_key = "a"
    bids_key = "b"

    def format_pair(self) -> str:
        return f'{self.pair.replace("/", "").lower()}@depth@100ms'
