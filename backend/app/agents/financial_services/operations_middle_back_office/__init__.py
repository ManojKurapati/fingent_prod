"""Operations (Middle & Back Office) group-agent — financial-services §10.

Turns front-office trade captures into confirmed, settled, reconciled records.

Orchestration is a **hybrid** pipeline (per ``claude2.md`` §10): a strict
sequential spine ``trade-support -> settlements`` — you cannot settle an
unconfirmed trade — feeding a PARALLEL reconciliation layer (``reconciliations``
‖ ``fund-accounting`` ‖ ``custody-ops`` ‖ ``collateral-mgmt``) over the settled
records. Instructing settlement moves cash/securities and is therefore a
**consequential** action: it is refused outright for an unconfirmed trade, and
otherwise routed through the guardrail engine (default-deny, human-in-the-loop).
"""
