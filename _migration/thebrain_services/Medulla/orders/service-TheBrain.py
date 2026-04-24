"""
Medulla: Orders Module.
Handles position sizing and order execution logic for the Brain Stem trigger.
"""


def calculate_position_size(equity: float, risk_pct: float, stop_distance: float,
                            current_price: float, min_qty: float = 0.001) -> float:
    """
    Calculate the position size based on equity, risk percentage, and stop distance.
    
    Args:
        equity: Total account equity
        risk_pct: Fraction of equity to risk per trade (e.g., 0.02 for 2%)
        stop_distance: Distance from entry to stop loss in price units
        current_price: Current asset price
        min_qty: Minimum order quantity
    
    Returns:
        Position size in asset units
    """
    if stop_distance <= 0 or current_price <= 0:
        return min_qty
    
    risk_amount = equity * risk_pct
    qty = risk_amount / stop_distance
    return max(qty, min_qty)


def buy(client, symbol: str, qty: float, **kwargs):
    """
    Submit a buy order through the trading client.
    
    Args:
        client: Trading API client (e.g., Alpaca)
        symbol: Asset symbol
        qty: Quantity to buy
    """
    try:
        order = client.submit_order(
            symbol=symbol,
            qty=round(qty, 6),
            side="buy",
            type="market",
            time_in_force="gtc"
        )
        print(f"[ORDERS] BUY submitted: {symbol} qty={qty:.6f} order_id={order.id}")
        return order
    except Exception as e:
        # MEDU-E-P55-506: Buy order submission exception
        print(f"[MEDU-E-P55-506] ORDERS_BUY_FAILED: {symbol} qty={qty:.6f} error={e}")
        return None


def sell(client, symbol: str, qty: float, **kwargs):
    """
    Submit a sell order through the trading client.
    
    Args:
        client: Trading API client (e.g., Alpaca)
        symbol: Asset symbol
        qty: Quantity to sell
    """
    try:
        order = client.submit_order(
            symbol=symbol,
            qty=round(qty, 6),
            side="sell",
            type="market",
            time_in_force="gtc"
        )
        print(f"[ORDERS] SELL submitted: {symbol} qty={qty:.6f} order_id={order.id}")
        return order
    except Exception as e:
        # MEDU-E-P55-507: Sell order submission exception
        print(f"[MEDU-E-P55-507] ORDERS_SELL_FAILED: {symbol} qty={qty:.6f} error={e}")
        return None
