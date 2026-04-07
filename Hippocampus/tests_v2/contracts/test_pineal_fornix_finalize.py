from Hippocampus.pineal import Pineal


class _StubPond:
    def __init__(self, count=10):
        self._count = int(count)
        self.archived = 0
        self.cleared = 0

    def get_synapse_count(self):
        return self._count

    def archive_history_synapse(self, run_id: str):
        self.archived += 1
        return self._count

    def clear_history_synapse(self):
        self.cleared += 1


def test_pineal_finalize_fornix_staging_clears_only_when_consumed():
    p = Pineal()

    pond_yes = _StubPond(count=5)
    p.finalize_fornix_staging(pond_yes, consumed_by_diamond=True, run_id="r1")
    assert pond_yes.archived == 1
    assert pond_yes.cleared == 1

    pond_no = _StubPond(count=5)
    p.finalize_fornix_staging(pond_no, consumed_by_diamond=False, run_id="r2")
    assert pond_no.archived == 1
    assert pond_no.cleared == 0
