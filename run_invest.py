import argparse
import uuid
import config
import time
from tinkoff.invest import Client, MoneyValue, OrderType, OrderDirection

# Задайте параметры
TOKEN = config.TOKEN  # Токен для доступа к API
DEFAULT_DISCOUNT = 3  # Дефолтная скидка в процентах

# Список ценных бумаг и параметры заявок
# - "amount": сумма, на которую планируется покупка данного инструмента.
# - "discount": процентная скидка от текущей рыночной цены для покупки. Если параметр не указан, используется дефолтная скидка DEFAULT_DISCOUNT.
# - "discount_price": фиксированная цена для покупки бумаги, игнорируя рыночную цену и скидку.
# 
# В зависимости от наличия скидки или фиксированной цены, будет рассчитана цена, по которой выставляется заявка.
SHARES = {
    "TRUR": {"amount": 3000, "discount_price": 8.6},
    "TMOS": {"amount": 3000},
    "TDIV": {"amount": 3000, "discount_price": 10},
    "TGLD": {"amount": 3000, "discount": 2},
    "SBER": {"amount": 3000, "discount_price": 302},
    "MOEX": {"amount": 3000, "discount_price": 197},
    "SU26248RMFS3": {"amount": 3000, "discount_price": 831},
}

def money_value_to_float(money: MoneyValue) -> float:
    """
    Конвертирует MoneyValue в float.
    """
    return round(money.units + money.nano / 1e9, 2)

def get_account_id(client: Client) -> str:
    """
    Получает первый доступный торговый счет пользователя.
    """
    accounts = client.users.get_accounts().accounts
    if not accounts:
        raise RuntimeError("🚨 Нет доступных счетов!")
    return accounts[0].id

def get_figi(client: Client, ticker: str) -> str:
    """
    Получает FIGI инструмента по его тикеру.
    """
    for method in [client.instruments.shares, client.instruments.etfs, client.instruments.bonds]:
        instruments = method().instruments
        figi = next((instr.figi for instr in instruments if instr.ticker == ticker), None)
        if figi:
            return figi
    raise ValueError(f"❌ Тикер {ticker} не найден!")

def get_share_price(client: Client, figi: str) -> float:
    """
    Получает текущую рыночную цену инструмента по его FIGI.
    """
    orderbook = client.market_data.get_order_book(figi=figi, depth=1)
    instruments = client.instruments.bonds()
    bond = next((b for b in instruments.instruments if b.figi == figi), None)
    if bond:
        price_percent = money_value_to_float(orderbook.last_price)
        nominal_value = money_value_to_float(bond.nominal)
        return round((price_percent * nominal_value) / 100, 2)
    return round(money_value_to_float(orderbook.last_price), 2)

def get_lot_size(client: Client, ticker: str) -> int:
    """
    Получает размер лота инструмента по тикеру.
    """
    for method in [client.instruments.shares, client.instruments.etfs, client.instruments.bonds]:
        instruments = method().instruments
        lot_size = next((instr.lot for instr in instruments if instr.ticker == ticker), None)
        if lot_size:
            return lot_size
    raise ValueError(f"⚠️ Лот для {ticker} не найден!")

