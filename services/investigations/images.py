"""Case pictures and images added to notes: checked, resized and stored as WebP."""
import io

from .constants import NOTE_IMAGE_FORMATS, NOTE_IMAGE_MAX_PIXELS, NOTE_IMAGE_MAX_SIDE, NOTE_IMAGE_MAX_UPLOAD, PICTURE_MAX_SIDE, PICTURE_MAX_UPLOAD


def process_picture(data: bytes) -> bytes:
    """Validate an uploaded image and return a resized WebP version."""
    from PIL import Image, UnidentifiedImageError

    if len(data) > PICTURE_MAX_UPLOAD:
        raise ValueError("Picture is too large (max 10 MB)")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("Picture is not a valid image") from e

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    img.thumbnail((PICTURE_MAX_SIDE, PICTURE_MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue()


def process_note_image(data: bytes) -> bytes:
    """Decode an uploaded image and encode it again as WebP, so only pixels are ever
    stored: scripts, trailing data and metadata (EXIF, GPS) in the upload are dropped."""
    from PIL import Image, ImageOps

    if len(data) > NOTE_IMAGE_MAX_UPLOAD:
        raise ValueError("Image is too large (max 20 MB)")
    try:
        img = Image.open(io.BytesIO(data), formats=NOTE_IMAGE_FORMATS)
        width, height = img.size
        if width * height > NOTE_IMAGE_MAX_PIXELS:
            raise ValueError("Image has too many pixels (max 50 megapixels)")
        img.load()
        img = ImageOps.exif_transpose(img)
    except ValueError:
        raise
    except Image.DecompressionBombError as e:
        raise ValueError("Image has too many pixels (max 50 megapixels)") from e
    except (OSError, SyntaxError) as e:
        raise ValueError("Only PNG, JPEG, WebP, GIF and BMP images can be added") from e

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
    img.thumbnail((NOTE_IMAGE_MAX_SIDE, NOTE_IMAGE_MAX_SIDE))
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=90, method=4)
    return out.getvalue()
