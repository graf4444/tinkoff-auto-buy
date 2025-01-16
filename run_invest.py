from tinkoff.invest import Client, MoneyValue, OrderType, OrderDirection
import uuid
import config

# Задайте параметры
TOKEN = config.TOKEN

SHARES = {
    "TRUR": 3000,             # ETF
    "TMOS": 3000,             # ETF
    "TDIV": 3000,             # ETF
    "TGLD": 3000,             # ETF
    "SBER": 3000,             # Акция
    "MOEX": 3000,             # Акция
    "SU26248RMFS3": 3000,     # ОФЗ
}

def money_value_to_float(money: MoneyValue) -> float:
    """Конвертация MoneyValue в float."""
    return money.units + money.nano / 1e9

def get_account_id(client: Client) -> str:
    """Получение ID первого доступного счета."""
    accounts = client.users.get_accounts().accounts
    if not accounts:
        raise RuntimeError("Нет доступных счетов")
    return accounts[0].id

def get_figi(client: Client, ticker: str) -> str:
    """Поиск FIGI для тикера среди акций, ETF и облигаций."""
    # Поиск среди акций
    instruments = client.instruments.shares()
    figi = next((share.figi for share in instruments.instruments if share.ticker == ticker), None)

    # Если не найдено, поиск среди ETF
    if not figi:
        instruments = client.instruments.etfs()
        figi = next((etf.figi for etf in instruments.instruments if etf.ticker == ticker), None)

    # Если не найдено, поиск среди облигаций
    if not figi:
        instruments = client.instruments.bonds()
        figi = next((bond.figi for bond in instruments.instruments if bond.ticker == ticker), None)

    if not figi:
        raise ValueError(f"Тикер {ticker} не найден среди акций, ETF или облигаций")
    
    return figi

def get_share_price(client: Client, figi: str) -> float:
    """Получение текущей цены акции, ETF или облигации по FIGI."""
    orderbook = client.market_data.get_order_book(figi=figi, depth=1)

    # Получаем данные о всех облигациях
    instruments = client.instruments.bonds()
    
    # Ищем облигацию по FIGI
    bond = next((b for b in instruments.instruments if b.figi == figi), None)
    
    if bond:
        # Получаем цену облигации в процентах от номинала
        price_percent = money_value_to_float(orderbook.last_price)  # Цена в процентах
        nominal_value = money_value_to_float(bond.nominal)  # Допустим номинал облигации 1000 рублей (можно взять из данных)
        
        # Рассчитываем реальную цену облигации в рублях
        real_price = (price_percent * nominal_value) / 100
        return real_price

    return money_value_to_float(orderbook.last_price)

def get_bond_nkd(client: Client, figi: str) -> float:
    """Получение НКД для облигации по FIGI."""
    instruments = client.instruments.bonds()
    bond = next((bond for bond in instruments.instruments if bond.figi == figi), None)
    if bond and bond.aci_value:
        return money_value_to_float(bond.aci_value)
    return 0.0

def get_lot_size(client: Client, ticker: str) -> int:
    """Поиск размера лота для тикера среди акций, ETF и облигаций."""
    # Поиск среди акций
    instruments = client.instruments.shares()
    lot_size = next((share.lot for share in instruments.instruments if share.ticker == ticker), None)

    # Если не найдено, поиск среди ETF
    if lot_size is None:
        instruments = client.instruments.etfs()
        lot_size = next((etf.lot for etf in instruments.instruments if etf.ticker == ticker), None)

    # Если не найдено, поиск среди облигаций
    if lot_size is None:
        instruments = client.instruments.bonds()
        lot_size = next((bond.lot for bond in instruments.instruments if bond.ticker == ticker), None)

    if lot_size is None:
        raise ValueError(f"Размер лота для тикера {ticker} не найден среди акций, ETF или облигаций")
    
    return lot_size


def buy_share(client: Client, account_id: str, figi: str, money_amount: float, ticker: str):
    """Покупка акции, ETF или облигации на заданную сумму с учетом НКД для облигаций."""
    print(ticker)

    # Получаем текущую цену бумаги
    price = get_share_price(client, figi)
    lot_size = get_lot_size(client, ticker)
    
    # Проверяем, является ли инструмент облигацией
    is_bond = any(bond.figi == figi for bond in client.instruments.bonds().instruments)

    if is_bond:
        # Если это облигация, добавляем НКД
        nkd = get_bond_nkd(client, figi)  # Получаем НКД
        price_with_nkd = price + nkd  # Добавляем НКД к цене
        print(f"Цена облигации {ticker}: {price:.2f} руб.".replace(".", ","))
        print(f"Учтен НКД: {nkd:.2f} руб.".replace(".", ","))
        print(f"Итоговая цена с учетом НКД: {price_with_nkd:.2f} руб.".replace(".", ","))

    # Рассчитываем количество лотов, которые можно купить
    lots = int(money_amount // (price * lot_size))

    if lots > 0:
        # Генерируем уникальный order_id с использованием uuid
        order_id = str(uuid.uuid4())

        # Отправляем заявку на покупку
        client.orders.post_order(
            figi=figi,
            quantity=lots,
            account_id=account_id,
            direction=OrderDirection.ORDER_DIRECTION_BUY,
            order_type=OrderType.ORDER_TYPE_MARKET,
            order_id=order_id,  # Уникальный ID заявки
        )
        spent_amount = price_with_nkd * lots * lot_size if 'SU' in ticker else price * lots * lot_size  # Сумма, потраченная на покупку
        print(f"Куплено {lots * lot_size} бумаги {ticker} на сумму {spent_amount:.2f} руб. по цене {price_with_nkd if 'SU' in ticker else price:.2f} за бумагу ({lot_size} в лоте)".replace(".", ","))
    else:
        print(f"Недостаточно средств для покупки {ticker}")


def main():
    with Client(TOKEN) as client:
        try:
            # Получаем ID счета
            account_id = get_account_id(client)
            print(f"Используемый ID счета: {account_id}")

            # Обрабатываем тикеры
            for ticker, amount in SHARES.items():
                print("----")
                try:
                    figi = get_figi(client, ticker)
                    buy_share(client, account_id, figi, amount, ticker)
                except ValueError as e:
                    print(e)
                except Exception as e:
                    print(f"Ошибка при обработке тикера {ticker}: {e}")
        except Exception as e:
            print(f"Ошибка: {e}")

if __name__ == "__main__":
    main()
