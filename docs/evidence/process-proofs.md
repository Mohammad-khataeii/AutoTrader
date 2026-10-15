# Actual process proof output

Earlier Windows launcher-only results are invalid as restart evidence. These outputs use the corrected actual-interpreter/kernel-termination harness.

## Windows full regression

```text
..............................PROOF_A actual interpreter killed pid=28656; restarted actual pid=20656; TP=[3,4,0]; reconciliation=[]
.PROOF_B actual worker killed=24100; replacement=24316; API equity=480 risk=RISK_HALTED
...........PROOF_C actual API pid=4408; actual worker restart 10652->29844; fills=4; targets=[2.256860850000,3.009147800000,0]; journal replay=[]
......................................
80 passed in 407.24s (0:06:47)
```

## Linux installed-runtime regression

```text
..............................PROOF_A actual interpreter killed pid=81; restarted actual pid=84; TP=[3,4,0]; reconciliation=[]
.PROOF_B actual worker killed=98; replacement=101; API equity=480 risk=RISK_HALTED
...........PROOF_C actual API pid=183; actual worker restart 184->193; fills=4; targets=[2.256860850000,3.009147800000,0]; journal replay=[]
......................................
80 passed in 341.53s (0:05:41)
```