def place_limit_order(client: Client, account_id: str, figi: str, money_amount: float, ticker: str, params: dict):
    """
    Выставляет лимитную заявку на покупку.
    """
    price = get_share_price(client, figi)
    lot_size = get_lot_size(client, ticker)
    
    discount = params.get("discount", DEFAULT_DISCOUNT)
    discount_price = params.get("discount_price")
    
    limit_price = discount_price if discount_price else round(price * (1 - discount / 100), 2)
    
    lots = int(money_amount // (limit_price * lot_size))
    
    if lots > 0:
        planned_total_cost = lots * lot_size * limit_price
        print(f"🔍 Планируется выставить заявку на покупку:")
        print(f"  Тикер: {ticker}")
        print(f"  Количество бумаг: {lots * lot_size}")
        print(f"  Цена за бумагу: {str(limit_price).replace('.', ',')} руб.")
        print(f"  Общая сумма заявки: {str(planned_total_cost).replace('.', ',')} руб.")
        print(f"  Текущая цена: {str(price).replace('.', ',')} руб.")
        print(f"  Скидка: {discount}%")

        order_id = str(uuid.uuid4())
        client.orders.post_order(
            figi=figi,
            quantity=lots,
            account_id=account_id,
            direction=OrderDirection.ORDER_DIRECTION_BUY,
            order_type=OrderType.ORDER_TYPE_LIMIT,
            order_id=order_id,
            price=MoneyValue(units=int(limit_price), nano=int((limit_price % 1) * 1e9)),
        )

        print(f"✅ Заявка на {lots * lot_size} бумаг {ticker} по {str(limit_price).replace('.', ',')} руб. выставлена. "
              f"(Текущая цена: {str(price).replace('.', ',')} руб.). Сумма: {str(lots * lot_size * limit_price).replace('.', ',')} руб.")

    else:
        print(f"❌ Недостаточно средств для заявки {ticker}")

def cancel_orders(client: Client, account_id: str):
    orders = client.orders.get_orders(account_id=account_id).orders
    for order in orders:
        try:
            client.orders.cancel_order(account_id=account_id, order_id=order.order_id)
            print(f"🛑 Отменена заявка {order.order_id}")
        except Exception as e:
            print(f"⚠️ Не удалось отменить заявку {order.order_id}: {e}")


def buy_share(client: Client, account_id: str, figi: str, money_amount: float, ticker: str):
    """
    Совершает рыночную покупку инструмента и сразу получает реальную цену,
    если она доступна в ответе post_order(). В противном случае ждет обновления портфеля.
    """
    lot_size = get_lot_size(client, ticker)
    price = get_share_price(client, figi)
    lots = int(money_amount // (price * lot_size))

    if lots > 0:
        order_id = str(uuid.uuid4())
        order_response = client.orders.post_order(
            figi=figi,
            quantity=lots,
            account_id=account_id,
            direction=OrderDirection.ORDER_DIRECTION_BUY,
            order_type=OrderType.ORDER_TYPE_MARKET,
            order_id=order_id,
        )

        total_price = lots * lot_size * price
        print(f"✅ Заявка на {lots * lot_size} бумаг {ticker} по {str(price).replace('.', ',')} руб. выставлена. "
              f"(Текущая цена: {str(price).replace('.', ',')} руб.). Сумма: {str(total_price).replace('.', ',')} руб.")


        real_price = None
        if order_response.executed_order_price:
            real_price = money_value_to_float(order_response.executed_order_price)
            print(f"💰 Фактическая цена покупки {ticker}: {str(real_price).replace('.', ',')} руб.")
            return

        for attempt in range(5):
            time.sleep(1)
            
            positions = client.operations.get_portfolio(account_id=account_id).positions
            for position in positions:
                if position.figi == figi and position.average_position_price:
                    real_price = money_value_to_float(position.average_position_price)
                    break

            if real_price:
                break

        if real_price:
            print(f"💰 Фактическая цена покупки {ticker}: {real_price:.2f} руб.")
        else:
            print(f"⚠️ Не удалось получить фактическую цену покупки {ticker}, API не успел обновить данные.")
    else:
        print(f"❌ Недостаточно средств для покупки {ticker}")



def main():
    """
    Основная функция: выбирает режим работы и выполняет соответствующие операции.
    """
    parser = argparse.ArgumentParser(description="Скрипт для торговли на Tinkoff API.",formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-m", "--mode", type=int, choices=[1, 2, 3], required=True,
                        help="Режим работы:\n"
                            "1 - Выставление заявок ниже текущих цен,\n"
                            "2 - Отмена всех заявок, "
                            "3 - Покупка по рынку")
    args = parser.parse_args()
    
    with Client(TOKEN) as client:
        account_id = get_account_id(client)
        print(f"📌 Используемый ID счета: {account_id}")
        
        if args.mode == 1:
            print("\n🚀 --- Выставление заявок ---")
            for ticker, params in SHARES.items():
                try:
                    figi = get_figi(client, ticker)
                    place_limit_order(client, account_id, figi, params["amount"], ticker, params)
                except Exception as e:
                    print(f"❌ Ошибка при обработке {ticker}: {e}")

        elif args.mode == 2:
            print("\n⛔ --- Отмена всех заявок ---")
            cancel_orders(client, account_id)

        elif args.mode == 3:
            print("\n💸 --- Покупка по текущей цене ---")
            for ticker, params in SHARES.items():
                try:
                    figi = get_figi(client, ticker)
                    buy_share(client, account_id, figi, params["amount"], ticker)
                except Exception as e:
                    print(f"❌ Ошибка при покупке {ticker}: {e}")

if __name__ == "__main__":
    main()
