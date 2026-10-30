"""Aviso quando aparece candidato forte que ninguém reportou ao TNS."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

from .rede import gravar_json, ler_json
from .registro import obter

# 60% do que os grupos profissionais reportaram passa de 18; nenhum candidato
# falso da varredura de 23/10/2026 passou
AVISO = 18.0


def corte(item: dict[str, Any]) -> float:
    """O Rubin tem escala de nota própria (ver caca_sn/rubin.py)."""
    if item.get("fonte") == "rubin":
        from .rubin import AVISO as AVISO_RUBIN

        return AVISO_RUBIN
    return AVISO


def notificar(titulo: str, texto: str, relatorio: str) -> None:
    """Notificação do macOS; em outros sistemas vai para o log."""
    obter().warning("alerta", titulo=titulo, texto=texto)
    if sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", f'display notification {json.dumps(texto)} with title {json.dumps(titulo)} sound name "Glass"'],
            check=False,
        )
        subprocess.run(["open", relatorio], check=False)


ENVIAR = "Enviar ao TNS"
# a janela some sozinha depois disso e conta como "Depois": nada é enviado sem clique
ESPERA_APROVACAO = 1800


def pedir_aprovacao(titulo: str, texto: str, espera: int = ESPERA_APROVACAO) -> bool:
    """Janela do macOS com os botões 'Depois' e 'Enviar ao TNS'. Só devolve True com o
    clique em Enviar; fora do macOS, sem resposta ou com erro, devolve False."""
    if sys.platform != "darwin":
        return False
    script = (
        f"display dialog {json.dumps(texto)} with title {json.dumps(titulo)} "
        f'buttons {{"Depois", {json.dumps(ENVIAR)}}} default button "Depois" giving up after {int(espera)}'
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    return r.returncode == 0 and f"button returned:{ENVIAR}" in r.stdout and "gave up:true" not in r.stdout


def avisar_novos(itens: list[dict[str, Any]], pasta: str) -> list[dict[str, Any]]:
    """Avisa uma vez por objeto; devolve os que foram avisados agora."""
    caminho = os.path.join(pasta, "avisados.json")
    vistos = set(ler_json(caminho, []))
    novos = [i for i in itens if i["conhecido"].startswith("NÃO") and i["nota"] >= corte(i) and i["oid"] not in vistos]
    if not novos:
        return []
    vistos.update(i["oid"] for i in novos)
    gravar_json(caminho, sorted(vistos))
    melhor = max(novos, key=lambda i: i["nota"])
    notificar(
        "CacaSN: reporte já!",
        f"{len(novos)} candidato(s) fora do TNS. Melhor: {melhor['oid']} nota {melhor['nota']}",
        os.path.join(pasta, "report.html"),
    )
    return novos
