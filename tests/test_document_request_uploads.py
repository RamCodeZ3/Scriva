import json
import unittest
from io import BytesIO
from pathlib import Path

from api.schemas.documents import AugmentDocumentRequest
from api.v1.documents import _request_with_files
from fastapi import HTTPException
from starlette.datastructures import FormData, Headers, UploadFile


class _Request:
    def __init__(
        self,
        content_type: str,
        *,
        json_body: dict | None = None,
        form: FormData | None = None,
    ) -> None:
        self.headers = Headers({"content-type": content_type})
        self._json_body = json_body
        self._form = form

    async def json(self) -> dict | None:
        return self._json_body

    async def form(self) -> FormData:
        if self._form is None:
            raise AssertionError("No form was configured.")
        return self._form


class DocumentRequestUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_json_requests(self) -> None:
        request = _Request(
            "application/json",
            json_body={"sources": ["Plain text"], "additional_notes": None},
        )

        body, cleanup = await _request_with_files(
            request, AugmentDocumentRequest
        )
        cleanup()

        self.assertEqual(body.sources, ["Plain text"])

    async def test_accepts_files_when_sources_is_empty(self) -> None:
        upload = UploadFile(
            BytesIO(b"audio-bytes"),
            filename="recording.mp3",
        )
        request = _Request(
            "multipart/form-data; boundary=test",
            form=FormData(
                [
                    ("payload", json.dumps({"sources": []})),
                    ("files", upload),
                ]
            ),
        )

        body, cleanup = await _request_with_files(
            request, AugmentDocumentRequest
        )
        uploaded_path = Path(body.sources[0])

        self.assertEqual(uploaded_path.read_bytes(), b"audio-bytes")
        cleanup()
        self.assertFalse(uploaded_path.exists())

    async def test_accepts_sources_without_files(self) -> None:
        request = _Request(
            "multipart/form-data; boundary=test",
            form=FormData(
                [("payload", json.dumps({"sources": ["Plain text"]}))]
            ),
        )

        body, cleanup = await _request_with_files(
            request, AugmentDocumentRequest
        )
        cleanup()

        self.assertEqual(body.sources, ["Plain text"])

    async def test_rejects_request_without_sources_or_files(self) -> None:
        request = _Request(
            "multipart/form-data; boundary=test",
            form=FormData([("payload", json.dumps({"sources": []}))]),
        )

        with self.assertRaises(HTTPException) as context:
            await _request_with_files(request, AugmentDocumentRequest)

        self.assertEqual(context.exception.status_code, 422)

    async def test_adds_uploaded_files_and_removes_them_on_cleanup(
        self,
    ) -> None:
        upload = UploadFile(
            BytesIO(b"audio-bytes"),
            filename="recording.mp3",
        )
        form = FormData(
            [
                ("payload", json.dumps({"sources": ["Plain text"]})),
                ("files", upload),
            ]
        )
        request = _Request(
            "multipart/form-data; boundary=test",
            form=form,
        )

        body, cleanup = await _request_with_files(
            request, AugmentDocumentRequest
        )
        uploaded_path = Path(body.sources[-1])

        self.assertEqual(body.sources[0], "Plain text")
        self.assertEqual(uploaded_path.suffix, ".mp3")
        self.assertEqual(uploaded_path.read_bytes(), b"audio-bytes")

        cleanup()

        self.assertFalse(uploaded_path.exists())


if __name__ == "__main__":
    unittest.main()
