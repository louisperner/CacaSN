"""Servidor local para o app do iPhone: candidatos, ficha, envio ao TNS com aprovação,
descobertas acompanhadas e eventos para notificação.

Só na rede local, com token (`servidor.json`, criado na primeira vez). A chave do TNS nunca sai do Mac:
o app só pede, quem envia é este processo. Anuncia-se por Bonjour (`_cacasn._tcp`)."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from . import acompanhamento, alertas, catalogos, envio, ficha, registro, rubin
from .rede import gravar_json, ler_json

ARQUIVO = "servidor.json"
PORTA = 8799
IGNORADOS = "ignorados.json"
EVENTOS = {"alerta", "envio_tns"}  # toda notificação do Mac passa por "alerta" (título e texto)
CAMPOS = ("oid", "ra", "dec", "nota", "mag", "fonte", "motivos", "stamps", "curva", "idade", "link", "conhecido", "mjd0")


def config(pasta: str) -> dict[str, Any]:
    """Token e porta; cria `servidor.json` (permissão 600) na primeira vez."""
    caminho = os.path.join(pasta, ARQUIVO)
    cfg = ler_json(caminho, {})
    if not cfg.get("token"):
        cfg = {"token": secrets.token_urlsafe(24), "porta": PORTA}
        gravar_json(caminho, cfg, indent=1)
        os.chmod(caminho, 0o600)
    return cfg


def _limite(it: dict[str, Any]) -> float:
    return rubin.AVISO if it.get("fonte") == "rubin" else alertas.AVISO


def candidatos(pasta: str) -> list[dict[str, Any]]:
    """Candidatos fora do TNS acima do limite de aviso, sem os ignorados, melhores primeiro."""
    ignorados = set(ler_json(os.path.join(pasta, IGNORADOS), []))
    saida = []
    for it in ler_json(os.path.join(pasta, "resultados.json"), []):
        if not str(it.get("conhecido", "")).startswith("NÃO") or it.get("nota", 0) < _limite(it) or it["oid"] in ignorados:
            continue
        c = {k: it.get(k) for k in CAMPOS}
        f = ler_json(os.path.join(pasta, "rascunhos", f"{str(it['oid']).replace(' ', '_')}.ficha.json"), None)
        c["ficha"] = f
        c["ficha_texto"] = ficha.texto(f) if f else None
        saida.append(c)
    return sorted(saida, key=lambda c: -c["nota"])


def descobertas(pasta: str) -> list[dict[str, Any]]:
    lista = ler_json(os.path.join(pasta, acompanhamento.ARQUIVO), {})
    return [dict(v, nome=k) for k, v in sorted(lista.items(), reverse=True)]


def eventos(pasta: str, desde: str = "", limite: int = 200) -> list[dict[str, Any]]:
    """Eventos do log que viram notificação no iPhone, depois de `desde` (timestamp ISO)."""
    saida: list[dict[str, Any]] = []
    try:
        with open(os.path.join(pasta, "cacasn.log"), encoding="utf-8") as f:
            linhas = f.readlines()[-5000:]
    except OSError:
        return []
    for linha in linhas:
        try:
            e = json.loads(linha)
        except ValueError:
            continue
        if e.get("event") in EVENTOS and str(e.get("timestamp", "")) > desde:
            saida.append(e)
    return saida[-limite:]


def ignorar(pasta: str, oid: str) -> None:
    caminho = os.path.join(pasta, IGNORADOS)
    lista = ler_json(caminho, [])
    if oid not in lista:
        gravar_json(caminho, lista + [oid], indent=1)


class App:
    """Lógica das rotas, separada do HTTP para testar sem rede."""

    def __init__(self, pasta: str, preparar: Callable[[str, str], Any], enviar: Callable[..., dict[str, Any]] = envio.enviar):
        self.pasta, self.preparar, self.enviar = pasta, preparar, enviar
        self.trava_envio = threading.Lock()

    def ficha(self, oid: str) -> tuple[int, dict[str, Any]]:
        r = self.preparar(oid, self.pasta)
        if r is None:
            return 404, {"erro": f"{oid} não está no último resultados.json"}
        _, f, _, pendencias = r
        return 200, {
            "ficha": f,
            "texto": ficha.texto(f),
            "pronto": bool(f.get("pronto")) and not pendencias,
            "pendencias": pendencias,
        }

    def enviar_tns(self, oid: str, confirmar: str) -> tuple[int, dict[str, Any]]:
        if not oid or confirmar != oid:
            return 400, {"erro": "confirmação não bate com o OID"}
        with self.trava_envio:  # dois toques seguidos não enviam duas vezes
            r = self.preparar(oid, self.pasta)  # ficha refeita na hora: TNS a 5" de novo
            if r is None:
                return 404, {"erro": f"{oid} não está no último resultados.json"}
            it, f, relatorio, pendencias = r
            if not f["pronto"] or pendencias:
                return 409, {"erro": "ficha não está pronta", "motivos": f.get("motivos", []), "pendencias": pendencias}
            res = self.enviar(relatorio, catalogos.tns_carregar(self.pasta) or {})
            registro.obter().warning(
                "envio_tns", oid=it["oid"], sandbox=False, ok=res["ok"], nome=res["nome"], erros=res["erros"], via="iphone"
            )
            if res["ok"] and res["nome"]:
                acompanhamento.adicionar(self.pasta, res["nome"])
                ignorar(self.pasta, str(it["oid"]))  # some da lista de candidatos
            return (200 if res["ok"] else 502), res

    def rota(self, metodo: str, caminho: str, corpo: dict[str, Any], consulta: dict[str, str]) -> tuple[int, Any]:
        if metodo == "GET" and caminho == "/candidatos":
            return 200, candidatos(self.pasta)
        if metodo == "GET" and caminho == "/descobertas":
            return 200, descobertas(self.pasta)
        if metodo == "GET" and caminho == "/eventos":
            return 200, eventos(self.pasta, consulta.get("desde", ""))
        if metodo == "GET" and caminho == "/estado":
            res = os.path.join(self.pasta, "resultados.json")
            quando = os.path.getmtime(res) if os.path.exists(res) else None
            return 200, {"ultima_rodada": quando, "servidor": "cacasn"}
        oid = str(corpo.get("oid", ""))
        if metodo == "POST" and caminho == "/ficha":
            return self.ficha(oid)
        if metodo == "POST" and caminho == "/enviar":
            return self.enviar_tns(oid, str(corpo.get("confirmar", "")))
        if metodo == "POST" and caminho == "/ignorar":
            ignorar(self.pasta, oid)
            return 200, {"ok": True}
        return 404, {"erro": "rota desconhecida"}


def criar(app: App, token: str, porta: int, host: str = "0.0.0.0") -> ThreadingHTTPServer:  # noqa: S104 (rede local)
    class Tratador(BaseHTTPRequestHandler):
        def _responder(self, metodo: str) -> None:
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth.encode(), f"Bearer {token}".encode()):
                return self._json(401, {"erro": "token"})
            caminho, _, q = self.path.partition("?")
            consulta = dict(p.split("=", 1) for p in q.split("&") if "=" in p)
            corpo: dict[str, Any] = {}
            if metodo == "POST":
                n = min(int(self.headers.get("Content-Length") or 0), 10_000)
                try:
                    corpo = json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return self._json(400, {"erro": "JSON inválido"})
            try:
                codigo, dados = app.rota(metodo, caminho, corpo, consulta)
            except Exception as e:  # erro numa rota não derruba o servidor
                registro.obter().error("servidor_erro", rota=caminho, erro=repr(e))
                codigo, dados = 500, {"erro": repr(e)}
            self._json(codigo, dados)

        def _json(self, codigo: int, dados: Any) -> None:
            corpo = json.dumps(dados, ensure_ascii=False, default=str).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self) -> None:  # noqa: N802
            self._responder("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._responder("POST")

        def log_message(self, *args: Any) -> None:  # silencia o log padrão no stderr
            pass

    return ThreadingHTTPServer((host, porta), Tratador)


def servir(pasta: str, preparar: Callable[[str, str], Any]) -> None:
    cfg = config(pasta)
    porta = int(cfg.get("porta", PORTA))
    srv = criar(App(pasta, preparar), cfg["token"], porta)
    bonjour = None
    try:
        bonjour = subprocess.Popen(
            ["dns-sd", "-R", "CacaSN", "_cacasn._tcp", "local", str(porta)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
    registro.obter().info("servidor_no_ar", porta=porta)
    print(f"CacaSN servindo na porta {porta} (token em {os.path.join(pasta, ARQUIVO)})")
    try:
        srv.serve_forever()
    finally:
        if bonjour:
            bonjour.terminate()
