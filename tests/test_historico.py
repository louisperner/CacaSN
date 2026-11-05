import json
import os
import tempfile
import unittest

from caca_sn import ficha, historico

CAB = "###MJD m dm uJy duJy F err chi/N RA Dec x y maj min phi apfit mag5sig Sky Obs"


def linha(mjd, ujy, dujy=10.0, f="o"):
    return f"{mjd} 19.0 0.1 {ujy} {dujy} {f} 0 1.0 60.86 16.80 1 1 2 2 0 -0.4 19.5 20.0 01a{int(mjd)}"


def arquivo(pontos):
    return "\n".join([CAB] + [linha(*p) for p in pontos])


class TesteLeitura(unittest.TestCase):
    def test_le_colunas(self):
        p = historico.ler_atlas(arquivo([(58000.1, 15.0), (58001.2, -3.0)]))
        self.assertEqual(len(p), 2)
        self.assertEqual((p[0]["MJD"], p[0]["uJy"], p[0]["F"]), (58000.1, 15.0, "o"))

    def test_ignora_linha_quebrada(self):
        self.assertEqual(len(historico.ler_atlas(CAB + "\n1 2 3")), 0)


class TesteResumo(unittest.TestCase):
    def test_nada_antes(self):
        pts = historico.ler_atlas(arquivo([(58000 + i, 5.0) for i in range(50)] + [(61340, 500.0)]))
        r = historico.resumir(pts, 61331)
        self.assertFalse(r["ativa_antes"])
        self.assertEqual(r["medidas_antes"], 50)
        self.assertIn("nada antes", r["veredito"])

    def test_agn_ja_variava(self):
        pts = historico.ler_atlas(arquivo([(58000.5, 80.0), (58100.5, 90.0), (58900.5, 70.0), (58000 + 3, 4.0)]))
        r = historico.resumir(pts, 61331)
        self.assertTrue(r["ativa_antes"])
        self.assertEqual(r["noites_detectadas_antes"], 3)

    def test_explosao_logo_antes_nao_conta(self):
        # detecções a menos de ANTES dias da descoberta podem ser a própria supernova subindo
        pts = historico.ler_atlas(arquivo([(61325.0, 80.0), (61326.0, 90.0), (61327.0, 95.0)]))
        self.assertFalse(historico.resumir(pts, 61331)["ativa_antes"])


class TesteFila(unittest.TestCase):
    def test_enfileira_espera_baixa_e_apaga(self):
        chamadas = []
        estados = iter([{"finishtimestamp": None}, {"finishtimestamp": "x", "error_msg": None, "result_url": "R"}])

        def pedir(url, token, dados=None, metodo=None):
            chamadas.append((url, metodo))
            if url.endswith("/queue/"):
                return 201, json.dumps({"url": "T"}).encode()
            if url == "T" and metodo is None:
                return 200, json.dumps(next(estados)).encode()
            if url == "R":
                return 200, arquivo([(58000.0, 1.0)]).encode()
            return 204, b""

        pts = historico.atlas(1.0, 2.0, "tok", pedir=pedir, dormir=lambda s: None)
        self.assertEqual(len(pts), 1)
        self.assertEqual(chamadas[-1], ("T", "DELETE"))

    def test_sem_token_devolve_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(historico.historico({"ra": 1, "dec": 2, "mjd0": 3}, d))

    def test_com_token_usa_o_arquivo(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, historico.ARQUIVO), "w") as f:
                json.dump({"atlas_token": "tok"}, f)
            r = historico.historico({"ra": 1, "dec": 2, "mjd0": 61331}, d, lambda ra, dec, tok: [])
            self.assertEqual(r["medidas_antes"], 0)


class TesteNaFicha(unittest.TestCase):
    IT = {"oid": "ZTF26x", "ra": 1.0, "dec": 2.0, "mjd0": 61331.0, "mag": 20.0, "curva": [(0, 1, 20), (1, 2, 20)]}
    BASE = {
        "tns": lambda cfg, ra, dec: [],
        "gaia": lambda ra, dec: [],
        "skybot": lambda ra, dec, mjd: [],
        "ned": lambda ra, dec: None,
        "nao_deteccao": lambda oid, mjd: {"mjd": 61329.0, "fid": 2, "limite": 20.2},
    }

    def test_variava_vira_aviso_sem_bloquear(self):
        ativo = {"ativa_antes": True, "veredito": "já variava antes: 3 noite(s)"}
        f = ficha.montar(self.IT, {"x": 1}, dict(self.BASE, historico=lambda it, p: ativo), pasta="/tmp")
        self.assertTrue(f["pronto"])
        self.assertTrue(any("histórico ATLAS" in a for a in f["avisos"]))
        self.assertIn("histórico ATLAS: já variava", ficha.texto(f))

    def test_falha_do_atlas_nao_bloqueia(self):
        def quebra(it, p):
            raise OSError("fora")

        f = ficha.montar(self.IT, {"x": 1}, dict(self.BASE, historico=quebra), pasta="/tmp")
        self.assertTrue(f["pronto"])
        self.assertIn("histórico ATLAS: não respondeu", ficha.texto(f))


if __name__ == "__main__":
    unittest.main()
