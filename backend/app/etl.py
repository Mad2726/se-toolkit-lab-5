"""ETL pipeline: fetch data from the autochecker API and load it into the database.

The autochecker dashboard API provides two endpoints:
- GET /api/items — lab/task catalog
- GET /api/logs  — anonymized check results (supports ?since= and ?limit= params)

Both require HTTP Basic Auth (email + password from settings).
"""

from datetime import datetime

import httpx
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.settings import settings


# ---------------------------------------------------------------------------
# Extract — fetch data from the autochecker API
# ---------------------------------------------------------------------------


async def fetch_items() -> list[dict]:
    """Fetch the lab/task catalog from the autochecker API."""
    url = f"{settings.autochecker_api_url}/api/items"

    async with httpx.AsyncClient(
        auth=(settings.autochecker_email, settings.autochecker_password),
        timeout=30.0,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, list):
        raise ValueError("Expected /api/items to return a list")

    return data


async def fetch_logs(since: datetime | None = None) -> list[dict]:
    """Fetch check results from the autochecker API."""
    url = f"{settings.autochecker_api_url}/api/logs"
    all_logs: list[dict] = []
    current_since = since

    async with httpx.AsyncClient(
        auth=(settings.autochecker_email, settings.autochecker_password),
        timeout=30.0,
    ) as client:
        while True:
            params = {"limit": 500}
            if current_since is not None:
                params["since"] = current_since.isoformat().replace("+00:00", "Z")

            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

            logs = payload.get("logs", [])
            has_more = payload.get("has_more", False)

            if not isinstance(logs, list):
                raise ValueError("Expected 'logs' to be a list")

            if not logs:
                break

            all_logs.extend(logs)

            if not has_more:
                break

            last_submitted_at = logs[-1]["submitted_at"]
            current_since = datetime.fromisoformat(
                last_submitted_at.replace("Z", "+00:00")
            )

    return all_logs


# ---------------------------------------------------------------------------
# Load — insert fetched data into the local database
# ---------------------------------------------------------------------------


async def load_items(items: list[dict], session: AsyncSession) -> int:
    """Load items (labs and tasks) into the database."""
    from app.models.item import ItemRecord

    created_count = 0
    lab_map: dict[str, ItemRecord] = {}

    labs = [item for item in items if item.get("type") == "lab"]
    tasks = [item for item in items if item.get("type") == "task"]

    for lab in labs:
        lab_short_id = lab["lab"]
        lab_title = lab["title"]

        result = await session.exec(
            select(ItemRecord).where(
                ItemRecord.type == "lab",
                ItemRecord.title == lab_title,
            )
        )
        existing_lab = result.first()

        if existing_lab is None:
            existing_lab = ItemRecord(
                type="lab",
                title=lab_title,
            )
            session.add(existing_lab)
            await session.flush()
            created_count += 1

        lab_map[lab_short_id] = existing_lab

    for task in tasks:
        task_title = task["title"]
        lab_short_id = task["lab"]
        parent_lab = lab_map.get(lab_short_id)

        if parent_lab is None:
            continue

        result = await session.exec(
            select(ItemRecord).where(
                ItemRecord.type == "task",
                ItemRecord.title == task_title,
                ItemRecord.parent_id == parent_lab.id,
            )
        )
        existing_task = result.first()

        if existing_task is None:
            new_task = ItemRecord(
                type="task",
                title=task_title,
                parent_id=parent_lab.id,
            )
            session.add(new_task)
            created_count += 1

    await session.commit()
    return created_count


async def load_logs(
    logs: list[dict], items_catalog: list[dict], session: AsyncSession
) -> int:
    """Load interaction logs into the database."""
    from app.models.interaction import InteractionLog
    from app.models.item import ItemRecord
    from app.models.learner import Learner

    created_count = 0

    item_title_lookup: dict[tuple[str, str | None], str] = {}
    for item in items_catalog:
        key = (item["lab"], item.get("task"))
        item_title_lookup[key] = item["title"]

    for log in logs:
        learner_result = await session.exec(
            select(Learner).where(Learner.external_id == log["student_id"])
        )
        learner = learner_result.first()

        if learner is None:
            learner = Learner(
                external_id=log["student_id"],
                student_group=log["group"],
            )
            session.add(learner)
            await session.flush()

        item_title = item_title_lookup.get((log["lab"], log.get("task")))
        if item_title is None:
            continue

        item_result = await session.exec(
            select(ItemRecord).where(ItemRecord.title == item_title)
        )
        item = item_result.first()
        if item is None:
            continue

        interaction_result = await session.exec(
            select(InteractionLog).where(InteractionLog.external_id == log["id"])
        )
        existing_interaction = interaction_result.first()

        if existing_interaction is not None:
            continue

        created_at = datetime.fromisoformat(
            log["submitted_at"].replace("Z", "+00:00")
        )

        interaction = InteractionLog(
            external_id=log["id"],
            learner_id=learner.id,
            item_id=item.id,
            kind="attempt",
            score=log["score"],
            checks_passed=log["passed"],
            checks_total=log["total"],
            created_at=created_at,
        )
        session.add(interaction)
        created_count += 1

    await session.commit()
    return created_count


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def sync(session: AsyncSession) -> dict:
    """Run the full ETL pipeline."""
    from app.models.interaction import InteractionLog

    items = await fetch_items()
    await load_items(items, session)

    result = await session.exec(select(func.max(InteractionLog.created_at)))
    last_synced_at = result.one()

    logs = await fetch_logs(since=last_synced_at)
    new_records = await load_logs(logs, items, session)

    total_result = await session.exec(select(func.count()).select_from(InteractionLog))
    total_records = total_result.one()

    return {
        "new_records": new_records,
        "total_records": total_records,
    }