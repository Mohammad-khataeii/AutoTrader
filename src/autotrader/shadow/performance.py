"""Null-safe aggregates; undefined performance remains unavailable."""
from decimal import Decimal


def metrics(total, known, net, wins, gross_profit, gross_loss, drawdown):
    profit = Decimal(gross_profit or 0)
    loss = -Decimal(gross_loss or 0)
    complete = total == known
    return {'closed_positions': total, 'priced_closed_positions': known,
            'missing_realized_pnl': total-known,
            'win_rate': wins/known if known and complete else None,
            'profit_factor': str(profit/loss) if complete and known and loss > 0 else None,
            'profit_factor_status': ('MISSING_PNL' if not complete else 'NO_TRADES' if not total else
                                     'NO_LOSSES' if loss == 0 else 'DEFINED'),
            'expectancy': str(net/known) if known and complete and net is not None else None,
            'max_drawdown': str(drawdown) if drawdown is not None else None}
