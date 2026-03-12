"""Router for analytics endpoints (Task 2).

Each endpoint performs SQL aggregation queries on the interaction data
populated by the ETL pipeline. All endpoints require a `lab` query
parameter to filter results by lab (e.g., "lab-01").
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models.item import ItemRecord
from app.models.learner import Learner
from app.models.interaction import InteractionLog

router = APIRouter()


def _lab_title_from_slug(lab: str) -> str:
    # "lab-04" -> "Lab 04"
    return lab.replace("lab-", "Lab ")


async def _get_lab_and_task_ids(session: AsyncSession, lab: str) -> tuple[ItemRecord | None, list[int]]:
    lab_title = _lab_title_from_slug(lab)

    lab_item = (
        await session.exec(
            select(ItemRecord).where(ItemRecord.title.contains(lab_title))
        )
    ).first()

    if not lab_item:
        return None, []

    task_ids = list(
        (
            await session.exec(
                select(ItemRecord.id).where(ItemRecord.parent_id == lab_item.id)
            )
        ).all()
    )

    return lab_item, task_ids


@router.get("/scores")
async def get_scores(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Score distribution histogram for a given lab."""
    _, task_ids = await _get_lab_and_task_ids(session, lab)

    buckets_template = ["0-25", "26-50", "51-75", "76-100"]

    if not task_ids:
        return [{"bucket": bucket, "count": 0} for bucket in buckets_template]

    bucket_case = case(
        (InteractionLog.score <= 25, "0-25"),
        (InteractionLog.score <= 50, "26-50"),
        (InteractionLog.score <= 75, "51-75"),
        else_="76-100",
    )

    rows = (
        await session.exec(
            select(
                bucket_case.label("bucket"),
                func.count().label("count"),
            )
            .where(
                InteractionLog.item_id.in_(task_ids),
                InteractionLog.score.is_not(None),
            )
            .group_by(bucket_case)
        )
    ).all()

    counts = {bucket: 0 for bucket in buckets_template}
    for row in rows:
        counts[row.bucket] = row.count

    return [{"bucket": bucket, "count": counts[bucket]} for bucket in buckets_template]


@router.get("/pass-rates")
async def get_pass_rates(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-task pass rates for a given lab."""
    _, task_ids = await _get_lab_and_task_ids(session, lab)

    if not task_ids:
        return []

    rows = (
        await session.exec(
            select(
                ItemRecord.title.label("task"),
                func.round(func.avg(InteractionLog.score), 1).label("avg_score"),
                func.count().label("attempts"),
            )
            .join(InteractionLog, InteractionLog.item_id == ItemRecord.id)
            .where(
                ItemRecord.id.in_(task_ids),
                InteractionLog.score.is_not(None),
            )
            .group_by(ItemRecord.id, ItemRecord.title)
            .order_by(ItemRecord.title)
        )
    ).all()

    return [
        {
            "task": row.task,
            "avg_score": float(row.avg_score) if row.avg_score is not None else None,
            "attempts": row.attempts,
        }
        for row in rows
    ]


@router.get("/timeline")
async def get_timeline(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Submissions per day for a given lab."""
    _, task_ids = await _get_lab_and_task_ids(session, lab)

    if not task_ids:
        return []

    date_expr = func.date(InteractionLog.created_at)

    rows = (
        await session.exec(
            select(
                date_expr.label("date"),
                func.count().label("submissions"),
            )
            .where(InteractionLog.item_id.in_(task_ids))
            .group_by(date_expr)
            .order_by(date_expr)
        )
    ).all()

    return [{"date": row.date, "submissions": row.submissions} for row in rows]


@router.get("/groups")
async def get_groups(
    lab: str = Query(..., description="Lab identifier, e.g. 'lab-01'"),
    session: AsyncSession = Depends(get_session),
):
    """Per-group performance for a given lab."""
    _, task_ids = await _get_lab_and_task_ids(session, lab)

    if not task_ids:
        return []

    rows = (
        await session.exec(
            select(
                Learner.student_group.label("group"),
                func.round(func.avg(InteractionLog.score), 1).label("avg_score"),
                func.count(func.distinct(InteractionLog.learner_id)).label("students"),
            )
            .join(Learner, Learner.id == InteractionLog.learner_id)
            .where(
                InteractionLog.item_id.in_(task_ids),
                InteractionLog.score.is_not(None),
            )
            .group_by(Learner.student_group)
            .order_by(Learner.student_group)
        )
    ).all()

    return [
        {
            "group": row.group,
            "avg_score": float(row.avg_score) if row.avg_score is not None else None,
            "students": row.students,
        }
        for row in rows
    ]