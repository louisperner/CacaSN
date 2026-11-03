import json
import os
import tempfile
import unittest
from unittest import mock

from caca_sn import catalogos, novas_anas
from caca_sn.rede import mjd_agora

T0 = mjd_agora() - 10


def det(dt, fid, mag, pos=1, stamp=True):
    return {
        "mjd": T0 + dt,
        "fid": fid,
        "magpsf": mag,
        "isdiffpos": pos,
        "has_stamp": stamp,
        "candid": f"c{dt}",
        "corrected": False,
        "magpsf_corr": None,
    }


# nova anã: subiu de abaixo de 20.5 para 16.5 e caiu em 6 dias, azul
ANA = {
    "detections": [det(0, 1, 16.5), det(0.05, 2, 16.6), det(2, 1, 17.0), det(2.05, 2, 17.1), det(6, 1, 18.5)],
    "non_detections": [{"mjd": T0 - i, "fid": 1, "diffmaglim": 20.5} for i in range(1, 11)],
}
# variável vermelha lenta: mesma amplitude, mas g-r ~ 1.5
VERMELHA = {
    "detections": [det(0, 1, 18.0), det(0.05, 2, 16.5), det(5, 1, 18.2), det(5.05, 2, 16.7), det(9, 2, 16.9)],
    "non_detections": [{"mjd": T0 - i, "fid": 2, "diffmaglim": 20.5} for i in range(1, 11)],
}


def obj(oid, ra):
    return {"oid": oid, "meanra": ra, "meandec": 10.0}


class Indice:
    def buscar(self, ra, dec, raio=3.0):
        return ["AT 2026x"] if ra == 3.0 else []


def falso_get_json(curvas):
    def f(url, tentativas=4):
        if "/objects/?" in url:
            return {"items": [obj("ZTF26ana", 1.0), obj("ZTF26verm", 2.0), obj("ZTF26tns", 3.0), obj("ZTF26vsx", 4.0)]}
        oid = url.split("/objects/")[1].split("/")[0]
        return curvas[oid]

    return f


def xmatch_ok(url, corpo, tipo):
    assert b"ZTF26vsx" in corpo and b"ZTF26tns" not in corpo  # quem está no TNS nem vai ao X-Match
    return b"angDist,oid,ra,dec,Name,Type\n0.3,ZTF26vsx,4.0,10.0,V0001 Cyg,UGSU\n"


class TesteMedidas(unittest.TestCase):
    def test_nova_ana_passa(self):
        m = novas_anas.medir(ANA)
        self.assertEqual(m["amplitude"], 4.0)  # 20.5 - 16.5
        self.assertEqual(m["base_amplitude"], "limite")
        self.assertEqual((m["deteccoes"], m["duracao"], m["pico"]), (5, 6.0, 16.5))
        self.assertAlmostEqual(m["cor_gr"], -0.1)
        self.assertIsNone(novas_anas.reprovado(m))

    def test_vermelha_nao_passa(self):
        m = novas_anas.medir(VERMELHA)
        self.assertIn("vermelha", novas_anas.reprovado(m))

    def test_amplitude_pela_curva_corrigida(self):
        dets = [dict(det(i, 1, 18.0), corrected=True, magpsf_corr=16.0 + i) for i in range(4)]
        self.assertEqual(novas_anas.medir({"detections": dets})["amplitude"], 3.0)

    def test_negativas_reprovam(self):
        lc = {"detections": ANA["detections"] + [det(7, 1, 19.0, pos="f")], "non_detections": ANA["non_detections"]}
        self.assertIn("positivas", novas_anas.reprovado(novas_anas.medir(lc)))


