"""Acompanha objetos no TNS (por exemplo, os que você descobriu) e avisa quando
alguém os classifica por espectro — a mesma informação dos emails de AstroNotes,
lida direto da API do TNS a cada rodada. Também avisa quando o ZTF (ALeRCE) ou o Rubin (Fink)
detectam o objeto de novo, pelos nomes internos que o TNS guarda."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

from . import alertas, registro
from .rede import get_json, gravar_json, ler_json

ARQUIVO = "acompanhar.json"
ALERCE = "https://api.alerce.online/ztf/v1/objects/"
FILTROS = {"ztf": {1: "g", 2: "r", 3: "i"}, "rubin": {0: "u", 1: "g", 2: "r", 3: "i", 4: "z", 5: "y"}}


def nomes_internos(obj: dict[str, Any]) -> list[tuple[str, str]]:
    """(fonte, id) de cada nome interno do TNS que dá para consultar: ZTF na ALeRCE, LSST no Fink."""
    saida = []
    for n in re.split(r"[,\s]+", str(obj.get("internal_names") or "")):
        if re.fullmatch(r"ZTF\d{2}[a-z]{7}", n):
            saida.append(("ztf", n))
        elif re.fullmatch(r"\d{15,20}", n):
            saida.append(("rubin", n))
    return saida


def ultima_deteccao(fonte: str, oid: str, consultar: Callable[[str], Any] = get_json) -> dict[str, Any] | None:
    """Última detecção positiva: {"mjd", "mag", "filtro", "fonte", "n"}."""
    if fonte == "ztf":
        dets = consultar(ALERCE + oid + "/detections") or []
        pts = [(d["mjd"], d.get("fid"), d.get("magpsf")) for d in dets if d.get("magpsf")]
    else:
        from . import rubin

        c = rubin.curva_completa(oid)
        pts = [(c[0] + t, f, m) for t, f, m in c[1]] if c else []
    if not pts:
        return None
    mjd, fid, mag = max(pts, key=lambda p: p[0])
    filtro = FILTROS[fonte].get(fid, "?")
    return {"mjd": round(mjd, 5), "mag": round(mag, 2), "filtro": filtro, "fonte": fonte, "n": len(pts)}


def data_mjd(mjd: float) -> str:
    return time.strftime("%d/%m %H:%M UTC", time.gmtime((mjd - 40587) * 86400))


def tns_objeto(cfg: dict[str, Any], nome: str) -> dict[str, Any]:
    """Registro do objeto no TNS (api/get/object)."""
    marker = json.dumps({"tns_id": cfg["bot_id"], "type": "bot", "name": cfg["bot_name"]})
    dados = urllib.parse.urlencode({"api_key": cfg["api_key"], "data": json.dumps({"objname": nome})}).encode()
    req = urllib.request.Request(
        "https://www.wis-tns.org/api/get/object", data=dados, headers={"User-Agent": "tns_marker" + marker}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("data") or {}


def situacao(obj: dict[str, Any]) -> dict[str, Any]:
    tipo = (obj.get("object_type") or {}).get("name")
    return {"prefixo": obj.get("name_prefix"), "tipo": tipo, "redshift": obj.get("redshift")}


def descrever(nome: str, s: dict[str, Any]) -> str:
    texto = f"{s.get('prefixo') or 'AT'} {nome}"
    if s.get("tipo"):
        texto += f" = {s['tipo']}"
    if s.get("redshift"):
        texto += f" (z = {s['redshift']})"
    return texto


def adicionar(pasta: str, nome: str) -> None:
    caminho = os.path.join(pasta, ARQUIVO)
    lista = ler_json(caminho, {})
    lista.setdefault(nome.replace("AT ", "").replace("SN ", "").strip(), {})
    gravar_json(caminho, lista, indent=1)


def verificar(
    cfg: dict[str, Any] | None,
    pasta: str,
    consultar: Any = tns_objeto,
    detectar: Callable[[str, str], dict[str, Any] | None] = ultima_deteccao,
) -> list[str]:
    """Confere cada objeto acompanhado; devolve (e notifica) o que mudou: classificação por
    espectro ou detecção nova."""
    caminho = os.path.join(pasta, ARQUIVO)
    lista: dict[str, dict[str, Any]] = ler_json(caminho, {})
    if not cfg or not lista:
        return []
    log = registro.obter()
    mudancas, novas = [], []
    for nome, antes in lista.items():
        try:
            obj = consultar(cfg, nome)
        except Exception as e:
            log.warning("acompanhamento_falhou", objeto=nome, erro=repr(e))
            continue
        agora = situacao(obj)
        if antes and agora.get("tipo") and agora.get("tipo") != antes.get("tipo"):
            mudancas.append(f"{descrever(nome, antes)} -> {descrever(nome, agora)}")
        ultimas = dict(antes.get("ultimas") or {})
        for fonte, oid in nomes_internos(obj):
            try:
                u = detectar(fonte, oid)
            except Exception as e:
                log.warning("deteccao_falhou", objeto=nome, oid=oid, erro=repr(e))
                u = None
            if not u:
                continue
            velha = ultimas.get(oid)
            if velha and u["mjd"] > velha["mjd"] + 0.001:
                novas.append(f"{nome}: {u['filtro']} {u['mag']} em {data_mjd(u['mjd'])} ({fonte.upper()})")
            ultimas[oid] = u
        if ultimas:
            agora["ultimas"] = ultimas
        lista[nome] = agora
    gravar_json(caminho, lista, indent=1)
    relatorio = os.path.join(pasta, "report.html")
    if mudancas:
        log.info("classificado", mudancas=mudancas)
        alertas.notificar("CacaSN: classificaram sua descoberta!", "; ".join(mudancas), relatorio)
    if novas:
        log.info("nova_deteccao", novas=novas)
        alertas.notificar("CacaSN: detecção nova de uma descoberta sua", "; ".join(novas), relatorio)
    return mudancas + novas
