from src.exchange import Exchange


class Binance(Exchange):
    exchange_name = "binance"
    template_subscribe_msg = '{{"method":"SUBSCRIBE","params":["{}"], "id": 1}}'
    ws_host = "wss://stream.binance.com/stream"
    template_data_url = "https://www.binance.com/api/v1/depth?symbol={}&limit=1000"
    asks_key = "a"
    bids_key = "b"

    def format_pair_to_subscribe(self) -> str:
        return f'{self.pair.replace("/", "").lower()}@depth@100ms'

    def format_pair_to_data_url(self) -> str:
        return self.pair.replace("/", "").upper()

    def format_data(self, data: list[tuple[str, ...]]) -> list[tuple[float, ...]]:
        return [(float(i[0]), float(i[1])) for i in data]
