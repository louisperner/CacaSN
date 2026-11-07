"""Caçador de novas anãs (dwarf novae: variáveis cataclísmicas em erupção) nos alertas do ZTF.

Método validado à mão em 25/10/2026 (achou 3 inéditas, hoje AT 2026agtu/agtv/agtw):
1. candidatos CV/Nova dos classificadores de curva da ALeRCE (primeira detecção nos últimos 60 dias);
2. fora do TNS (índice local, 3") e fora do VSX (UM cruzamento em lote no CDS X-Match, 5");
3. curva: quase só detecções positivas, subiu >= 2 mag, >= 4 detecções, erupção curta (<= 40 dias)
   e cor não vermelha (g-r <= 1; uma variável vermelha lenta passava sem isso);
4. Gaia DR3 só para os aprovados, com o movimento próprio projetado até a última detecção: estrela que
   andou até a posição, ou estrela mais brilhante que o pico em cima dela (raio maior se brilhante),
   reprova; Gaia fora do ar marca "suspeito"."""

from __future__ import annotations

import csv
import html
import io
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import alertas, catalogos, registro, tns_local
from .avaliacao import API, STAMP
from .rascunho import rascunho
from .rede import HDR, espera_429, get_json, gravar_json, gravar_texto, ler_json, mjd_agora
from .relatorio import mini_curva

CLASSIFICADORES = ("lc_classifier", "lc_classifier_BHRF_forced_phot_stochastic")
XMATCH = "http://cdsxmatch.u-strasbg.fr/xmatch/api/v1/sync"
DIAS = 60
PROB = 0.4
RAIO_TNS = 3.0  # arcsec
RAIO_VSX = 5.0  # arcsec
# critério (validado em 25/10/2026)
MIN_POSITIVAS = 0.9
MIN_AMPLITUDE = 2.0
MIN_DETECCOES = 4
MAX_DURACAO = 40.0
MAX_COR = 1.0  # g-r acima disso = estrela vermelha variando, não CV
ESTADO = "novas_anas_estado.json"
SAIDA_JSON = "novas_anas.json"
SAIDA_HTML = "novas_anas.html"
# TODO: confirmar no sandbox do TNS o id do at_type "Other" (no rascunho.py só "1" = PSN é conhecido).
# Enquanto não houver confirmação, o rascunho sai com at_type vazio e uma pendência.
AT_TYPE_OUTRO: str | None = None


def positiva(d: dict[str, Any]) -> bool:
    return d.get("isdiffpos") in (1, "t", True, "1")


def candidatos(dias: float = DIAS, prob: float = PROB) -> list[dict[str, Any]]:
    """Objetos CV/Nova dos dois classificadores de curva da ALeRCE, sem repetir oid."""
    vistos: dict[str, dict[str, Any]] = {}
    for c in CLASSIFICADORES:
        q = urllib.parse.urlencode(
            [
                ("classifier", c),
                ("class_name", "CV/Nova"),
                ("probability", prob),
                ("firstmjd", f"{mjd_agora() - dias:.3f}"),
                ("page_size", 500),
                ("order_by", "probability"),
                ("order_mode", "DESC"),
            ]
        )
        for o in get_json(f"{API}/objects/?{q}").get("items", []):
            if o.get("meanra") is not None and o.get("meandec") is not None:
                vistos.setdefault(o["oid"], o)
    return list(vistos.values())


def _multipart(campos: dict[str, str], arquivo: tuple[str, str, bytes]) -> tuple[bytes, str]:
    limite = uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f'--{limite}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    nome, arq, conteudo = arquivo
    partes.append(
        f'--{limite}\r\nContent-Disposition: form-data; name="{nome}"; filename="{arq}"\r\n'
        "Content-Type: text/csv\r\n\r\n".encode()
        + conteudo
        + b"\r\n"
    )
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


def postar(url: str, corpo: bytes, tipo: str, timeout: float = 120, tentativas: int = 3) -> bytes:
    """POST com novas tentativas; no 429 espera o que o servidor mandar (como rede.abrir)."""
    falhas_429 = i = 0
    while True:
        try:
            req = urllib.request.Request(url, data=corpo, headers={**HDR, "Content-Type": tipo})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 and falhas_429 < 6:
                time.sleep(espera_429(e, falhas_429))
                falhas_429 += 1
                continue
            i += 1
            if i >= tentativas:
                raise
        except Exception:
            i += 1
            if i >= tentativas:
                raise


