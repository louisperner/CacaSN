"""Novidades do TNS sem depender de email.

- Dias fechados: o arquivo diário de mudanças (tns_public_objects_AAAAMMDD.csv.zip)
  traz os transientes reportados e as classificações de cada dia — o resumo vai
  para novidades.md.
- Dia em andamento: o arquivo só sai depois que o dia fecha, então a busca da API
  por `public_timestamp` traz as classificações desde a última rodada.

Avisa só o que importa (classificação de um objeto que o CacaSN viu, ou tipo raro)
e nunca o mesmo objeto duas vezes."""

from __future__ import annotations

import csv
import io
import json
import os
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any

from . import alertas, registro
from .rede import gravar_json, ler_json

URL = "https://www.wis-tns.org/system/files/tns_public_objects/tns_public_objects_{}.csv.zip"
ESTADO = "novidades_estado.json"
RESUMO = "novidades.md"
# tipos raros: valem aviso mesmo que o CacaSN não tenha visto o objeto
RAROS = ("SLSN", "TDE", "Kilonova", "FBOT", "Ic-BL", "IIn", "Ibn", "Icn", "Ca-rich", "LRN", "LBV")
MAX_DIAS = 7


def _marker(cfg: dict[str, Any]) -> str:
    return "tns_marker" + json.dumps({"tns_id": cfg["bot_id"], "type": "bot", "name": cfg["bot_name"]})


def baixar_dia(cfg: dict[str, Any], dia: date) -> list[dict[str, str]]:
    """Objetos que mudaram no TNS num dia (UTC) já fechado."""
    dados = urllib.parse.urlencode({"api_key": cfg["api_key"]}).encode()
    req = urllib.request.Request(URL.format(dia.strftime("%Y%m%d")), data=dados, headers={"User-Agent": _marker(cfg)})
    with urllib.request.urlopen(req, timeout=120) as r:
        return ler_csv(r.read())


def ler_csv(conteudo: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        texto = z.read(z.namelist()[0]).decode("utf-8", "replace")
    linhas = list(csv.reader(io.StringIO(texto)))
    if len(linhas) < 2:
        return []
    cabecalho = linhas[1]  # a primeira linha é o intervalo de datas
    return [dict(zip(cabecalho, linha)) for linha in linhas[2:]]


def _api(cfg: dict[str, Any], rota: str, dados: dict[str, Any]) -> Any:
    corpo = urllib.parse.urlencode({"api_key": cfg["api_key"], "data": json.dumps(dados)}).encode()
    req = urllib.request.Request(f"https://www.wis-tns.org/api/get/{rota}", data=corpo, headers={"User-Agent": _marker(cfg)})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r).get("data")


def buscar_modificados(cfg: dict[str, Any], desde: str) -> list[dict[str, str]]:
    """Objetos modificados no TNS desde um instante (UTC) que já têm classificação
    (prefixo diferente de AT), no mesmo formato das linhas do arquivo diário."""
    saida = []
    for o in _api(cfg, "search", {"public_timestamp": desde}) or []:
        if o.get("prefix") in (None, "", "AT"):
            continue
        d = _api(cfg, "object", {"objname": o["objname"]}) or {}
        saida.append(
            {
                "name_prefix": d.get("name_prefix") or o["prefix"],
                "name": o["objname"],
                "type": (d.get("object_type") or {}).get("name") or "",
                "redshift": str(d.get("redshift") or ""),
                "internal_names": d.get("internal_names") or "",
            }
        )
    return saida


def destaque(d: dict[str, str], vistos: set[str]) -> str | None:
    """Texto do aviso se o objeto classificado interessa: o CacaSN viu ou é de tipo raro."""
    internos = {n.strip() for n in d.get("internal_names", "").split(",") if n.strip()}
    if internos & vistos:
        return f"{d['name_prefix']} {d['name']} = {d['type']}: o CacaSN tinha visto ({', '.join(sorted(internos & vistos))})"
    if any(r in d.get("type", "") for r in RAROS):
        return f"{d['name_prefix']} {d['name']} = {d['type']} (raro, z = {d.get('redshift') or '?'})"
    return None


