import telegram
import configparser
from telegram import Update
from telegram.ext import CallbackContext, MessageHandler, Filters, Updater
import logging
import time
import re
# import MetaTrader5 as mt5
from mt5linux import MetaTrader5 as mt5

# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Read the token and your user ID from the config.ini file
config = configparser.ConfigParser()
config.read('config.ini')

my_username = config.get('Telegram', 'my_username')
# Add your_user_id to your config file
my_user_id = int(config.get('Telegram', 'my_user_id'))

token = config.get('TradingBot', 'token')

lot_size = float(config.get('Settings', 'lot_size'))


def initialize_bot():
    # Initialize MT5 connection without login credentials
    if not mt5.initialize():
        print("initialize() failed, error code =", mt5.last_error())
        quit()

    # Now you're connected. You can fetch account information, place trades, etc.
    print(mt5.account_info())


def handle_message(update: Update, context: CallbackContext) -> None:
    text = None

    # Check if the update contains a regular message
    if update.message:
        text = update.message.text
    # Check if the update contains a channel post
    elif update.channel_post:
        text = update.channel_post.text

    # If no text was found, return
    if not text:
        return

    if re.search(r'\s?([A-Z]{6})\s', text):
        print(f"Received matching message: {text}")
        context.bot.send_message(
            my_user_id, f"Received a new matching message: {text}")
        info = extract_order_info(text)

        # Get the list of TP values
        tp_values = [value for key, value in info.items() if key.startswith("tp")]
        if not tp_values:
            print("No TP targets found!")
            return

        # Calculate the volume per TP
        volume_per_tp = float(lot_size) / len(tp_values)

        i = 1
        msg = []

        for tp in tp_values:
            place_market_order(info['symbol'], info['order_type'], float(
                format(float(volume_per_tp), '.2f')), float(info['sl']), float(tp))
            print(
                f"Placed order for {float(format(float(volume_per_tp), '.2f'))} lots of {info['symbol']} at {info['order_type']} {info['order_price']} with SL {info['sl']} and TP {tp}")
            # simply send one message with all the TP values appended to it
            msg.append(
                f"TP {i}: Placed order for {float(format(float(volume_per_tp), '.2f'))} lots of {info['symbol']} at {info['order_type']} {info['order_price']} with SL {info['sl']} and TP {tp}")
            i += 1

        context.bot.send_message(my_user_id, "\n".join(msg))


def extract_order_info(text: str) -> dict:
    results = {}

    # Extract the symbol (e.g., XAUUSD, GBPJPY)
    symbol_match = re.search(r'(\w+)', text)
    if symbol_match:
        results['symbol'] = symbol_match.group(1)

    # Extract order type (Buy/Sell)
    order_type_match = re.search(r'(BUY|SELL)', text, re.IGNORECASE)
    if order_type_match:
        results['order_type'] = order_type_match.group(1).upper()

    # Extract order price and format to three decimal places (including optional NOW)
    price_match = re.search(r'(BUY|SELL)(?:\s+NOW)?\s+([\d\.]+)(?:\/[\d\.]+)?', text, re.IGNORECASE)
    if price_match:
        results['order_price'] = float(format(float(price_match.group(2)), ".3f"))

    # Extract SL value and format to three decimal places
    sl_match = re.search(r'SL\s*:?\s*([\d:,\']+)(?=\D|$)', text, re.IGNORECASE)
    if sl_match:
        sl_value = sl_match.group(1).replace(",", "").replace("'", ".").replace(":", ".")
        results['sl'] = float(format(float(sl_value), ".3f"))

    # Extract TP values and format each to three decimal places
    # Regex pattern to match 'TP' followed by an optional word character, optional whitespace, and a semicolon
    tpReplacePattern = r'(Tp\d*\s*);'
    
    # Replacement function to replace ';' with ':' after 'Tp'
    def replace_semicolon(match):
        return match.group(0).replace(';', ':')

    # Use re.sub() to apply the replacement to the entire text
    updated_text = re.sub(tpReplacePattern, replace_semicolon, text, flags=re.IGNORECASE)
    
    tp_matches = re.findall(r'TP\w?\s*:?\s*([\d:,\']+)(?=\D|$)', updated_text, re.IGNORECASE)
    for index, tp_value in enumerate(tp_matches, start=1):
        tp_value = tp_value.replace(",", "").replace("'", ".").replace(":", ".")
        key = f"tp{index}"
        results[key] = float(format(float(tp_value), ".3f"))

    return results


def place_market_order(symbol, action, volume, sl, tp):
    if action == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        tick_info = mt5.symbol_info_tick(symbol)
        if tick_info is None:
            print(f"Could not fetch tick data for symbol: {symbol}")
            return
        price = tick_info.ask
    elif action == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        tick_info = mt5.symbol_info_tick(symbol)
        if tick_info is None:
            print(f"Could not fetch tick data for symbol: {symbol}")
            return
        price = tick_info.bid
    else:
        print(f"Unknown action: {action}")
        return

    # Create the request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,  # This is for immediate execution
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,  # This means the current market price will be used
        "sl": sl,
        "tp": tp,
        "magic": 99999,  # Magic number, can be any identifier you choose
        "comment": "python script open",  # Comment on the order
        "type_time": mt5.ORDER_TIME_GTC,  # Good Till Cancelled
        "type_filling": mt5.ORDER_FILLING_IOC,  # Return an error if the order cannot be filled immediately
    }

    # Send the request
    result = mt5.order_send(request)

    if result is None:
        print("Failed to send order. No response received.")
        error = mt5.last_error()
        print("Error in order_send(): ", error)
        return

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Failed to send order. Error: {result.comment}")
        return
    print(f"Order successfully placed with ticket {result.order}")
    return result.order

def run_bot():
    try:
        # Create an updater and pass your bot's token
        updater = Updater(token=token)

        # On each message, call the 'handle_message' function
        dp = updater.dispatcher
        dp.add_handler(MessageHandler(Filters.text & ~
                       Filters.command, handle_message))
        # Assuming you have the error_callback from the previous message
        dp.add_error_handler(error_callback)

        updater.start_polling()
        print("Bot started polling...")
        updater.idle()  # This will block until the bot is stopped or Ctrl+C is pressed
    except telegram.error.NetworkError:
        print("Network error encountered. Retrying in 10 seconds...")
        time.sleep(10)
        run_bot()
    except Exception as e:
        print(f"Unexpected error: {e}. Retrying in 10 seconds...")
        time.sleep(10)
        run_bot()


def error_callback(update: Update, context: CallbackContext) -> None:
    """Log the error, send a telegram message to notify the developer, and re-raise the error."""
    logging.error(msg="Exception while handling an update:",
                  exc_info=context.error)

    # Send a message to the developer with the error, except if the error is network error then dont send
    if not isinstance(context.error, telegram.error.NetworkError):
        context.bot.send_message(
            chat_id=my_user_id, text=f"An error occurred: {context.error}")

    # Re-raise the error
    raise context.error


def gold_trading_main():
    initialize_bot()
    run_bot()


if __name__ == '__main__':
    gold_trading_main()