def vsx_em_lote(objs: list[dict[str, Any]], enviar: Any = None) -> dict[str, str]:
    """oid -> "NOME (TIPO)" de quem está no VSX a até 5", numa única consulta ao CDS X-Match.
    Consultar o VizieR um por um abre o disjuntor; aqui, se falhar, a exceção sobe."""
    if not objs:
        return {}
    tabela = io.StringIO()
    w = csv.writer(tabela)
    w.writerow(["oid", "ra", "dec"])
    for o in objs:
        w.writerow([o["oid"], f"{o['meanra']:.6f}", f"{o['meandec']:.6f}"])
    corpo, tipo = _multipart(
        {
            "request": "xmatch",
            "distMaxArcsec": str(RAIO_VSX),
            "RESPONSEFORMAT": "csv",
            "cat2": "vizier:B/vsx/vsx",
            "colRA1": "ra",
            "colDec1": "dec",
        },
        ("cat1", "candidatos.csv", tabela.getvalue().encode()),
    )
    texto = (enviar or postar)(XMATCH, corpo, tipo).decode("utf-8", "replace")
    linhas = list(csv.DictReader(io.StringIO(texto)))
    if linhas and "oid" not in linhas[0]:
        raise ValueError(f"resposta inesperada do X-Match: {texto[:200]!r}")
    achados: dict[str, str] = {}
    for l in linhas:
        nome, tipo_vsx = (l.get("Name") or "?").strip(), (l.get("Type") or "?").strip()
        achados.setdefault(l["oid"], f"{nome} ({tipo_vsx})")
    return achados


def vsx_um_por_um(objs: list[dict[str, Any]], consultar: Any = None) -> dict[str, str]:
    """Plano B quando o X-Match do CDS cai: cone de 5" no VSX objeto por objeto, pelos espelhos do
    VizieR. Se algum ficar sem resposta, a exceção sobe (sem o VSX não dá para dizer que é inédito)."""
    consultar = consultar or catalogos.vizier

    def um(o: dict[str, Any]) -> tuple[str, str | None]:
        linhas = consultar("B/vsx/vsx", o["meanra"], o["meandec"], RAIO_VSX, "Name,Type")
        if linhas is None:
            raise OSError(f"VSX não respondeu para {o['oid']}")
        return o["oid"], (f"{linhas[0][0].strip()} ({linhas[0][1].strip()})" if linhas else None)

    with ThreadPoolExecutor(4) as ex:
        return {oid: v for oid, v in ex.map(um, objs) if v}


def _percentil(valores: list[float], p: float) -> float:
    v = sorted(valores)
    return v[round(p * (len(v) - 1))]


def medir(lc: dict[str, Any]) -> dict[str, Any] | None:
    """Números da curva de brilho (endpoint /lightcurve da ALeRCE); None sem detecção positiva."""
    dets = [d for d in lc.get("detections") or [] if d.get("magpsf") is not None]
    pos = sorted((d for d in dets if positiva(d)), key=lambda d: d["mjd"])
    if not pos:
        return None
    pico = min(d["magpsf"] for d in pos)
    corr = [d["magpsf_corr"] for d in dets if d.get("corrected") and d.get("magpsf_corr") is not None]
    limites = [n["diffmaglim"] for n in lc.get("non_detections") or [] if n.get("diffmaglim") is not None]
    if corr:
        amplitude: float | None = max(corr) - min(corr)
        base = "corrigida"
    elif limites:
        amplitude = _percentil(limites, 0.9) - pico
        base = "limite"
    else:
        amplitude, base = None, ""
    # cor: g-r de noites com os dois filtros
    noites: dict[int, dict[int, list[float]]] = {}
    for d in pos:
        noites.setdefault(int(d["mjd"]), {}).setdefault(d["fid"], []).append(d["magpsf"])
    difs = [sum(f[1]) / len(f[1]) - sum(f[2]) / len(f[2]) for f in noites.values() if 1 in f and 2 in f]
    return {
        "fracao_positiva": round(len(pos) / len(dets), 3),
        "amplitude": None if amplitude is None else round(amplitude, 2),
        "base_amplitude": base,
        "pico": round(pico, 2),
        "duracao": round(pos[-1]["mjd"] - pos[0]["mjd"], 2),
        "deteccoes": len(pos),
        "cor_gr": round(sum(difs) / len(difs), 2) if difs else None,
        "mjd0": pos[0]["mjd"],
        "curva": [(round(d["mjd"] - pos[0]["mjd"], 4), d["fid"], round(d["magpsf"], 2)) for d in pos],
        "candid_stamp": next((d["candid"] for d in pos if d.get("has_stamp")), None),
    }