class TesteRodada(unittest.TestCase):
    def rodar(self, d, enviar=xmatch_ok, gaia=None, plano_b=None):
        curvas = {"ZTF26ana": ANA, "ZTF26verm": VERMELHA, "ZTF26vsx": ANA, "ZTF26tns": ANA}
        with (
            mock.patch.object(novas_anas, "get_json", falso_get_json(curvas)),
            mock.patch.object(novas_anas, "postar", enviar),
            mock.patch.object(novas_anas, "gaia_brilhante", return_value=gaia),
            mock.patch.object(novas_anas, "vsx_um_por_um", plano_b or mock.Mock(side_effect=OSError("espelhos fora"))),
            mock.patch.object(novas_anas.alertas, "notificar") as n,
        ):
            return novas_anas.rodar(d, avisar=True, cfg={}, indice=Indice()), n

    def test_descarta_tns_vsx_e_vermelha_e_avisa_uma_vez(self):
        with tempfile.TemporaryDirectory() as d:
            aprovadas, n = self.rodar(d)
            self.assertEqual([a["oid"] for a in aprovadas], ["ZTF26ana"])
            self.assertIn("ZTF26ana", aprovadas[0]["stamps"]["science"])
            with open(os.path.join(d, novas_anas.SAIDA_JSON)) as f:
                self.assertEqual(len(json.load(f)), 1)
            self.assertTrue(os.path.exists(os.path.join(d, novas_anas.SAIDA_HTML)))
            self.assertEqual(n.call_count, 1)
            _, n2 = self.rodar(d)
            n2.assert_not_called()  # já avisada

    def test_xmatch_falhando_nao_avisa(self):
        def quebra(url, corpo, tipo):
            raise OSError("fora do ar")

        with tempfile.TemporaryDirectory() as d:
            aprovadas, n = self.rodar(d, enviar=quebra)
            self.assertEqual(aprovadas, [])
            n.assert_not_called()
            self.assertFalse(os.path.exists(os.path.join(d, novas_anas.SAIDA_JSON)))

    def test_xmatch_fora_usa_espelhos(self):
        def quebra(url, corpo, tipo):
            raise OSError("CDS fora")

        with tempfile.TemporaryDirectory() as d:
            aprovadas, n = self.rodar(d, enviar=quebra, plano_b=lambda objs: {"ZTF26vsx": "V1 (UGSS)"})
            self.assertEqual([a["oid"] for a in aprovadas], ["ZTF26ana"])

    def test_gaia_brilhante_marca_suspeito(self):
        with tempfile.TemporaryDirectory() as d:
            aprovadas, _ = self.rodar(d, gaia="Gaia DR3 1 G=12.00")
        self.assertEqual(aprovadas[0]["suspeito"], "Gaia DR3 1 G=12.00")

    def test_gaia_brilhante(self):
        with mock.patch.object(catalogos, "vizier", return_value=[["123 ", "15.0"], ["9", "19"]]):
            self.assertEqual(novas_anas.gaia_brilhante(1, 1, 16.5), "Gaia DR3 123 G=15.00")
        with mock.patch.object(catalogos, "vizier", return_value=[["9", "19"]]):
            self.assertIsNone(novas_anas.gaia_brilhante(1, 1, 16.5))

    def test_rascunho_outro_e_observacao(self):
        it = dict(novas_anas.medir(ANA), oid="ZTF26ana", ra=1.0, dec=10.0, fonte="ztf")
        rel, pend = novas_anas.rascunho_nova_ana(it, {})
        r = rel["at_report"]["0"]
        self.assertTrue(r["remarks"].startswith("likely dwarf nova outburst"))
        self.assertTrue(any("at_type" in p for p in pend))


class TesteVsxPlanoB(unittest.TestCase):
    OBJS = [{"oid": "a", "meanra": 1.0, "meandec": 2.0}, {"oid": "b", "meanra": 3.0, "meandec": 4.0}]

    def test_acha_e_ignora_vazios(self):
        resp = {1.0: [["V0001 And", "UGSS"]], 3.0: []}
        r = novas_anas.vsx_um_por_um(self.OBJS, lambda f, ra, dec, raio, cols: resp[ra])
        self.assertEqual(r, {"a": "V0001 And (UGSS)"})

    def test_sem_resposta_sobe(self):
        with self.assertRaises(OSError):
            novas_anas.vsx_um_por_um(self.OBJS, lambda *a: None)


if __name__ == "__main__":
    unittest.main()
