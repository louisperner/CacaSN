"""Ficha do candidato antes de reportar: as checagens que antes eram feitas à mão,
todas por serviços fora do CDS (que cai às vezes e levava junto SIMBAD/VizieR).

- TNS: ninguém reportou a menos de 5"?
- Gaia DR3 (servidor da ESA): há estrela na posição?
- SkyBoT (IMCCE): é um asteroide conhecido na hora da detecção?
- NED: galáxia hospedeira com redshift -> magnitude absoluta
- ALeRCE: última não-detecção antes da descoberta (o TNS exige)

`montar` devolve um dicionário com cada resposta e um veredito: pronto para
reportar, ou a lista de motivos para não reportar."""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
from typing import Any, Callable

from . import catalogos
from .rede import abrir, get_json

ALERCE = "https://api.alerce.online/ztf/v1/objects/"
GAIA_TAPS = (
    ("https://gea.esac.esa.int/tap-server/tap/sync?", "gaiadr3.gaia_source"),
    ("https://dc.zah.uni-heidelberg.de/tap/sync?", "gaia.dr3lite"),  # espelho do GAVO
)
SKYBOT = "https://ssp.imcce.fr/webservices/skybot/api/conesearch.php?"
NED = "https://ned.ipac.caltech.edu/cgi-bin/objsearch?"
RAIO_GAIA = 3.0  # arcsec
RAIO_SKYBOT = 36.0  # arcsec: asteroides conhecidos têm erro de posição de alguns "
RAIO_NED = 15.0  # arcsec: a supernova pode estar longe do núcleo
# paralaxe acima disso (em sigmas) é estrela da Via Láctea, não galáxia
PARALAXE_SIGMA = 5.0
# com uma detecção só não dá para separar de artefato ou asteroide ainda não catalogado
DETECCOES_MIN = 2
NUCLEAR = 1.0  # arcsec do centro da galáxia: suspeita de AGN/TDE
C_KM_S, H0 = 299792.458, 70.0
FINK = "https://api.lsst.fink-portal.org/api/v1"
FID_LSST = {"u": 0, "g": 1, "r": 2, "i": 3, "z": 4, "y": 5}


def _rapido(url: str) -> bytes:
    """Gaia/NED/SkyBoT às vezes ficam lentos: 30 s e 2 tentativas, não 60 s e 4 (a ficha
    ficava 10 min parada). Se não responder, a ficha bloqueia o envio e pede para refazer."""
    return abrir(url, 30, 2)


def nao_deteccao(oid: str, mjd0: float, consultar: Callable[[str], Any] = get_json) -> dict[str, Any] | None:
    """Última não-detecção do ZTF antes da primeira detecção: {mjd, fid, limite}."""
    ndet = consultar(ALERCE + oid + "/non_detections") or []
    antes = [n for n in ndet if n.get("mjd") is not None and n["mjd"] < mjd0 and n.get("diffmaglim") is not None]
    if not antes:
        return None
    # na última noite costuma haver várias exposições: vale a mais profunda
    ultima = max(n["mjd"] for n in antes)
    n = max((n for n in antes if ultima - n["mjd"] < 0.5), key=lambda n: n["diffmaglim"])
    return {"mjd": float(n["mjd"]), "fid": int(n["fid"]), "limite": round(float(n["diffmaglim"]), 2)}


def nao_deteccao_rubin(oid: str, mjd0: float, consultar: Callable[[str], Any] = get_json) -> dict[str, Any] | None:
    """Última não-detecção do Rubin pela fotometria forçada do Fink: medida de uma noite
    anterior com S/R < 3; o limite é 5 x o erro do fluxo (nJy) em magnitude AB."""
    q = urllib.parse.urlencode(
        {"diaObjectId": oid.replace("LSST ", ""), "columns": "r:midpointMjdTai,r:psfFlux,r:psfFluxErr,r:band"}
    )
    pontos = consultar(f"{FINK}/fp?{q}") or []
    antes = [
        p
        for p in pontos
        if (p.get("r:psfFluxErr") or 0) > 0
        and p["r:midpointMjdTai"] < mjd0 - 0.3  # outra noite
        and abs(p.get("r:psfFlux") or 0) / p["r:psfFluxErr"] < 3
    ]
    if not antes:
        return None
    ultima = max(p["r:midpointMjdTai"] for p in antes)
    p = min((p for p in antes if ultima - p["r:midpointMjdTai"] < 0.5), key=lambda p: p["r:psfFluxErr"])
    limite = 31.4 - 2.5 * math.log10(5 * p["r:psfFluxErr"])
    return {"mjd": float(p["r:midpointMjdTai"]), "fid": FID_LSST.get(str(p.get("r:band")), 9), "limite": round(limite, 2)}