def reprovado(m: dict[str, Any]) -> str | None:
    """Motivo de não ser nova anã, ou None se passa no critério."""
    if m["fracao_positiva"] < MIN_POSITIVAS:
        return f"só {m['fracao_positiva']:.0%} de detecções positivas"
    if m["amplitude"] is None or m["amplitude"] < MIN_AMPLITUDE:
        return f"amplitude {m['amplitude']} < {MIN_AMPLITUDE}"
    if m["deteccoes"] < MIN_DETECCOES:
        return f"{m['deteccoes']} detecções"
    if m["duracao"] > MAX_DURACAO:
        return f"dura {m['duracao']:.0f} dias"
    if m["cor_gr"] is not None and m["cor_gr"] > MAX_COR:
        return f"vermelha (g-r {m['cor_gr']})"
    return None


def estrela_gaia(it: dict[str, Any]) -> Any:
    """Motivo (texto) se a "erupção" é uma estrela do Gaia (que andou até ali ou brilhante em cima),
    None, ou SEM_RESPOSTA. Usa a data da última detecção para projetar o movimento próprio."""
    curva = it.get("curva") or []
    mjd = it["mjd0"] + (curva[-1][0] if curva else 0.0)
    return catalogos.estrela_no_lugar(it["ra"], it["dec"], mjd, it["pico"])


def avaliar(obj: dict[str, Any]) -> dict[str, Any] | None:
    oid = obj["oid"]
    m = medir(get_json(f"{API}/objects/{oid}/lightcurve") or {})
    if m is None:
        return None
    c = m.pop("candid_stamp")
    stamps = {t: f"{STAMP}?oid={oid}&candid={c}&type={t}&format=png" for t in ("science", "template", "difference")}
    return dict(m, oid=oid, ra=obj["meanra"], dec=obj["meandec"], fonte="ztf", stamps=stamps if c else {}, motivo=reprovado(m))


