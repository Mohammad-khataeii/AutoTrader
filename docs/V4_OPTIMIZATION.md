# Frozen chronological optimization

`autotrader research full` acquires/resumes genuine cached history, validates
content hashes, builds completed-bar features, and evaluates a predeclared grid.
The default full study uses daily and four-hour data, six entry hypotheses and
three parameter choices. Optional `--timeframes` supports all six dataset intervals;
insufficient history produces an explicit failed run, not a manufactured result.

The first 60% of timestamps train; the next 20% validate; the final 20% test.
Twelve bars are purged before boundaries and one bar embargoes the next segment.
Maximum configured holding horizon is twelve bars. Parameters are selected only on
training results and written to a frozen file before validation or test evaluation.
Validation/test can reject a candidate; neither retunes it.

Four rolling test windows independently select among the same grid using only
their preceding training windows. Reports retain each window's dates, selected
index, costs, samples, return and drawdown. Each window starts a fresh EUR500
account; stitched capital continuity across windows is not claimed.

Validation requires positive test return and expectancy, PF>1.2, >=60 closed
positions, >=30 independent entry dates, bounded drawdown (default10%), positive
contribution from >=3 adequately sampled assets and >=2 regimes, >=3 positive
walk-forward windows, cost-stress resilience, stable training-grid performance,
positive validation return and multiple timeframes. A four-active-week block
bootstrap uses10,000 resamples and a familywise alpha adjustment for all180
default training/window search choices. Active weeks omit no-entry weeks; sparse
regimes and overlapping positions still limit inference.

Artifacts include source-file fingerprints, dataset versions/hashes, frozen
parameters, training grid results, validation/test JSON, full fills, marked equity,
drawdown, closed-position excursions, open residuals, regime/strategy contributions,
benchmarks, sensitivities and explicit failure reasons. Earlier diagnostic studies
remain in the run history. Historical holdouts were observed during engineering;
this is chronological held-out research, not a never-seen prospective trial.
