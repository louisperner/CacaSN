"""Histórico longo: a fotometria forçada do ATLAS no ponto do candidato, desde 2015.

Uma supernova sai do nada; um núcleo ativo (AGN) ou uma estrela variável já variava antes. Aqui se
mede, no ponto exato, quantas noites ANTES da descoberta tiveram fluxo significativo. Precisa de uma
conta gratuita no servidor do ATLAS (https://fallingstar-data.com/forcedphot/), com o token em
`fotometria.json` (`{"atlas_token": "..."}`, permissão 600, fora do git).
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

from .rede import HDR, ler_json

ARQUIVO = "fotometria.json"
ATLAS = "https://fallingstar-data.com/forcedphot"
MJD_INICIO = 57200.0  # meados de 2015, começo da fotometria útil do ATLAS
ANTES = 15.0  # dias antes da 1ª detecção: o que vem depois já pode ser a própria explosão
SIGMA = 5.0  # S/R mínima de uma detecção
NOITES_ATIVAS = 3  # noites distintas com detecção antes = a fonte já variava
ESPERA_MAX = 900  # s; a fila do ATLAS às vezes demora


def credenciais(pasta: str) -> dict[str, Any]:
    return ler_json(os.path.join(pasta, ARQUIVO), {}) or {}


def ler_atlas(texto: str) -> list[dict[str, float | str]]:
    """Linhas do arquivo do ATLAS (cabeçalho `###MJD m dm uJy duJy F ...`) em dicionários."""
    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        return []
    nomes = linhas[0].lstrip("#").split()
    pontos = []
    for l in linhas[1:]:
        campos = l.split()
        if len(campos) != len(nomes):
            continue
        p: dict[str, float | str] = {}
        for n, v in zip(nomes, campos):
            try:
                p[n] = float(v)
            except ValueError:
                p[n] = v
        pontos.append(p)
    return pontos


def resumir(pontos: list[dict[str, Any]], mjd0: float) -> dict[str, Any]:
    """Atividade no ponto antes da descoberta: noites com S/R >= SIGMA (positivas)."""
    antes = [p for p in pontos if isinstance(p.get("MJD"), float) and p["MJD"] < mjd0 - ANTES]
    boas = [p for p in antes if (p.get("duJy") or 0) > 0]
    signif = [p for p in boas if p["uJy"] / p["duJy"] >= SIGMA]
    noites = sorted({int(p["MJD"]) for p in signif})
    ativa = len(noites) >= NOITES_ATIVAS
    return {
        "medidas_antes": len(boas),
        "noites_detectadas_antes": len(noites),
        "primeira": noites[0] if noites else None,
        "ultima": noites[-1] if noites else None,
        "ativa_antes": ativa,
        "veredito": (
            f"já variava antes: {len(noites)} noite(s) com S/R >= {SIGMA:g} desde MJD {noites[0]}"
            if ativa
            else f"nada antes em {len(boas)} medidas do ATLAS desde 2015"
        ),
    }


def _pedir(url: str, token: str, dados: dict[str, Any] | None = None, metodo: str | None = None) -> tuple[int, Any]:
    corpo = urllib.parse.urlencode(dados).encode() if dados else None
    h = dict(HDR, Authorization=f"Token {token}", Accept="application/json")
    req = urllib.request.Request(url, data=corpo, headers=h, method=metodo)
    with urllib.request.urlopen(req, timeout=60) as r:
        bruto = r.read()
        return r.status, bruto


def atlas(
    ra: float,
    dec: float,
    token: str,
    pedir: Callable[..., tuple[int, Any]] = _pedir,
    dormir: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Enfileira, espera e baixa a fotometria forçada do ATLAS; apaga a tarefa no fim."""
    _, b = pedir(f"{ATLAS}/queue/", token, {"ra": ra, "dec": dec, "mjd_min": MJD_INICIO, "send_email": False})
    tarefa = json.loads(b)["url"]
    try:
        esperou = 0.0
        while True:
            _, b = pedir(tarefa, token)
            d = json.loads(b)
            if d.get("finishtimestamp"):
                if d.get("error_msg"):
                    raise RuntimeError(f"ATLAS: {d['error_msg']}")
                _, txt = pedir(d["result_url"], token)
                return ler_atlas(txt.decode() if isinstance(txt, bytes) else str(txt))
            if esperou >= ESPERA_MAX:
                raise TimeoutError(f"ATLAS não terminou em {ESPERA_MAX} s")
            dormir(15)
            esperou += 15
    finally:
        try:  # o servidor pede para apagar as tarefas já baixadas
            pedir(tarefa, token, metodo="DELETE")
        except Exception:
            pass


def historico(it: dict[str, Any], pasta: str, consultar: Callable[..., list[dict[str, Any]]] = atlas) -> dict[str, Any] | None:
    """Resumo do histórico longo do candidato, ou None sem token do ATLAS."""
    token = credenciais(pasta).get("atlas_token")
    if not token:
        return None
    return resumir(consultar(it["ra"], it["dec"], token), it["mjd0"])
