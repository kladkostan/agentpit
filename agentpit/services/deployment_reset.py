"""Resetting a stale deposit ledger after the chain underneath it changed.

The database outlives a disposable anvil, so after a redeploy an account
holds nothing on chain while TOTAL_DEPOSITED still carries every historical
grant and `earned` reads deeply negative. The stored deployment identity
makes the reset an edge rather than a level: `TableWrite.reset_deposits`
writes the new identity in the same statement it zeroes the ledger, so this
fires once per redeploy per account and is a no-op on every later call. (An
earlier attempt used a zero native balance instead, which is a level --
nothing on that path refunds gas, so it stayed true and re-fired, discarding
whatever had just been recorded.)

Two callers apply this rule against two different triggers:
`BalanceService.top_up`, reached only by a human who logs in and presses a
button, and `LeaderboardService.take_snapshot`, the valuation pass that
reaches every account that has traded regardless of how it authenticates --
including the API-key-only accounts that never take the first path. Both
must keep firing, which is why the rule is written once, here, and called
from both rather than transcribed twice.
"""
import psycopg

from agentpit.db.table_read import TableRead
from agentpit.db.table_write import TableWrite


def reconcile_deployment(
    conn: psycopg.Connection, user_id: str, current_deployment: str
) -> None:
    seen = TableRead.get_deployment_id(conn, user_id)
    if seen is None:
        # Predates the column: record it, but claim no knowledge of a wipe.
        TableWrite.set_deployment_id(conn, user_id, current_deployment)
    elif seen != current_deployment:
        TableWrite.reset_deposits(conn, user_id, current_deployment)
