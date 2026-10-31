import json
import os
import tempfile
import unittest
from unittest import mock

from caca_sn import avaliacao, catalogos, cli
from tests.ajuda import OBJ, det, falso_get_json


class TesteRodada(unittest.TestCase):
    def test_rodada_completa_grava_tudo(self):
        dets = [det(1, 1, 20.0, stamp=True), det(2, 1, 19.5)]
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(avaliacao, "candidatos", return_value=[OBJ, dict(OBJ, oid="ZTF26quebrado", meanra=None)]),
            mock.patch.object(avaliacao, "get_json", falso_get_json(dets)),
            mock.patch.object(catalogos, "vizier", return_value=[]),
            mock.patch.object(catalogos, "tns_carregar", return_value=None),
        ):
            itens = cli.rodar(3, 0.5, avisar=False, pasta=d, fontes=("ztf",))
            with open(os.path.join(d, "resultados.json")) as f:
                salvos = json.load(f)
            with open(os.path.join(d, "report.html")) as f:
                html = f.read()
        self.assertEqual([i["oid"] for i in itens], ["ZTF26teste"])  # o quebrado não derruba a rodada
        self.assertEqual(salvos[0]["oid"], "ZTF26teste")
        self.assertIn("ZTF26teste", html)

    def _main(self, argv, livre=True):
        trava = mock.MagicMock()
        trava.return_value.__enter__.return_value = livre
        with mock.patch.object(cli, "rodar") as r, mock.patch.object(cli, "trava", trava):
            with mock.patch.object(cli.registro, "configurar"), mock.patch("builtins.print"):
                self.assertEqual(cli.main(argv), 0)
        return r

    def test_argumentos(self):
        r = self._main(["--dias", "1", "--prob", "0.7", "--avisar"])
        r.assert_called_once_with(1.0, 0.7, True, fontes=("ztf", "rubin"), a_partir=0.0, rapido=False)

    def test_rapido_usa_2_dias(self):
        r = self._main(["--rapido", "--avisar"])
        r.assert_called_once_with(2, 0.5, True, fontes=("ztf", "rubin"), a_partir=0.0, rapido=True)

    def test_outra_rodada_em_andamento_pula(self):
        self._main(["--avisar"], livre=False).assert_not_called()

    def test_juntar_mantem_os_antigos(self):
        antigos = [{"oid": "a", "nota": 1}, {"oid": "b", "nota": 2}]
        self.assertEqual(cli.juntar(antigos, [{"oid": "b", "nota": 9}]), [{"oid": "b", "nota": 9}, {"oid": "a", "nota": 1}])

    def test_trava_de_verdade(self):
        with tempfile.TemporaryDirectory() as d, cli.trava(d) as a, cli.trava(d) as b:
            self.assertEqual((a, b), (True, False))


class TesteSegundaPassada(unittest.TestCase):
    def test_quem_falhou_e_tentado_de_novo(self):
        tentativas = {}

        def avaliar(obj, tns):
            tentativas[obj["oid"]] = tentativas.get(obj["oid"], 0) + 1
            if obj["oid"] == "instavel" and tentativas["instavel"] == 1:
                raise OSError("429")
            if obj["oid"] == "quebrado":
                raise ValueError("sempre")
            return {"oid": obj["oid"], "nota": 1.0, "ra": 1, "dec": 2, "motivos": [], "conhecido": ""}

        objs = [{"oid": "bom"}, {"oid": "instavel"}, {"oid": "quebrado"}]
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(cli.avaliacao, "candidatos", return_value=objs),
            mock.patch.object(cli.avaliacao, "avaliar", side_effect=avaliar),
            mock.patch.object(cli.avaliacao, "conferir_conhecidos"),
        ):
            itens = cli.rodar_ztf(3, 0.5, None, pasta=d)
        self.assertEqual(sorted(i["oid"] for i in itens), ["bom", "instavel"])
        self.assertEqual(tentativas, {"bom": 1, "instavel": 2, "quebrado": 2})


