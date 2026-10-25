"""Koperta SDK v0.24.0 dla tras legacy ``/api/v1/file/*`` (CONTRACT E4-5b §D2).

Upstream ``api/utils/api_utils.py`` (``get_json_result``): HTTP zawsze 200, trzy klucze
``code``/``data``/``message``, a ``message`` przy sukcesie to ``"success"``. Prezentery
kształtów sukcesu (``file_created``/``file_parent``/…) zostają w ``present/files.py``
(E4-5a); tutaj tylko koperta, wspólna dla T2 i T3.
"""

from fastapi.responses import JSONResponse


def sdk_ok(data: object) -> JSONResponse:
    """``{"code":0,"data":data,"message":"success"}`` (upstream ``get_json_result``)."""
    return JSONResponse({"code": 0, "data": data, "message": "success"})


def sdk_error(code: int, message: str, data: object = None) -> JSONResponse:
    """``{"code":code,"data":data,"message":message}`` (upstream ``get_json_result`` z kodem)."""
    return JSONResponse({"code": code, "data": data, "message": message})


def sdk_exception(err: BaseException) -> JSONResponse:
    """Koperta wyjątku: ``sdk_error(100, repr(err))`` (upstream ``server_error_response``)."""
    return sdk_error(100, repr(err))
