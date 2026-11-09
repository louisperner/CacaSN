import io
import os
import tempfile
import unittest
import zipfile
from datetime import date
from unittest import mock

from caca_sn import novidades

CFG = {"bot_id": 1, "bot_name": "b", "api_key": "k"}
CAB = '"objid","name_prefix","name","redshift","type","internal_names"\n'


def zipado(linhas):
    texto = "2026-10-23 00:00:00 - 23:59:59\n" + CAB + "".join(linhas)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("tns.csv", texto)
    return buf.getvalue()


LINHAS = [
    '1,"SN","2026aady","0.362","SLSN-I","GOTO26iqr"\n',
    '2,"SN","2026afou","0.11","SN Ia","ZTF26acbihrg, ATLAS26mrp"\n',
    '3,"AT","2026zzz","","","ZTF26novo"\n',
]


class TesteLeitura(unittest.TestCase):
    def test_le_o_csv_do_tns(self):
        dados = novidades.ler_csv(zipado(LINHAS))
        self.assertEqual([d["name"] for d in dados], ["2026aady", "2026afou", "2026zzz"])

    def test_resumo_e_destaques(self):
        r = novidades.resumir(novidades.ler_csv(zipado(LINHAS)), vistos={"ZTF26acbihrg"})
        self.assertEqual(r["novos"], 1)
        self.assertEqual(len(r["classificados"]), 2)
        self.assertIn(("2026afou", "SN 2026afou = SN Ia: o CacaSN tinha visto (ZTF26acbihrg)"), r["destaques"])
        self.assertTrue(any("2026aady = SLSN-I (raro" in x for _, x in r["destaques"]))


class TesteVerificar(unittest.TestCase):
    def test_processa_os_dias_que_faltam_uma_vez(self):
        dias = []

        def baixar(cfg, dia):
            dias.append(dia)
            return novidades.ler_csv(zipado(LINHAS))

        with tempfile.TemporaryDirectory() as d, mock.patch.object(novidades.alertas, "notificar") as n:
            hoje = date(2026, 10, 24)
            d1 = novidades.verificar(CFG, d, set(), hoje=hoje, baixar=baixar)
            d2 = novidades.verificar(CFG, d, set(), hoje=hoje, baixar=baixar)
            with open(os.path.join(d, novidades.RESUMO)) as f:
                texto = f.read()
        self.assertEqual(dias, [date(2026, 10, 23)])  # 1ª vez: só ontem (hoje não fechou); depois não repete
        self.assertEqual(d2, [])
        self.assertTrue(d1)
        self.assertEqual(n.call_count, 1)
        self.assertIn("## 2026-10-23", texto)
        self.assertIn("SLSN-I", texto)

    def test_recupera_os_dias_perdidos(self):
        dias = []
        with tempfile.TemporaryDirectory() as d:
            novidades.gravar_json(os.path.join(d, novidades.ESTADO), {"ultimo_dia": "2026-10-20"})
            novidades.verificar(CFG, d, set(), hoje=date(2026, 10, 24), baixar=lambda c, dia: dias.append(dia) or [])
        self.assertEqual([x.day for x in dias], [21, 22, 23])

    def test_dentro_do_dia_sem_aviso_repetido(self):
        hoje = [{"name_prefix": "SN", "name": "2026iin", "type": "SN IIn", "redshift": "0.02", "internal_names": "X"}]
        chamadas = []

        def buscar(cfg, desde):
            chamadas.append(desde)
            return hoje

        with tempfile.TemporaryDirectory() as d, mock.patch.object(novidades.alertas, "notificar") as n:
            a = novidades.verificar(CFG, d, set(), hoje=date(2026, 10, 24), baixar=lambda c, dia: [], buscar_hoje=buscar)
            b = novidades.verificar(CFG, d, set(), hoje=date(2026, 10, 24), baixar=lambda c, dia: [], buscar_hoje=buscar)
        self.assertEqual(len(a), 1)
        self.assertIn("IIn", a[0])
        self.assertEqual(b, [])  # o mesmo objeto não é avisado de novo
        self.assertEqual(n.call_count, 1)
        self.assertTrue(chamadas[0].endswith("00:00:00"))  # 1ª consulta: desde a meia-noite UTC

    def test_diario_nao_repete_o_que_ja_foi_avisado_no_dia(self):
        dia = [{"name_prefix": "SN", "name": "2026iin", "type": "SN IIn", "redshift": "", "internal_names": ""}]
        with tempfile.TemporaryDirectory() as d, mock.patch.object(novidades.alertas, "notificar") as n:
            novidades.verificar(CFG, d, set(), hoje=date(2026, 10, 24), baixar=lambda c, x: [], buscar_hoje=lambda c, s: dia)
            depois = novidades.verificar(CFG, d, set(), hoje=date(2026, 10, 25), baixar=lambda c, x: dia)
        self.assertEqual(depois, [])
        self.assertEqual(n.call_count, 1)

    def test_falha_para_e_tenta_depois(self):
        def falha(cfg, dia):
            raise OSError("fora")

        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(novidades.verificar(CFG, d, set(), hoje=date(2026, 10, 24), baixar=falha), [])
            self.assertNotIn("ultimo_dia", novidades.ler_json(os.path.join(d, novidades.ESTADO), {}))  # tenta de novo depois

    def test_sem_credenciais(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(novidades.verificar(None, d, set()), [])


class TesteRarosNovos(unittest.TestCase):
    def test_ia_csm_e_outros_avisam(self):
        for tipo in ("SN Ia-CSM", "SN Iax[02cx-like]", "SN Ia-SC", "SN II-pec"):
            d = {"name_prefix": "SN", "name": "2026sqf", "type": tipo, "redshift": "0.03"}
            self.assertIn("raro", novidades.destaque(d, set()) or "", tipo)

    def test_ia_comum_nao_avisa(self):
        d = {"name_prefix": "SN", "name": "2026x", "type": "SN Ia", "redshift": "0.03"}
        self.assertIsNone(novidades.destaque(d, set()))


if __name__ == "__main__":
    unittest.main()
