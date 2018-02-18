import time
import csv
import traceback
from datetime import datetime
from functools import wraps

from logger import setup_logger, DEBUG
from stocks import Bittrex
# import winsound

BITTREX_KEY = 'b3d84ada73c24f4f9126f5b0a4f7427e'
BITTREX_SECRET = '45b36050b0364e7193673d0fda066794'


def get_profit():
    with open('profit.csv', "r", newline="") as file:
        reader = list(csv.reader(file))
        if reader and reader[-1]:
            return float(reader[-1][1])
        else:
            return 0


def write_profit(sum_profit):
    with open('profit.csv', "a", newline="") as file:
        profit = [str(datetime.now()), round(sum_profit, 8)]
        writer = csv.writer(file)
        writer.writerow(profit)


class StoplossError(Exception): pass
class NotEnoughBalancesError(Exception): pass
class StopBalanceError(Exception): pass


class ShotgunBot:
    FEE = .9975
    STEP = .00000001
    STOPBALANCE = .15

    def __init__(self, pair, amount, profit=0.15, stoploss_buy=.00064,
                 stoploss_sell=.00083, prf=.00087, mandatory_spread=.0025,
                 timeout=3):
        """
        :param pair: пара
        :param amount: значение ордера
        :param profit: профит при котором бот работает
        :param stoploss_buy:
        :param stoploss_sell:
        :param prf: расчетный профит
        :param mandatory_spread: спред для обязательного ордера
        :param timeout: таймаут основного цикла
        """
        self.blc_logger = setup_logger(name='Balances', log_file='blc_log.txt', level=DEBUG)
        self.logger = setup_logger(name=__class__.__name__)
        self.api = Bittrex(pair=pair, key=BITTREX_KEY, secret=BITTREX_SECRET)

        self.stoploss_buy = stoploss_buy
        self.stoploss_sell = stoploss_sell
        self.timeout = timeout
        self.mandatory_spread = mandatory_spread
        self.prf = prf

        self.pair = pair
        self.profit = profit
        self.amount = amount  # if amount else self.get_min_amount() todo: Допилить stocks

        self.all_amount = self.counter = self.sum_buy = self.sum_sell = 0
        self.base_currency, self.market_currency = self.pair.split('-')
        self.sum_profit = get_profit()

    # def get_min_amount(self):
    #     try:
    #         markets = self.api.get_markets()['result']
    #         for market in markets:
    #             if market['MarketName'] == self.pair:
    #                 min_amount = market['MinTradeSize']
    #                 break
    #         else:
    #             raise ValueError
    #
    #     except (ValueError, KeyError):
    #         self.logger.error(f'Ошибка запроса статуса маркета!')
    #         raise
    #     else:
    #         return min_amount

    def price_out(self, order_type):
        # При нехватке base
        if order_type == 'LIMIT_SELL':
            # Способ 1
            open_orders = self.api.get_open_orders()
            if not open_orders:
                return
            prices = self.api.get_price()
            if not prices:
                return
            current = prices['Ask']
            for order in open_orders[order_type]:
                if order['Limit'] == current:
                    return
            # Способ 2
            market_blc = self.api.get_balances()
            if not market_blc:
                return
            market_blc = market_blc[self.market_currency]['Available']
            if market_blc >= 2 * self.amount:
                mandatory_order = self.api.set_mandatory_order(self.amount, 'sell',
                                                               self.base_currency,
                                                               self.mandatory_spread)
                if mandatory_order:
                    self.logger.info(
                        f"Внутренний займ {self.base_currency} осуществлен. Курс "
                        f"{mandatory_order['Limit']}, количество {mandatory_order['Quantity']}"
                    )
                    return
                else:
                    self.logger.debug(f"Внутренний займ {self.base_currency} не осуществлен")
            # Способ 3
            #orders_by_type = self.api.get_open_orders()
            #if not orders_by_type:
            #    return
            #orders_by_type = orders_by_type['LIMIT_BUY']
            #bottom_order = {'Limit': 99999999}
            #for order in orders_by_type:
            #    if order['Limit'] < bottom_order['Limit']:
            #        bottom_order = order
            #uuid = bottom_order.get('OrderUuid')
            #if uuid:
            #    self.api.cancel_order(uuid)

        # При нехватке market
        elif order_type == 'LIMIT_BUY':
            # Способ 1
            open_orders = self.api.get_open_orders()
            if not open_orders:
                return
            prices = self.api.get_price()
            if not prices:
                return
            current = prices['Bid']
            for order in open_orders[order_type]:
                if order['Limit'] == current:
                    return
            # Способ 2
            base_blc = self.api.get_balances()
            if not base_blc:
                return
            base_blc = base_blc[self.base_currency]['Available']
            rate = self.api.get_price()
            if not rate:
                return
            rate = rate['Bid'] + self.STEP
            if base_blc >= 2 * self.amount * rate:
                mandatory_order = self.api.set_mandatory_order(self.amount, 'buy',
                                                               self.market_currency,
                                                               self.mandatory_spread)
                if mandatory_order:
                    self.logger.info(
                        f"Внутренний займ {self.market_currency} осуществлен. Курс "
                        f"{mandatory_order['Limit']}, количество {mandatory_order['Quantity']}"
                    )
                    return
                else:
                    self.logger.debug(f"Внутренний займ {self.market_currency} не осуществлен")
            # Способ 3
            #orders_by_type = self.api.get_open_orders()
            #if not orders_by_type:
            #    return
            #orders_by_type = orders_by_type['LIMIT_SELL']
            #bottom_order = {'Limit': 0}
            #for order in orders_by_type:
            #    if order['Limit'] > bottom_order['Limit']:
            #        bottom_order = order
            #uuid = bottom_order.get('OrderUuid')
            #if uuid:
            #    self.api.cancel_order(uuid)

        else:
            # При нехватке base и market
            pass

    def activate(self):
        prev_price_buy = prev_price_sell = 0
        sum_profit = 0

        while True:
            try:
                base_available = market_available = 0
                try:
                    ticker = self.api.get_price()
                    balances = self.api.get_balances()

                    bid = round(ticker['Bid'], 8)
                    ask = round(ticker['Ask'], 8)

                    price_buy = bid + (0 if prev_price_buy == bid else self.STEP)
                    price_sell = ask - (0 if prev_price_sell == ask else self.STEP)

                    market_available = balances[self.market_currency]['Available']
                    market_balance = balances[self.market_currency]['Balance']
                    base_available = balances[self.base_currency]['Available']
                    base_balance = balances[self.base_currency]['Balance']

                    blc_log = (
                        f"Баланс по курсу покупки {bid:.8f}: {(base_balance + market_balance * bid ):.8f}"
                        f" {self.base_currency}   "
                        #f", Расчетный {(base_balance + market_balance * self.prf):.6f}"
                        #f" {self.base_currency}"
                        #f"(всего {market_balance:.2f}  {self.market_currency} )"
                        f"(всего {base_balance:.6f}({base_available:.6f}) {self.base_currency} "
                        f"и {market_balance:.2f}({market_available:.2f}) {self.market_currency})"
                    )
                    self.logger.debug(blc_log)

                    if price_buy < self.stoploss_buy or price_sell > self.stoploss_sell:
                        raise StoplossError

                    # проверка заданного лимита баланса. Если порог лимита баланса(сумма  размещенных ордеров
                    # базовой валюты и общего баланса покупаемой валюты)  исчерпан,
                    # то происходит возврат в основной цикл. Т.е., ждем пока какие либо ордера не реализуются.
                    limit_balance = base_balance - base_available + market_balance * price_buy
                    if limit_balance > self.STOPBALANCE:
                        raise StopBalanceError

                    base_amount = self.amount * price_buy
                    if (base_available < base_amount) and (market_available < self.amount):
                        raise NotEnoughBalancesError('ALL')
                    elif base_available < base_amount:
                        raise NotEnoughBalancesError('LIMIT_SELL')
                    elif market_available < self.amount:
                        raise NotEnoughBalancesError('LIMIT_BUY')

                except NotEnoughBalancesError as E:
                    if base_available < base_amount :
                        self.logger.debug(f'Недостаточно баланса! {base_available:.8f} из {base_amount:.8f}  {self.base_currency}')
                    if  market_available <  self.amount :
                        self.logger.debug (f'Недостаточно баланса! {market_available:.2f} из {self.amount} {self.market_currency}')

                   #self.logger.debug(
                   #    f'Недостаточно баланса! {base_available:.8f} из {base_amount:.8f} '
                   #    f'{self.base_currency}; {market_available:.2f} из {self.amount} '
                   #    f'{self.market_currency}')
                    self.price_out(*E.args)
                    time.sleep(10)
                    continue
                except StoplossError:
                    self.logger.debug(
                        f'Выход за пределы диапазона! {price_buy:.8f}  -  {price_sell:.8f}')
                    time.sleep(10)
                    continue
                except StopBalanceError:
                    self.logger.debug(
                        f'Превышен лимит доступного баланса  {self.STOPBALANCE:.8f} на '
                        f'{(limit_balance - self.STOPBALANCE):.8f} {self.base_currency}')

                    time.sleep(10)
                    continue
                except (KeyError, TypeError):
                    self.logger.error(f'Ошибка АПИ!')
                    time.sleep(5)
                    continue

                spread = round((price_sell * self.FEE / price_buy * self.FEE - 1) * 100, 2)
                self.logger.debug(f'Чистый спрэд {spread}, порог профита {self.profit:.2f}')
                if self.profit < spread:

                    buy_order_id = self.api.set_order('buy', self.amount, price_buy)
                    sell_order_id = self.api.set_order('sell', self.amount, price_sell)
                    self.counter += 1

                    if buy_order_id:
                        self.logger.info(f'Создан ордер на покупку {self.amount} '
                                         f'{self.market_currency} по курсу {price_buy:.8f}')
                        prev_price_buy = price_buy
                    else:
                        self.logger.error(f'Ошибка создания ордера на покупку!')
                        continue

                    if sell_order_id:
                        self.logger.info(f'Создан ордер на продажу {self.amount} '
                                         f'{self.market_currency} по курсу {price_sell:.8f}')
                        prev_price_sell = price_sell
                    else:
                        self.logger.error(f'Ошибка создания ордера на продажу!')
                        continue

                    # winsound.Beep(frequency=100, duration=200)
                    profit = self.amount * (price_sell * self.FEE - price_buy / self.FEE)
                    self.sum_profit += profit
                    sum_profit += profit
                    write_profit(self.sum_profit)
                    time.sleep(self.timeout)

                    self.sum_buy += self.amount * price_buy
                    self.sum_sell += self.amount * price_sell
                    self.all_amount += self.amount

                    self.logger.debug(
                        f'Прибыль: расчетная по паре {profit:.8f}, общая {self.sum_profit:.8f},'
                        f' за сеанс {sum_profit:.8f}')
                    self.logger.info(
                        f'Всего: {self.counter } пар ордеров. Куплено {self.all_amount} '
                        f'{self.market_currency} на сумму {self.sum_buy:.8f} {self.base_currency}, '
                        f'Продано {self.all_amount} на сумму {self.sum_sell:.8f} {self.base_currency}')
            except:
                print(datetime.now(), traceback.format_exc())
            m = 0

if __name__ == '__main__':
    bot = ShotgunBot(pair='BTC-WAVES', amount=3, mandatory_spread=.0025)
    bot.activate()