def resumir(dados: list[dict[str, str]], vistos: set[str]) -> dict[str, Any]:
    """Classificados do dia e os destaques (nome, texto)."""
    classificados = [d for d in dados if d.get("type")]
    destaques = [(d["name"], t) for d in classificados if (t := destaque(d, vistos))]
    return {"novos": len(dados) - len(classificados), "classificados": classificados, "destaques": destaques}


def markdown(dia: date, r: dict[str, Any]) -> str:
    linhas = [f"## {dia.isoformat()}", "", f"{r['novos']} transientes reportados, {len(r['classificados'])} classificados.", ""]
    for d in r["classificados"]:
        linhas.append(
            f"- {d['name_prefix']} {d['name']} — {d['type']}, z = {d.get('redshift') or '?'}"
            f" ({d.get('internal_names', '').strip(', ')[:60]})"
        )
    for _, texto in r["destaques"]:
        linhas.append(f"- **destaque:** {texto}")
    return "\n".join(linhas) + "\n\n"


def dias_fechados(
    cfg: dict[str, Any], pasta: str, estado: dict[str, Any], vistos: set[str], hoje: date, baixar: Any
) -> list[tuple[str, str]]:
    """Processa os dias completos desde a última verificação (no máximo MAX_DIAS)."""
    ultimo = date.fromisoformat(estado["ultimo_dia"]) if estado.get("ultimo_dia") else hoje - timedelta(days=2)
    dia = max(ultimo + timedelta(days=1), hoje - timedelta(days=MAX_DIAS))
    destaques: list[tuple[str, str]] = []
    while dia < hoje:  # o dia de hoje ainda não fechou
        try:
            r = resumir(baixar(cfg, dia), vistos)
        except Exception as e:
            registro.obter().warning("novidades_falhou", dia=dia.isoformat(), erro=repr(e))
            break
        with open(os.path.join(pasta, RESUMO), "a", encoding="utf-8") as f:
            f.write(markdown(dia, r))
        registro.obter().info("novidades", dia=dia.isoformat(), novos=r["novos"], classificados=len(r["classificados"]))
        destaques += r["destaques"]
        estado["ultimo_dia"] = dia.isoformat()
        dia += timedelta(days=1)
    return destaques


def dia_em_andamento(cfg: dict[str, Any], estado: dict[str, Any], vistos: set[str], buscar: Any) -> list[tuple[str, str]]:
    """Classificações desde a última consulta (ou desde a meia-noite UTC na primeira)."""
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    desde = estado.get("ultimo_instante") or agora[:10] + " 00:00:00"
    try:
        dados = buscar(cfg, desde)
    except Exception as e:
        registro.obter().warning("novidades_hoje_falhou", erro=repr(e))
        return []
    estado["ultimo_instante"] = agora
    return [(d["name"], t) for d in dados if d.get("type") and (t := destaque(d, vistos))]


def verificar(
    cfg: dict[str, Any] | None,
    pasta: str,
    vistos: set[str],
    hoje: date | None = None,
    baixar: Any = baixar_dia,
    buscar_hoje: Any = None,
) -> list[str]:
    """Dias fechados + dia em andamento; notifica o que ainda não foi avisado."""
    if not cfg:
        return []
    caminho = os.path.join(pasta, ESTADO)
    estado = ler_json(caminho, {})
    avisados = set(estado.get("avisados", []))
    candidatos = dias_fechados(cfg, pasta, estado, vistos, hoje or date.today(), baixar)
    if buscar_hoje is not None:
        candidatos += dia_em_andamento(cfg, estado, vistos, buscar_hoje)
    novos = []
    for nome, texto in candidatos:
        if nome not in avisados:
            novos.append(texto)
            avisados.add(nome)
    estado["avisados"] = sorted(avisados)[-500:]
    gravar_json(caminho, estado)
    if novos:
        texto = "; ".join(novos)[:250]
        alertas.notificar("CacaSN: novidades no TNS", texto, os.path.join(pasta, RESUMO), alertas.link_tns(texto))
    return novos
