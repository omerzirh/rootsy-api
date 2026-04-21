import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger(__name__)

SIGNED_URL_EXPIRY = int(os.getenv("STORAGE_SIGNED_URL_EXPIRY", "3600"))  # 1 hour


def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=os.getenv("SUPABASE_S3_ENDPOINT"),
        aws_access_key_id=os.getenv("SUPABASE_S3_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("SUPABASE_S3_SECRET_ACCESS_KEY"),
        region_name=os.getenv("SUPABASE_S3_REGION", "eu-central-1"),
        config=Config(signature_version="s3v4"),
    )


BUCKET = os.getenv("SUPABASE_S3_BUCKET", "rootsybucket")


def generate_upload_url(object_key: str, content_type: str = "image/jpeg") -> str:
    """Return a pre-signed PUT URL the client can upload to directly."""
    client = _get_client()
    url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": object_key, "ContentType": content_type},
        ExpiresIn=SIGNED_URL_EXPIRY,
    )
    return url


def generate_download_url(object_key: str) -> str:
    """Return a pre-signed GET URL valid for SIGNED_URL_EXPIRY seconds."""
    client = _get_client()
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": object_key},
        ExpiresIn=SIGNED_URL_EXPIRY,
    )
    return url


def delete_object(object_key: str) -> None:
    """Delete an object from the bucket."""
    try:
        client = _get_client()
        client.delete_object(Bucket=BUCKET, Key=object_key)
    except ClientError as e:
        logger.warning(f"Failed to delete {object_key}: {e}")


def plant_photo_key(user_id: str, planting_id: str, filename: str) -> str:
    return f"plant-photos/{user_id}/{planting_id}/{filename}"


def garden_photo_key(user_id: str, garden_id: str) -> str:
    return f"garden-photos/{user_id}/{garden_id}/background.jpg"