class TesteRubinNaRodada(unittest.TestCase):
    def test_so_rubin_e_escolha_da_fonte(self):
        it = {
            "oid": "LSST 1",
            "nota": 14.0,
            "ra": 1.0,
            "dec": 2.0,
            "conhecido": "",
            "fonte": "rubin",
            "mag": 20.0,
            "idade": 1.0,
            "prob": 0.9,
            "drb": 0.99,
            "motivos": [],
            "stamps": {},
            "curva": [],
        }
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(cli.rubin, "alertas", return_value=[]),
            mock.patch.object(cli.rubin, "por_objeto", return_value={1: []}),
            mock.patch.object(cli.rubin, "objeto", return_value=dict(it)),
            mock.patch.object(cli, "vigiar_fluxo_rubin", return_value=True),
            mock.patch.object(cli.avaliacao, "candidatos") as ztf,
            mock.patch.object(catalogos, "tns_carregar", return_value={"bot_id": 1, "bot_name": "b", "api_key": "k"}),
            mock.patch.object(cli.avaliacao, "conferir_conhecidos"),
            mock.patch.object(cli.rubin, "curva_completa", return_value=(61000.0, [(0.0, 1, 20.0)])),
            mock.patch.object(cli.avaliacao, "situacao_tns", return_value="NÃO está no TNS — dá para reportar"),
        ):
            itens = cli.rodar(3, 0.5, avisar=False, pasta=d, fontes=("rubin",))
        ztf.assert_not_called()
        self.assertEqual(itens[0]["conhecido"], "NÃO está no TNS — dá para reportar")

    def test_fonte_na_linha_de_comando(self):
        with mock.patch.object(cli, "rodar") as r, mock.patch.object(cli.registro, "configurar"), mock.patch("builtins.print"):
            cli.main(["--fonte", "rubin"])
        self.assertEqual(r.call_args.kwargs["fontes"], ("rubin",))


