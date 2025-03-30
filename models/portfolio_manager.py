from typing import List, Dict, Optional
import datetime
from models.database_manager import DatabaseManager
from models.yfinance_source import YFinanceDataSource
from models.entities import Portfolio, Symbol, Transaction
from models.entities import Symbol


class PortfolioManager:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
        self.yf = YFinanceDataSource()

    def create_portfolio(self, user_id: int, name: str) -> int:
        return self.db_manager.execute_action(
            "INSERT INTO portfolios (user_id, name) VALUES (?, ?)", (user_id, name)
        )

    def get_user_portfolios(self, user_id: int) -> List[Portfolio]:
        rows = self.db_manager.execute_query(
            "SELECT portfolio_id, user_id, name FROM portfolios WHERE user_id = ?",
            (user_id,)
        )
        return [Portfolio(row[0], row[1], row[2]) for row in rows]

    def get_portfolio_symbols(self, portfolio_id: int) -> List[Symbol]:
        rows = self.db_manager.execute_query(
            "SELECT symbol_id, portfolio_id, ticker, sector FROM symbols WHERE portfolio_id = ?",
            (portfolio_id,)
        )
        symbols = []
        for row in rows:
            s = Symbol(*row)
            s.current_data = self.yf.fetch_data(s.ticker)
            s.transactions = self.get_symbol_transactions(s.symbol_id)
            symbols.append(s)
        return symbols

    def add_symbol(self, portfolio_id: int, ticker: str, sector: str) -> Optional[int]:
        exists = self.db_manager.execute_query(
            "SELECT symbol_id FROM symbols WHERE portfolio_id = ? AND ticker = ?",
            (portfolio_id, ticker)
        )
        if exists:
            return None

        return self.db_manager.execute_action(
            "INSERT INTO symbols (portfolio_id, ticker, sector) VALUES (?, ?, ?)",
            (portfolio_id, ticker, sector)
        )

    def add_transaction(self, symbol_id: int, transaction_type: str, shares: float, price: float,
                        transaction_cost: float, transaction_date: str) -> int:
        return self.db_manager.execute_action(
            "INSERT INTO transactions (symbol_id, transaction_type, shares, price, transaction_cost, transaction_date) VALUES (?, ?, ?, ?, ?, ?)",
            (symbol_id, transaction_type, shares, price, transaction_cost, transaction_date)
        )

    def get_symbol_transactions(self, symbol_id: int) -> List[Transaction]:
        rows = self.db_manager.execute_query(
            "SELECT transaction_id, symbol_id, transaction_type, shares, price, transaction_cost, transaction_date FROM transactions WHERE symbol_id = ?",
            (symbol_id,)
        )
        return [Transaction(*row) for row in rows]

    def get_symbol_by_id(self, symbol_id: int) -> Optional[Symbol]:
        row = self.db_manager.execute_query(
            "SELECT symbol_id, portfolio_id, ticker, sector FROM symbols WHERE symbol_id = ?",
            (symbol_id,)
        )

        if row:
            symbol = Symbol(*row[0])
            symbol.transactions = self.get_symbol_transactions(symbol.symbol_id)
            symbol.current_data = self.yf.fetch_data(symbol.ticker)
            return symbol
        return None

    def calculate_sector_exposure(self, portfolio_id: int) -> dict:
        symbols = self.get_portfolio_symbols(portfolio_id)
        exposure = {}

        # Calculate total portfolio value by summing symbol metrics
        total_value = 0
        symbol_metrics = {}

        for s in symbols:
            metrics = self.calculate_symbol_metrics(s)
            symbol_metrics[s.ticker] = metrics
            total_value += metrics["current_value"]

        if total_value == 0:
            return {}

        for s in symbols:
            sector = s.sector or "Unknown"
            value = symbol_metrics[s.ticker]["current_value"]
            if sector not in exposure:
                exposure[sector] = value
            else:
                exposure[sector] += value

        for sector in exposure:
            value = exposure[sector]
            exposure[sector] = {
                "value": round(value, 2),
                "percentage": round((value / total_value) * 100, 2)
            }

        return exposure

    def calculate_symbol_metrics(self, symbol):
        current_price = symbol.current_data.get("last_price",
                                                0) if symbol.current_data and "error" not in symbol.current_data else 0
        total_shares = 0
        total_investment = 0
        total_sold_amount = 0
        total_sold_shares = 0

        for txn in symbol.transactions:
            if txn.transaction_type.lower() == "buy":
                total_shares += txn.shares
                total_investment += (txn.shares * txn.price) + txn.transaction_cost
            elif txn.transaction_type.lower() == "sell":
                total_sold_shares += txn.shares
                total_sold_amount += (txn.shares * txn.price) - txn.transaction_cost

        current_shares = total_shares - total_sold_shares
        avg_cost = total_investment / total_shares if total_shares > 0 else 0

        # Realised P/L
        realised_pl = 0
        if total_sold_shares > 0:
            avg_cost_per_share = total_investment / total_shares if total_shares > 0 else 0
            realised_pl = total_sold_amount - (total_sold_shares * avg_cost_per_share)

        current_value = current_shares * current_price
        unrealised_pl = current_value - (current_shares * avg_cost)

        return {
            "ticker": symbol.ticker,
            "sector": symbol.sector,
            "current_price": current_price,
            "avg_cost": avg_cost,
            "current_shares": current_shares,
            "total_investment": total_investment,
            "realised_pl": realised_pl,
            "current_value": current_value,
            "unrealised_pl": unrealised_pl,
            "unrealised_pl_percent": (unrealised_pl / (
                        current_shares * avg_cost) * 100) if current_shares > 0 and avg_cost > 0 else 0,
            "day_change": symbol.current_data.get("change",
                                                  0) if symbol.current_data and "error" not in symbol.current_data else 0,
            "day_change_percent": symbol.current_data.get("change_percent",
                                                          0) if symbol.current_data and "error" not in symbol.current_data else 0
        }

