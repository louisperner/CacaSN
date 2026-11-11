import io
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from caca_sn import catalogos


class TesteGaia(unittest.TestCase):
    def test_estrela_com_paralaxe(self):
        with mock.patch.object(catalogos, "vizier", return_value=[["123", "5.0", "0.5", "1", "1"]]):
            self.assertEqual(catalogos.estrela_gaia(1, 2), "123")

    def test_sem_estrela(self):
        with mock.patch.object(catalogos, "vizier", return_value=[["9", "0.1", "0.5", "0", "0"]]):
            self.assertIsNone(catalogos.estrela_gaia(1, 2))

    def test_catalogo_fora_do_ar(self):
        with mock.patch.object(catalogos, "vizier", return_value=None):
            self.assertIs(catalogos.estrela_gaia(1, 2), catalogos.SEM_RESPOSTA)


class TesteDisjuntor(unittest.TestCase):
    def setUp(self):
        catalogos.VIZIER.falhas = 0

    def tearDown(self):
        catalogos.VIZIER.falhas = 0

    def test_abre_depois_de_falhas_seguidas(self):
        with (
            mock.patch("urllib.request.urlopen", side_effect=OSError("fora")) as abre,
            mock.patch.object(catalogos.time, "sleep"),
        ):
            for _ in range(5):
                self.assertIsNone(catalogos.vizier("X", 1, 2, 1, "a"))
        self.assertEqual(abre.call_count, len(catalogos.SERVIDORES) * catalogos.VIZIER.limite)  # depois de aberto, nem tenta
        self.assertTrue(catalogos.VIZIER.aberto)

    def test_cai_no_espelho_e_lembra_dele(self):
        resposta = mock.MagicMock()
        resposta.__enter__.return_value.read.return_value = b"#c\na\n-\n---\nV1\n"
        chamadas = []

        def abrir(req, timeout):
            chamadas.append(req.full_url.split("/viz-bin")[0])
            if "unistra" in req.full_url:
                raise OSError("CDS fora")
            return resposta

        with mock.patch("urllib.request.urlopen", side_effect=abrir), mock.patch.object(catalogos.time, "sleep"):
            self.assertEqual(catalogos.vizier("B/vsx/vsx", 1, 2, 5, "a"), [["V1"]])
            self.assertEqual(catalogos.vizier("B/vsx/vsx", 1, 2, 5, "a"), [["V1"]])
        self.assertEqual(chamadas, [catalogos.SERVIDORES[0], catalogos.SERVIDORES[1], catalogos.SERVIDORES[1]])
        catalogos._preferido = 0

    def test_resposta_boa_zera(self):
        catalogos.VIZIER.resultado(False)
        catalogos.VIZIER.resultado(False)
        catalogos.VIZIER.resultado(True)
        self.assertFalse(catalogos.VIZIER.aberto)
        self.assertEqual(catalogos.VIZIER.falhas, 0)


class TesteVSX(unittest.TestCase):
    def test_variavel_conhecida(self):
        with mock.patch.object(catalogos, "vizier", return_value=[["ASASSN-26de   ", "UG  "]]):
            self.assertEqual(catalogos.variavel_conhecida(1, 2), "ASASSN-26de (UG)")

    def test_nada_ou_fora_do_ar(self):
        with mock.patch.object(catalogos, "vizier", return_value=[]):
            self.assertIsNone(catalogos.variavel_conhecida(1, 2))
        with mock.patch.object(catalogos, "vizier", return_value=None):
            self.assertIs(catalogos.variavel_conhecida(1, 2), catalogos.SEM_RESPOSTA)


class TesteCredenciais(unittest.TestCase):
    def test_variaveis_de_ambiente(self):
        env = {"TNS_BOT_ID": "7", "TNS_BOT_NAME": "b", "TNS_API_KEY": "k"}
        with mock.patch.dict(os.environ, env), tempfile.TemporaryDirectory() as d:
            self.assertEqual(catalogos.tns_carregar(d), {"bot_id": 7, "bot_name": "b", "api_key": "k"})

    def test_arquivo_ou_nada(self):
        limpo = {k: v for k, v in os.environ.items() if not k.startswith("TNS_")}
        with mock.patch.dict(os.environ, limpo, clear=True), tempfile.TemporaryDirectory() as d:
            self.assertIsNone(catalogos.tns_carregar(d))
            with open(os.path.join(d, "tns.json"), "w") as f:
                json.dump({"bot_id": 1, "bot_name": "x", "api_key": "y"}, f)
            self.assertEqual(catalogos.tns_carregar(d)["bot_id"], 1)


class TesteTNS(unittest.TestCase):
    CFG = {"bot_id": 1, "bot_name": "b", "api_key": "k"}

    def resposta(self, dados):
        ok = mock.MagicMock()
        ok.__enter__.return_value = io.StringIO(json.dumps({"data": dados}))
        return ok

    def test_429_espera_e_tenta_de_novo(self):
        erro = urllib.error.HTTPError("u", 429, "x", {"x-cone-rate-limit-reset": "0"}, None)
        with (
            mock.patch("urllib.request.urlopen", side_effect=[erro, self.resposta([{"prefix": "AT", "objname": "2026abc"}])]),
            mock.patch.object(catalogos.time, "sleep"),
        ):
            self.assertEqual(catalogos.tns_busca(self.CFG, 1.0, 2.0), ["AT 2026abc"])

    def test_erro_de_rede_tenta_de_novo(self):
        with (
            mock.patch("urllib.request.urlopen", side_effect=[urllib.error.URLError("x"), self.resposta([])]),
            mock.patch.object(catalogos.time, "sleep"),
        ):
            self.assertEqual(catalogos.tns_busca(self.CFG, 1.0, 2.0), [])

    def test_outro_erro_http_sobe(self):
        erro = urllib.error.HTTPError("u", 401, "x", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=erro), mock.patch.object(catalogos.time, "sleep"):
            with self.assertRaises(urllib.error.HTTPError):
                catalogos.tns_busca(self.CFG, 1.0, 2.0)


class TestePS1(unittest.TestCase):
    CAB = "objName,rMeanPSFMag,rMeanKronMag\n"

    def test_pontual_brilhante_marca(self):
        r = catalogos.ps1_puntiforme(1, 1, 20.0, ler=lambda u: self.CAB + "PSO A,19.80,19.78\n")
        self.assertIn("pontual", r)

    def test_estendida_nao_marca(self):
        # AT 2026ajce: PSO J109.0233+10.2745, r PSF 20,51, Kron 20,37 (galáxia compacta)
        self.assertIsNone(catalogos.ps1_puntiforme(109.02, 10.27, 20.17, ler=lambda u: self.CAB + "PSO J,20.51,20.37\n"))

    def test_pontual_fraca_nao_marca(self):
        self.assertIsNone(catalogos.ps1_puntiforme(1, 1, 20.0, ler=lambda u: self.CAB + "PSO A,21.50,21.49\n"))

    def test_latitude_galactica(self):
        self.assertAlmostEqual(catalogos.latitude_galactica(109.02304, 10.27428), 10.1, delta=0.1)
        self.assertAlmostEqual(catalogos.latitude_galactica(192.85948, 27.12825), 90.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
