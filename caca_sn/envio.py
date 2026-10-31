"""Envio do relatório ao TNS pela API (`api/set/bulk-report`) e leitura da resposta
(`api/get/bulk-report-reply`). Só é chamado depois da aprovação explícita do usuário
(cli.enviar ou alertas.pedir_aprovacao); nunca sozinho."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

PRODUCAO = "https://www.wis-tns.org/api"
SANDBOX = "https://sandbox.wis-tns.org/api"
# o TNS processa o lote em segundos; 404 na resposta = ainda processando
ESPERA, TENTATIVAS = 15.0, 8


def _post(url: str, campos: dict[str, str], cfg: dict[str, Any]) -> dict[str, Any]:
    marker = "tns_marker" + json.dumps({"tns_id": cfg["bot_id"], "type": "bot", "name": cfg["bot_name"]})
    req = urllib.request.Request(url, data=urllib.parse.urlencode(campos).encode(), headers={"User-Agent": marker})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except json.JSONDecodeError:
            return {"id_code": e.code, "id_message": str(e)}


def _erros(resposta: dict[str, Any]) -> list[str]:
    """As mensagens de erro do TNS ({campo: [{message}]}), achatadas."""
    out: list[str] = []

    def andar(no: Any, caminho: str) -> None:
        if isinstance(no, dict):
            if "message" in no and isinstance(no["message"], str):
                out.append(f"{caminho}: {no['message']}")
            for k, v in no.items():
                if k != "message":
                    andar(v, f"{caminho}.{k}" if caminho else k)
        elif isinstance(no, list):
            for v in no:
                andar(v, caminho)

    andar(((resposta.get("data") or {}).get("feedback") or {}), "")
    return out


def _nome(resposta: dict[str, Any]) -> str | None:
    """Nome dado pelo TNS (ex.: '2026ahcq') na resposta do lote."""
    texto = json.dumps(resposta)
    for chave in ('"objname": "', '"objname":"'):
        i = texto.find(chave)
        if i >= 0:
            return texto[i + len(chave) :].split('"')[0]
    return None


def enviar(
    relatorio: dict[str, Any],
    cfg: dict[str, Any],
    sandbox: bool = False,
    post: Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]] = _post,
    dormir: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Envia e espera a resposta: {ok, nome, report_id, erros, resposta}."""
    base = SANDBOX if sandbox else PRODUCAO
    e = post(f"{base}/set/bulk-report", {"api_key": cfg["api_key"], "data": json.dumps(relatorio)}, cfg)
    rid = (e.get("data") or {}).get("report_id")
    if not rid:
        return {"ok": False, "nome": None, "report_id": None, "erros": [str(e.get("id_message", e))], "resposta": e}
    r: dict[str, Any] = {}
    for _ in range(TENTATIVAS):
        dormir(ESPERA)
        r = post(f"{base}/get/bulk-report-reply", {"api_key": cfg["api_key"], "report_id": str(rid)}, cfg)
        if r.get("id_code") != 404:
            break
    erros = _erros(r) if r.get("id_code") != 200 else []
    if r.get("id_code") == 404:
        erros = ["o TNS ainda não respondeu: confira depois pelo report_id"]
    return {"ok": r.get("id_code") == 200 and not erros, "nome": _nome(r), "report_id": rid, "erros": erros, "resposta": r}
