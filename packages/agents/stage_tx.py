"""Transaction hygiene for pipeline stages that call the LLM.

Every fan-out stage (routing, contract, corporate, corporate-intro, tax,
financial) used to do its bookkeeping — delete the previous outputs, open
the ``AgentRun`` — and then hold that transaction open across the whole LLM
phase. On a real data room that phase runs for many minutes (925 s for 66
contracts) while *nothing* travels on the database connection, so the
managed Postgres proxy closes it as idle and the first write afterwards
fails with ``SSL connection has been closed unexpectedly``. The stage is
then rolled back and every minute of LLM work is lost.

The contract is now:

1. Open the running ``AgentRun`` (only bookkeeping, no output deletes).
2. Read the inputs and copy the values the workers need into plain Python
   objects — after the commit below the ORM instances are expired and must
   not be touched from worker threads.
3. :func:`release_connection_before_llm` — commits the bookkeeping and hands
   the connection back to the pool. The running row also becomes visible to
   the progress stream, so the UI shows the live stage instead of the
   previous run's rows.
4. Fan out the LLM work with no transaction open.
5. In a fresh transaction (started implicitly by the next query): delete
   the previous outputs, persist the new ones, mark the run completed. The
   orchestrator commits; a failure rolls this whole phase back, so the
   previous run's results survive exactly as before.
"""

from __future__ import annotations

from sqlalchemy.orm import Session


def release_connection_before_llm(db: Session) -> None:
    """Commit the stage's bookkeeping and return the DB connection to the pool.

    Call it right before the LLM fan-out, once the running ``AgentRun`` has
    been flushed and the inputs have been copied out of the ORM. Only
    bookkeeping may be pending at this point — output deletes belong to the
    persistence phase so that a failed stage still rolls them back.
    """
    db.commit()
