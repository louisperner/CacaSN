"""Já é conhecido? Gaia DR3 (via VizieR) e o Transient Name Server."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .rede import HDR, ler_json

SEM_RESPOSTA = object()  # o catálogo falhou: não dá para afirmar nada


class Disjuntor:
    """Depois de `limite` falhas seguidas, desiste na hora até a próxima resposta boa
    (ou a próxima rodada). Sem isso, um VizieR fora do ar custa ~90 s por candidato."""

    def __init__(self, limite: int = 3) -> None:
        self.limite = limite
        self.falhas = 0
        self._trava = threading.Lock()

    @property
    def aberto(self) -> bool:
        return self.falhas >= self.limite

    def resultado(self, ok: bool) -> None:
        with self._trava:
            self.falhas = 0 if ok else self.falhas + 1


VIZIER = Disjuntor()


# O CDS (Estrasburgo) e seus espelhos; quando o CDS cai (como em 01-03/11/2026) os espelhos seguem no ar.
# Só leitura de catálogos públicos: os que não têm HTTPS válido vão por HTTP.
SERVIDORES = (
    "https://vizier.cds.unistra.fr",
    "https://vizier.idia.ac.za",
    "http://vizier.china-vo.org",
    "http://vizier.nao.ac.jp",
)
_preferido = 0  # o último que respondeu é tentado primeiro


def vizier(fonte: str, ra: float, dec: float, raio: float, cols: str, maximo: int = 5) -> list[list[str]] | None:
    """Linhas do catálogo perto da posição, ou None se nenhum servidor do VizieR respondeu."""
    global _preferido
    if VIZIER.aberto:
        return None
    consulta = f"/viz-bin/asu-tsv?-source={fonte}&-c={ra:.6f}%20{dec:+.6f}&-c.rs={raio}&-out={cols}&-out.max=5&-sort=_r"
    ordem = [_preferido] + [i for i in range(len(SERVIDORES)) if i != _preferido]
    for n, i in enumerate(ordem):
        try:
            req = urllib.request.Request(SERVIDORES[i] + consulta, headers=HDR)
            with urllib.request.urlopen(req, timeout=20) as r:
                linhas = [l.split("\t") for l in r.read().decode().splitlines() if l and not l.startswith("#")]
            VIZIER.resultado(True)
            _preferido = i
            return [l for l in linhas[3:] if len(l) == len(cols.split(","))]
        except Exception:
            if n < len(ordem) - 1:
                time.sleep(1)
    VIZIER.resultado(False)
    return None


def _sep(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Separação angular em ″ (haversine)."""
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a)))) * 3600


# Gaia DR3: posições na época 2016,0 (MJD 57388). Uma estrela próxima anda até alguns ″ por ano; projetada para
# a data da detecção ela pode cair em cima de um "transiente" que é só ela fora do lugar da referência
# (ZTF26acctnkb, 2026-11: G 13,6 a 9 pc, 1,57″/ano, a 17″ da posição de 2016 e a 0,1″ da detecção).
EPOCA_GAIA_MJD = 57388.0
RAIO_MOVEL = 30.0  # ″: cobre ~3″/ano por 10 anos
PM_ALTO = 50.0  # mas/ano


def raio_brilho(g: float) -> float:
    """Raio (″) em que uma estrela do Gaia de magnitude g ainda contamina a medida do ZTF."""
    return 4.0 if g < 14 else 2.5 if g < 17 else 1.5


