"""Koperta odpowiedzi ragflow (C2) — JSONResponse HTTP 200."""

from fastapi.responses import JSONResponse

from app.core.error_codes import RetCode


def ok(data: object = None) -> JSONResponse:
    """{"code":0,"message":"success","data":data} — pole data zawsze obecne."""
    return JSONResponse({"code": 0, "message": "success", "data": data})


def ok_result(data: object = None, *, total: int | None = None) -> JSONResponse:
    """Koperta bez pustych pól: data i total_datasets tylko gdy podane.

    Kolejność kluczy: code, message, data, total_datasets.
    """
    body: dict[str, object] = {"code": 0, "message": "success"}
    if data is not None:
        body["data"] = data
    if total is not None:
        body["total_datasets"] = total
    return JSONResponse(body)


def ok_true() -> JSONResponse:
    """{"code":0,"message":"success","data":true}."""
    return JSONResponse({"code": 0, "message": "success", "data": True})


def data_error(message: str) -> JSONResponse:
    """Błąd danych bez pola ``data`` (upstream ``get_data_error_result``, code 102)."""
    return JSONResponse({"code": int(RetCode.DATA_ERROR), "message": message})


def argument_error(message: str) -> JSONResponse:
    """Błąd argumentu bez pola ``data`` (upstream ``get_error_data_result``, code 101).

    Trasy OpenAI-compat wracają nim także przy HTTP 200 (K3 #3, złoto
    ``openai___chat__completions/openai_dify--10.json``).
    """
    return JSONResponse({"code": int(RetCode.ARGUMENT_ERROR), "message": message})


def server_error(message: str) -> JSONResponse:
    """Błąd serwera bez pola ``data`` (upstream ``RetCode.SERVER_ERROR``, code 500).

    Używa go upload nieobsługiwanego typu pliku (``document_api.py:705`` → komunikat
    ``<nazwa>: This type of file has not been supported yet!``, DOC:571).
    """
    return JSONResponse({"code": int(RetCode.SERVER_ERROR), "message": message})
