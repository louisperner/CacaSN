"""Cliente da API "get" do TNS que respeita o limite de pedidos (30 por minuto por bot, em 2026-11).

Lê `x-rate-limit-remaining` / `x-rate-limit-reset` de cada resposta: quando sobram poucos pedidos,
espera o reset antes do próximo; num 429, espera o reset e tenta de novo. Sem isso o acompanhamento
(um pedido por descoberta, 34 em 2026-11) esgotava a cota e as novidades do dia levavam 429 em toda rodada.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

BASE = "https://www.wis-tns.org/api/get/"
FOLGA = 2  # pedidos que sobram antes de esperar o reset
ESPERA_MAX = 90.0  # s
TENTATIVAS = 3

_trava = threading.Lock()
_pausa_ate = 0.0


def marker(cfg: dict[str, Any]) -> str:
    return "tns_marker" + json.dumps({"tns_id": cfg["bot_id"], "type": "bot", "name": cfg["bot_name"]})


def _reset(headers: Any, padrao: float) -> float:
    try:
        return min(float(headers.get("x-rate-limit-reset", padrao)), ESPERA_MAX)
    except (TypeError, ValueError):
        return padrao


def pedir(
    cfg: dict[str, Any],
    rota: str,
    dados: dict[str, Any],
    abrir: Callable[..., Any] = urllib.request.urlopen,
    dormir: Callable[[float], None] = time.sleep,
    agora: Callable[[], float] = time.monotonic,
) -> Any:
    """`data` da resposta de api/get/<rota>."""
    global _pausa_ate
    corpo = urllib.parse.urlencode({"api_key": cfg["api_key"], "data": json.dumps(dados)}).encode()
    for tentativa in range(TENTATIVAS):
        with _trava:
            falta = _pausa_ate - agora()
        if falta > 0:
            dormir(falta)
        req = urllib.request.Request(BASE + rota, data=corpo, headers={"User-Agent": marker(cfg)})
        try:
            with abrir(req, timeout=60) as r:
                h = r.headers
                resposta = json.load(r).get("data")
        except urllib.error.HTTPError as e:
            if e.code != 429 or tentativa == TENTATIVAS - 1:
                raise
            with _trava:
                _pausa_ate = agora() + _reset(e.headers, 60.0) + 1
            continue
        try:
            restam = int(h.get("x-rate-limit-remaining", "99"))
        except (TypeError, ValueError):
            restam = 99
        if restam <= FOLGA:
            with _trava:
                _pausa_ate = agora() + _reset(h, 60.0) + 1
        return resposta
    raise RuntimeError("TNS: limite de pedidos")  # inalcançável: a última tentativa sobe o erro
