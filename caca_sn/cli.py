"""Linha de comando: busca, avalia, grava resultados.json e report.html."""

from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from . import (
    acompanhamento,
    alertas,
    avaliacao,
    catalogos,
    curva,
    envio,
    ficha,
    novas_anas,
    novidades,
    registro,
    rubin,
    tns_local,
)
from .rascunho import rascunho
from .rede import gravar_json, gravar_texto, ler_json
from .relatorio import relatorio

# onde ficam resultados, relatório, log e tns.json: ao lado do programa, ou CACASN_SAIDA (ex.: Docker)
PASTA = os.environ.get("CACASN_SAIDA") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTES = ("ztf", "rubin")
# consulta ao TNS (10/min) só para os melhores do Rubin que o Fink não marcou
TOP_RUBIN_TNS = 30
# no ZTF o TNS só é consultado de 15 para cima: no teste de 30 dias (out/2026) todos os
# 6 alarmes (>= 18, fora do TNS) estavam acima disso, e as consultas caem de 447 para 159
CORTE_TNS = 15.0
# VSX (variáveis conhecidas) só para os melhores do ZTF
TOP_CONFERIR = 20


class Falhou:
    """Marca o objeto que deu erro (diferente de None = não é candidato), para a 2ª passada."""


FALHOU = Falhou()


def _seguro(obj: dict[str, Any], tns: dict[str, Any] | None) -> dict[str, Any] | None | Falhou:
    try:
        return avaliacao.avaliar(obj, tns)
    except Exception as e:  # um objeto quebrado não derruba a rodada
        registro.obter().warning("erro_no_objeto", oid=obj.get("oid"), erro=repr(e))
        return FALHOU


def tns_com_cache(itens: list[dict[str, Any]], tns: dict[str, Any] | None, pasta: str, corte: float, indice: Any = None) -> None:
    """Situação no TNS só para quem pode disparar o alarme (nota >= corte).

    Ordem: cache dos já reportados (tns_cache.json) -> arquivo completo do TNS em cache
    local (tns_local) -> API. A API só é usada para confirmar o "não está" de quem
    chega no corte do alarme, porque o arquivo local é da meia-noite UTC."""
    caminho = os.path.join(pasta, "tns_cache.json")
    cache: dict[str, str] = ler_json(caminho, {})
    for it in sorted(itens, key=lambda x: -x["nota"]):
        if it["oid"] in cache:
            it["conhecido"] = cache[it["oid"]]
            continue
        if it["nota"] < corte:
            it["conhecido"] = "TNS não consultado (nota baixa)"
            continue
        if indice is not None:
            nomes = indice.buscar(it["ra"], it["dec"])
            if nomes:
                it["conhecido"] = "TNS: " + ", ".join(nomes)
            elif it["nota"] < alertas.AVISO:
                it["conhecido"] = "NÃO está no TNS — dá para reportar (arquivo do TNS de hoje 00h UTC)"
            else:
                it["conhecido"] = avaliacao.situacao_tns(tns, it["ra"], it["dec"])
        else:
            it["conhecido"] = avaliacao.situacao_tns(tns, it["ra"], it["dec"])
        if it["conhecido"].startswith("TNS:"):
            cache[it["oid"]] = it["conhecido"]
    gravar_json(caminho, cache)


def rodar_ztf(
    dias: float, prob: float, tns: dict[str, Any] | None, pasta: str = PASTA, a_partir: float = 0
) -> list[dict[str, Any]]:
    objs = avaliacao.candidatos(dias, prob, a_partir)
    with ThreadPoolExecutor(4) as ex:
        resultados = list(ex.map(lambda o: _seguro(o, None), objs))
    # 2ª passada, um por vez, para quem falhou (em geral limite da ALeRCE em rodadas grandes)
    falhos = [o for o, r in zip(objs, resultados) if r is FALHOU]
    resultados = [r for r in resultados if r is not FALHOU] + [_seguro(o, None) for o in falhos]
    itens = [r for r in resultados if isinstance(r, dict)]
    perdidos = sum(r is FALHOU for r in resultados)
    if falhos:
        registro.obter().info("segunda_passada", tentados=len(falhos), perdidos=perdidos)
    for i in itens:
        i.setdefault("fonte", "ztf")
    for it in sorted(itens, key=lambda x: -x["nota"])[:TOP_CONFERIR]:
        avaliacao.conferir_conhecidos(it)
    tns_com_cache(itens, tns, pasta, CORTE_TNS, tns_local.carregar(tns, pasta))
    return itens


