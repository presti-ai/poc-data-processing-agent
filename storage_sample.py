from io import BytesIO

import numpy as np
import tifffile
from google.cloud import storage
from PIL import Image
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError
from retry import retry

BUCKET_NAME = "presti-tmp-test"
DESTINATION_FOLDER = "gallery"
VIDEO_FOLDER = "videos"
FILE_FOLDER = "files"

storage_client = None


# To cache the google cloud storage client
def get_storage_client() -> storage.Client:
    global storage_client
    if not storage_client:
        storage_client = storage.Client()
    return storage_client


def upload_blob_from_memory(
    bucket_name: str, contents: bytes, destination_blob_name: str, content_type: str | None = None
) -> str:
    """Uploads a file to the bucket.

    Args:
        bucket_name (str): Name of the bucket to upload to.
        contents (bytes): Contents of the file to upload.
        destination_blob_name (str): Name of the blob to upload to.
        content_type (str, optional): MIME type of the file. If unset, defaults to "text/plain" which is the default for blob.upload_from_string(...).
            When uploading images, use "image/png" or "image/jpeg".

    Returns:
        str: Public URL of the uploaded blob.
    """
    storage_client = get_storage_client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    if content_type is None:
        blob.upload_from_string(contents)
    else:
        blob.upload_from_string(contents, content_type=content_type)

    return blob.public_url


@retry(exceptions=(SSLError, RequestsConnectionError), tries=3, delay=1, backoff=2)
def upload_image(image: bytes, file_path: str, format: str | None = None) -> str:  # noqa: A002
    """Uploads an image file to Google Cloud Storage.

    Args:
        image: Bytes of the image file
        file_path: Path of the image file in the bucket
        format: Format of the image file (e.g., "png", "jpeg"). If None, content_type defaults to "image/*"
    """
    path_uploaded_image = f"{DESTINATION_FOLDER}/{file_path}"
    if format:
        content_type = f"image/{format.lower()}"
    else:
        content_type = "image/*"
    return upload_blob_from_memory(BUCKET_NAME, image, path_uploaded_image, content_type=content_type)


def upload_image_pil(
    image: Image.Image,
    file_path: str,
    format: str = "PNG",  # noqa: A002
    dpi: tuple[int, int] | None = None,
) -> str:
    buffered = BytesIO()
    if dpi:
        image.save(buffered, format=format, dpi=dpi)
    else:
        image.save(buffered, format=format)
    url = upload_image(buffered.getvalue(), file_path, format)
    return url


@retry(exceptions=(SSLError, RequestsConnectionError), tries=3, delay=1, backoff=2)
def upload_single_tiff(
    image: Image.Image,
    file_path: str,
    dpi: tuple[int, int] | None = None,
) -> str:
    """Uploads a single image as TIFF to Google Cloud Storage.

    Creates a single-page TIFF file with proper DPI metadata.
    This is compatible with Photoshop and other image editors.

    Args:
        image: PIL Image to upload (should be RGBA for transparency support)
        file_path: Path of the image file in the bucket
        dpi: Optional DPI setting for the TIFF (e.g., (300, 300))

    Returns:
        Public URL of the uploaded TIFF file
    """
    buffered = BytesIO()

    # Ensure RGBA mode for transparency
    img_rgba = image.convert("RGBA") if image.mode != "RGBA" else image
    img_array = np.array(img_rgba)

    # Prepare metadata
    resolution = None
    resolution_unit = None
    if dpi:
        resolution = (dpi[0], dpi[1])
        resolution_unit = 2  # 2 = inches in TIFF spec

    # Write single-page TIFF
    with tifffile.TiffWriter(buffered, bigtiff=False) as tif:
        tif.write(
            img_array,
            photometric="rgb",
            compression="zlib",  # DEFLATE compression, no external codec needed
            resolution=resolution,
            resolutionunit=resolution_unit,
        )

    # Upload to storage
    path_uploaded_image = f"{DESTINATION_FOLDER}/{file_path}"
    url = upload_blob_from_memory(BUCKET_NAME, buffered.getvalue(), path_uploaded_image, content_type="image/tiff")
    return url


def upload_video_from_file(video_path: str, destination_filename: str) -> str:
    """Uploads a video file to Google Cloud Storage.

    Args:
        video_path: Local path to the video file
        destination_filename: Filename for the uploaded video

    Returns:
        Public URL of the uploaded video
    """
    storage_client = get_storage_client()
    bucket = storage_client.bucket(BUCKET_NAME)

    destination_blob_name = f"{VIDEO_FOLDER}/{destination_filename}"
    blob = bucket.blob(destination_blob_name)

    with open(video_path, "rb") as video_file:
        blob.upload_from_file(video_file)

    return blob.public_url


@retry(exceptions=(SSLError, RequestsConnectionError), tries=3, delay=1, backoff=2)
def upload_video_from_bytes(
    video_bytes: BytesIO, destination_filename: str, video_format: str | None = None, folder: str = VIDEO_FOLDER
) -> str:
    """Uploads a base64-encoded video to Google Cloud Storage.

    Args:
        video_bytes: BytesIO object of the video
        destination_filename: Filename for the uploaded video
        video_format: Format of the video file (e.g., "mp4", "webm"). If None, content_type defaults to "video/*"
        folder: Folder in the bucket to upload the video to. If None, defaults to VIDEO_FOLDER

    Returns:
        Public URL of the uploaded video
    """
    path_uploaded_video = f"{folder}/{destination_filename}"
    if video_format:
        content_type = f"video/{video_format.lower()}"
    else:
        content_type = "video/*"
    return upload_blob_from_memory(BUCKET_NAME, video_bytes.getvalue(), path_uploaded_video, content_type=content_type)


@retry(exceptions=(SSLError, RequestsConnectionError), tries=3, delay=1, backoff=2)
def upload_file(file_data: bytes, file_path: str, content_type: str | None = None) -> str:
    """Uploads a generic file to the bucket.

    Args:
        file_data: Bytes of the file to upload
        file_path: Path of the file in the bucket (without folder prefix)
        content_type: Optional MIME type of the file (e.g., "model/gltf-binary" for GLB files)

    Returns:
        Public URL of the uploaded file
    """
    path_uploaded_file = f"{FILE_FOLDER}/{file_path}"
    return upload_blob_from_memory(BUCKET_NAME, file_data, path_uploaded_file, content_type=content_type)