def gaia_propagado(ra: float, dec: float, mjd: float, raio: float = RAIO_MOVEL) -> list[dict[str, Any]] | None:
    """Estrelas do Gaia num raio de `raio`″, com a posição projetada para `mjd` pelo movimento próprio.
    None se nenhum servidor do VizieR respondeu."""
    linhas = vizier("I/355/gaiadr3", ra, dec, raio, "Source,RA_ICRS,DE_ICRS,Gmag,pmRA,pmDE", maximo=50)
    if linhas is None:
        return None
    anos = (mjd - EPOCA_GAIA_MJD) / 365.25
    saida = []
    for src, r0, d0, g, pmra, pmde in linhas:
        try:
            r0f, d0f, gf = float(r0), float(d0), float(g)
        except ValueError:
            continue
        pa = float(pmra) if pmra.strip() else 0.0  # mas/ano, já multiplicado por cos(dec)
        pd = float(pmde) if pmde.strip() else 0.0
        d1 = d0f + pd * anos / 3.6e6
        r1 = r0f + pa * anos / 3.6e6 / math.cos(math.radians(d1))
        saida.append(
            {
                "source": src.strip(),
                "g": gf,
                "pm": round(math.hypot(pa, pd), 1),
                "sep_2016": round(_sep(ra, dec, r0f, d0f), 2),
                "sep_agora": round(_sep(ra, dec, r1, d1), 2),
            }
        )
    return saida


def estrela_no_lugar(ra: float, dec: float, mjd: float, mag: float, consultar: Any = None) -> Any:
    """A "fonte nova" é uma estrela do Gaia? Texto do motivo, None, ou SEM_RESPOSTA se o VizieR falhou.
    (a) estrela de movimento próprio alto que ANDOU até a posição; (b) estrela mais brilhante que a
    detecção + 1 mag em cima dela (raio maior para estrela brilhante): é ela variando."""
    estrelas = (consultar or gaia_propagado)(ra, dec, mjd)
    if estrelas is None:
        return SEM_RESPOSTA
    for e in sorted(estrelas, key=lambda e: e["sep_agora"]):
        if e["pm"] >= PM_ALTO and e["sep_agora"] <= 2.0 and e["sep_2016"] > 1.0:
            return (
                f"estrela de movimento próprio alto: Gaia DR3 {e['source']} G={e['g']:.1f}, {e['pm'] / 1000:.2f}″/ano, "
                f"a {e['sep_agora']}″ hoje (estava a {e['sep_2016']}″ em 2016)"
            )
        if e["g"] < mag + 1 and e["sep_agora"] <= raio_brilho(e["g"]):
            return f"estrela do Gaia em cima: DR3 {e['source']} G={e['g']:.1f} a {e['sep_agora']}″ (é ela variando)"
    return None


PS1 = "https://catalogs.mast.stsci.edu/api/v0.1/panstarrs/dr2/mean.csv"


def latitude_galactica(ra: float, dec: float) -> float:
    """Latitude galáctica b (graus), polo norte galáctico J2000 em (192,85948; 27,12825)."""
    r, d = math.radians(ra), math.radians(dec)
    rp, dp = math.radians(192.85948), math.radians(27.12825)
    return math.degrees(math.asin(math.sin(d) * math.sin(dp) + math.cos(d) * math.cos(dp) * math.cos(r - rp)))


def ps1_puntiforme(ra: float, dec: float, mag: float, raio: float = 1.5, ler: Any = None) -> str | None:
    """Fonte PONTUAL do Pan-STARRS DR2 a até `raio`″, mais brilhante que a detecção + 1 mag: uma estrela
    fraca demais para o Gaia (G > 21) que pode ser a própria fonte variando (AT 2026ajce, 2026-11:
    r 20,5 pontual a 1,2″, transiente em 20,2). Pontual = PSF - Kron < 0,05 mag. Erro de rede sobe."""
    q = urllib.parse.urlencode({"ra": ra, "dec": dec, "radius": raio / 3600, "nDetections.gte": 2})
    if ler is None:
        with urllib.request.urlopen(urllib.request.Request(f"{PS1}?{q}", headers=HDR), timeout=60) as r:
            texto = r.read().decode()
    else:
        texto = ler(f"{PS1}?{q}")
    for l in csv.DictReader(io.StringIO(texto)):
        try:
            psf, kron = float(l["rMeanPSFMag"]), float(l["rMeanKronMag"])
        except (KeyError, ValueError):
            continue
        if psf > 0 and kron > 0 and psf - kron < 0.05 and psf < mag + 1:
            return f"fonte pontual do Pan-STARRS {l.get('objName', '').strip()} r={psf:.2f} (estrela fraca para o Gaia?)"
    return None


