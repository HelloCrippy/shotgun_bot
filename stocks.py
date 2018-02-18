import bittrex

import traceback
from time import sleep
from functools import wraps

from logger import setup_logger, INFO, WARNING, DEBUG
from simplejson.scanner import JSONDecodeError

STEP = .00000001

class StocksError(Exception): pass
class StockRespondedNotSuccess(StocksError): pass
class MandatoryOrderNotExecuted(StocksError): pass


def stock_errors(func):
    """
    Возвращает результат функции или None в случае ошибки
    :param func: оборачиваемая функция
    :return: result or None
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            result = func(self, *args, **kwargs)
        except StockRespondedNotSuccess as Error:
            self.logger.warning(f"called::{func.__name__} неуспешно: {Error.args[0]}")
        except KeyError:
            self.logger.error(f"called::{func.__name__} инвалидный ответ")
        else:
            self.logger.debug(f"called::{func.__name__} вернула {result}")
            return result
    return wrapper


class Bittrex:
    def __init__(self, pair: str, key, secret):
        """
        Экземпляр биржи для работы на соответствубщей пары.
        :param pair: пара с которой будет работать объект
        """
        self.api = bittrex.Bittrex(api_key=key, api_secret=secret)
        self.logger = setup_logger(name=__class__.__name__, level=INFO)
        self.pair = pair

    def __get_result(static, resp):
        if not resp['success']:
                raise StockRespondedNotSuccess(resp['message'])
        return resp['result']

    @stock_errors
    def set_mandatory_order(self, amount, order_type, currency,
                            timeout=1, permissible_spread=.0025):
        """
        Функция принудительно закрывает ордер. По таймауту перевыставляет
        ордер в верх стакана, если разница в курсах не больше stoploss процентах
        :param amount: значение ордера
        :param order_type: покупка или продажа
        :param currency: недостающая валюта
        :param timeout: время перевыставления ордера
        :param permissible_spread: допустимый для сделки спрэд
        :return: json закрытый ордер
        :rtype: dict
        """
        prev_rate = 0
        order_id = None

        while True:
            blc = self.get_balances()[currency]['Available']
            if blc is None:
                self.logger.debug("Обязательный ордер не выполнен. Ошибка апи!")
                continue

            order_book = self.get_order_book()
            if order_book is None:
                self.logger.debug("Обязательный ордер не выполнен. Ошибка апи!")
                continue
            rate = order_book[order_type][0]['Rate']

            if currency == 'BTC':
                current_amount = rate * amount
            else:
                current_amount = amount

            if blc > current_amount:
                self.logger.info(f"Обязательный ордер не выполнен. Валюта найдена")
                break

            spread = float(order_book['sell'][0]['Rate'] /
                           order_book['buy'][0]['Rate'] - 1)
            if spread < permissible_spread:
                self.logger.debug(f"Обязательный ордер не выполнен. Недопустимый спред "
                                 f"{spread:.2f} < {permissible_spread}")
                break

            if rate != prev_rate:
                if order_id:
                    self.cancel_order(order_id)
                rate += (STEP if order_type == 'buy' else -STEP)
                order_id = self.set_order(order_type, amount, rate)
                if not order_id:
                    self.logger.debug("Обязательный ордер не выполнен. Ошибка апи!")
                    continue

                prev_rate = rate
            else:
                lower_rate = order_book[order_type][1]['Rate']
                lower_rate += (STEP if order_type == 'buy' else -STEP)
                if lower_rate < rate:
                    if order_id:
                        self.cancel_order(order_id)
                    rate = prev_rate = lower_rate
                    order_id = self.set_order(order_type, amount, rate)
                    if not order_id:
                        self.logger.debug("Обязательный ордер не выполнен. Ошибка апи!")
                        continue

            sleep(timeout)
            order = self.check_order(order_id)
            if not order:
                self.logger.info("Обязательный ордер не выполнен. Ошибка апи!")
                break
            if not order['IsOpen']:
                self.logger.info(
                    f"Обязательный ордер #{order_id} выполнен. Курс {order['Limit']}, "
                    f"значение {order['Quantity'] - order['QuantityRemaining']}, "
                    f"плата {order['Price']}"
                )
                return order

        if order_id:
            self.cancel_order(order_id)

    @stock_errors
    def cancel_order(self, order_id):
        """
        Отменяет ордер по id
        :param order_id: id ордера
        :return: True or None
        :rtype: bool
        """
        response = self.api.cancel(order_id)
        self.__get_result(response)

        self.logger.info(f"Ордер #{order_id} снят")
        return True

    @stock_errors
    def get_price(self):
        """
        Курс покупки, продажи и последней сделки с Bittrex
        :return: JSON с Bittrex
        :rtype : dict
        """
        response = self.api.get_ticker(self.pair)
        result = self.__get_result(response)
        return result

    @stock_errors
    def get_balances(self):
        """
        Возвращает курс криптовалюты
        :return: словарь курсов валют с Bittrex
        :rtype : dict
        """
        response = self.api.get_balances()
        result = self.__get_result(response)

        balances = {c['Currency']: c for c in result}
        return balances

    @stock_errors
    def set_order(self, order_type, amount, rate, pair=None):
        """
        Выставляет ордер и возвращает его id
        :param order_type: buy или sell
        :param amount: сумма ордера
        :param rate: курс
        :param pair: пара, если нужна не дефолтная
        :return: order id
        :rtype: str
        """
        if not pair:
            pair = self.pair
        if order_type == 'buy':
            response = self.api.buy_limit(pair, amount, rate)
        else:
            response = self.api.sell_limit(pair, amount, rate)
        result = self.__get_result(response)

        order_id = result['uuid']
        return order_id

    @stock_errors
    def check_order(self, order_id):
        """
        Возвращает информацию об ордере
        :param order_id: id ордера
        :return: JSON с данными об ордере
        :rtype: dict
        """
        response = self.api.get_order(order_id)
        order = self.__get_result(response)
        return order

    @stock_errors
    def get_open_orders(self):
        """
        Возвращает словарь активных ордеров, в котором ордера
        находятся в парах ключ-значение, где ключ - это тип ордера,
        значение - список ордеров
        :return: Словарь с ордерами по типам
        :rtype: dict
        """
        response = self.api.get_open_orders(self.pair)
        result = self.__get_result(response)

        orders = {
            'LIMIT_SELL': [],
            'LIMIT_BUY': []
        }
        for order in result:
            orders[order['OrderType']].append(order)
        return orders

    @stock_errors
    def get_order_book(self):
        """
        Возвращает лучшие ордера по данной паре
        :return: Словарь лучших ордеров
        :rtype: dict
        """
        response = self.api.get_orderbook(self.pair)
        result = self.__get_result(response)
        return result
