from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from app.core.errors import NotFoundError
from app.services.storage import Storage


@pytest.fixture
def storage() -> Iterator[Storage]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        yield Storage(client, "test-bucket")


async def test_put_get_roundtrip(storage: Storage) -> None:
    await storage.ensure_bucket()
    await storage.ensure_bucket()  # idempotent
    key = await storage.put("dms/PRJ-26-001/a.pdf", b"%PDF-1.7", "application/pdf")
    obj = await storage.get(key)
    assert obj.data == b"%PDF-1.7"
    assert obj.content_type == "application/pdf"
    assert "dms/PRJ-26-001/a.pdf" in await storage.presigned_url(key)


async def test_missing_key(storage: Storage) -> None:
    await storage.ensure_bucket()
    with pytest.raises(NotFoundError) as err:
        await storage.get("nope")
    assert err.value.code == "FILE_NOT_FOUND"