def estrela_gaia(ra: float, dec: float) -> Any:
    """Estrela do Gaia com paralaxe ou movimento significativo em 1.5": a
    'supernova' quase certamente é a estrela variando de brilho.
    Devolve o id da estrela, None, ou SEM_RESPOSTA se o catálogo falhou."""
    linhas = vizier("I/355/gaiadr3", ra, dec, 1.5, "Source,Plx,e_Plx,pmRA,pmDE")
    if linhas is None:
        return SEM_RESPOSTA
    for src, plx, eplx, pmra, pmde in linhas:
        try:
            if float(plx) > 3 * float(eplx) or (float(pmra) ** 2 + float(pmde) ** 2) ** 0.5 > 5:
                return src.strip()
        except ValueError:
            continue
    return None


def variavel_conhecida(ra: float, dec: float) -> Any:
    """Estrela variável já catalogada no VSX (AAVSO) a até 5": anãs novas, novas,
    variáveis da nossa galáxia que não vão para o TNS. Devolve "NOME (TIPO)",
    None, ou SEM_RESPOSTA se o catálogo falhou."""
    linhas = vizier("B/vsx/vsx", ra, dec, 5, "Name,Type")
    if linhas is None:
        return SEM_RESPOSTA
    for nome, tipo in linhas:
        return f"{nome.strip()} ({tipo.strip()})"
    return None


def tns_carregar(pasta: str) -> dict[str, Any] | None:
    """Credenciais do bot do TNS: variáveis TNS_BOT_ID/TNS_BOT_NAME/TNS_API_KEY
    (Docker, CI) ou o arquivo tns.json ao lado do programa (fora do git)."""
    if all(os.environ.get(k) for k in ("TNS_BOT_ID", "TNS_BOT_NAME", "TNS_API_KEY")):
        return {
            "bot_id": int(os.environ["TNS_BOT_ID"]),
            "bot_name": os.environ["TNS_BOT_NAME"],
            "api_key": os.environ["TNS_API_KEY"],
        }
    cfg = ler_json(os.path.join(pasta, "tns.json"), None)
    return cfg if isinstance(cfg, dict) else None


_tns_trava = threading.Lock()
_tns_ultima = [0.0]


def tns_busca(cfg: dict[str, Any], ra: float, dec: float, tentativas: int = 4) -> list[str]:
    """Objetos do TNS a até 3". A busca por região aceita 10 por minuto: uma por
    vez, a cada 6.5 s; no 429 espera o tempo que o cabeçalho manda, em erro de
    rede espera e tenta de novo."""
    marker = json.dumps({"tns_id": cfg["bot_id"], "type": "bot", "name": cfg["bot_name"]})
    dados = urllib.parse.urlencode(
        {
            "api_key": cfg["api_key"],
            "data": json.dumps({"ra": f"{ra:.6f}", "dec": f"{dec:.6f}", "radius": "3", "units": "arcsec"}),
        }
    ).encode()
    for i in range(tentativas):
        with _tns_trava:
            espera = 6.5 - (time.time() - _tns_ultima[0])
            if espera > 0:
                time.sleep(espera)
            try:
                req = urllib.request.Request(
                    "https://www.wis-tns.org/api/get/search", data=dados, headers={"User-Agent": "tns_marker" + marker}
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    resp = json.load(r)
                return [f"{o.get('prefix', '')} {o['objname']}".strip() for o in resp.get("data", [])]
            except urllib.error.HTTPError as e:
                if e.code != 429 or i == tentativas - 1:
                    raise
                time.sleep(int(e.headers.get("x-cone-rate-limit-reset", "30")) + 1)
            except urllib.error.URLError:
                if i == tentativas - 1:
                    raise
                time.sleep(2 ** (i + 1))
            finally:
                _tns_ultima[0] = time.time()
    return []