def vigiar_fluxo_rubin(pasta: str) -> bool:
    """O Rubin está mandando alertas? Avisa uma vez quando o fluxo volta depois de parado."""
    log = registro.obter()
    caminho = os.path.join(pasta, "rubin_estado.json")
    estado = ler_json(caminho, {})
    noite = rubin.ultima_noite()
    if noite is None:
        log.warning("rubin_sem_estatistica")
        return False
    dias = (datetime.now(timezone.utc) - datetime.strptime(noite, "%Y%m%d").replace(tzinfo=timezone.utc)).days
    ativo = dias <= rubin.DIAS_PARADO
    if ativo and estado.get("parado_desde"):
        alertas.notificar(
            "CacaSN: o Rubin voltou!",
            f"Alertas do Rubin de novo (noite {noite}). Pouca concorrência agora.",
            os.path.join(pasta, "report.html"),
        )
    if not ativo:
        log.warning("rubin_parado", ultima_noite=noite, dias=dias)
    gravar_json(caminho, {"ultima_noite": noite, "parado_desde": None if ativo else (estado.get("parado_desde") or noite)})
    return ativo


def rodar_rubin(dias: float, tns: dict[str, Any] | None) -> list[dict[str, Any]]:
    itens = [rubin.objeto(oid, als) for oid, als in rubin.por_objeto(rubin.alertas(dias)).items()]
    itens.sort(key=lambda x: -x["nota"])
    for it in itens[:TOP_RUBIN_TNS]:
        completa = rubin.curva_completa(it["oid"].replace("LSST ", ""))
        if completa:
            it["mjd0"], it["curva"] = completa
            dias = curva.duracao(it["curva"])
            if dias > curva.DURACAO_VARIAVEL:
                it["nota"] = round(it["nota"] - 5, 2)
                it["motivos"].append(f"detectado há {dias:.0f} dias ({len(it['curva'])} pontos): varia há meses")
        avaliacao.conferir_conhecidos(it)
    itens.sort(key=lambda x: -x["nota"])
    for i, it in enumerate(itens):
        if it["conhecido"]:
            continue
        if tns and i < TOP_RUBIN_TNS:
            it["conhecido"] = avaliacao.situacao_tns(tns, it["ra"], it["dec"])
        else:
            it["conhecido"] = "TNS não consultado (fora do top)" if tns else "TNS não consultado (falta tns.json)"
    return itens


def rodar(
    dias: float,
    prob: float,
    avisar: bool,
    pasta: str = PASTA,
    fontes: tuple[str, ...] = FONTES,
    a_partir: float = 0,
) -> list[dict[str, Any]]:
    log = registro.obter()
    tns = catalogos.tns_carregar(pasta)
    itens: list[dict[str, Any]] = []
    if "ztf" in fontes:
        itens += rodar_ztf(dias, prob, tns, pasta, a_partir)
    if "rubin" in fontes:
        vigiar_fluxo_rubin(pasta)
        itens += rodar_rubin(dias, tns)
    for it in itens:
        if (m := curva.motivo_subida(it.get("curva", []), it.get("idade", 99))) and m not in it["motivos"]:
            it["motivos"].append(m)
    gravar_json(os.path.join(pasta, "resultados.json"), itens, indent=1)
    gravar_texto(os.path.join(pasta, "report.html"), relatorio(itens))
    for fonte in fontes:
        sel = [i for i in itens if i.get("fonte") == fonte]
        log.info(
            "rodada",
            fonte=fonte,
            dias=dias,
            avaliados=len(sel),
            fora_do_tns=sum(i["conhecido"].startswith("NÃO") for i in sel),
            melhor_nota=max((i["nota"] for i in sel), default=0),
            top=[[i["oid"], i["nota"], i["conhecido"]] for i in sorted(sel, key=lambda x: -x["nota"])[:5]],
        )
    if avisar:
        novos = alertas.avisar_novos(itens, pasta)
        try:
            oferecer_envio(novos, pasta)
        except Exception as e:  # erro no envio não derruba a rodada
            log.error("oferecer_envio_falhou", erro=repr(e))
    acompanhamento.verificar(tns, pasta)
    vistos = {str(i["oid"]).replace("LSST ", "") for i in itens} | set(ler_json(os.path.join(pasta, "tns_cache.json"), {}))
    novidades.verificar(tns, pasta, vistos, buscar_hoje=novidades.buscar_modificados)
    if avisar:  # no agendamento (a cada 3 h) caça também novas anãs
        try:
            novas_anas.rodar(pasta, avisar=True, cfg=tns)
        except Exception as e:  # falha aqui não derruba a rodada de supernovas
            log.error("novas_anas_falhou", erro=repr(e))
    return itens


