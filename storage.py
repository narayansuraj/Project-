"""Storage abstraction for learning-resource files.

* Local mode (default): files are saved in ./uploads and referenced as  local:<name>
* Azure mode: if AZURE_STORAGE_CONNECTION_STRING is set (and the optional package
  `azure-storage-blob` is installed) files go to a PRIVATE Azure Blob container and are
  referenced as  blob:<container>/<name>.  Students never get a public URL - the app issues a
  short-lived read-only SAS link after checking the user is logged in.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.environ.get("LEARNGAP_UPLOADS", os.path.join(BASE, "uploads"))
CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER", "learning-resources")
ALLOWED_EXT = {"pdf", "doc", "docx", "ppt", "pptx", "txt", "png", "jpg", "jpeg", "mp4"}


def _ext(filename):
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""


def allowed(filename):
    return _ext(filename) in ALLOWED_EXT


def azure_enabled():
    return bool(os.environ.get("AZURE_STORAGE_CONNECTION_STRING"))


def save_upload(file_storage):
    """Save an uploaded file and return the reference string for resources.blob_url."""
    name = f"{uuid.uuid4().hex}.{_ext(file_storage.filename)}"      # random name: no path tricks
    if azure_enabled():
        from azure.storage.blob import BlobServiceClient            # optional dependency
        svc = BlobServiceClient.from_connection_string(os.environ["AZURE_STORAGE_CONNECTION_STRING"])
        svc.get_blob_client(CONTAINER, name).upload_blob(file_storage.stream, overwrite=False)
        return f"blob:{CONTAINER}/{name}"
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    file_storage.save(os.path.join(UPLOAD_DIR, name))
    return f"local:{name}"


def blob_read_url(reference, minutes=10):
    """Return a short-lived SAS URL for a blob: reference (Azure mode only)."""
    from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas
    container, name = reference[len("blob:"):].split("/", 1)
    svc = BlobServiceClient.from_connection_string(os.environ["AZURE_STORAGE_CONNECTION_STRING"])
    token = generate_blob_sas(
        account_name=svc.account_name, container_name=container, blob_name=name,
        account_key=svc.credential.account_key, permission=BlobSasPermissions(read=True),
        expiry=datetime.now(timezone.utc) + timedelta(minutes=minutes))
    return f"{svc.url}{container}/{name}?{token}"