class TesteFluxoRubin(unittest.TestCase):
    def test_avisa_uma_vez_quando_volta(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(cli.alertas, "notificar") as n:
            with mock.patch.object(cli.rubin, "ultima_noite", return_value="20260714"):
                self.assertFalse(cli.vigiar_fluxo_rubin(d))
            hoje = cli.datetime.now(cli.timezone.utc).strftime("%Y%m%d")
            with mock.patch.object(cli.rubin, "ultima_noite", return_value=hoje):
                self.assertTrue(cli.vigiar_fluxo_rubin(d))
                self.assertTrue(cli.vigiar_fluxo_rubin(d))
        self.assertEqual(n.call_count, 1)
        self.assertIn("Rubin voltou", n.call_args[0][0])


class TesteDuracaoNaRodada(unittest.TestCase):
    def test_curva_longa_perde_pontos(self):
        it = {
            "oid": "LSST 1",
            "nota": 20.0,
            "ra": 1.0,
            "dec": 2.0,
            "conhecido": "TNS: x",
            "fonte": "rubin",
            "mag": 20.0,
            "idade": 1.0,
            "prob": 0.9,
            "drb": 0.99,
            "motivos": [],
            "stamps": {},
            "curva": [],
        }
        longa = (61000.0, [(0.0, 1, 20.0), (200.0, 1, 20.1)])
        with (
            mock.patch.object(cli.rubin, "alertas", return_value=[]),
            mock.patch.object(cli.rubin, "por_objeto", return_value={1: []}),
            mock.patch.object(cli.rubin, "objeto", return_value=dict(it)),
            mock.patch.object(cli.rubin, "curva_completa", return_value=longa),
            mock.patch.object(cli.avaliacao, "conferir_conhecidos"),
        ):
            r = cli.rodar_rubin(3, None)[0]
        self.assertEqual(r["nota"], 15.0)
        self.assertTrue(any("varia há meses" in m for m in r["motivos"]))


class TesteTnsComCache(unittest.TestCase):
    def itens(self):
        return [
            {"oid": "a", "nota": 20.0, "ra": 1, "dec": 2, "conhecido": ""},
            {"oid": "b", "nota": 19.0, "ra": 1, "dec": 2, "conhecido": ""},
            {"oid": "c", "nota": 5.0, "ra": 1, "dec": 2, "conhecido": ""},
        ]

    def test_so_consulta_acima_do_corte_e_guarda_os_reportados(self):
        respostas = {"a": "TNS: AT 2026x", "b": "NÃO está no TNS — dá para reportar"}
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(cli.avaliacao, "situacao_tns", side_effect=lambda t, ra, dec: respostas[ordem.pop(0)]) as s:
                ordem = ["a", "b"]
                itens = self.itens()
                cli.tns_com_cache(itens, {"x": 1}, d, 15)
            self.assertEqual(s.call_count, 2)
            self.assertEqual(itens[2]["conhecido"], "TNS não consultado (nota baixa)")
            # segunda rodada: "a" vem do cache, "b" (não reportado) é conferido de novo
            with mock.patch.object(cli.avaliacao, "situacao_tns", return_value="TNS: AT 2026y") as s2:
                itens = self.itens()
                cli.tns_com_cache(itens, {"x": 1}, d, 15)
            self.assertEqual(s2.call_count, 1)
            self.assertEqual(itens[0]["conhecido"], "TNS: AT 2026x")
            self.assertEqual(itens[1]["conhecido"], "TNS: AT 2026y")


class TesteTnsLocalNaOrdem(unittest.TestCase):
    def test_local_antes_da_api_e_api_so_no_alarme(self):
        indice = mock.Mock()
        indice.buscar.side_effect = lambda ra, dec: ["AT 2026x"] if ra == 1 else []
        itens = [
            {"oid": "rep", "nota": 20.0, "ra": 1, "dec": 0, "conhecido": ""},
            {"oid": "alarme", "nota": 19.0, "ra": 2, "dec": 0, "conhecido": ""},
            {"oid": "medio", "nota": 16.0, "ra": 3, "dec": 0, "conhecido": ""},
        ]
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(cli.avaliacao, "situacao_tns", return_value="NÃO está no TNS — dá para reportar") as api,
        ):
            cli.tns_com_cache(itens, {"x": 1}, d, 15, indice)
        self.assertEqual(itens[0]["conhecido"], "TNS: AT 2026x")
        self.assertEqual(api.call_count, 1)  # só o de nota de alarme é confirmado na API
        self.assertIn("arquivo do TNS", itens[2]["conhecido"])


class TesteRascunho(unittest.TestCase):
    IT = {
        "oid": "ZTF26x",
        "ra": 10.0,
        "dec": -5.0,
        "mjd0": 61330.25,
        "fonte": "ztf",
        "motivos": ["2 noites"],
        "conhecido": "NÃO está no TNS — dá para reportar",
        "curva": [(0.0, 1, 19.8), (1.0, 2, 19.5)],
        "nota": 20,
    }

    def test_gera_arquivo_e_avisa_pendencias(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print") as p:
            rede_json = os.path.join(d, "resultados.json")
            with open(rede_json, "w") as f:
                json.dump([self.IT], f)
            with mock.patch.object(catalogos, "tns_carregar", return_value={}):
                self.assertEqual(cli.gerar_rascunho("ZTF26x", pasta=d), 0)
            with open(os.path.join(d, "rascunhos", "ZTF26x.json")) as f:
                r = json.load(f)["at_report"]["0"]
        self.assertEqual(r["internal_name"], "ZTF26x")
        self.assertTrue(any("reporting_groupid" in str(c) for c in p.call_args_list))
        self.assertTrue(any("nada foi enviado" in str(c) for c in p.call_args_list))

    def test_oid_que_nao_existe(self):
        with tempfile.TemporaryDirectory() as d, mock.patch("builtins.print"):
            self.assertEqual(cli.gerar_rascunho("nada", pasta=d), 1)


if __name__ == "__main__":
    unittest.main()