def _candidato(oid: str, pasta: str) -> dict[str, Any] | None:
    itens = ler_json(os.path.join(pasta, "resultados.json"), [])
    return next((i for i in itens if i["oid"] == oid or i["oid"] == f"LSST {oid}"), None)


def _gravar_rascunho(it: dict[str, Any], relatorio: dict[str, Any], pasta: str) -> str:
    os.makedirs(os.path.join(pasta, "rascunhos"), exist_ok=True)
    destino = os.path.join(pasta, "rascunhos", f"{it['oid'].replace(' ', '_')}.json")
    gravar_json(destino, relatorio, indent=2, ensure_ascii=False)
    return destino


def gerar_rascunho(oid: str, pasta: str = PASTA) -> int:
    """Escreve rascunhos/<oid>.json para revisar e enviar pelo site do TNS."""
    it = _candidato(oid, pasta)
    anas = ler_json(os.path.join(pasta, novas_anas.SAIDA_JSON), [])
    ana: dict[str, Any] | None = next((i for i in anas if i["oid"] == oid), None)
    if it is None:
        if ana is None:
            print(f"{oid} não está no último resultados.json nem em {novas_anas.SAIDA_JSON}")
            return 1
        it = ana
        if it.get("suspeito"):
            print(f"atenção: {it['suspeito']}")
        relatorio, pendencias = novas_anas.rascunho_nova_ana(it, catalogos.tns_carregar(pasta))
    else:
        if not it["conhecido"].startswith("NÃO"):
            print(f"atenção: {it['conhecido']}")
        relatorio, pendencias = rascunho(it, catalogos.tns_carregar(pasta))
    print(_gravar_rascunho(it, relatorio, pasta))
    for p in pendencias:
        print(f"  pendente: {p}")
    print("  nada foi enviado. Revise e envie pelo site do TNS (teste antes em https://sandbox.wis-tns.org).")
    return 0


def preparar(oid: str, pasta: str = PASTA) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]] | None:
    """Ficha + rascunho de um candidato da última rodada (não envia)."""
    it = _candidato(oid, pasta)
    if it is None:
        print(f"{oid} não está no último resultados.json")
        return None
    cfg = catalogos.tns_carregar(pasta)
    f = ficha.montar(it, cfg)
    os.makedirs(os.path.join(pasta, "rascunhos"), exist_ok=True)
    gravar_json(os.path.join(pasta, "rascunhos", f"{it['oid'].replace(' ', '_')}.ficha.json"), f, indent=2, ensure_ascii=False)
    relatorio, pendencias = rascunho(it, cfg, f)
    _gravar_rascunho(it, relatorio, pasta)
    return it, f, relatorio, pendencias


def mostrar_ficha(oid: str, pasta: str = PASTA) -> int:
    r = preparar(oid, pasta)
    if r is None:
        return 1
    _, f, _, pendencias = r
    print(ficha.texto(f))
    for p in pendencias:
        print(f"  pendente: {p}")
    print("  nada foi enviado.")
    return 0


def oferecer_envio(novos: list[dict[str, Any]], pasta: str, aprovar: Any = alertas.pedir_aprovacao) -> list[str]:
    """No agendamento: para cada candidato novo do ZTF com ficha pronta, pergunta numa
    janela se envia. Só com "aprovar_por_dialogo": true no tns.json; devolve os nomes AT."""
    cfg = catalogos.tns_carregar(pasta) or {}
    if not cfg.get("aprovar_por_dialogo"):
        return []
    log, nomes = registro.obter(), []
    for novo in novos:
        if novo.get("fonte", "ztf") != "ztf":
            continue
        r = preparar(str(novo["oid"]), pasta)
        if r is None:
            continue
        it, f, relatorio, pendencias = r
        if not f["pronto"] or pendencias:
            log.info("ficha_nao_pronta", oid=it["oid"], motivos=f["motivos"], pendencias=pendencias)
            continue
        if not aprovar(f"CacaSN: enviar {it['oid']}?", ficha.texto(f)):
            log.info("envio_adiado", oid=it["oid"])
            continue
        res = envio.enviar(relatorio, cfg)
        log.warning("envio_tns", oid=it["oid"], sandbox=False, ok=res["ok"], nome=res["nome"], erros=res["erros"])
        if res["ok"] and res["nome"]:
            acompanhamento.adicionar(pasta, res["nome"])
            nomes.append(res["nome"])
            alertas.notificar("CacaSN: enviado!", f"{it['oid']} virou AT {res['nome']}", os.path.join(pasta, "report.html"))
        else:
            alertas.notificar(
                "CacaSN: o TNS recusou", f"{it['oid']}: " + "; ".join(res["erros"])[:180], os.path.join(pasta, "report.html")
            )
    return nomes


