# V3.4 position management

Ordinary worker operation runs a protective task separately from discovery/allocation. It queries every durable open position, resolves metadata independently of the scanner shortlist and uses validated order books without requiring fresh candle history for a protective sale.

Persisted state includes the initial and effective stop, highest observed favorable price, trailing distance, original/remaining quantity, plan/target identities, expiry and last monitoring timestamp. Stop priority precedes time expiry, emergency/regime reduction and profit targets. Conflicting pending exits are reconciled under the account lock.

After TP1 completes, the effective stop can advance to fee-inclusive entry basis and the high-water price less a 3% trailing distance. A falling observed price cannot lower that stop. Strategy profiles select holding horizons; plans preserve their settings. Exits create a durable 30-minute symbol cooldown and a separate five-minute strategy-wide cooldown across symbols. The originating strategy is selected from actual persisted entry evidence.

Partial target fills preserve the unfilled quantity. Subsequent observations can submit a fresh intention; retrying the same observation retains its stable identity. Stop fills never advance target completion. Legacy positions lacking proven account attribution are not autonomously sold.

Historical replay assumes a stop before a target when both are touched in one candle, and uses an adverse opening price for gaps. No favorable intrabar sequence is invented.

Coverage includes actual process restart, target and stop crash rollback, trailing monotonicity, holding expiry, cooldown persistence and protective exit operation during an equity halt.