def gaia(ra: float, dec: float, ler: Callable[[str], bytes] = _rapido) -> list[dict[str, Any]]:
    """Fontes do Gaia DR3 a menos de RAIO_GAIA": TAP da ESA e, se ela não responder, o
    espelho do GAVO (Heidelberg) com o mesmo catálogo."""
    erro: Exception | None = None
    for tap, tabela in GAIA_TAPS:
        q = (
            "SELECT source_id, phot_g_mean_mag, parallax, parallax_error, "
            f"DISTANCE(POINT({ra},{dec}),POINT(ra,dec))*3600 AS sep FROM {tabela} "
            f"WHERE 1=CONTAINS(POINT(ra,dec),CIRCLE({ra},{dec},{RAIO_GAIA / 3600})) ORDER BY sep"
        )
        url = tap + urllib.parse.urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": q})
        try:
            linhas = json.loads(ler(url))["data"]
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            erro = e
            continue
        return [
            {
                "source_id": l[0],
                "g": l[1],
                "paralaxe": l[2],
                "paralaxe_sigma": l[2] / l[3] if l[2] is not None and l[3] else None,
                "sep": round(l[4], 2),
            }
            for l in linhas
        ]
    raise erro or OSError("nenhum servidor do Gaia respondeu")


def skybot(ra: float, dec: float, mjd: float, ler: Callable[[str], bytes] = _rapido) -> list[str]:
    """Asteroides conhecidos perto da posição na hora (resposta vazia = nenhum)."""
    p = {
        "-ep": f"{mjd + 2400000.5:.5f}",
        "-ra": ra,
        "-dec": dec,
        "-rd": RAIO_SKYBOT / 3600,
        "-mime": "text",
        "-output": "basic",
        "-loc": "I41",
    }
    texto = ler(SKYBOT + urllib.parse.urlencode(p)).decode(errors="replace")
    return [l.strip() for l in texto.splitlines() if l.strip() and not l.startswith("#")]


def ned_hospedeira(ra: float, dec: float, ler: Callable[[str], bytes] = _rapido) -> dict[str, Any] | None:
    """Galáxia mais próxima com redshift no NED a menos de RAIO_NED"."""
    p = {
        "search_type": "Near Position Search",
        "in_csys": "Equatorial",
        "in_equinox": "J2000",
        "lon": f"{ra}d",
        "lat": f"{dec}d",
        "radius": RAIO_NED / 60,
        "of": "ascii_tab",
        "out_csys": "Equatorial",
        "out_equinox": "J2000",
        "obj_sort": "Distance to search center",
        "list_limit": "10",
        "img_stamp": "NO",
    }
    linhas = ler(NED + urllib.parse.urlencode(p)).decode(errors="replace").splitlines()
    i = next((k for k, l in enumerate(linhas) if l.startswith("No.")), None)
    if i is None:
        return None
    cab = linhas[i].split("\t")
    for l in linhas[i + 1 :]:
        c = dict(zip(cab, l.split("\t")))
        z = (c.get("Redshift") or "").strip()
        if c.get("Type", "").strip() in ("G", "GPair", "GTrpl", "GGroup") and z:
            try:
                sep = float(c.get("Separation") or "nan") * 60  # arcmin
                return {"nome": c["Object Name"].strip(), "z": float(z), "sep": round(sep, 1)}
            except ValueError:
                continue
    return None


def magnitude_absoluta(mag: float, z: float) -> float:
    """M = m - módulo de distância, com d ~ cz/H0 (bom para z < 0.1)."""
    d_mpc = C_KM_S * z / H0 * (1 + z / 2)
    return round(mag - 5 * math.log10(d_mpc * 1e5), 1)


def fonte_nova_rubin(it: dict[str, Any]) -> bool:
    """Rubin sem nada na imagem de referência (rubin.pontuar marca 'fonte nova'): vale como
    informação de arquivo no lugar da não-detecção, quando o Fink não tem noite anterior."""
    return it.get("fonte") == "rubin" and "fonte nova" in (it.get("motivos") or [])