def enviar(oid: str, pasta: str = PASTA, sandbox: bool = False, perguntar: Any = input) -> int:
    """Mostra a ficha e só envia se o usuário digitar o OID para confirmar."""
    r = preparar(oid, pasta)
    if r is None:
        return 1
    it, f, relatorio, pendencias = r
    print(ficha.texto(f))
    if not f["pronto"] or pendencias:
        for p in pendencias:
            print(f"  pendente: {p}")
        print("  não enviado: resolva os motivos acima primeiro.")
        return 1
    destino = "SANDBOX (teste)" if sandbox else "TNS (público, definitivo)"
    resposta = perguntar(f"Enviar {it['oid']} ao {destino}? Digite o OID para confirmar: ").strip()
    if resposta != str(it["oid"]):
        print("  não enviado.")
        return 1
    res = envio.enviar(relatorio, catalogos.tns_carregar(pasta) or {}, sandbox=sandbox)
    registro.obter().warning("envio_tns", oid=it["oid"], sandbox=sandbox, ok=res["ok"], nome=res["nome"], erros=res["erros"])
    if res["ok"]:
        print(f"  enviado: AT {res['nome']} (relatório {res['report_id']})")
        if not sandbox and res["nome"]:
            acompanhamento.adicionar(pasta, res["nome"])
        return 0
    print(f"  o TNS recusou (relatório {res['report_id']}): " + "; ".join(res["erros"]))
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="cacasn", description="Caçador de supernovas nos alertas do ZTF (ALeRCE) e do Rubin (Fink)."
    )
    ap.add_argument(
        "--dias",
        type=float,
        default=21,
        help="primeira detecção há no máximo N dias (a nota sobe com as noites: os 2 de out/2026 tinham 16-20 dias)",
    )
    ap.add_argument(
        "--a-partir",
        type=float,
        default=0,
        metavar="N",
        help="ZTF: pula os N dias mais recentes (ex.: --dias 120 --a-partir 30 procura no passado)",
    )
    ap.add_argument("--prob", type=float, default=0.5, help="ZTF: probabilidade mínima de SN no stamp classifier")
    ap.add_argument("--fonte", choices=(*FONTES, "ambas"), default="ambas", help="de onde buscar os alertas")
    ap.add_argument(
        "--avisar",
        action="store_true",
        help=f"avisa candidato fora do TNS (ZTF: nota >= {alertas.AVISO}; Rubin: >= {rubin.AVISO})",
    )
    ap.add_argument(
        "--acompanhar", metavar="NOME", help="passa a acompanhar um objeto do TNS (ex.: 2026agsv) e avisa quando for classificado"
    )
    ap.add_argument("--rascunho", metavar="OID", help="gera o relatório para o TNS de um candidato da última rodada (não envia)")
    ap.add_argument("--ficha", metavar="OID", help="checagens antes de reportar (TNS, Gaia, SkyBoT, NED) e rascunho; não envia")
    ap.add_argument("--enviar", metavar="OID", help="mostra a ficha e envia ao TNS pela API depois que você digita o OID")
    ap.add_argument("--sandbox", action="store_true", help="com --enviar: usa o sandbox do TNS (teste, não público)")
    ap.add_argument(
        "--novas-anas",
        action="store_true",
        help="só caça novas anãs em erupção (CV/Nova da ALeRCE fora do TNS e do VSX); grava novas_anas.html",
    )
    args = ap.parse_args(argv)
    if args.rascunho:
        return gerar_rascunho(args.rascunho)
    if args.ficha:
        return mostrar_ficha(args.ficha)
    if args.enviar:
        registro.configurar(os.path.join(PASTA, "cacasn.log"))
        return enviar(args.enviar, sandbox=args.sandbox)
    if args.acompanhar:
        acompanhamento.adicionar(PASTA, args.acompanhar)
        acompanhamento.verificar(catalogos.tns_carregar(PASTA), PASTA)
        print(acompanhamento.ler_json(os.path.join(PASTA, acompanhamento.ARQUIVO), {}))
        return 0
    registro.configurar(os.path.join(PASTA, "cacasn.log"))
    if args.novas_anas:
        aprovadas = novas_anas.rodar(PASTA, avisar=args.avisar)
        print(f"{len(aprovadas)} nova(s) anã(s)")
        print(os.path.join(PASTA, novas_anas.SAIDA_HTML))
        return 0
    fontes = FONTES if args.fonte == "ambas" else (args.fonte,)
    try:
        rodar(args.dias, args.prob, args.avisar, fontes=fontes, a_partir=args.a_partir)
    except Exception as e:
        registro.obter().error("rodada_falhou", erro=repr(e))
        raise
    print(os.path.join(PASTA, "report.html"))
    return 0
