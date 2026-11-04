"""Separate entry freshness from protective execution availability."""
from autotrader.domain import utc_now
from autotrader.persistence.accounting import aware

POLICY = {'version': '4.9.9-entry-freshness.1', 'maximum_entry_book_age_seconds': 20,
          'future_tolerance_seconds': 2, 'protective_exit_max_age_seconds': 90,
          'stale_entry_action': 'DEFER_UNTIL_FRESH_OBSERVATION',
          'exit_policy': 'Existing protective path; never gated by entry freshness'}


def entry_freshness(book, now=None):
    age = ((now or utc_now())-aware(book.timestamp)).total_seconds()
    qualified = -POLICY['future_tolerance_seconds'] <= age <= POLICY['maximum_entry_book_age_seconds']
    return {'policy': POLICY, 'book_at': book.timestamp.isoformat(), 'book_age_seconds': age,
            'entry_qualified': qualified, 'freshness': 'FRESH' if qualified else 'FUTURE' if age < 0 else 'STALE',
            'reason': None if qualified else 'personal_entry_quote_stale_or_future',
            'protective_exit_qualified': None}
