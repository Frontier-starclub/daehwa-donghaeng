import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.dependencies import CurrentUser, DbSession
from app.errors import AppError
from app.models import DurCheck, DurWarning, Medication, MedicationScan
from app.providers import MedicationForCheck, dur_provider, ocr_provider
from app.schemas import (
    DurCheckIn,
    DurCheckOut,
    MedicationBatchIn,
    MedicationDraft,
    MedicationOut,
    MedicationScanOut,
    MedicationUpdateIn,
)

router = APIRouter(prefix="/api/v1", tags=["medications"])
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}


def owned_medication(db: DbSession, user_id: uuid.UUID, medication_id: uuid.UUID) -> Medication:
    medication = db.scalar(
        select(Medication).where(
            Medication.id == medication_id, Medication.user_id == user_id
        )
    )
    if medication is None:
        raise AppError(404, "MEDICATION_NOT_FOUND", "약 정보를 찾을 수 없습니다.")
    return medication


@router.post("/medication-scans", response_model=MedicationScanOut)
async def scan_medication(
    user: CurrentUser,
    db: DbSession,
    image: Annotated[UploadFile, File()],
    scenario: Annotated[
        Literal["success", "empty", "failure"], Query()
    ] = "success",
) -> MedicationScanOut:
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise AppError(415, "UNSUPPORTED_IMAGE", "JPEG 또는 PNG 이미지만 사용할 수 있습니다.")
    contents = await image.read(MAX_IMAGE_BYTES + 1)
    if len(contents) > MAX_IMAGE_BYTES:
        raise AppError(413, "IMAGE_TOO_LARGE", "이미지는 10MiB 이하여야 합니다.")

    scan = MedicationScan(
        user_id=user.id,
        status="success",
        provider=ocr_provider.name,
        scenario=scenario,
    )
    db.add(scan)
    try:
        recognized = ocr_provider.recognize(contents, scenario)
    except RuntimeError:
        scan.status = "failed"
        scan.error_code = "OCR_PROVIDER_ERROR"
        db.commit()
        raise AppError(
            502, "OCR_PROVIDER_ERROR", "약봉투를 읽지 못했습니다. 다시 시도해주세요."
        ) from None

    items = [MedicationDraft(**asdict(item)) for item in recognized]
    scan.result_json = [item.model_dump(mode="json") for item in items]
    if not items:
        scan.status = "empty"
        db.commit()
        raise AppError(422, "OCR_EMPTY", "인식된 약이 없습니다. 다시 촬영하거나 직접 입력해주세요.")

    db.commit()
    db.refresh(scan)
    return MedicationScanOut(
        id=scan.id,
        status=scan.status,
        provider=scan.provider,
        items=items,
        created_at=scan.created_at,
    )


@router.post("/medications/batch", response_model=list[MedicationOut], status_code=201)
def confirm_medications(
    payload: MedicationBatchIn, user: CurrentUser, db: DbSession
) -> list[Medication]:
    source = "manual"
    if payload.scan_id is not None:
        scan = db.scalar(
            select(MedicationScan).where(
                MedicationScan.id == payload.scan_id,
                MedicationScan.user_id == user.id,
            )
        )
        if scan is None:
            raise AppError(404, "SCAN_NOT_FOUND", "OCR 요청을 찾을 수 없습니다.")
        if scan.status != "success":
            raise AppError(409, "SCAN_NOT_CONFIRMABLE", "성공한 OCR 결과만 확정할 수 있습니다.")
        source = "ocr"

    medications = [
        Medication(
            user_id=user.id,
            name=item.name,
            ingredient_name=item.ingredient_name,
            ingredient_code=item.ingredient_code,
            item_seq=item.item_seq,
            dose_frequency_per_day=item.dose_frequency_per_day,
            source=source,
        )
        for item in payload.items
    ]
    db.add_all(medications)
    db.commit()
    for medication in medications:
        db.refresh(medication)
    return medications


@router.get("/medications", response_model=list[MedicationOut])
def list_medications(
    user: CurrentUser,
    db: DbSession,
    status: Literal["active", "ended", "all"] = Query(default="active"),
) -> list[Medication]:
    statement = select(Medication).where(Medication.user_id == user.id)
    if status != "all":
        statement = statement.where(Medication.status == status)
    return list(db.scalars(statement.order_by(Medication.confirmed_at.desc())))


@router.patch("/medications/{medication_id}", response_model=MedicationOut)
def update_medication(
    medication_id: uuid.UUID,
    payload: MedicationUpdateIn,
    user: CurrentUser,
    db: DbSession,
) -> Medication:
    medication = owned_medication(db, user.id, medication_id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(medication, key, value)
    if payload.status == "ended":
        medication.ended_at = datetime.now(UTC)
    elif payload.status == "active":
        medication.ended_at = None
    db.commit()
    db.refresh(medication)
    return medication


@router.post("/dur-checks", response_model=DurCheckOut, status_code=201)
def create_dur_check(
    payload: DurCheckIn,
    user: CurrentUser,
    db: DbSession,
    scenario: Literal["none", "warning", "failure"] = Query(default="none"),
) -> DurCheck:
    medications = list(
        db.scalars(
            select(Medication).where(
                Medication.user_id == user.id, Medication.status == "active"
            )
        )
    )
    if payload.medication_ids:
        owned_ids = {medication.id for medication in medications}
        missing = set(payload.medication_ids) - owned_ids
        if missing:
            raise AppError(
                404,
                "MEDICATION_NOT_FOUND",
                "선택한 약 중 현재 사용자의 활성 약이 아닌 항목이 있습니다.",
                [str(item) for item in sorted(missing, key=str)],
            )
    if not medications:
        raise AppError(409, "NO_ACTIVE_MEDICATIONS", "먼저 약을 등록해주세요.")

    provider_items = [
        MedicationForCheck(
            id=str(item.id),
            name=item.name,
            ingredient_code=item.ingredient_code,
            item_seq=item.item_seq,
        )
        for item in medications
    ]
    snapshot = [
        {"id": item.id, "name": item.name, "item_seq": item.item_seq}
        for item in provider_items
    ]
    check = DurCheck(
        user_id=user.id,
        status="no_warnings",
        provider=dur_provider.name,
        medication_snapshot=snapshot,
    )
    db.add(check)
    db.flush()
    try:
        provider_warnings = dur_provider.check(provider_items, scenario)
    except RuntimeError:
        check.status = "failed"
        check.error_code = "DUR_PROVIDER_ERROR"
        db.commit()
        raise AppError(
            502,
            "DUR_PROVIDER_ERROR",
            "주의사항을 확인하지 못했습니다. 나중에 다시 시도해주세요.",
        ) from None

    check.status = "warnings" if provider_warnings else "no_warnings"
    for item in provider_warnings:
        check.warnings.append(
            DurWarning(
                warning_type=item.warning_type,
                medication_ids=item.medication_ids,
                message=item.message,
                source_code=item.source_code,
            )
        )
    db.commit()
    return db.scalar(
        select(DurCheck)
        .options(selectinload(DurCheck.warnings))
        .where(DurCheck.id == check.id)
    )


@router.get("/dur-checks/{check_id}", response_model=DurCheckOut)
def get_dur_check(check_id: uuid.UUID, user: CurrentUser, db: DbSession) -> DurCheck:
    check = db.scalar(
        select(DurCheck)
        .options(selectinload(DurCheck.warnings))
        .where(DurCheck.id == check_id, DurCheck.user_id == user.id)
    )
    if check is None:
        raise AppError(404, "DUR_CHECK_NOT_FOUND", "조회 결과를 찾을 수 없습니다.")
    return check
