import logging
from collections.abc import Callable

from apscheduler.schedulers.blocking import BlockingScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from backend.api.main import COLLECTORS
from backend.app.db import get_session_factory
from backend.normalize.dedupe import dedupe_organizations
from backend.scoring.engine import score_all_organizations

logger = logging.getLogger(__name__)


def run_collector_job(collector_name: str) -> None:
    """Run one collector. Failures are logged and do not raise."""
    try:
        collector_cls = COLLECTORS[collector_name]
        collector_cls().run()
    except Exception:
        logger.exception(
            "Collector %s failed; remaining scheduled jobs continue",
            collector_name,
        )


def run_post_collect() -> None:
    try:
        factory = get_session_factory()
        with factory() as session:
            dedupe_organizations(session)
            score_all_organizations(session)
    except Exception:
        logger.exception("Normalize/score job failed; remaining scheduled jobs continue")


def run_full_pipeline() -> None:
    for name in COLLECTORS:
        run_collector_job(name)
    run_post_collect()


def _wrapped(job: Callable[[], None], label: str) -> Callable[[], None]:
    def inner() -> None:
        try:
            job()
        except Exception:
            logger.exception("%s failed; remaining scheduled jobs continue", label)

    inner.__name__ = label
    return inner


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler()
    scheduler.add_job(
        _wrapped(lambda: run_collector_job("nonprofit_990"), "nonprofit_990"),
        CronTrigger(day=1, hour=3, minute=0),
        id="nonprofit_990",
        replace_existing=True,
    )
    scheduler.add_job(
        _wrapped(lambda: run_collector_job("policy_monitor"), "policy_monitor"),
        CronTrigger(hour=4, minute=0),
        id="policy_monitor",
        replace_existing=True,
    )
    scheduler.add_job(
        _wrapped(lambda: run_collector_job("youth_orgs"), "youth_orgs"),
        CronTrigger(month="1,4,7,10", day=1, hour=5, minute=0),
        id="youth_orgs",
        replace_existing=True,
    )
    scheduler.add_job(
        _wrapped(lambda: run_collector_job("sponsor_logos"), "sponsor_logos"),
        CronTrigger(month="1,4,7,10", day=2, hour=5, minute=0),
        id="sponsor_logos",
        replace_existing=True,
    )
    scheduler.add_job(
        _wrapped(lambda: run_collector_job("staff_directory"), "staff_directory"),
        CronTrigger(day=1, hour=6, minute=0),
        id="staff_directory",
        replace_existing=True,
    )
    scheduler.add_job(
        _wrapped(run_post_collect, "post_collect"),
        CronTrigger(hour=7, minute=0),
        id="post_collect",
        replace_existing=True,
    )
    return scheduler


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Running full pipeline once, then starting the scheduler")
    run_full_pipeline()
    scheduler = build_scheduler()
    scheduler.start()


if __name__ == "__main__":
    main()
