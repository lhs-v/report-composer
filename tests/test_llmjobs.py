import threading, time, unittest
from composer_lib.llm import FakeProvider, FallbackProvider, LlmError
from composer_lib.llmjobs import JobQueue
from tests.test_outline import tree_draft


class SlowFake(FakeProvider):
    def __init__(self, answers, gate):
        super().__init__(answers); self.gate = gate
    def complete(self, prompt, *, system=None):
        self.gate.wait(2); return super().complete(prompt, system=system)


class Boom:
    def complete(self, prompt, *, system=None):
        raise RuntimeError("boom")


def wait_done(q, jid, t=5):
    end = time.time() + t
    while time.time() < end:
        j = q.get(jid)
        if j["status"] in ("done", "failed", "cancelled"): return j
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def wait_running(q, jid, t=5):
    end = time.time() + t
    while time.time() < end:
        if q.get(jid)["status"] == "running": return
        time.sleep(0.01)
    raise AssertionError("job never started")


def first_claim(d):
    return next(n for n in d["nodes"].values() if n["kind"] == "claim")


class QueueTests(unittest.TestCase):
    def test_a_job_runs_in_the_background_and_caches_the_same_input(self):
        fake = FakeProvider(["다듬은 본문"])
        q = JobQueue(lambda: FallbackProvider(fake, None))
        d = tree_draft(); claim = first_claim(d)
        j = q.submit("node", d, claim["id"], "brief")
        self.assertIn(j["status"], ("queued", "running"))
        j = wait_done(q, j["id"])
        self.assertEqual((j["status"], j["result"]["value"]), ("done", "다듬은 본문"))
        self.assertEqual((j["result"]["via"], j["cached"], j["error"]), ("primary", False, None))
        self.assertEqual(j["result"]["before"], claim["text"])
        again = q.submit("node", d, claim["id"], "brief")          # cache: the fake has no answer left, yet it is done
        self.assertEqual((again["status"], again["result"]["value"], again["cached"]), ("done", "다듬은 본문", True))
        self.assertEqual(q.get(again["id"])["status"], "done")

    def test_a_failing_provider_marks_the_job_failed_with_the_reason(self):
        q = JobQueue(lambda: FallbackProvider(FakeProvider([]), None))
        d = tree_draft(); claim = first_claim(d)
        j = wait_done(q, q.submit("node", d, claim["id"], "brief")["id"])
        self.assertEqual(j["status"], "failed"); self.assertTrue(j["error"])

    def test_cancel_drops_a_queued_job_and_discards_a_running_one(self):
        gate = threading.Event()
        slow = SlowFake(["늦은 답", "둘째"], gate)
        q = JobQueue(lambda: FallbackProvider(slow, None))
        d = tree_draft(); claims = [n for n in d["nodes"].values() if n["kind"] == "claim"]
        first = q.submit("node", d, claims[0]["id"], "brief")
        second = q.submit("node", d, claims[1]["id"], "brief")
        wait_running(q, first["id"])
        self.assertTrue(q.cancel(second["id"]))                     # still queued
        self.assertTrue(q.cancel(first["id"]))                      # running: flagged
        gate.set()
        self.assertEqual(wait_done(q, first["id"])["status"], "cancelled")
        self.assertEqual(q.get(second["id"])["status"], "cancelled")
        time.sleep(0.1)                                             # the late answer must not revive the cancelled job
        self.assertEqual((q.get(first["id"])["status"], q.get(first["id"])["result"]), ("cancelled", None))
        self.assertEqual(len(slow.calls), 1)                        # the dropped second job never reached the provider
        self.assertFalse(q.cancel(first["id"])); self.assertFalse(q.cancel("nope"))

    def test_a_cancelled_running_answer_is_not_cached(self):
        gate = threading.Event()
        slow = SlowFake(["늦은 답", "새 답"], gate)
        q = JobQueue(lambda: FallbackProvider(slow, None))
        d = tree_draft(); claim = first_claim(d)
        j = q.submit("node", d, claim["id"], "brief"); wait_running(q, j["id"])
        q.cancel(j["id"]); gate.set()
        j2 = wait_done(q, q.submit("node", d, claim["id"], "brief")["id"])
        self.assertEqual((j2["status"], j2["cached"], j2["result"]["value"]), ("done", False, "새 답"))

    def test_a_rejected_answer_is_not_cached(self):
        fake = FakeProvider(["97% 달성", "92% 달성"])
        q = JobQueue(lambda: FallbackProvider(fake, None))
        d = tree_draft(); claim = first_claim(d)
        claim["text"] = "정확도 92%였다."
        j1 = wait_done(q, q.submit("node", d, claim["id"], "brief")["id"])
        self.assertEqual(j1["status"], "failed"); self.assertIn("97", j1["error"])
        j2 = wait_done(q, q.submit("node", d, claim["id"], "brief")["id"])
        self.assertEqual((j2["status"], j2["result"]["value"]), ("done", "92% 달성"))

    def test_the_worker_survives_an_unexpected_exception(self):
        box = [Boom()]
        q = JobQueue(lambda: box[0])
        d = tree_draft(); claims = [n for n in d["nodes"].values() if n["kind"] == "claim"]
        j1 = wait_done(q, q.submit("node", d, claims[0]["id"], "brief")["id"])
        self.assertEqual(j1["status"], "failed"); self.assertIn("RuntimeError", j1["error"])
        box[0] = FallbackProvider(FakeProvider(["살아 있다"]), None)
        j2 = wait_done(q, q.submit("node", d, claims[1]["id"], "brief")["id"])
        self.assertEqual((j2["status"], j2["result"]["value"]), ("done", "살아 있다"))

    def test_no_provider_fails_the_job_and_reports_not_ready(self):
        q = JobQueue(lambda: None)
        self.assertFalse(q.ready())
        d = tree_draft()
        j = wait_done(q, q.submit("node", d, first_claim(d)["id"], "brief")["id"])
        self.assertEqual(j["status"], "failed"); self.assertIn("공급자", j["error"])
        self.assertTrue(JobQueue(lambda: FallbackProvider(FakeProvider([]), None)).ready())

    def test_a_fallback_answer_says_so_and_a_bad_request_raises(self):
        q = JobQueue(lambda: FallbackProvider(FakeProvider([]), FakeProvider(["폴백 답"])))
        d = tree_draft()
        j = wait_done(q, q.submit("node", d, first_claim(d)["id"], "brief")["id"])
        self.assertEqual((j["status"], j["result"]["via"]), ("done", "fallback"))
        with self.assertRaises(ValueError):
            q.submit("poem", d, None, "brief")

    def test_only_the_latest_200_records_are_kept(self):
        fake = FakeProvider(["본문"])
        q = JobQueue(lambda: FallbackProvider(fake, None))
        d = tree_draft(); cid = first_claim(d)["id"]
        wait_done(q, q.submit("node", d, cid, "brief")["id"])
        ids = [q.submit("node", d, cid, "brief")["id"] for _ in range(210)]       # all cache hits, recorded instantly
        self.assertIsNone(q.get(ids[0])); self.assertIsNotNone(q.get(ids[-1]))


if __name__ == "__main__":
    unittest.main()