def _tentar(f: Callable[[], Any]) -> tuple[Any, str | None]:
    try:
        return f(), None
    except (urllib.error.URLError, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        return None, repr(e)


def montar(
    it: dict[str, Any], cfg: dict[str, Any] | None, servicos: dict[str, Callable[..., Any]] | None = None
) -> dict[str, Any]:
    """Todas as checagens de um candidato e o veredito."""
    s: dict[str, Callable[..., Any]] = {
        "tns": catalogos.tns_busca,
        "gaia": gaia,
        "skybot": skybot,
        "ned": ned_hospedeira,
        "nao_deteccao": nao_deteccao,
        "nao_deteccao_rubin": nao_deteccao_rubin,
    }
    s.update(servicos or {})
    ra, dec, mjd0 = it["ra"], it["dec"], it["mjd0"]
    ficha: dict[str, Any] = {"oid": it["oid"], "ra": ra, "dec": dec, "mag": it.get("mag"), "falhas": {}}
    for nome, chamada in (
        ("tns", lambda: s["tns"](cfg, ra, dec) if cfg else None),
        ("gaia", lambda: s["gaia"](ra, dec)),
        ("skybot", lambda: s["skybot"](ra, dec, mjd0)),
        ("ned", lambda: s["ned"](ra, dec)),
        (
            "nao_deteccao",
            lambda: (
                s["nao_deteccao"](it["oid"], mjd0)
                if it.get("fonte", "ztf") == "ztf"
                else s["nao_deteccao_rubin"](it["oid"], mjd0)
            ),
        ),
    ):
        ficha[nome], erro = _tentar(chamada)
        if erro:
            ficha["falhas"][nome] = erro
    if ficha["ned"] and ficha["mag"] is not None:
        ficha["M"] = magnitude_absoluta(float(ficha["mag"]), ficha["ned"]["z"])
    motivos = []
    if not cfg:
        motivos.append("sem credenciais do TNS: não deu para conferir se já foi reportado")
    elif ficha["tns"]:
        motivos.append(f"já está no TNS: {', '.join(ficha['tns'])}")
    estrelas = [g for g in ficha["gaia"] or [] if (g["paralaxe_sigma"] or 0) > PARALAXE_SIGMA]
    if estrelas:
        motivos.append(f'estrela do Gaia a {estrelas[0]["sep"]}" (paralaxe {estrelas[0]["paralaxe_sigma"]:.0f} sigma)')
    if ficha["skybot"]:
        motivos.append(f"asteroide conhecido na posição: {ficha['skybot'][0][:60]}")
    if not ficha["nao_deteccao"] and not fonte_nova_rubin(it):
        motivos.append("sem última não-detecção (o TNS exige)")
    if len(it.get("curva") or []) < DETECCOES_MIN:
        motivos.append(
            f"só {len(it.get('curva') or [])} detecção: espere a próxima (pode ser artefato ou asteroide desconhecido)"
        )
    for nome in ("tns", "gaia", "skybot"):
        if nome in ficha["falhas"]:
            motivos.append(f"{nome} não respondeu: refaça a ficha")
    avisos = []
    h = ficha["ned"]
    if h and h["sep"] == h["sep"] and h["sep"] < NUCLEAR:  # sep == sep: não é nan
        avisos.append(f'no núcleo da galáxia ({h["sep"]}"): pode ser núcleo ativo (AGN) ou evento de maré, não só supernova')
    ficha["motivos"], ficha["avisos"] = motivos, avisos
    ficha["pronto"] = not motivos
    return ficha


def texto(ficha: dict[str, Any]) -> str:
    """Resumo de poucas linhas para mostrar antes de pedir aprovação."""
    falhas = ficha.get("falhas", {})
    linhas = [f"{ficha['oid']}  RA {ficha['ra']:.5f}  Dec {ficha['dec']:.5f}  mag {ficha.get('mag')}"]
    h = ficha.get("ned")
    if h:
        linhas.append(f'galáxia: {h["nome"]} z={h["z"]} a {h["sep"]}" -> M = {ficha.get("M")}')
    else:
        linhas.append("NED: não respondeu" if "ned" in falhas else 'galáxia: nenhuma com redshift no NED a 15"')
    g = ficha.get("gaia")
    perto = f'{len(g)} fonte(s), a mais perto a {g[0]["sep"]}" G={g[0]["g"]}' if g else ""
    linhas.append("Gaia: " + ("não respondeu" if "gaia" in falhas else perto or 'nenhuma fonte a 3"'))
    sky = ficha["skybot"][0][:70] if ficha.get("skybot") else "nenhum asteroide conhecido"
    linhas.append("SkyBoT: " + ("não respondeu" if "skybot" in falhas else sky))
    n = ficha.get("nao_deteccao")
    linhas.append("última não-detecção: " + (f"MJD {n['mjd']:.3f} lim {n['limite']}" if n else "nenhuma"))
    linhas += [f"atenção: {a}" for a in ficha.get("avisos", [])]
    linhas.append("PRONTO PARA REPORTAR" if ficha["pronto"] else "NÃO REPORTAR: " + "; ".join(ficha["motivos"]))
    return "\n".join(linhas)
