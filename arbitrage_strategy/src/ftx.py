from src.exchange import Exchange


class FTX(Exchange):
    exchange_name = "ftx"
    template_subscribe_msg = '{{"op":"subscribe","channel":"orderbook","market":"{}"}}'
    ws_host = "wss://ws.ftx.com/ws"
    template_data_url = "https://ftx.com/api/markets/{}/orderbook?depth=25"
    asks_key = "asks"
    bids_key = "bids"

    def format_response(self, data: dict) -> dict:
        return data["result"]
