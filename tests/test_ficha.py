import json
import unittest

from caca_sn import ficha

IT = {
    "oid": "ZTF26x",
    "ra": 157.527366,
    "dec": 8.09058,
    "mjd0": 61338.5354,
    "mag": 18.87,
    "fonte": "ztf",
    "curva": [(0.0, 2, 18.87), (0.001, 2, 18.88)],
}
CFG = {"bot_id": 1, "bot_name": "b", "api_key": "k"}


def servicos(**troca):
    s = {
        "tns": lambda cfg, ra, dec: [],
        "gaia": lambda ra, dec: [],
        "skybot": lambda ra, dec, mjd: [],
        "ned": lambda ra, dec: {"nome": "WISEA J103006.48+080525.1", "z": 0.0528, "sep": 1.3},
        "nao_deteccao": lambda oid, mjd0: {"mjd": 61321.531, "fid": 2, "limite": 19.18},
    }
    s.update(troca)
    return s


class TesteVeredito(unittest.TestCase):
    def test_pronto_e_magnitude_absoluta(self):
        f = ficha.montar(IT, CFG, servicos())
        self.assertTrue(f["pronto"], f["motivos"])
        self.assertEqual(f["M"], -18.0)  # AT 2026ahcq; à mão, só com cz/H0, dava -17.9
        self.assertIn("PRONTO", ficha.texto(f))

    def test_ja_no_tns(self):
        f = ficha.montar(IT, CFG, servicos(tns=lambda cfg, ra, dec: ["2026ahcq"]))
        self.assertFalse(f["pronto"])
        self.assertIn("2026ahcq", f["motivos"][0])

    def test_estrela_com_paralaxe(self):
        estrela = [{"source_id": 1, "g": 18.9, "paralaxe": 2.0, "paralaxe_sigma": 12.0, "sep": 0.3}]
        f = ficha.montar(IT, CFG, servicos(gaia=lambda ra, dec: estrela))
        self.assertTrue(any("estrela do Gaia" in m for m in f["motivos"]))

    def test_nucleo_de_galaxia_sem_paralaxe_nao_e_estrela(self):
        nucleo = [{"source_id": 1, "g": 21.0, "paralaxe": None, "paralaxe_sigma": None, "sep": 0.9}]
        self.assertTrue(ficha.montar(IT, CFG, servicos(gaia=lambda ra, dec: nucleo))["pronto"])

    def test_asteroide_e_sem_nao_deteccao(self):
        f = ficha.montar(IT, CFG, servicos(skybot=lambda ra, dec, mjd: ["(1234) Ceres"], nao_deteccao=lambda o, m: None))
        self.assertEqual(len(f["motivos"]), 2)

    def test_servico_fora_do_ar_nao_libera(self):
        def cai(ra, dec):
            raise OSError("timeout")

        f = ficha.montar(IT, CFG, servicos(gaia=cai))
        self.assertFalse(f["pronto"])
        self.assertIn("gaia", f["falhas"])
        self.assertTrue(any("gaia não respondeu" in m for m in f["motivos"]))

    def test_sem_credenciais_nao_libera(self):
        self.assertFalse(ficha.montar(IT, None, servicos())["pronto"])

    def test_uma_deteccao_so_espera(self):
        f = ficha.montar(dict(IT, curva=[(0.0, 2, 19.3)]), CFG, servicos())
        self.assertFalse(f["pronto"])
        self.assertIn("só 1 detecção", f["motivos"][0])

    def test_nuclear_avisa_mas_nao_bloqueia(self):
        f = ficha.montar(IT, CFG, servicos(ned=lambda ra, dec: {"nome": "G", "z": 0.094, "sep": 0.4}))
        self.assertTrue(f["pronto"])
        self.assertIn("núcleo", f["avisos"][0])
        self.assertIn("atenção: no núcleo", ficha.texto(f))


class TesteServicos(unittest.TestCase):
    def test_nao_deteccao_pega_a_ultima_antes(self):
        nd = [
            {"mjd": 61314.53, "fid": 2, "diffmaglim": 18.46},
            {"mjd": 61321.531, "fid": 2, "diffmaglim": 19.183},
            {"mjd": 61321.541, "fid": 2, "diffmaglim": 17.83},  # mais tarde na mesma noite, mas rasa
            {"mjd": 61339.0, "fid": 1, "diffmaglim": 20.0},
        ]
        self.assertEqual(ficha.nao_deteccao("x", 61338.5, lambda url: nd), {"mjd": 61321.531, "fid": 2, "limite": 19.18})
        self.assertIsNone(ficha.nao_deteccao("x", 61300.0, lambda url: nd))

    def test_gaia_le_tap(self):
        corpo = json.dumps({"data": [[42, 18.5, 1.1, 8.0, 0.256]]}).encode()
        esperado = {"source_id": 42, "g": 18.5, "paralaxe": 1.1, "paralaxe_sigma": 8.0, "sep": 0.26}
        self.assertEqual(ficha.gaia(1.0, 2.0, lambda url: corpo)[0], esperado)

    def test_skybot_vazio_e_nenhum(self):
        self.assertEqual(ficha.skybot(1.0, 2.0, 61338.5, lambda url: b""), [])

    def test_ned_pega_galaxia_com_redshift(self):
        tab = (
            b"cabecalho\nNo.\tObject Name\tRA\tDEC\tType\tVelocity\tRedshift\tRedshift Flag\t"
            b"Magnitude and Filter\tSeparation\n"
            b"1\tSTAR X\t1\t2\t*\t\t\t\t\t0.01\n"
            b"2\tWISEA J1\t1\t2\tG\t15828\t0.052798\tSLS\t\t0.022\n"
        )
        self.assertEqual(ficha.ned_hospedeira(1.0, 2.0, lambda url: tab), {"nome": "WISEA J1", "z": 0.052798, "sep": 1.3})


if __name__ == "__main__":
    unittest.main()
