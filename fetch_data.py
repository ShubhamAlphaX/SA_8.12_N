import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import List
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from dateutil.relativedelta import relativedelta
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler

from config import (
    SYMBOL_EQUITY_QUOTE_URL,
    SYMBOL_FUTURES_QUOTE_URL,
    SYMBOL_SUBSCRIPTION_URL,
    SYMBOLS,
)

# Configure logging
logging.basicConfig(
    filename="app.log",
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
file_handler = RotatingFileHandler('app.log', maxBytes=94371840, backupCount=5)
time_handler = TimedRotatingFileHandler('app.log', when='h', interval=5, backupCount=5)


logger = logging.getLogger()
logger.addHandler(file_handler)
logger.addHandler(time_handler)

LOT_SIZE_FILE_PATH = os.path.join(os.path.dirname(__file__), "dict_symbol_lotsize.json")


def get_lotsize_dict():
    try:
        with open(LOT_SIZE_FILE_PATH, "r") as f:
            dict_symbol_lotsize = json.load(f)
        return dict_symbol_lotsize
    except FileNotFoundError:
        logging.error(f"Lot size file {LOT_SIZE_FILE_PATH} not found.")
        raise
    except json.JSONDecodeError:
        logging.error(f"Error decoding JSON from {LOT_SIZE_FILE_PATH}.")
        raise


def is_float(string: str):
    pattern = r"^-?\d+(\.\d+)?$"
    return re.match(pattern, string) is not None


def subscribe_equity_symbols(symbols: List = SYMBOLS):
    list_inst_not_subscribed = []
    retry_dict = {symbol: 0 for symbol in symbols}

    for symbol in symbols:
        while retry_dict[symbol] < 5:
            logging.info(f"Attempting subscription for symbol: {symbol}")
            try:
                response = requests.get(
                    url=SYMBOL_SUBSCRIPTION_URL.format(stock_symbol=f"{symbol}EQ")
                )
                if (
                    response.status_code == 200
                    and f"Subscription requested for dispname : {symbol}EQ"
                    == response.content.decode("utf-8")
                ):
                    logging.info(f"{symbol} SUBSCRIBED SUCCESSFULLY")
                    break
                else:
                    retry_dict[symbol] += 1
                    logging.warning(f"Retry {retry_dict[symbol]} for {symbol}EQ")
            except requests.RequestException as e:
                retry_dict[symbol] += 1
                logging.error(f"Error subscribing to {symbol}: {e}")

        if retry_dict[symbol] >= 5:
            logging.error(f"Subscription failed for {symbol}EQ after 5 attempts.")
            list_inst_not_subscribed.append(symbol)

    return list_inst_not_subscribed


def subscribe_futures_symbols(symbols: List = SYMBOLS):
    MAX_RETRIES = 5
    retry_dict = {symbol: 0 for symbol in symbols}
    
    # Calculate all expiries at once
    now = datetime.now()
    expiries = [
        now.strftime("%y%b").upper(),
        (now + relativedelta(months=1)).strftime("%y%b").upper(),
        (now + relativedelta(months=2)).strftime("%y%b").upper()
    ]
    
    for expiry in expiries:
        for symbol in symbols:
            symbol_expiry = f"{symbol}{expiry}FUT"
            expected_response = f"Subscription requested for dispname : {symbol_expiry}"
            
            while retry_dict[symbol] < MAX_RETRIES:
                logging.info(f"Subscribing: stock_symbol : {symbol_expiry}")
                
                try:
                    response = requests.get(
                        url=SYMBOL_SUBSCRIPTION_URL.format(stock_symbol=symbol_expiry)
                    )
                    
                    if response.status_code == 200 and response.content.decode("utf-8") == expected_response:
                        logging.info(f"{symbol_expiry} SUBSCRIBED SUCCESSFULLY")
                        break
                        
                    retry_dict[symbol] += 1
                    logging.warning(f"Retry {retry_dict[symbol]} for {symbol_expiry}")
                    
                except requests.RequestException as e:
                    retry_dict[symbol] += 1
                    logging.error(f"Error subscribing to {symbol}: {e}")
            
            if retry_dict[symbol] >= MAX_RETRIES:
                logging.error(f"Subscription failed for {symbol_expiry} after {MAX_RETRIES} attempts.")



def fetch_equity_data(symbol: str):
    logging.info(f"Fetching equity data for symbol: {symbol}")
    try:
        response = requests.get(url=SYMBOL_EQUITY_QUOTE_URL.format(stock_symbol=symbol))
        if not response.status_code == 200:
            logging.error(
                f"Failed to fetch equity data for {symbol}. Status code: {response.status_code}"
            )
            raise Exception("Error in request")

        content = {}
        for data in response.content.decode("utf-8").split("\r\n"):
            if not data:
                continue
            key, value = data.split("=")
            content[key] = float(value) if is_float(value) else value

        logging.info(f"Successfully fetched equity data for {symbol}")
        return content
    except requests.RequestException as e:
        logging.error(f"Error fetching equity data for {symbol}: {e}")
        raise


def fetch_futures_data(symbol: str, expiry: str):
    logging.info(f"Fetching futures data for symbol: {symbol}, expiry: {expiry}")
    response = requests.get(
        url=SYMBOL_FUTURES_QUOTE_URL.format(stock_symbol=symbol, expiry=expiry)
    )
    if not response.status_code == 200:
        raise Exception("Error in request")

    content = {}
    for data in response.content.decode("utf-8").split("\r\n"):
        if not data:
            continue
        key, value = data.split("=")
        content[key] = float(value) if is_float(value) else value
    return content


def fetch_symbol_data(
    symbol: str, dict_symbol_lotsize, expiry, no_of_days_left, open_factor):
       
    try:
        open_factor = float(open_factor)
    except (ValueError, TypeError):
        logging.error(f"Invalid open_factor value: {open_factor}. Setting default to 1.0")
        open_factor = 1.0  # Set a default value

    equity_data = fetch_equity_data(symbol=symbol)
    futures_data = fetch_futures_data(symbol, expiry)
    
     
    data = {
        "LOT_SIZE": dict_symbol_lotsize.get(symbol, 1),
        "SYMBOL": symbol,
        "CASH_BID": equity_data.get("bidp1"),
        "CASH_ASK": equity_data.get("askp1"),
        "FUT_BID": futures_data.get("bidp1"),
        "FUT_ASK": futures_data.get("askp1"),
    }
    # Expense Details
    def calculate_expenses(data):
        factors = {
            "CASH_INTRA_BUY": 800,
            "CASH_INTRA_SELL": 3000,
            "CASH_DLV_BUY": 12000,
            "CASH_DLV_SELL": 10500,
            "FUTURE_BUY": 550,
            "FUTURE_SELL": 1600
        }

        for key, factor in factors.items():
            price_key = "CASH_ASK" if "BUY" in key else "CASH_BID" if "CASH" in key else "FUT_ASK" if "BUY" in key else "FUT_BID"
            data[f"{key}_EXP"] = round((data[price_key] * factor / 10000000), 2)

    calculate_expenses(data)

    # Open & Close
    data["CNN_OPEN"] = "{:.2f}".format(data["FUT_BID"] - data["CASH_ASK"])
    data["CNN_CLOSE"] = "{:.2f}".format(data["CASH_BID"] - data["FUT_ASK"])

    # Intra and Delivery Open & Close Calculations
    def calculate_open_close(data, cash_ask_exp, cash_bid_exp, fut_sell_exp, fut_buy_exp, lot_size):
        return {
            'INTRA_OPEN': round((-(data["CASH_ASK"]) + data["FUT_BID"] - cash_ask_exp - fut_sell_exp) * lot_size, 2),
            'INTRA_CLOSE': round((data["CASH_BID"] - data["FUT_ASK"] - cash_bid_exp - fut_buy_exp) * lot_size, 2),
            'DLV_OPEN': round((-(data["CASH_ASK"]) + data["FUT_BID"] - data["CASH_DLV_BUY_EXP"] - fut_sell_exp) * lot_size, 2),
            'DLV_CLOSE': round((data["CASH_BID"] - data["FUT_ASK"] - data["CASH_DLV_SELL_EXP"] - fut_buy_exp) * lot_size, 2)
        }

    open_close_data = calculate_open_close(
        data, 
        data["CASH_INTRA_BUY_EXP"], 
        data["CASH_INTRA_SELL_EXP"], 
        data["FUTURE_SELL_EXP"], 
        data["FUTURE_BUY_EXP"], 
        data['LOT_SIZE']
    )
    data.update(open_close_data)

    # Margin Calculation
    margin = equity_data['ltp'] * 1.2 * data['LOT_SIZE']

    # Relative Return
    data['RLT_RETURN_OPEN'] = round(((data['DLV_OPEN'] * 100 / margin) / no_of_days_left) * 365, 2)
    data['RLT_RETURN_CLOSE'] = round(((data['DLV_CLOSE'] * 100 / margin) / no_of_days_left) * 365, 2)

    # Round Expense
    def calculate_round_exp(data, buy_exp_keys, sell_exp_keys):
        return round(sum(data[key] for key in buy_exp_keys + sell_exp_keys), 2)

    data['INTRA_ROUND_EXP'] = calculate_round_exp(
        data, 
        ['CASH_INTRA_BUY_EXP'], 
        ['CASH_INTRA_SELL_EXP', 'FUTURE_BUY_EXP', 'FUTURE_SELL_EXP']
    )
    data['DLV_ROUND_EXP'] = calculate_round_exp(
        data, 
        ['CASH_DLV_BUY_EXP'], 
        ['CASH_DLV_SELL_EXP', 'FUTURE_BUY_EXP', 'FUTURE_SELL_EXP']
    )

    # Move expense keys to the end
    expenses = {key: data[key] for key in ['CASH_INTRA_BUY_EXP', 'CASH_INTRA_SELL_EXP', 'CASH_DLV_BUY_EXP', 'CASH_DLV_SELL_EXP', 'FUTURE_BUY_EXP', 'FUTURE_SELL_EXP']}
    for key in expenses:
        del data[key]
    data.update(expenses)

    # M_parity & Parity
    data['M_PARITY'] = round((equity_data['ltp'] * data['LOT_SIZE'] * open_factor / 100) + data['DLV_OPEN'] * data['LOT_SIZE'], 2)
    data['PARITY'] = round((equity_data['ltp'] * open_factor / 100) + data['DLV_OPEN'], 2)

    return data


def fetch_all_stocks_data(expiry, no_of_days_left, open_factor):
    dict_symbol_lotsize = get_lotsize_dict()
    all_data = []

    max_workers = 10

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all symbol data fetching tasks to the executor
        futures = {
            executor.submit(fetch_symbol_data, symbol, dict_symbol_lotsize, expiry, no_of_days_left, open_factor): symbol
            for symbol in SYMBOLS
        }
    for future in as_completed(futures):
            symbol = futures[future]
            try:
                data = future.result()
                all_data.append(data)
            except Exception as e:
                logging.error(f"Error fetching data for {symbol}: {e}")

    return sorted(all_data, key=lambda x: x['SYMBOL']) 
    # return all_data

def subscribe_symbols():
    list_inst_not_subscribed = subscribe_equity_symbols()
    valid_symbols = [
        instrument
        for instrument in SYMBOLS
        if instrument not in list_inst_not_subscribed
    ]
    subscribe_futures_symbols(valid_symbols)


def last_thursday_of_month(year, month):

    if month > 12:
        year += (month - 1) // 12
        month = ((month - 1) % 12) + 1

    next_month_first_day = (
        datetime(year, month % 12 + 1, 1) if month != 12 
        else datetime(year + 1, 1, 1)
    )
    last_day_of_month = next_month_first_day - timedelta(days=1)
    days_back = (
        last_day_of_month.weekday() - 3
    ) % 7  # Thursday is the 4th day of the week
    last_thursday = last_day_of_month - timedelta(days=days_back)
    return last_thursday


def get_expiry_data():
    today = datetime.today().date()
    current_year = today.year
    current_month = today.month

    # Get the last Thursday of the current month
    near_expiry = last_thursday_of_month(current_year, current_month).date()

    # If today is past the last Thursday of the month, move to the next month
    if today > near_expiry:
        current_month += 1
    mid_expiry = last_thursday_of_month(current_year, current_month + 1).date()
    far_expiry = last_thursday_of_month(current_year, current_month + 2).date()

    return {
        "today": today.strftime("%Y-%m-%d"),
        "near_expiry": near_expiry.strftime("%Y-%m-%d"),
        "mid_expiry": mid_expiry.strftime("%Y-%m-%d"),
        "far_expiry": far_expiry.strftime("%Y-%m-%d"),
        "days_left_near": (near_expiry - today).days,
        "days_left_mid": (mid_expiry - today).days,
        "days_left_far": (far_expiry - today).days,
    }
