from src.exchange import Exchange


class FTX(Exchange):
    exchange_name = "ftx"
    template_subscribe_msg = '{{"op":"subscribe","channel":"orderbook","market":"{}"}}'
    host = "wss://ws.ftx.com/ws"
    asks_key = "asks"
    bids_key = "bids"
