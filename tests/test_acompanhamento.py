import json
import os
import tempfile
import unittest
from unittest import mock

from caca_sn import acompanhamento

CFG = {"bot_id": 1, "bot_name": "b", "api_key": "k"}
SEM_TIPO = {"name_prefix": "AT", "object_type": {"name": None}, "redshift": None}
SN_IA = {"name_prefix": "SN", "object_type": {"name": "SN Ia"}, "redshift": 0.05}


SEM_DET = lambda fonte, oid: None  # noqa: E731


class TesteDeteccaoNova(unittest.TestCase):
    def test_nomes_internos(self):
        obj = {"internal_names": "ZTF26accxrjc, 171141186204467235, ATLAS26abc"}
        self.assertEqual(acompanhamento.nomes_internos(obj), [("ztf", "ZTF26accxrjc"), ("rubin", "171141186204467235")])

    def test_ultima_deteccao_ztf(self):
        dets = [{"mjd": 61338.5, "fid": 2, "magpsf": 18.87}, {"mjd": 61340.4, "fid": 1, "magpsf": 18.6}]
        u = acompanhamento.ultima_deteccao("ztf", "ZTF26x", lambda url: dets)
        self.assertEqual((u["mjd"], u["filtro"], u["mag"], u["n"]), (61340.4, "g", 18.6, 2))

    def test_avisa_deteccao_nova_uma_vez(self):
        obj = dict(SEM_TIPO, internal_names="ZTF26accxrjc")
        dets = [{"mjd": 61338.5, "mag": 18.87, "filtro": "r"}, {"mjd": 61345.3, "mag": 19.1, "filtro": "g"}]
        estado = {"i": 0}

        def detectar(fonte, oid):
            return dets[min(estado["i"], 1)]

        with tempfile.TemporaryDirectory() as d, mock.patch.object(acompanhamento.alertas, "notificar") as n:
            acompanhamento.adicionar(d, "2026ahcq")
            self.assertEqual(acompanhamento.verificar(CFG, d, lambda c, nm: obj, detectar), [])
            estado["i"] = 1
            r = acompanhamento.verificar(CFG, d, lambda c, nm: obj, detectar)
            self.assertEqual(len(r), 1)
            self.assertIn("2026ahcq: g 19.1", r[0])
            self.assertEqual(acompanhamento.verificar(CFG, d, lambda c, nm: obj, detectar), [])
        self.assertEqual(n.call_count, 1)

    def test_falha_na_deteccao_nao_quebra(self):
        def falha(fonte, oid):
            raise OSError("fora")

        obj = dict(SEM_TIPO, internal_names="ZTF26accxrjc")
        with tempfile.TemporaryDirectory() as d:
            acompanhamento.adicionar(d, "2026ahcq")
            self.assertEqual(acompanhamento.verificar(CFG, d, lambda c, nm: obj, falha), [])


class TesteAcompanhamento(unittest.TestCase):
    def test_avisa_quando_classificam_e_so_uma_vez(self):
        respostas = [SEM_TIPO, SN_IA, SN_IA]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(acompanhamento.alertas, "notificar") as n:
            acompanhamento.adicionar(d, "AT 2026agsv")
            consultar = lambda cfg, nome: respostas.pop(0)  # noqa: E731
            self.assertEqual(acompanhamento.verificar(CFG, d, consultar, SEM_DET), [])
            esperado = ["AT 2026agsv -> SN 2026agsv = SN Ia (z = 0.05)"]
            self.assertEqual(acompanhamento.verificar(CFG, d, consultar, SEM_DET), esperado)
            self.assertEqual(acompanhamento.verificar(CFG, d, consultar, SEM_DET), [])
            with open(os.path.join(d, acompanhamento.ARQUIVO)) as f:
                self.assertEqual(json.load(f)["2026agsv"]["tipo"], "SN Ia")
        self.assertEqual(n.call_count, 1)

    def test_primeira_consulta_ja_classificado_nao_avisa(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(acompanhamento.alertas, "notificar") as n:
            acompanhamento.adicionar(d, "2026adfo")
            self.assertEqual(acompanhamento.verificar(CFG, d, lambda c, nome: SN_IA, SEM_DET), [])
        n.assert_not_called()

    def test_falha_do_tns_nao_quebra(self):
        def falha(cfg, nome):
            raise OSError("fora")

        with tempfile.TemporaryDirectory() as d:
            acompanhamento.adicionar(d, "2026agsv")
            self.assertEqual(acompanhamento.verificar(CFG, d, falha), [])

    def test_sem_credenciais_ou_lista(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(acompanhamento.verificar(None, d), [])
            self.assertEqual(acompanhamento.verificar(CFG, d), [])


if __name__ == "__main__":
    unittest.main()