def _seguro(obj: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return avaliar(obj)
    except Exception as e:  # um objeto quebrado não derruba a rodada
        registro.obter().warning("nova_ana_erro_no_objeto", oid=obj.get("oid"), erro=repr(e))
        return None


def cartao(it: dict[str, Any]) -> str:
    imgs = "".join(f'<img src="{html.escape(u)}" loading="lazy" title="{t}">' for t, u in it["stamps"].items())
    cor = "—" if it["cor_gr"] is None else f"{it['cor_gr']:+.2f}"
    aviso = (
        f'<span class="velho">suspeito: {html.escape(it["suspeito"])}</span>'
        if it.get("suspeito")
        else '<span class="novo">NÃO está no TNS nem no VSX</span>'
    )
    return (
        f'<div class="c"><div class="n">{it["amplitude"]:.1f}</div>{imgs}{mini_curva(it["curva"])}<div>'
        f"<b>{it['oid']}</b> · pico {it['pico']:.2f} · {it['duracao']:.0f} dias · {it['deteccoes']} detecções · "
        f"g-r {cor} · {it['fracao_positiva']:.0%} positivas<br>{aviso}<br>"
        f"<small>RA {it['ra']:.5f} Dec {it['dec']:+.5f} · amplitude pela {it['base_amplitude']}</small> · "
        f'<a href="https://alerce.online/object/{it["oid"]}" target="_blank">ALeRCE</a></div></div>'
    )


def pagina(itens: list[dict[str, Any]]) -> str:
    from .relatorio import CABECALHO

    topo = CABECALHO.replace("CacaSN — candidatos a supernova (ZTF e Rubin)", "CacaSN — novas anãs em erupção (ZTF)").replace(
        "<title>CacaSN</title>", "<title>CacaSN novas anãs</title>"
    )
    corpo = [cartao(it) for it in itens] or ["<p>Nenhuma candidata nesta rodada.</p>"]
    return "\n".join([topo, "<p><small>Número grande = amplitude (mag).</small></p>", *corpo])


def rascunho_nova_ana(it: dict[str, Any], cfg: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Rascunho do TNS (não envia) com tipo "Other" e a observação de nova anã."""
    rel, pendencias = rascunho(it, cfg)
    r = rel["at_report"]["0"]
    if AT_TYPE_OUTRO is None:
        r["at_type"] = ""
        pendencias.append('at_type: escolha "Other" no site do TNS (id ainda não confirmado, ver TODO em novas_anas.py)')
    else:
        r["at_type"] = AT_TYPE_OUTRO
    r["remarks"] = (
        f"likely dwarf nova outburst. Amplitude {it['amplitude']} mag, peak {it['pico']} mag, "
        f"{it['deteccoes']} detections over {it['duracao']:.0f} days; not in VSX. Found with CacaSN."
    )
    return rel, pendencias


def rodar(pasta: str, avisar: bool = False, cfg: Any = None, indice: Any = None, dias: float = DIAS) -> list[dict[str, Any]]:
    """Uma rodada completa. Devolve as aprovadas; [] (sem gravar nem avisar) se TNS ou X-Match faltarem."""
    log = registro.obter()
    cfg = cfg if cfg is not None else catalogos.tns_carregar(pasta)
    indice = indice if indice is not None else tns_local.carregar(cfg, pasta)
    if indice is None:
        log.error("novas_anas_sem_tns", motivo="sem índice local do TNS: não dá para saber o que é inédito")
        return []
    objs = candidatos(dias)
    fora_tns = [o for o in objs if not indice.buscar(o["meanra"], o["meandec"], RAIO_TNS)]
    try:
        vsx = vsx_em_lote(fora_tns)
    except Exception as e:
        log.warning("novas_anas_xmatch_falhou", erro=repr(e), plano_b="VSX um por um nos espelhos do VizieR")
        try:
            vsx = vsx_um_por_um(fora_tns)
        except Exception as e2:
            log.error("novas_anas_vsx_falhou", erro=repr(e2))
            return []
    restantes = [o for o in fora_tns if o["oid"] not in vsx]
    with ThreadPoolExecutor(4) as ex:
        medidos = [m for m in ex.map(_seguro, restantes) if m]
    aprovados = []
    for it in sorted((m for m in medidos if m["motivo"] is None), key=lambda m: -m["amplitude"]):
        g = estrela_gaia(it)
        if g is catalogos.SEM_RESPOSTA:
            it["suspeito"] = "Gaia não respondeu"
        elif g:  # é uma estrela: some do relatório
            log.info("nova_ana_descartada", oid=it["oid"], motivo=g)
            continue
        aprovados.append(it)
    log.info(
        "novas_anas",
        candidatos=len(objs),
        fora_do_tns=len(fora_tns),
        fora_do_vsx=len(restantes),
        aprovados=len(aprovados),
        lista=[[a["oid"], a["amplitude"], a["pico"], a["duracao"]] for a in aprovados],
    )
    gravar_json(os.path.join(pasta, SAIDA_JSON), aprovados, indent=1)
    gravar_texto(os.path.join(pasta, SAIDA_HTML), pagina(aprovados))
    if avisar:
        avisar_novas(aprovados, pasta)
    return aprovados


def avisar_novas(aprovados: list[dict[str, Any]], pasta: str) -> list[dict[str, Any]]:
    """Notifica só as que nunca foram avisadas (estado em novas_anas_estado.json)."""
    caminho = os.path.join(pasta, ESTADO)
    vistos = set(ler_json(caminho, []))
    novas = [a for a in aprovados if a["oid"] not in vistos]
    if not novas:
        return []
    gravar_json(caminho, sorted(vistos | {a["oid"] for a in novas}))
    suspeitas = sum(bool(a.get("suspeito")) for a in novas)
    alertas.notificar(
        "CacaSN: nova anã em erupção!",
        f"{len(novas)} fora do TNS/VSX ({suspeitas} suspeita(s)). Maior: {novas[0]['oid']} {novas[0]['amplitude']} mag",
        os.path.join(pasta, SAIDA_HTML),
    )
    return novas
