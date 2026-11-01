import json
import os
import tempfile
import threading
import unittest
import urllib.request
from unittest import mock

from caca_sn import servidor

ITENS = [
    {"oid": "ZTF26bom", "fonte": "ztf", "nota": 20.0, "conhecido": "NÃO está no TNS — dá para reportar", "ra": 1, "dec": 2},
    {"oid": "ZTF26baixo", "fonte": "ztf", "nota": 10.0, "conhecido": "NÃO está no TNS — dá para reportar"},
    {"oid": "LSST 1", "fonte": "rubin", "nota": 14.0, "conhecido": "NÃO está no TNS — dá para reportar"},
    {"oid": "ZTF26velho", "fonte": "ztf", "nota": 25.0, "conhecido": "TNS: AT 2026aaa"},
]
FICHA_OK = {"pronto": True, "motivos": []}


def _preparar(f=FICHA_OK, pend=()):
    return mock.Mock(side_effect=lambda oid, pasta: ({"oid": oid}, f, {"at_report": {}}, list(pend)))


class TesteRotas(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        with open(os.path.join(self.d, "resultados.json"), "w") as f:
            json.dump(ITENS, f)
        self.reg = mock.patch.object(servidor.registro, "obter").start()
        mock.patch.object(servidor.catalogos, "tns_carregar", return_value={"api_key": "k"}).start()
        self.addCleanup(mock.patch.stopall)

    def test_candidatos_so_fora_do_tns_e_acima_do_limite(self):
        self.assertEqual([c["oid"] for c in servidor.candidatos(self.d)], ["ZTF26bom", "LSST 1"])

    def test_ignorar_tira_da_lista(self):
        servidor.ignorar(self.d, "ZTF26bom")
        self.assertEqual([c["oid"] for c in servidor.candidatos(self.d)], ["LSST 1"])

    def test_enviar_exige_confirmacao(self):
        app = servidor.App(self.d, _preparar(), enviar=mock.Mock())
        self.assertEqual(app.rota("POST", "/enviar", {"oid": "ZTF26bom", "confirmar": "x"}, {})[0], 400)
        app.enviar.assert_not_called()

    def test_enviar_com_ficha_pendente_recusa(self):
        app = servidor.App(self.d, _preparar({"pronto": False, "motivos": ["no TNS"]}), enviar=mock.Mock())
        codigo, r = app.rota("POST", "/enviar", {"oid": "ZTF26bom", "confirmar": "ZTF26bom"}, {})
        self.assertEqual((codigo, r["motivos"]), (409, ["no TNS"]))
        app.enviar.assert_not_called()

    def test_enviar_ok_acompanha_e_some_da_lista(self):
        res = {"ok": True, "nome": "2026zzz", "erros": [], "report_id": 1}
        app = servidor.App(self.d, _preparar(), enviar=mock.Mock(return_value=res))
        with mock.patch.object(servidor.acompanhamento, "adicionar") as ad:
            codigo, r = app.rota("POST", "/enviar", {"oid": "ZTF26bom", "confirmar": "ZTF26bom"}, {})
        self.assertEqual((codigo, r["nome"]), (200, "2026zzz"))
        ad.assert_called_once_with(self.d, "2026zzz")
        self.assertNotIn("ZTF26bom", [c["oid"] for c in servidor.candidatos(self.d)])

    def test_eventos_filtra_e_usa_desde(self):
        linhas = [
            {"event": "rodada", "timestamp": "2026-11-01T01:00:00"},
            {"event": "alerta", "timestamp": "2026-11-01T01:00:00", "titulo": "a"},
            {"event": "alerta", "timestamp": "2026-11-01T02:00:00", "titulo": "b"},
        ]
        with open(os.path.join(self.d, "cacasn.log"), "w") as f:
            f.write("\n".join(json.dumps(x) for x in linhas) + "\nlixo\n")
        self.assertEqual([e["titulo"] for e in servidor.eventos(self.d)], ["a", "b"])
        self.assertEqual([e["titulo"] for e in servidor.eventos(self.d, "2026-11-01T01:00:00")], ["b"])

    def test_config_cria_token_privado(self):
        cfg = servidor.config(self.d)
        self.assertGreater(len(cfg["token"]), 20)
        self.assertEqual(os.stat(os.path.join(self.d, servidor.ARQUIVO)).st_mode & 0o777, 0o600)
        self.assertEqual(servidor.config(self.d), cfg)


class TesteHTTP(unittest.TestCase):
    def test_token_obrigatorio_e_json(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "resultados.json"), "w") as f:
            json.dump(ITENS, f)
        srv = servidor.criar(servidor.App(d, _preparar()), "segredo", 0, host="127.0.0.1")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_address[1]}/candidatos"
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(url, timeout=5)
        self.assertEqual(e.exception.code, 401)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer segredo"})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual([c["oid"] for c in json.load(r)], ["ZTF26bom", "LSST 1"])


if __name__ == "__main__":
    unittest.main()
